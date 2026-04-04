# Plan: Sistema Multi-Sede con Superadmin

## Contexto
La empresa tiene 4 sedes. Se necesita que cada admin solo vea y gestione los datos de su sede. Un superadmin puede ver todas las sedes, configurar admins y crear sedes.

## Principio clave
**Misma base de datos, mismo backend, mismo frontend.** Solo se agrega filtrado por sede. Cero costo adicional en la nube.

## Archivos a modificar
- `backend/models.py` — 2 modelos nuevos + sede_id en 3 tablas existentes + migracion
- `backend/main.py` — helper de autorizacion, endpoint /mi-perfil, 6 endpoints /admin/*, modificar 8 endpoints existentes
- `frontend/index.html` — selector de sede, badge de sede, boton config, modal de configuracion
- `frontend/app.js` — cargarPerfil, cambio de sede, panel de configuracion superadmin
- `backend/auth.py` — sin cambios
- `frontend/login.html` — sin cambios

## Dependencias nuevas
**Ninguna.**

---

## Prerequisitos

### 1. Variable de entorno en Render
| Variable | Valor |
|---|---|
| `SUPERADMIN_EMAIL` | email del primer superadmin (el tuyo) |

### 2. SQL en Supabase (ejecutar DESPUES del primer deploy)
```sql
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS sede_id INTEGER REFERENCES sedes(id);
ALTER TABLE dias_globales ADD COLUMN IF NOT EXISTS sede_id INTEGER REFERENCES sedes(id);
ALTER TABLE log_auditoria ADD COLUMN IF NOT EXISTS sede_id INTEGER REFERENCES sedes(id);

-- Cambiar uniqueness de dias_globales (un dia puede estar bloqueado en una sede y no en otra)
ALTER TABLE dias_globales DROP CONSTRAINT IF EXISTS dias_globales_fecha_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_diaglobal_fecha_sede ON dias_globales(fecha, sede_id);

-- Indices de rendimiento
CREATE INDEX IF NOT EXISTS idx_usuarios_sede ON usuarios(sede_id);
CREATE INDEX IF NOT EXISTS idx_diasglobales_sede ON dias_globales(sede_id);
```
Nota: La app intentara hacer la migracion automaticamente al arrancar, pero si falla se ejecuta manual.

---

## Modelos nuevos (models.py)

### Tabla `sedes`
```
id          Integer, PK
nombre      String, unique, not null (ej: "Sede Norte", "Sede Sur")
activa      Integer, default 1 (1=activa, 0=inactiva)
```

### Tabla `admin_sedes`
Mapea cada email de Supabase Auth a una sede y un rol. Es la tabla central de autorizacion.
```
id          Integer, PK
email       String, unique, not null, index (email del admin en Supabase)
sede_id     Integer, FK a sedes.id, nullable (NULL = superadmin, ve todas)
rol         String, not null ("admin" o "superadmin")
```

### Columna `sede_id` agregada a tablas existentes
- `usuarios.sede_id` — FK a sedes.id, nullable
- `dias_globales.sede_id` — FK a sedes.id, nullable
- `log_auditoria.sede_id` — FK a sedes.id, nullable

Las tablas `saldos` y `excepciones` NO necesitan sede_id porque ya referencian a un usuario que tiene sede.

### Bootstrap automatico (al arrancar el backend)
Si la tabla `admin_sedes` esta vacia:
1. Crear sede "Principal" (id=1)
2. Crear superadmin con el email de la variable `SUPERADMIN_EMAIL`
3. Asignar todos los usuarios existentes a sede 1
4. Asignar todos los dias_globales existentes a sede 1

---

## Endpoints nuevos (main.py)

### `GET /mi-perfil`
Retorna rol, sede y lista de sedes del admin logueado.
```json
// Admin regular
{ "email": "admin@empresa.com", "rol": "admin", "sede_id": 1, "sede_nombre": "Sede Norte", "sedes": [] }

// Superadmin
{ "email": "super@empresa.com", "rol": "superadmin", "sede_id": null, "sede_nombre": null, "sedes": [{"id":1,"nombre":"Norte"},{"id":2,"nombre":"Sur"}] }
```

### Helper `obtener_admin_sede(db, email)`
Se llama en cada endpoint. Busca en admin_sedes por email.
- No existe → HTTP 403 "No tienes acceso"
- Existe → retorna AdminSede con .rol y .sede_id

### Endpoints de configuracion (solo superadmin)

| Endpoint | Metodo | Descripcion |
|---|---|---|
| `/admin/sedes` | GET | Listar todas las sedes |
| `/admin/sedes` | POST | Crear sede (body: nombre) |
| `/admin/sedes/{id}` | PUT | Editar nombre o activar/desactivar |
| `/admin/admins` | GET | Listar todos los admins con su sede |
| `/admin/admins` | POST | Asignar admin (body: email, sede_id, rol) |
| `/admin/admins/{id}` | PUT | Cambiar sede o rol |
| `/admin/admins/{id}` | DELETE | Quitar acceso |

---

## Modificaciones a endpoints existentes

### `GET /dashboard`
- Acepta `?sede_id=X`. Admin se fuerza a su sede. Superadmin elige.
- Filtra usuarios y dias_globales por sede_id

### `POST /usuarios/`
- Auto-asigna sede_id del admin o sede seleccionada del superadmin

### `POST /usuarios/{id}/tickets`, `POST /usuarios/{id}/excepcion`, `DELETE /usuarios/{id}`
- Verifica que el usuario pertenece a la sede del admin

### `POST /dias-globales/`
- Asocia al sede_id actual. Al eliminar, filtra por sede.

### `GET /auditoria`
- Admin ve logs de su sede. Superadmin ve todos.

### `GET /exportar`
- Filtra por sede

### `registrar_log()`
- Nuevo parametro: sede_id

---

## Frontend: cambios

### Variables globales nuevas (app.js)
```javascript
var miPerfil = null;    // {email, rol, sede_id, sede_nombre, sedes}
var sedeActual = null;  // sede_id actualmente visible
```

### Flujo de inicio modificado
```
Login → getSession() → cargarPerfil() → actualizarUISegunPerfil() → cargarDashboard()
```

### Header (index.html)
- **Admin regular**: badge estatico con nombre de sede ("Sede Norte")
- **Superadmin**: dropdown para cambiar entre sedes + boton engranaje (config)

### Modal de configuracion (superadmin)
Dos pestanas:
1. **Sedes**: tabla de sedes, crear/editar/activar-desactivar
2. **Administradores**: tabla de admins, crear/editar/eliminar, asignar sede y rol

### Dashboard
- URL cambia a `/dashboard?sede_id=X`
- `cambiarSede(id)` recarga el dashboard con la nueva sede

### Manejo de 403 (sin acceso)
Si /mi-perfil retorna 403, mostrar mensaje centrado: "Tu cuenta no tiene acceso. Contacta al administrador." Sin dashboard.

---

## Flujo por rol

### Admin regular
```
Login → ve badge "Sede Sur" → Dashboard solo de Sede Sur
→ Crea persona → se asigna a Sede Sur automaticamente
→ No ve boton config ni selector de sede
```

### Superadmin
```
Login → ve dropdown con todas las sedes + boton config
→ Selecciona sede → Dashboard de esa sede
→ Boton config → Crear sedes, asignar admins
```

### Sin acceso
```
Login OK en Supabase → /mi-perfil → 403
→ Mensaje: "Tu cuenta no tiene acceso"
```

---

## Seguridad
- Backend valida sede en CADA endpoint (no depende del frontend)
- Admin no puede modificar usuarios de otra sede
- Solo superadmin accede a /admin/*
- obtener_admin_sede() es obligatorio en todos los endpoints

---

## Orden de implementacion

1. `backend/models.py` — modelos + migracion + bootstrap
2. `backend/main.py` — /mi-perfil, /admin/*, modificar endpoints
3. Agregar `SUPERADMIN_EMAIL` en Render
4. Deploy backend
5. Ejecutar SQL en Supabase (si la migracion automatica fallo)
6. `frontend/index.html` — selector, badge, config modal
7. `frontend/app.js` — cargarPerfil, sede switching, panel config
8. Deploy frontend

---

## Verificacion

1. Login superadmin → ver dropdown y boton config
2. Crear 3 sedes desde config
3. Crear admin asignado a una sede
4. Login con ese admin → ver solo su sede
5. Crear personas en diferentes sedes → no se mezclan
6. Bloquear dia en una sede → no afecta otra
7. Exportar Excel → solo personas de la sede
8. Historial → admin ve su sede, superadmin ve todo
