# models.py
import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, Float, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import NullPool
import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tiqueteras.db")

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"prepare_threshold": None},
        poolclass=NullPool,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# === Modelos ===

class Sede(Base):
    __tablename__ = "sedes"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, unique=True, nullable=False)
    activa = Column(Integer, default=1)

class AdminSede(Base):
    __tablename__ = "admin_sedes"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True)
    rol = Column(String, nullable=False, default="admin")

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True, index=True)
    activo = Column(Integer, default=1)
    email = Column(String, nullable=True)
    tipo = Column(String, default="recurrente")  # recurrente | esporadico | empresa
    saldos = relationship("Saldo", back_populates="usuario")
    excepciones = relationship("Excepcion", back_populates="usuario")

class Saldo(Base):
    __tablename__ = "saldos"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    cantidad_tickets = Column(Integer)
    fecha_compra = Column(Date, default=datetime.date.today)
    # Snapshot del precio en el momento del pago (nunca cambia con ajustes futuros)
    precio_snapshot = Column(Float, nullable=True)
    # Monto en COP efectivamente pagado (para el flujo de caja)
    monto_pagado = Column(Float, nullable=True)
    observacion = Column(String, nullable=True)
    usuario = relationship("Usuario", back_populates="saldos")

class Excepcion(Base):
    __tablename__ = "excepciones"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    fecha = Column(Date)
    tipo_excepcion = Column(String)
    usuario = relationship("Usuario", back_populates="excepciones")

class DiaGlobal(Base):
    __tablename__ = "dias_globales"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, index=True)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True, index=True)

class LogAuditoria(Base):
    __tablename__ = "log_auditoria"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    email = Column(String)
    accion = Column(String)
    detalle = Column(String)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True)

class ConfiguracionSede(Base):
    """Precio del tiquete por sede. El snapshot en Saldo preserva el precio historico."""
    __tablename__ = "configuracion_sede"
    id = Column(Integer, primary_key=True, index=True)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True, unique=True)
    precio_ticket = Column(Float, default=0.0)

class ComprasMercado(Base):
    """Registro de compras de mercado/insumos. El dinero sale del fondo de pagos."""
    __tablename__ = "compras_mercado"
    id = Column(Integer, primary_key=True, index=True)
    monto = Column(Float, nullable=False)
    descripcion = Column(String, nullable=True)
    observacion = Column(String, nullable=True)
    fecha = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    sede_id = Column(Integer, ForeignKey("sedes.id"), nullable=True, index=True)
    admin_email = Column(String)

# === Crear tablas nuevas ===
Base.metadata.create_all(bind=engine)

# === Migraciones ===

def migrar_sedes():
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT sede_id FROM usuarios LIMIT 1"))
            return
        except Exception:
            conn.rollback()

        logger.info("Ejecutando migracion multi-sede...")
        try:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN sede_id INTEGER REFERENCES sedes(id)"))
        except Exception:
            conn.rollback()
        try:
            conn.execute(text("ALTER TABLE dias_globales ADD COLUMN sede_id INTEGER REFERENCES sedes(id)"))
        except Exception:
            conn.rollback()
        try:
            conn.execute(text("ALTER TABLE log_auditoria ADD COLUMN sede_id INTEGER REFERENCES sedes(id)"))
        except Exception:
            conn.rollback()
        try:
            conn.execute(text("ALTER TABLE dias_globales DROP CONSTRAINT IF EXISTS dias_globales_fecha_key"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_diaglobal_fecha_sede ON dias_globales(fecha, sede_id)"))
        except Exception:
            conn.rollback()
        try:
            conn.execute(text("ALTER TABLE usuarios ADD COLUMN activo INTEGER DEFAULT 1"))
        except Exception:
            conn.rollback()
        conn.commit()
        logger.info("Migracion multi-sede completada")

def bootstrap_superadmin():
    superadmin_email = os.getenv("SUPERADMIN_EMAIL", "")
    if not superadmin_email:
        return

    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM admin_sedes")).scalar()
        if count > 0:
            return

        logger.info("Bootstrap: creando sede Principal y superadmin...")
        conn.execute(text("INSERT INTO sedes (nombre, activa) VALUES ('Principal', 1)"))
        conn.execute(text(
            "INSERT INTO admin_sedes (email, sede_id, rol) VALUES (:email, NULL, 'superadmin')"
        ), {"email": superadmin_email})
        conn.execute(text("UPDATE usuarios SET sede_id = 1 WHERE sede_id IS NULL"))
        conn.execute(text("UPDATE dias_globales SET sede_id = 1 WHERE sede_id IS NULL"))
        conn.commit()
        logger.info("Bootstrap completado")

def migrar_activo_usuario():
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT activo FROM usuarios LIMIT 1"))
        except Exception:
            conn.rollback()
            try:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN activo INTEGER DEFAULT 1"))
                conn.commit()
            except Exception:
                conn.rollback()

def migrar_email_usuario():
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT email FROM usuarios LIMIT 1"))
        except Exception:
            conn.rollback()
            try:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN email VARCHAR"))
                conn.commit()
            except Exception:
                conn.rollback()

def migrar_tipo_usuario():
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT tipo FROM usuarios LIMIT 1"))
        except Exception:
            conn.rollback()
            try:
                conn.execute(text("ALTER TABLE usuarios ADD COLUMN tipo VARCHAR DEFAULT 'recurrente'"))
                conn.commit()
            except Exception:
                conn.rollback()

def migrar_saldo_precio():
    """Agrega precio_snapshot, monto_pagado y observacion a saldos existentes."""
    with engine.connect() as conn:
        try:
            conn.execute(text("SELECT precio_snapshot FROM saldos LIMIT 1"))
        except Exception:
            conn.rollback()
            for col in [
                "ALTER TABLE saldos ADD COLUMN precio_snapshot REAL",
                "ALTER TABLE saldos ADD COLUMN monto_pagado REAL",
                "ALTER TABLE saldos ADD COLUMN observacion VARCHAR",
            ]:
                try:
                    conn.execute(text(col))
                except Exception:
                    conn.rollback()
            try:
                conn.commit()
                logger.info("Migracion: columnas de precio agregadas a saldos")
            except Exception:
                conn.rollback()

# Ejecutar migraciones y bootstrap al importar
try:
    migrar_sedes()
    migrar_activo_usuario()
    migrar_email_usuario()
    migrar_tipo_usuario()
    migrar_saldo_precio()
    bootstrap_superadmin()
except Exception as e:
    logger.warning(f"Migracion/bootstrap: {e} (ejecutar SQL manualmente si falla)")
