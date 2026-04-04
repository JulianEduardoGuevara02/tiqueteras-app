# models.py
import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, Date, DateTime, ForeignKey, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import datetime

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tiqueteras.db")

# Asegurar que PostgreSQL use el driver psycopg (v3)
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# SQLite necesita check_same_thread=False, PostgreSQL con pooler necesita prepare_threshold=0
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"prepare_threshold": 0},
        pool_pre_ping=True,
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
    saldos = relationship("Saldo", back_populates="usuario")
    excepciones = relationship("Excepcion", back_populates="usuario")

class Saldo(Base):
    __tablename__ = "saldos"
    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"))
    cantidad_tickets = Column(Integer)
    fecha_compra = Column(Date, default=datetime.date.today)
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

# === Crear tablas nuevas ===
Base.metadata.create_all(bind=engine)

# === Migracion: agregar columnas a tablas existentes ===

def migrar_sedes():
    with engine.connect() as conn:
        # Verificar si ya se migro
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
                logger.info("Migracion: columna activo agregada a usuarios")
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
                logger.info("Migracion: columna email agregada a usuarios")
            except Exception:
                conn.rollback()

# Ejecutar migraciones y bootstrap al importar
try:
    migrar_sedes()
    migrar_activo_usuario()
    migrar_email_usuario()
    bootstrap_superadmin()
except Exception as e:
    logger.warning(f"Migracion/bootstrap: {e} (ejecutar SQL manualmente si falla)")
