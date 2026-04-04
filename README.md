# Tiqueteras - Sistema de Gestion de Alimentacion

Sistema web para gestionar las tiqueteras de almuerzos de las sedes de la empresa. Permite controlar tickets, excepciones, bloqueos de dias y exportar reportes por sede.

## Sedes

| Sede | Descripcion |
|------|-------------|
| Caribe | Sede principal |
| Manantiales | Sede secundaria |
| Olas | Sede secundaria |
| Aguas Claras | Sede secundaria |

## Como funciona

### Tickets y calendario
- Cada persona tiene un saldo de **tickets de almuerzo**
- El calendario muestra los proximos dias con colores:
  - **Verde**: dia cubierto (tiene tickets)
  - **Naranja**: dia fiado (sin tickets, genera deuda)
  - **Gris**: sin cobertura
  - **Rojo**: no come (excepcion) o dia bloqueado
- Un admin puede **abonar tickets** (la persona pago) o **quitar tickets** (corregir error)
- Click en un dia del calendario para marcar excepciones (ausencia, habilitar domingo, etc.)
- Click en el encabezado de fecha para **bloquear/desbloquear** un dia completo para toda la sede

### Roles

| Rol | Permisos |
|-----|----------|
| **Superadmin** | Ve todas las sedes, puede cambiar entre ellas, crear/desactivar sedes, agregar/eliminar admins, acceso total |
| **Admin** | Ve unicamente su sede asignada, gestiona personas, tickets, excepciones y dias bloqueados de su sede |

- El superadmin tiene un **dropdown** en el header para cambiar de sede
- El admin ve un **badge** fijo con el nombre de su sede
- Cada admin solo ve los **logs de auditoria** de su propia sede

### Panel de configuracion (solo superadmin)
- **Tab Sedes**: crear nuevas sedes, activar/desactivar sedes existentes
- **Tab Administradores**: asignar email + sede + rol, eliminar acceso a admins

### Auditoria
Todas las acciones quedan registradas: crear personas, ajustar tickets, bloquear dias, exportar Excel, etc. Cada log incluye fecha, email del admin, accion y detalle.

### Exportar Excel
Genera un archivo `.xlsx` con los comensales programados para el dia actual, filtrado por la sede seleccionada.

## Arquitectura

```
Frontend (Vercel)          Backend (Render)           Base de datos (Supabase)
  index.html  ──────────>  FastAPI + SQLAlchemy  ──>  PostgreSQL
  login.html                                           Supabase Auth (login)
  app.js
```

- **Frontend**: HTML + JavaScript + Tailwind CSS (CDN). Hosting estatico en Vercel.
- **Backend**: FastAPI con SQLAlchemy. Hosting en Render (free tier, cold start ~30-60s).
- **Base de datos**: PostgreSQL en Supabase. Autenticacion via Supabase Auth (JWT ES256).
- **Autenticacion**: Supabase Auth genera JWT → backend verifica con clave publica JWKS.

## Variables de entorno (Render)

| Variable | Descripcion |
|----------|-------------|
| `DATABASE_URL` | Connection string de PostgreSQL (Supabase) |
| `SUPABASE_URL` | URL del proyecto Supabase (ej: `https://xxx.supabase.co`) |
| `SUPERADMIN_EMAIL` | Email del primer superadmin (se crea automaticamente al iniciar) |
| `ALLOWED_ORIGINS` | Origenes permitidos para CORS (URL de Vercel) |

## Analisis de uso mensual (free tier)

Estimacion para 4 sedes con distintos niveles de uso.

### Escenarios

| Metrica | 1x/dia por sede | 3x/semana por sede | 1x/semana por sede |
|---------|-----------------|---------------------|--------------------|
| Sesiones/mes | ~88 | ~48 | ~16 |
| API calls/mes | ~1,760 | ~960 | ~320 |

*(~20 acciones por sesion: login, dashboard, ajustar tickets, excepciones, etc.)*

### Supabase Auth
- **Limite**: 50,000 usuarios activos/mes
- **Uso estimado**: 4-8 usuarios
- **Estado**: Sin riesgo (0.01% del limite)

### Supabase Database
- **Limite**: 500MB de almacenamiento
- **Crecimiento estimado**: ~0.5MB/mes
  - Usuarios: ~50KB/mes
  - Saldos: ~30KB/mes
  - Excepciones: ~15KB/mes
  - Logs auditoria: ~350KB/mes
- **Estado**: Sin riesgo. Tardaria anos en alcanzar el limite.

### Render (Backend)
- **Limite**: 750 horas/mes de ejecucion
- **Uso estimado**:
  - Uso normal (1x/dia): ~44 horas/mes
  - Uso intensivo (4 sedes simultaneas en horario laboral): ~176 horas/mes
  - Peor caso (24/7 sin apagarse): 720 horas/mes
- **Estado**: Sin riesgo en cualquier escenario.

### Vercel (Frontend)
- **Limite**: 100GB bandwidth/mes
- **Uso estimado**: ~9MB/mes (pagina estatica ~100KB por carga)
- **Estado**: Sin riesgo (0.009% del limite)

### Posibles puntos de atencion

1. **Cold starts de Render**: despues de 15 min de inactividad, el servidor se duerme y la primera peticion tarda 30-60 segundos. La app maneja esto con reintentos automaticos y un indicador de carga.

2. **Conexiones simultaneas a la BD**: Supabase free tiene conexiones directas limitadas. Con 4 sedes es poco probable que falle, pero si las 4 hacen peticiones en el mismo instante podria haber rechazo temporal.

3. **Logs de auditoria a largo plazo**: la tabla crece ~20,000 filas/ano (~4MB). No afecta almacenamiento pero consultas sin paginacion serian lentas. La app ya usa paginacion.

### Veredicto

Con 4 sedes el sistema **no excede ningun limite** en ninguno de los escenarios. El unico punto debil es la experiencia del cold start en Render, que ya esta controlado con reintentos automaticos.
