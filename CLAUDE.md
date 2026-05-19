# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Tiqueteras is a multi-sede lunch ticket management system. Spanish-language UI and code identifiers (no translation needed — keep new code in Spanish to match).

Stack:
- **Backend** (`backend/`): FastAPI + SQLAlchemy 2.0, deployed to Render. Single-file `main.py` (~1160 lines) — no router split.
- **Frontend** (`frontend/`): static HTML + vanilla JS + Tailwind via CDN, deployed to Vercel. No build step, no bundler, no framework.
- **DB**: PostgreSQL on Supabase in prod, SQLite (`backend/tiqueteras.db`) in local dev — selected by `DATABASE_URL`.
- **Auth**: Supabase Auth issues ES256 JWTs; backend verifies via JWKS (`backend/auth.py`). Frontend uses `supabase-js` from CDN.

## Running locally

```powershell
# Backend (uses backend/tiqueteras.db SQLite when DATABASE_URL is unset)
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend has no build step — open `frontend/index.html` directly, or serve the folder statically. `app.js:6` auto-switches `API_URL` to `http://localhost:8000` when running on `localhost`, otherwise hits `https://tiqueteras-app.onrender.com`. The Supabase URL and anon key are hardcoded in `app.js:2-3` and `login.html`.

There are no tests, no linter, and no CI in this repo.

## Required environment variables (backend)

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | PostgreSQL connection string. Unset = SQLite fallback. `postgresql://` is auto-rewritten to `postgresql+psycopg://`. |
| `SUPABASE_URL` | Used to fetch JWKS for token verification (`auth.py`). |
| `SUPERADMIN_EMAIL` | Bootstrap-only: creates first sede "Principal" + superadmin row if `admin_sedes` is empty (`models.py:bootstrap_superadmin`). |
| `ALLOWED_ORIGINS` | CSV list for CORS. |
| `ALERTAS_API_KEY` | API key for the `/alertas/saldo-bajo` endpoint consumed by Power Automate. |
| `WEBHOOK_COMPRA_URL` | Optional. Power Automate webhook fired after a positive ticket purchase (sends purchase confirmation email). |

## Architecture

### Multi-sede authorization (`backend/main.py:85-108`)

Every protected endpoint resolves the caller through this pattern:
```python
admin = obtener_admin_sede(db, auth_user["email"])
sid = obtener_sede_id(admin, sede_id_param)  # superadmin uses query param, admin is forced to their own sede
```

`AdminSede.rol` is either `"admin"` (locked to `sede_id`) or `"superadmin"` (sees all, picks sede via `?sede_id=` query). `verificar_acceso_usuario` enforces sede ownership on per-user mutations. **Never call sede-scoped queries without going through these helpers** — they are the only authorization barrier between admins of different sedes.

### Projection engine (`calcular_proyeccion_usuario`, `main.py:163-276`)

The core domain logic. Given a user, a visible-window start date, and the set of sede holidays (`DiaGlobal`), it simulates day-by-day ticket consumption from the user's earliest activity through the visible window. It produces:
- A per-day `estado` string used as a CSS class by the frontend (e.g. `covered`, `fiado`, `sin_cobertura`, `empresa`, `past_*`, `global_blocked`, `sunday_blocked`).
- `saldo_actual` (tickets minus debt as of today).
- `fecha_cobertura` (when tickets run out, or "Suficiente para el mes" / "En deuda").

Behavior branches on `Usuario.tipo`:
- `recurrente`: eats every weekday by default, can mark absence/Sunday-enable/come-on-global-holiday.
- `esporadico`: only eats when there's an explicit `Asistencia` exception.
- `empresa`: like `esporadico` but **does not consume tickets** — settled separately via `precio_empresa`. Calendar state is `empresa`.

`/dashboard`, `/exportar`, `/finanzas/quincenas`, and `/alertas/saldo-bajo` all flow through this same function. If you change ticket/debt semantics, change them here.

### Snapshot pricing

`ConfiguracionSede.precio_ticket` is the **current** ticket price (mutable). `Saldo.precio_snapshot` + `Saldo.monto_pagado` freeze the price at payment time so historical records and the financial summary stay correct after a price change. When adding tickets, `POST /usuarios/{id}/tickets` accepts either `cantidad` (manual) or `monto_pagado` (derived: `round(monto / precio_actual)`). Preserve this snapshot pattern — historical Saldo rows must never be rewritten.

### Financial summaries

- `GET /finanzas/resumen?sede_id=`: current bi-weekly period (1–15 or 16–end-of-month). Sums `Saldo.monto_pagado` as income and `ComprasMercado.monto` as expense.
- `GET /finanzas/quincenas?sede_id=&offset=&cantidad=`: per-ISO-week breakdown (pagados / fiados / empresa / mercado). Iterates weeks backward from current Monday. Used by the "Finanzas" tab modal.

### DB migrations

There is no Alembic. `backend/models.py` runs `Base.metadata.create_all()` plus a chain of idempotent `ALTER TABLE` calls (`migrar_*` functions) at import time. They `SELECT` the new column, rollback on failure, then `ALTER TABLE ... ADD COLUMN`. To add a column: add it to the model **and** add a `migrar_*` function to this chain — don't expect `create_all` to alter existing tables.

### Frontend layout

`frontend/app.js` is one ~1500-line script using global `var` state (`usuarioActualId`, `sedeActual`, `precioTicket`, `sortMode`, `ultimosDatosDashboard`, etc.). All data fetches go through `obtenerToken()` to get a fresh Supabase JWT, then `fetch(API_URL + path, { headers: { Authorization: "Bearer " + token } })`. Cold-start handling: the loading overlay (`mostrarCarga`/`ocultarCarga`) covers the 30–60s Render wake-up on the first request.

State worth knowing:
- `ultimosDatosDashboard` caches the last `/dashboard` response so re-sorting (`sortMode = "nombre" | "saldo_asc"`) re-renders without a refetch.
- The calendar shows a 19-day window starting `today - 4 + offsetDias`. The `offsetDias` global pages it.

## Conventions

- **All identifiers and user-facing strings are in Spanish.** Keep it that way — don't translate.
- **No comments unless non-obvious.** Existing code mostly follows this; don't add narration.
- **Single-file backend / single-file frontend.** Don't split into routers, modules, or components unless the user asks — the project is intentionally small.
- **No tests.** When the user asks for verification of a change, run the backend locally and exercise the endpoint, or load `index.html` in a browser. Don't propose a test suite unprompted.
- **Logs are user-visible audit trail**, not debug output. Every mutation calls `registrar_log(db, admin.email, accion, detalle, sede_id)` and these surface in the UI's audit tab — write `accion`/`detalle` strings the admin will read.
