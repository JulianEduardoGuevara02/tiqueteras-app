# Plan: Sistema de Recordatorios por Email

## Contexto
La app gestiona tiquetes de almuerzo para empleados. Se necesita enviar correos de recordatorio a personas con deuda (>7 tickets) o saldo bajo (<=3 tickets) desde el correo corporativo de la auxiliar via Microsoft Office 365 SMTP. El envio es manual desde un boton en el dashboard.

## Archivos a modificar
- `backend/models.py` — agregar campo `email` a Usuario
- `backend/main.py` — 3 endpoints nuevos + templates de email
- `frontend/index.html` — campo email en modal perfil + boton y modal de recordatorios
- `frontend/app.js` — funciones de guardar email + recordatorios

## Dependencias nuevas
**Ninguna.** Se usa `smtplib` y `email.mime` de la libreria estandar de Python.

---

## Prerequisitos (hacer ANTES de implementar)

### 1. Configurar SMTP de Office 365
La auxiliar necesita generar una **contrasena de aplicacion**:
1. Ir a https://account.microsoft.com/security
2. Iniciar sesion con el correo corporativo
3. Seguridad > Contrasenas de aplicacion > Crear nueva
4. Nombre: "Tiqueteras" > Copiar la contrasena generada

**Si no aparece la opcion:** el admin de IT tiene bloqueado SMTP AUTH. Alternativa: usar Resend (100 emails gratis/dia).

### 2. Ejecutar SQL en Supabase
Ir a Supabase > SQL Editor y ejecutar:
```sql
ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS email VARCHAR;
```
(`create_all` de SQLAlchemy no agrega columnas a tablas que ya existen)

### 3. Variables de entorno en Render
Agregar en Render > Environment:
| Variable | Valor |
|---|---|
| `SMTP_EMAIL` | correo de la auxiliar (ej: auxiliar@empresa.com) |
| `SMTP_PASSWORD` | contrasena de aplicacion generada en el paso 1 |

---

## Plan de implementacion

### Paso 1: Agregar campo `email` al modelo Usuario (models.py)
- Agregar `email = Column(String, nullable=True)` a la clase Usuario
- Nullable porque los usuarios existentes no tendran email al inicio

### Paso 2: Backend - 3 endpoints nuevos (main.py)

**2a. `PATCH /usuarios/{id}/email`**
- Actualiza el email de una persona
- Registra en auditoria

**2b. `POST /recordatorios/preview`**
- Recorre todos los usuarios y calcula su saldo
- Filtra: deuda > 7 tickets O saldo <= 3
- Retorna lista con: id, nombre, email, saldo_actual, tipo (deuda/saldo_bajo), tiene_email
- No envia nada, solo preview

**2c. `POST /recordatorios/enviar`**
- Recibe `{ usuario_ids: [1, 3, 7] }` (los seleccionados en el modal)
- Abre conexion SMTP a smtp.office365.com:587 con TLS
- Por cada usuario: genera email HTML segun tipo (deuda o saldo bajo) y envia
- Registra resultado en auditoria: "X enviados, Y errores"
- Retorna resumen de resultados por persona

**2d. Funciones helper de templates HTML**
- `_generar_email_deuda(nombre, deuda)` — "Tienes X tiquetes en deuda, por favor regulariza"
- `_generar_email_saldo_bajo(nombre, saldo)` — "Te quedan X tiquetes, te recomendamos adquirir mas"
- HTML inline simple con estilos, colores de la marca

**Imports necesarios (stdlib, no requieren pip):**
```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
```

### Paso 3: Frontend - campo email en modal de perfil (index.html + app.js)
- Agregar input de email + boton "Guardar" en el modal de perfil existente
- Incluir campo `email` en la respuesta del endpoint `/dashboard`
- Modificar `abrirModalPerfil()` para recibir y mostrar el email
- Nueva funcion `guardarEmail()` que hace PATCH al backend

### Paso 4: Frontend - boton y modal de recordatorios (index.html + app.js)

**En el header:**
- Boton icono de email (sobre/carta) antes del boton de historial

**Modal `modalRecordatorios`:**
- Tabla con columnas: checkbox, nombre, email, balance, tipo
- Checkbox "seleccionar todos" en el header de la tabla
- Personas sin email: checkbox deshabilitado + texto "Sin email" en gris
- Footer: contador "X con email de Y destinatarios" + boton "Enviar correos"
- Boton cambia a "Enviando..." mientras procesa
- Toast al terminar: "X correo(s) enviados" (verde) / "X fallaron" (rojo)

---

## Flujo del usuario
```
1. Agregar email a cada persona desde su perfil (una sola vez)
2. Click en boton "Recordatorios" en el header
3. Modal muestra preview: quienes recibirian correo y por que
4. Desmarcar si quiere excluir a alguien
5. Click "Enviar correos"
6. Backend envia via SMTP desde el correo de la auxiliar
7. Toast con resultado
8. Queda registrado en el historial de auditoria
```

## Verificacion post-implementacion
1. Agregar email a una persona de prueba desde su perfil
2. Asignar deuda >7 tickets a esa persona
3. Abrir modal de recordatorios > debe aparecer en la lista
4. Enviar > verificar que llega el correo al destinatario
5. Revisar historial de auditoria > debe registrar el envio
