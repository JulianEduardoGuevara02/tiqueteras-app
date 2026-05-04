import os
import calendar as cal_module
from fastapi import FastAPI, Depends, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc
from datetime import date, datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import io
import openpyxl
from models import SessionLocal, Usuario, Saldo, Excepcion, DiaGlobal, LogAuditoria, Sede, AdminSede, ConfiguracionSede, ComprasMercado
from auth import verificar_token

app = FastAPI(title="API Tiqueteras")

allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _cors_headers(request: Request) -> dict:
    origin = request.headers.get("origin", "")
    if "*" in allowed_origins or origin in allowed_origins:
        return {"Access-Control-Allow-Origin": origin or "*"}
    return {}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    headers = _cors_headers(request)
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)
    return JSONResponse(status_code=500, content={"detail": "Error interno del servidor"}, headers=headers)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# === Autorizacion por sede ===

def obtener_admin_sede(db: Session, email: str) -> AdminSede:
    admin = db.query(AdminSede).filter(AdminSede.email == email).first()
    if not admin:
        raise HTTPException(status_code=403, detail="No tienes acceso. Contacta al superadmin.")
    return admin

def obtener_sede_id(admin: AdminSede, sede_id_param: Optional[int] = None) -> Optional[int]:
    """Determina el sede_id a usar: admin usa su sede, superadmin usa el parametro."""
    if admin.rol == "superadmin":
        return sede_id_param
    return admin.sede_id

def verificar_acceso_usuario(admin: AdminSede, usuario: Usuario):
    """Verifica que el admin tiene acceso al usuario."""
    if admin.rol == "superadmin":
        return
    if usuario.sede_id != admin.sede_id:
        raise HTTPException(status_code=403, detail="No tienes acceso a este usuario")

def verificar_superadmin(admin: AdminSede):
    if admin.rol != "superadmin":
        raise HTTPException(status_code=403, detail="Acceso solo para superadmin")

def registrar_log(db: Session, email: str, accion: str, detalle: str, sede_id: Optional[int] = None):
    db.add(LogAuditoria(email=email, accion=accion, detalle=detalle, sede_id=sede_id))

# === Pydantic models ===

class UsuarioCreate(BaseModel):
    nombre: str
    sede_id: Optional[int] = None
    tipo: str = "recurrente"

class SaldoCreate(BaseModel):
    cantidad: Optional[int] = None
    precio_snapshot: Optional[float] = None
    monto_pagado: Optional[float] = None
    observacion: Optional[str] = None

class ExcepcionToggle(BaseModel): fecha: str
class DiaGlobalToggle(BaseModel): fecha: str
class EmailUpdate(BaseModel): email: Optional[str] = None
class TipoUpdate(BaseModel): tipo: str
class SedeCreate(BaseModel): nombre: str
class SedeUpdate(BaseModel):
    nombre: Optional[str] = None
    activa: Optional[int] = None

class AdminSedeCreate(BaseModel):
    email: str
    sede_id: Optional[int] = None
    rol: str = "admin"

class AdminSedeUpdate(BaseModel):
    sede_id: Optional[int] = None
    rol: Optional[str] = None

class PrecioTicketUpdate(BaseModel):
    precio_ticket: float

class PrecioEmpresaUpdate(BaseModel):
    precio_empresa: float

class CompraCreate(BaseModel):
    monto: float
    descripcion: Optional[str] = None
    observacion: Optional[str] = None
    sede_id: Optional[int] = None
    fecha: Optional[str] = None  # YYYY-MM-DD; si no se envía usa hoy

class CompraUpdate(BaseModel):
    monto: float
    descripcion: Optional[str] = None

# === Proyeccion (sin cambios) ===

def calcular_proyeccion_usuario(usuario: Usuario, fecha_inicio_visual: date, dias_a_mostrar: int, dias_globales: set):
    tipo = getattr(usuario, "tipo", "recurrente") or "recurrente"
    es_esporadico = tipo == "esporadico"
    es_empresa = tipo == "empresa"
    saldos = usuario.saldos
    total_tickets = sum(s.cantidad_tickets for s in saldos)

    excepciones_db = usuario.excepciones
    excepciones = {e.fecha: e.tipo_excepcion for e in excepciones_db}

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
    limite_simulacion = max(hoy, fecha_inicio_visual + timedelta(days=dias_a_mostrar))
    fecha_iter = fecha_inicio_consumo

    fecha_cobertura = None
    saldo_al_dia_de_hoy = 0

    while fecha_iter <= limite_simulacion:
        es_domingo = fecha_iter.weekday() == 6
        tipo_exc = excepciones.get(fecha_iter)
        es_global = fecha_iter in dias_globales

        come = False
        estado_base = ""

        if es_empresa:
            # Cuenta empresa: come solo cuando hay asistencia explícita (igual que esporádico)
            if tipo_exc == "Asistencia":
                come = True
                estado_base = "empresa"
            else:
                estado_base = "sunday_blocked"
        elif es_esporadico:
            if tipo_exc == "Asistencia":
                come = True
            else:
                estado_base = "sunday_blocked"
        else:
            # Recurrente: logica original
            if es_global and tipo_exc != "Come_Global":
                estado_base = "global_blocked"
            elif tipo_exc == "Ausencia":
                estado_base = "absence"
            elif es_domingo and tipo_exc != "Domingo_Habilitado":
                estado_base = "sunday_blocked"
            else:
                come = True

        if come and not es_empresa:
            if tickets_restantes > 0:
                tickets_restantes -= 1
                estado_base = "covered"
                if tickets_restantes == 0:
                    fecha_cobertura = fecha_iter
            else:
                deuda += 1
                estado_base = "fiado"

        if fecha_iter < hoy:
            if estado_base == "covered": estado_visual = "past_covered"
            elif estado_base == "empresa": estado_visual = "past_empresa"
            elif estado_base == "fiado": estado_visual = "past_fiado"
            elif estado_base == "absence": estado_visual = "past_absence"
            elif estado_base == "global_blocked": estado_visual = "past_global_blocked"
            else: estado_visual = "sunday_blocked"
        elif fecha_iter == hoy:
            estado_visual = estado_base
        else:
            if estado_base == "fiado":
                estado_visual = "fiado" if es_esporadico else "sin_cobertura"
            else:
                estado_visual = estado_base

        estados_dias[fecha_iter] = estado_visual

        if fecha_iter == hoy:
            saldo_al_dia_de_hoy = tickets_restantes - deuda

        fecha_iter += timedelta(days=1)

    calendario = []
    curr_date = fecha_inicio_visual
    for _ in range(dias_a_mostrar):
        if es_esporadico or es_empresa:
            default = "sunday_blocked"
        else:
            default = "past_absence" if curr_date < hoy else "sin_cobertura"
        estado = estados_dias.get(curr_date, default)
        calendario.append({"fecha": str(curr_date), "estado": estado, "es_hoy": curr_date == hoy})
        curr_date += timedelta(days=1)

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

# === Endpoint: Mi perfil ===

@app.get("/mi-perfil")
def mi_perfil(db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    email = auth_user.get("email", "")
    admin = obtener_admin_sede(db, email)
    resultado = {
        "email": admin.email,
        "rol": admin.rol,
        "sede_id": admin.sede_id,
        "sede_nombre": None,
        "sedes": []
    }
    if admin.sede_id:
        sede = db.query(Sede).filter(Sede.id == admin.sede_id).first()
        resultado["sede_nombre"] = sede.nombre if sede else None
    if admin.rol == "superadmin":
        resultado["sedes"] = [
            {"id": s.id, "nombre": s.nombre, "activa": s.activa}
            for s in db.query(Sede).order_by(Sede.id).all()
        ]
    return resultado

# === Endpoints: CRUD de operaciones (filtrado por sede) ===

@app.post("/usuarios/")
def crear_usuario(user: UsuarioCreate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sede_id = obtener_sede_id(admin, user.sede_id)
    existente = db.query(Usuario).filter(
        Usuario.nombre == user.nombre, Usuario.sede_id == sede_id
    ).first()
    if existente:
        raise HTTPException(status_code=400, detail=f'Ya existe "{user.nombre}" en esta sede')
    tipo = user.tipo if user.tipo in ("recurrente", "esporadico", "empresa") else "recurrente"
    db.add(Usuario(nombre=user.nombre, sede_id=sede_id, tipo=tipo))
    registrar_log(db, admin.email, "Crear persona", user.nombre, sede_id)
    db.commit()
    return {"message": "Usuario creado"}

@app.post("/usuarios/{usuario_id}/tickets")
def agregar_tickets(usuario_id: int, saldo: SaldoCreate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)

    # Calcular cantidad desde monto si se provee
    if saldo.monto_pagado is not None and saldo.monto_pagado > 0:
        config = db.query(ConfiguracionSede).filter_by(sede_id=usuario.sede_id).first()
        precio = config.precio_ticket if config and config.precio_ticket > 0 else 0.0
        if precio <= 0:
            raise HTTPException(status_code=400, detail="Configura el precio del tiquete antes de registrar un pago por monto")
        cantidad = round(saldo.monto_pagado / precio)
        precio_snap = precio
        monto = saldo.monto_pagado
    elif saldo.cantidad is not None:
        cantidad = saldo.cantidad
        precio_snap = saldo.precio_snapshot
        monto = saldo.monto_pagado
    else:
        raise HTTPException(status_code=400, detail="Debes indicar cantidad o monto_pagado")

    db.add(Saldo(
        usuario_id=usuario_id,
        cantidad_tickets=cantidad,
        fecha_compra=date.today(),
        precio_snapshot=precio_snap,
        monto_pagado=monto,
        observacion=saldo.observacion,
    ))
    signo = "+" if cantidad > 0 else ""
    detalle = f"{signo}{cantidad} tickets a {usuario.nombre}"
    if saldo.observacion:
        detalle += f" — {saldo.observacion}"
    registrar_log(db, admin.email, "Ajustar tickets", detalle, usuario.sede_id)
    db.commit()
    return {"message": "Tickets ajustados", "cantidad": cantidad}

@app.put("/usuarios/{usuario_id}/email")
def actualizar_email(usuario_id: int, req: EmailUpdate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)
    email_anterior = usuario.email or "vacio"
    usuario.email = req.email.strip() if req.email and req.email.strip() else None
    registrar_log(db, admin.email, "Actualizar email", f"{usuario.nombre}: {email_anterior} -> {usuario.email or 'vacio'}", usuario.sede_id)
    db.commit()
    return {"message": "Email actualizado", "email": usuario.email}

@app.get("/dashboard")
def obtener_dashboard(
    sede_id: Optional[int] = Query(default=None),
    incluir_inactivos: int = Query(default=0),
    offset_dias: int = Query(default=0),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)

    query_usuarios = db.query(Usuario).options(
        joinedload(Usuario.saldos),
        joinedload(Usuario.excepciones)
    )
    if not incluir_inactivos:
        query_usuarios = query_usuarios.filter(Usuario.activo == 1)
    if sid is not None:
        query_usuarios = query_usuarios.filter(Usuario.sede_id == sid)
    usuarios = query_usuarios.all()

    hoy = date.today()
    fecha_inicio = hoy - timedelta(days=4) + timedelta(days=offset_dias)
    dias_a_mostrar = 19

    query_globales = db.query(DiaGlobal)
    if sid is not None:
        query_globales = query_globales.filter(DiaGlobal.sede_id == sid)
    dias_globales = {d.fecha for d in query_globales.all()}

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
            "activo": u.activo,
            "email": u.email,
            "tipo": getattr(u, "tipo", "recurrente") or "recurrente",
            "saldo_actual": proyeccion["saldo_actual"],
            "fecha_cobertura": proyeccion["fecha_cobertura"],
            "calendario": proyeccion["calendario"]
        })

    # Nombre de la sede actual
    sede_nombre = None
    if sid is not None:
        sede = db.query(Sede).filter(Sede.id == sid).first()
        sede_nombre = sede.nombre if sede else None

    return {
        "sede_id": sid,
        "sede_nombre": sede_nombre,
        "fechas_columnas": [str(fecha_inicio + timedelta(days=i)) for i in range(dias_a_mostrar)],
        "usuarios": resultado,
        "dias_globales": [str(d) for d in dias_globales],
        "metricas": {"almuerzos_hoy": total_hoy, "almuerzos_proximos": total_futuro}
    }

@app.post("/usuarios/{usuario_id}/excepcion")
def toggle_excepcion(usuario_id: int, req: ExcepcionToggle, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)
    fecha_obj = datetime.strptime(req.fecha, "%Y-%m-%d").date()
    es_esporadico = getattr(usuario, "tipo", "recurrente") == "esporadico"
    es_empresa = getattr(usuario, "tipo", "recurrente") == "empresa"
    es_domingo = fecha_obj.weekday() == 6
    es_global = db.query(DiaGlobal).filter_by(fecha=fecha_obj, sede_id=usuario.sede_id).first() is not None

    if es_esporadico or es_empresa:
        tipo = "Asistencia"
    elif es_global:
        tipo = "Come_Global"
    elif es_domingo:
        tipo = "Domingo_Habilitado"
    else:
        tipo = "Ausencia"

    exc_existente = db.query(Excepcion).filter_by(usuario_id=usuario_id, fecha=fecha_obj).first()

    if exc_existente:
        db.delete(exc_existente)
        registrar_log(db, admin.email, "Quitar excepcion", f"{usuario.nombre} en {req.fecha} ({tipo})", usuario.sede_id)
    else:
        db.add(Excepcion(usuario_id=usuario_id, fecha=fecha_obj, tipo_excepcion=tipo))
        registrar_log(db, admin.email, "Agregar excepcion", f"{usuario.nombre} en {req.fecha} ({tipo})", usuario.sede_id)

    db.commit()
    return {"message": "Excepcion procesada"}

@app.post("/dias-globales/")
def toggle_dia_global(req: DiaGlobalToggle, sede_id: Optional[int] = Query(default=None), db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    fecha_obj = datetime.strptime(req.fecha, "%Y-%m-%d").date()
    existente = db.query(DiaGlobal).filter_by(fecha=fecha_obj, sede_id=sid).first()

    if existente:
        # Limpiar excepciones Come_Global de esa sede/fecha
        usuarios_sede = [u.id for u in db.query(Usuario.id).filter(Usuario.sede_id == sid).all()]
        if usuarios_sede:
            db.query(Excepcion).filter(
                Excepcion.fecha == fecha_obj,
                Excepcion.tipo_excepcion == "Come_Global",
                Excepcion.usuario_id.in_(usuarios_sede)
            ).delete(synchronize_session=False)
        db.delete(existente)
        registrar_log(db, admin.email, "Quitar festivo", req.fecha, sid)
        activo = False
    else:
        db.add(DiaGlobal(fecha=fecha_obj, sede_id=sid))
        registrar_log(db, admin.email, "Marcar festivo", req.fecha, sid)
        activo = True

    db.commit()
    return {"message": "Dia global procesado", "activo": activo}

@app.delete("/usuarios/{usuario_id}")
def eliminar_usuario(usuario_id: int, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)
    nombre = usuario.nombre
    sid = usuario.sede_id
    db.query(Saldo).filter(Saldo.usuario_id == usuario_id).delete()
    db.query(Excepcion).filter(Excepcion.usuario_id == usuario_id).delete()
    db.delete(usuario)
    registrar_log(db, admin.email, "Eliminar persona", nombre, sid)
    db.commit()
    return {"message": "Usuario eliminado"}

@app.put("/usuarios/{usuario_id}/toggle-activo")
def toggle_activo_usuario(usuario_id: int, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)
    usuario.activo = 0 if usuario.activo == 1 else 1
    estado = "Activar" if usuario.activo == 1 else "Desactivar"
    registrar_log(db, admin.email, f"{estado} persona", usuario.nombre, usuario.sede_id)
    db.commit()
    return {"message": f"Usuario {'activado' if usuario.activo == 1 else 'desactivado'}", "activo": usuario.activo}

@app.put("/usuarios/{usuario_id}/tipo")
def cambiar_tipo_usuario(usuario_id: int, req: TipoUpdate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    verificar_acceso_usuario(admin, usuario)
    if req.tipo not in ("recurrente", "esporadico", "empresa"):
        raise HTTPException(status_code=400, detail="Tipo debe ser 'recurrente', 'esporadico' o 'empresa'")
    usuario.tipo = req.tipo
    registrar_log(db, admin.email, "Cambiar tipo", f"{usuario.nombre}: {req.tipo}", usuario.sede_id)
    db.commit()
    return {"message": "Tipo actualizado", "tipo": usuario.tipo}

@app.get("/auditoria")
def obtener_auditoria(
    limite: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)

    query = db.query(LogAuditoria)
    if admin.rol != "superadmin":
        query = query.filter(LogAuditoria.sede_id == admin.sede_id)
    elif sid is not None:
        query = query.filter((LogAuditoria.sede_id == sid) | (LogAuditoria.sede_id == None))

    total = query.count()
    logs = query.order_by(desc(LogAuditoria.fecha)).offset(offset).limit(limite).all()
    return {
        "total": total,
        "logs": [
            {
                "fecha": log.fecha.strftime("%Y-%m-%d %H:%M") if log.fecha else "",
                "email": log.email,
                "accion": log.accion,
                "detalle": log.detalle,
            }
            for log in logs
        ]
    }

@app.get("/exportar")
def exportar_excel(fecha: str, sede_id: Optional[int] = Query(default=None), db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    fecha_obj = datetime.strptime(fecha, "%Y-%m-%d").date()

    query_usuarios = db.query(Usuario).options(
        joinedload(Usuario.saldos),
        joinedload(Usuario.excepciones)
    ).filter(Usuario.activo == 1)
    if sid is not None:
        query_usuarios = query_usuarios.filter(Usuario.sede_id == sid)
    usuarios = query_usuarios.all()

    query_globales = db.query(DiaGlobal)
    if sid is not None:
        query_globales = query_globales.filter(DiaGlobal.sede_id == sid)
    dias_globales = {d.fecha for d in query_globales.all()}

    comensales = []
    for u in usuarios:
        proyeccion = calcular_proyeccion_usuario(u, fecha_obj, 1, dias_globales)
        estado_dia = proyeccion["calendario"][0]["estado"]
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

    registrar_log(db, admin.email, "Exportar Excel", f"Fecha: {fecha}, {len(comensales)} comensales", sid)
    db.commit()

    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=comensales_{fecha}.xlsx"}
    )

# === Endpoints: Superadmin - Gestión de sedes ===

@app.get("/admin/sedes")
def listar_sedes(db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    sedes = db.query(Sede).order_by(Sede.id).all()
    return [{"id": s.id, "nombre": s.nombre, "activa": s.activa} for s in sedes]

@app.post("/admin/sedes")
def crear_sede(req: SedeCreate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    existente = db.query(Sede).filter(Sede.nombre == req.nombre).first()
    if existente:
        raise HTTPException(status_code=400, detail="Ya existe una sede con ese nombre")
    sede = Sede(nombre=req.nombre, activa=1)
    db.add(sede)
    registrar_log(db, admin.email, "Crear sede", req.nombre)
    db.commit()
    return {"id": sede.id, "nombre": sede.nombre, "activa": sede.activa}

@app.put("/admin/sedes/{sede_id}")
def editar_sede(sede_id: int, req: SedeUpdate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    sede = db.query(Sede).filter(Sede.id == sede_id).first()
    if not sede:
        raise HTTPException(status_code=404, detail="Sede no encontrada")
    if req.nombre is not None:
        sede.nombre = req.nombre
    if req.activa is not None:
        sede.activa = req.activa
    registrar_log(db, admin.email, "Editar sede", f"{sede.nombre} (activa={sede.activa})")
    db.commit()
    return {"id": sede.id, "nombre": sede.nombre, "activa": sede.activa}

# === Endpoints: Superadmin - Gestión de admins ===

@app.get("/admin/admins")
def listar_admins(db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    admins = db.query(AdminSede).order_by(AdminSede.id).all()
    resultado = []
    for a in admins:
        sede_nombre = None
        if a.sede_id:
            sede = db.query(Sede).filter(Sede.id == a.sede_id).first()
            sede_nombre = sede.nombre if sede else None
        resultado.append({
            "id": a.id,
            "email": a.email,
            "sede_id": a.sede_id,
            "sede_nombre": sede_nombre,
            "rol": a.rol
        })
    return resultado

@app.post("/admin/admins")
def crear_admin(req: AdminSedeCreate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    existente = db.query(AdminSede).filter(AdminSede.email == req.email).first()
    if existente:
        raise HTTPException(status_code=400, detail="Este email ya tiene un rol asignado")
    if req.rol not in ("admin", "superadmin"):
        raise HTTPException(status_code=400, detail="Rol debe ser 'admin' o 'superadmin'")
    nuevo = AdminSede(email=req.email, sede_id=req.sede_id, rol=req.rol)
    db.add(nuevo)
    registrar_log(db, admin.email, "Crear admin", f"{req.email} como {req.rol}")
    db.commit()
    return {"id": nuevo.id, "email": nuevo.email, "sede_id": nuevo.sede_id, "rol": nuevo.rol}

@app.put("/admin/admins/{admin_id}")
def editar_admin(admin_id: int, req: AdminSedeUpdate, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    target = db.query(AdminSede).filter(AdminSede.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin no encontrado")
    if req.sede_id is not None:
        target.sede_id = req.sede_id
    if req.rol is not None:
        if req.rol not in ("admin", "superadmin"):
            raise HTTPException(status_code=400, detail="Rol debe ser 'admin' o 'superadmin'")
        target.rol = req.rol
    registrar_log(db, admin.email, "Editar admin", f"{target.email}: rol={target.rol}, sede={target.sede_id}")
    db.commit()
    return {"id": target.id, "email": target.email, "sede_id": target.sede_id, "rol": target.rol}

@app.delete("/admin/admins/{admin_id}")
def eliminar_admin(admin_id: int, db: Session = Depends(get_db), auth_user: dict = Depends(verificar_token)):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    verificar_superadmin(admin)
    target = db.query(AdminSede).filter(AdminSede.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Admin no encontrado")
    if target.email == admin.email:
        raise HTTPException(status_code=400, detail="No puedes eliminarte a ti mismo")
    email_target = target.email
    db.delete(target)
    registrar_log(db, admin.email, "Eliminar admin", email_target)
    db.commit()
    return {"message": "Admin eliminado"}

# === Endpoints: Configuracion de precio ===

@app.get("/configuracion")
def obtener_configuracion(
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    config = db.query(ConfiguracionSede).filter_by(sede_id=sid).first()
    return {"precio_ticket": config.precio_ticket if config else 0.0, "sede_id": sid}

@app.put("/configuracion/precio-ticket")
def actualizar_precio_ticket(
    req: PrecioTicketUpdate,
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    if req.precio_ticket < 0:
        raise HTTPException(status_code=400, detail="El precio no puede ser negativo")
    config = db.query(ConfiguracionSede).filter_by(sede_id=sid).first()
    if config:
        precio_anterior = config.precio_ticket
        config.precio_ticket = req.precio_ticket
    else:
        precio_anterior = 0.0
        db.add(ConfiguracionSede(sede_id=sid, precio_ticket=req.precio_ticket))
    registrar_log(db, admin.email, "Cambiar precio tiquete",
                  f"${precio_anterior:,.0f} → ${req.precio_ticket:,.0f} COP", sid)
    db.commit()
    return {"precio_ticket": req.precio_ticket, "sede_id": sid}

@app.put("/configuracion/precio-empresa")
def actualizar_precio_empresa(
    req: PrecioEmpresaUpdate,
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    if req.precio_empresa < 0:
        raise HTTPException(status_code=400, detail="El precio no puede ser negativo")
    config = db.query(ConfiguracionSede).filter_by(sede_id=sid).first()
    if config:
        config.precio_empresa = req.precio_empresa
    else:
        db.add(ConfiguracionSede(sede_id=sid, precio_empresa=req.precio_empresa))
    db.commit()
    return {"precio_empresa": req.precio_empresa, "sede_id": sid}

# === Endpoints: Compras de mercado ===

@app.post("/mercado/")
def registrar_compra(
    req: CompraCreate,
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, req.sede_id or sede_id)
    if req.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    if req.fecha:
        try:
            fecha_dt = datetime.combine(date.fromisoformat(req.fecha), datetime.min.time())
        except ValueError:
            fecha_dt = datetime.utcnow()
    else:
        fecha_dt = datetime.utcnow()
    compra = ComprasMercado(
        monto=req.monto,
        descripcion=req.descripcion,
        observacion=req.observacion,
        fecha=fecha_dt,
        sede_id=sid,
        admin_email=admin.email,
    )
    db.add(compra)
    detalle = f"${req.monto:,.0f} COP"
    if req.descripcion:
        detalle += f" — {req.descripcion}"
    registrar_log(db, admin.email, "Compra mercado", detalle, sid)
    db.commit()
    db.refresh(compra)
    return {
        "id": compra.id,
        "monto": compra.monto,
        "descripcion": compra.descripcion,
        "observacion": compra.observacion,
        "fecha": compra.fecha.strftime("%Y-%m-%d %H:%M"),
    }

@app.delete("/mercado/{compra_id}")
def eliminar_compra(
    compra_id: int,
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    compra = db.query(ComprasMercado).filter(ComprasMercado.id == compra_id).first()
    if not compra:
        raise HTTPException(status_code=404, detail="Compra no encontrada")
    if admin.rol != "superadmin" and compra.sede_id != admin.sede_id:
        raise HTTPException(status_code=403, detail="Sin acceso a esta compra")
    registrar_log(db, admin.email, "Eliminar compra mercado",
                  f"${compra.monto:,.0f} COP — {compra.descripcion or 'sin descripcion'}", sid)
    db.delete(compra)
    db.commit()
    return {"message": "Compra eliminada"}

@app.put("/mercado/{compra_id}")
def editar_compra(
    compra_id: int,
    req: CompraUpdate,
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    compra = db.query(ComprasMercado).filter(ComprasMercado.id == compra_id).first()
    if not compra:
        raise HTTPException(status_code=404, detail="Compra no encontrada")
    if admin.rol != "superadmin" and compra.sede_id != admin.sede_id:
        raise HTTPException(status_code=403, detail="Sin acceso a esta compra")
    compra.monto = req.monto
    compra.descripcion = req.descripcion
    registrar_log(db, admin.email, "Editar compra mercado",
                  f"${req.monto:,.0f} — {req.descripcion or ''}", compra.sede_id)
    db.commit()
    return {"message": "Compra actualizada"}

# === Helpers semanas ===

def _rangos_semanas(cantidad: int, offset: int):
    """Returns list of (year_iso, week_iso, lunes, sabado) going backward, newest first."""
    hoy = date.today()
    lunes = hoy - timedelta(days=hoy.weekday())  # Monday of current week
    lunes -= timedelta(weeks=offset)
    rangos = []
    for _ in range(cantidad):
        sabado = lunes + timedelta(days=5)
        iso_cal = lunes.isocalendar()
        rangos.append((iso_cal[0], iso_cal[1], lunes, sabado))
        lunes -= timedelta(weeks=1)
    return rangos

@app.get("/finanzas/quincenas")
def resumen_quincenas(
    sede_id: Optional[int] = Query(default=None),
    offset: int = Query(default=0),
    cantidad: int = Query(default=5),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)
    rangos = _rangos_semanas(cantidad, offset)
    if not rangos:
        return {"quincenas": [], "precio_ticket": 0}

    fecha_global_inicio = rangos[-1][2]
    fecha_global_fin = rangos[0][3]
    dias_total = (fecha_global_fin - fecha_global_inicio).days + 1

    q_usuarios = db.query(Usuario).options(
        joinedload(Usuario.saldos),
        joinedload(Usuario.excepciones)
    ).filter(Usuario.activo == 1)
    if sid is not None:
        q_usuarios = q_usuarios.filter(Usuario.sede_id == sid)
    usuarios = q_usuarios.all()

    q_globales = db.query(DiaGlobal)
    if sid is not None:
        q_globales = q_globales.filter(DiaGlobal.sede_id == sid)
    dias_globales_set = {d.fecha for d in q_globales.all()}

    config = db.query(ConfiguracionSede).filter_by(sede_id=sid).first()
    precio = config.precio_ticket if config and config.precio_ticket else 0.0
    precio_empresa = config.precio_empresa if config and config.precio_empresa else 0.0

    # Mapear fecha → índice de semana
    fecha_a_idx = {}
    for i, (_, _, inicio, fin) in enumerate(rangos):
        d = inicio
        while d <= fin:
            fecha_a_idx[d] = i
            d += timedelta(days=1)

    stats = [{"pagados": 0, "fiados": 0, "empresa": 0} for _ in rangos]
    caja_pagado_tiq = 0
    caja_deuda_tiq = 0
    hoy = date.today()
    lunes_actual = hoy - timedelta(days=hoy.weekday())
    caja_empresa_tiq = 0

    for u in usuarios:
        proy = calcular_proyeccion_usuario(u, fecha_global_inicio, dias_total, dias_globales_set)
        for dia in proy["calendario"]:
            fd = date.fromisoformat(dia["fecha"])
            idx = fecha_a_idx.get(fd)
            if idx is None:
                continue
            estado = dia["estado"]
            if estado in ("covered", "past_covered"):
                stats[idx]["pagados"] += 1
            elif estado in ("fiado", "past_fiado"):
                stats[idx]["fiados"] += 1
            elif estado in ("empresa", "past_empresa"):
                stats[idx]["empresa"] += 1

        if (getattr(u, "tipo", "recurrente") or "recurrente") == "empresa":
            for e in u.excepciones:
                if e.tipo_excepcion == "Asistencia" and e.fecha >= lunes_actual:
                    caja_empresa_tiq += 1
        else:
            saldo = proy["saldo_actual"]
            if saldo > 0:
                caja_pagado_tiq += saldo
            elif saldo < 0:
                caja_deuda_tiq += abs(saldo)

    resultado = []
    for i, (year_iso, week_iso, inicio, fin) in enumerate(rangos):
        inicio_dt = datetime.combine(inicio, datetime.min.time())
        fin_dt = datetime.combine(fin, datetime.max.time())
        q_c = db.query(ComprasMercado).filter(
            ComprasMercado.fecha >= inicio_dt,
            ComprasMercado.fecha <= fin_dt,
        )
        if sid is not None:
            q_c = q_c.filter(ComprasMercado.sede_id == sid)
        compras = q_c.order_by(desc(ComprasMercado.fecha)).all()
        resultado.append({
            "year": year_iso,
            "semana_iso": f"{year_iso:04d}{week_iso:02d}",
            "fecha_inicio": str(inicio),
            "fecha_fin": str(fin),
            "pagados": {"tiquetes": stats[i]["pagados"], "cop": stats[i]["pagados"] * precio},
            "fiados":  {"tiquetes": stats[i]["fiados"],  "cop": stats[i]["fiados"]  * precio},
            "empresa": {"tiquetes": stats[i]["empresa"], "cop": stats[i]["empresa"] * precio_empresa},
            "mercado": {
                "cop": sum(c.monto for c in compras),
                "items": [{"id": c.id, "monto": c.monto, "descripcion": c.descripcion or "", "fecha": c.fecha.strftime("%Y-%m-%d")} for c in compras],
            },
        })
    return {
        "quincenas": resultado,
        "precio_ticket": precio,
        "precio_empresa": precio_empresa,
        "caja": {
            "pagado":  {"tiquetes": caja_pagado_tiq,  "cop": caja_pagado_tiq  * precio},
            "deuda":   {"tiquetes": caja_deuda_tiq,   "cop": caja_deuda_tiq   * precio},
            "empresa": {"tiquetes": caja_empresa_tiq, "cop": caja_empresa_tiq * precio_empresa},
        },
    }

# === Endpoints: Resumen financiero quincenal ===

@app.get("/finanzas/resumen")
def resumen_finanzas(
    sede_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    auth_user: dict = Depends(verificar_token)
):
    admin = obtener_admin_sede(db, auth_user.get("email", ""))
    sid = obtener_sede_id(admin, sede_id)

    # Quincena actual: 1-15 o 16-fin de mes
    hoy = date.today()
    if hoy.day <= 15:
        inicio = date(hoy.year, hoy.month, 1)
        fin = date(hoy.year, hoy.month, 15)
    else:
        inicio = date(hoy.year, hoy.month, 16)
        mes_siguiente = hoy.month % 12 + 1
        anio_siguiente = hoy.year + (1 if hoy.month == 12 else 0)
        fin = date(anio_siguiente, mes_siguiente, 1) - timedelta(days=1)

    inicio_dt = datetime.combine(inicio, datetime.min.time())
    fin_dt = datetime.combine(fin, datetime.max.time())

    # Ingresos: saldos positivos con monto en el periodo
    q_saldos = db.query(Saldo).join(Usuario).filter(
        Saldo.fecha_compra >= inicio,
        Saldo.fecha_compra <= fin,
        Saldo.monto_pagado != None,
        Saldo.monto_pagado > 0,
    )
    if sid is not None:
        q_saldos = q_saldos.filter(Usuario.sede_id == sid)
    saldos_periodo = q_saldos.all()
    total_pagos = sum(s.monto_pagado for s in saldos_periodo if s.monto_pagado)

    # Egresos: compras de mercado en el periodo
    q_compras = db.query(ComprasMercado).filter(
        ComprasMercado.fecha >= inicio_dt,
        ComprasMercado.fecha <= fin_dt,
    )
    if sid is not None:
        q_compras = q_compras.filter(ComprasMercado.sede_id == sid)
    compras_periodo = q_compras.order_by(desc(ComprasMercado.fecha)).all()
    total_compras = sum(c.monto for c in compras_periodo)

    config = db.query(ConfiguracionSede).filter_by(sede_id=sid).first()
    precio = config.precio_ticket if config else 0.0

    return {
        "periodo_inicio": str(inicio),
        "periodo_fin": str(fin),
        "precio_ticket": precio,
        "total_pagos": total_pagos,
        "total_compras": total_compras,
        "saldo_caja": total_pagos - total_compras,
        "compras": [
            {
                "id": c.id,
                "fecha": c.fecha.strftime("%Y-%m-%d %H:%M"),
                "monto": c.monto,
                "descripcion": c.descripcion or "",
                "observacion": c.observacion or "",
                "admin_email": c.admin_email,
            }
            for c in compras_periodo
        ],
    }
