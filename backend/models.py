# models.py
import os
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import datetime

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./tiqueteras.db")

# SQLite necesita check_same_thread=False, PostgreSQL no
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Usuario(Base):
    __tablename__ = "usuarios"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, index=True)
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
    tipo_excepcion = Column(String) # 'Ausencia', 'Domingo_Habilitado' o 'Come_Global'
    usuario = relationship("Usuario", back_populates="excepciones")

class DiaGlobal(Base):
    __tablename__ = "dias_globales"
    id = Column(Integer, primary_key=True, index=True)
    fecha = Column(Date, unique=True, index=True)

Base.metadata.create_all(bind=engine)
