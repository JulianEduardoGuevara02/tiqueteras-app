import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

security = HTTPBearer()


def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verifica el JWT de Supabase y retorna el payload del usuario."""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"JWT error: {type(e).__name__}: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def diagnostico_token(token: str):
    """Endpoint temporal para diagnosticar problemas de JWT."""
    import base64, json
    resultado = {
        "jwt_secret_configurado": bool(SUPABASE_JWT_SECRET),
        "jwt_secret_longitud": len(SUPABASE_JWT_SECRET),
        "jwt_secret_inicio": SUPABASE_JWT_SECRET[:4] + "..." if SUPABASE_JWT_SECRET else "(vacio)",
    }

    # Decodificar header del token sin verificar firma
    try:
        partes = token.split(".")
        header_raw = partes[0] + "=" * (4 - len(partes[0]) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_raw))
        resultado["token_header"] = header
    except Exception as e:
        resultado["token_header_error"] = str(e)

    # Intentar decodificar sin verificar
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], options={"verify_aud": False})
        resultado["decode_sin_aud"] = "OK"
        resultado["payload_aud"] = payload.get("aud")
    except JWTError as e:
        resultado["decode_sin_aud_error"] = f"{type(e).__name__}: {e}"

    # Intentar con audience
    try:
        jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
        resultado["decode_completo"] = "OK"
    except JWTError as e:
        resultado["decode_completo_error"] = f"{type(e).__name__}: {e}"

    return resultado
