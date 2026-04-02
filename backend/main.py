import os
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from datetime import date, datetime, timedelta
from pydantic import BaseModel
import io
import openpyxl
from models import SessionLocal, Usuario, Saldo, Excepcion, DiaGlobal

app = FastAPI(title="API Tiqueteras")

# CORS: en produccion lee la variable ALLOWED_ORIGINS, en local permite todo
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class UsuarioCreate(BaseModel): nombre: str
class SaldoCreate(BaseModel): cantidad: int
class ExcepcionToggle(BaseModel): fecha: str
class DiaGlobalToggle(BaseModel): fecha: str

def calcular_proyeccion_usuario(usuario: Usuario, fecha_inicio_visual: date, dias_a_mostrar: int, dias_globales: set):
    # Usar las relaciones ya cargadas (eager loading)
    saldos = usuario.saldos
    total_tickets = sum(s.cantidad_tickets for s in saldos)

    excepciones_db = usuario.excepciones
    excepciones = {e.fecha: e.tipo_excepcion for e in excepciones_db}

    # Determinar desde cuándo empezamos a contar la contabilidad de este usuario
    fechas_relevantes = [date.today()]
    if saldos:
        fechas_relevantes.append(min(s.fecha_compra for s in saldos))
    if excepciones_db:
        fechas_relevantes.append(min(e.fecha for e in excepciones_db))
    fecha_inicio_consumo = min(fechas_relevantes)

    hoy = date.today()
    tickets_restantes = total_tickets
    deuda = 0

    estados_dias = {}
    limite_simulacion = max(hoy, fecha_inicio_visual) + timedelta(days=dias_a_mostrar)
    fecha_iter = fecha_inicio_consumo

    fecha_cobertura = None
    saldo_al_dia_de_hoy = 0

    # Simular día por día (La máquina del tiempo)
    while fecha_iter <= limite_simulacion:
        es_domingo = fecha_iter.weekday() == 6
        tipo_exc = excepciones.get(fecha_iter)
        es_global = fecha_iter in dias_globales

        come = False
        estado_base = ""

        # Día bloqueado globalmente (festivo, almuerzo empresa, etc.)
        if es_global and tipo_exc != "Come_Global":
            estado_base = "global_blocked"
        elif tipo_exc == "Ausencia":
            estado_base = "absence"
        elif es_domingo and tipo_exc != "Domingo_Habilitado":
            estado_base = "sunday_blocked"
        else:
            come = True

        if come:
            if tickets_restantes > 0:
                tickets_restantes -= 1
                estado_base = "covered"
                if tickets_restantes == 0:
                    fecha_cobertura = fecha_iter
            else:
                deuda += 1
                estado_base = "fiado"

        # Lógica de colores (Separar pasado, hoy y futuro)
        if fecha_iter < hoy:
            if estado_base == "covered": estado_visual = "past_covered"
            elif estado_base == "fiado": estado_visual = "past_fiado"
            elif estado_base == "absence": estado_visual = "past_absence"
            elif estado_base == "global_blocked": estado_visual = "past_global_blocked"
            else: estado_visual = "sunday_blocked"
        elif fecha_iter == hoy:
            estado_visual = estado_base
        else:
            if estado_base == "fiado":
                estado_visual = "sin_cobertura"
            else:
                estado_visual = estado_base

        estados_dias[fecha_iter] = estado_visual

        # Calcular el balance exacto hasta el día de hoy
        if fecha_iter == hoy:
            saldo_al_dia_de_hoy = tickets_restantes - deuda

        fecha_iter += timedelta(days=1)

    # Construir el calendario visual
    calendario = []
    curr_date = fecha_inicio_visual
    for _ in range(dias_a_mostrar):
        estado = estados_dias.get(curr_date, "past_absence" if curr_date < hoy else "sin_cobertura")
        calendario.append({"fecha": str(curr_date), "estado": estado, "es_hoy": curr_date == hoy})
        curr_date += timedelta(days=1)

    # Texto amigable para la cobertura
    if saldo_al_dia_de_hoy < 0:
        texto_cobertura = "En deuda"
    elif saldo_al_dia_de_hoy > 0 and not fecha_cobertura:
        texto_cobertura = "Suficiente para el mes"
    else:
        texto_cobertura = str(fecha_cobertura) if fecha_cobertura else "Sin saldo"

    return {
        "calendario": calendario,
        "saldo_actual": saldo_al_dia_de_hoy,
        "fecha_cobertura": texto_cobertura
    }

@app.post("/usuarios/")
def crear_usuario(user: UsuarioCreate, db: Session = Depends(get_db)):
    db.add(Usuario(nombre=user.nombre))
    db.commit()
    return {"message": "Usuario creado"}

@app.post("/usuarios/{usuario_id}/tickets")
def agregar_tickets(usuario_id: int, saldo: SaldoCreate, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.add(Saldo(usuario_id=usuario_id, cantidad_tickets=saldo.cantidad, fecha_compra=date.today()))
    db.commit()
    return {"message": "Tickets ajustados"}

@app.get("/dashboard")
def obtener_dashboard(db: Session = Depends(get_db)):
    usuarios = db.query(Usuario).options(
        joinedload(Usuario.saldos),
        joinedload(Usuario.excepciones)
    ).all()
    hoy = date.today()
    fecha_inicio = hoy - timedelta(days=4)
    dias_a_mostrar = 19

    # Cargar días globales bloqueados
    dias_globales_db = db.query(DiaGlobal).all()
    dias_globales = {d.fecha for d in dias_globales_db}

    resultado = []
    total_hoy = 0
    total_futuro = 0

    for u in usuarios:
        proyeccion = calcular_proyeccion_usuario(u, fecha_inicio, dias_a_mostrar, dias_globales)

        for dia in proyeccion["calendario"]:
            if dia["estado"] in ["covered", "fiado", "sin_cobertura"]:
                if dia["fecha"] == str(hoy): total_hoy += 1
                elif datetime.strptime(dia["fecha"], "%Y-%m-%d").date() > hoy: total_futuro += 1

        resultado.append({
            "id": u.id,
            "nombre": u.nombre,
            "saldo_actual": proyeccion["saldo_actual"],
            "fecha_cobertura": proyeccion["fecha_cobertura"],
            "calendario": proyeccion["calendario"]
        })

    return {
        "fechas_columnas": [str(fecha_inicio + timedelta(days=i)) for i in range(dias_a_mostrar)],
        "usuarios": resultado,
        "dias_globales": [str(d) for d in dias_globales],
        "metricas": {"almuerzos_hoy": total_hoy, "almuerzos_proximos": total_futuro}
    }

@app.post("/usuarios/{usuario_id}/excepcion")
def toggle_excepcion(usuario_id: int, req: ExcepcionToggle, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    fecha_obj = datetime.strptime(req.fecha, "%Y-%m-%d").date()
    es_domingo = fecha_obj.weekday() == 6
    es_global = db.query(DiaGlobal).filter_by(fecha=fecha_obj).first() is not None

    # Determinar el tipo de excepción según contexto
    if es_global:
        tipo = "Come_Global"  # Reactiva a esta persona en un día bloqueado
    elif es_domingo:
        tipo = "Domingo_Habilitado"
    else:
        tipo = "Ausencia"

    exc_existente = db.query(Excepcion).filter_by(usuario_id=usuario_id, fecha=fecha_obj).first()

    if exc_existente:
        db.delete(exc_existente)
    else:
        db.add(Excepcion(usuario_id=usuario_id, fecha=fecha_obj, tipo_excepcion=tipo))

    db.commit()
    return {"message": "Excepción procesada"}

@app.post("/dias-globales/")
def toggle_dia_global(req: DiaGlobalToggle, db: Session = Depends(get_db)):
    fecha_obj = datetime.strptime(req.fecha, "%Y-%m-%d").date()
    existente = db.query(DiaGlobal).filter_by(fecha=fecha_obj).first()

    if existente:
        # Al desactivar, limpiar excepciones Come_Global de ese día
        db.query(Excepcion).filter_by(fecha=fecha_obj, tipo_excepcion="Come_Global").delete()
        db.delete(existente)
        activo = False
    else:
        db.add(DiaGlobal(fecha=fecha_obj))
        activo = True

    db.commit()
    return {"message": "Día global procesado", "activo": activo}

@app.delete("/usuarios/{usuario_id}")
def eliminar_usuario(usuario_id: int, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.query(Saldo).filter(Saldo.usuario_id == usuario_id).delete()
    db.query(Excepcion).filter(Excepcion.usuario_id == usuario_id).delete()
    db.delete(usuario)
    db.commit()
    return {"message": "Usuario eliminado"}

@app.get("/exportar")
def exportar_excel(fecha: str, db: Session = Depends(get_db)):
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()
    usuarios = db.query(Usuario).options(
        joinedload(Usuario.saldos),
        joinedload(Usuario.excepciones)
    ).all()
    dias_globales = {d.fecha for d in db.query(DiaGlobal).all()}
    comensales = []

    for u in usuarios:
        proyeccion = calcular_proyeccion_usuario(u, fecha_obj, 1, dias_globales)
        estado_dia = proyeccion["calendario"][0]["estado"]
        # Se exportan a Excel tanto los que tienen tickets (covered) como los que deben (fiado)
        if estado_dia in ["covered", "fiado", "past_covered", "past_fiado"]:
            comensales.append(u.nombre)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"Comensales {fecha}"
    ws.append(["Nombre del Comensal", "Estado"])
    for c in comensales:
        ws.append([c, "Programado"])

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    
    return StreamingResponse(
        stream, 
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=comensales_{fecha}.xlsx"}
    )