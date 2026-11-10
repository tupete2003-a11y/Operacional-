"""TikTok Login Kit OAuth 2.0 flow. Tokens are encrypted before database storage."""
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from cryptography.fernet import Fernet, InvalidToken

from . import store

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


class TikTokOAuthError(Exception):
    pass


def _settings():
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "").strip()
    encryption_key = os.getenv("AUTOMA_TOKEN_ENCRYPTION_KEY", "").strip()
    if not client_key or not client_secret or not redirect_uri:
        raise TikTokOAuthError("Configure TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET e TIKTOK_REDIRECT_URI no Render.")
    if not redirect_uri.startswith("https://") or "?" in redirect_uri or "#" in redirect_uri:
        raise TikTokOAuthError("TIKTOK_REDIRECT_URI precisa ser uma URL HTTPS fixa, sem parâmetros ou fragmentos.")
    if not encryption_key:
        raise TikTokOAuthError("A chave de criptografia do armazenamento seguro não está configurada.")
    try:
        cipher = Fernet(encryption_key.encode("ascii"))
    except Exception as exc:
        raise TikTokOAuthError("AUTOMA_TOKEN_ENCRYPTION_KEY inválida; use uma chave Fernet válida.") from exc
    return client_key, client_secret, redirect_uri, cipher


def begin_authorization():
    if store.backend() != "postgresql":
        raise TikTokOAuthError("Para preservar os tokens após reinicializações, o AUTOMA X precisa de um banco PostgreSQL durável. A conexão OAuth ficará bloqueada até esse banco estar configurado.")
    client_key, _, redirect_uri, _ = _settings()
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    store.save_oauth_state(state_hash, expires_at)
    scopes = os.getenv("TIKTOK_SCOPES", "user.info.basic,video.publish").strip()
    if not scopes:
        scopes = "user.info.basic,video.publish"
    params = {
        "client_key": client_key,
        "response_type": "code",
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return AUTHORIZE_URL + "?" + urlencode(params), state


def complete_authorization(code, returned_state, cookie_state):
    if not code or not returned_state or not cookie_state:
        raise TikTokOAuthError("Retorno OAuth incompleto. Inicie a conexão novamente.")
    if not secrets.compare_digest(returned_state, cookie_state):
        raise TikTokOAuthError("Validação de segurança do OAuth falhou. Inicie a conexão novamente.")
    state_hash = hashlib.sha256(cookie_state.encode("utf-8")).hexdigest()
    if not store.consume_oauth_state(state_hash):
        raise TikTokOAuthError("Estado OAuth expirado ou já utilizado. Inicie a conexão novamente.")

    client_key, client_secret, redirect_uri, cipher = _settings()
    body = urlencode({
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Never log or return the request body, client secret, or authorization code.
        raise TikTokOAuthError("TikTok recusou a troca do código OAuth (HTTP {}).".format(exc.code)) from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise TikTokOAuthError("Não foi possível concluir a comunicação segura com o TikTok.") from exc

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not access_token or not refresh_token:
        # TikTok may return structured error information; expose only a generic message.
        raise TikTokOAuthError("TikTok não retornou os tokens esperados. Confira o produto Login Kit e as permissões do app.")
    scopes = payload.get("scope") or os.getenv("TIKTOK_SCOPES", "user.info.basic,video.publish")
    expires_in = int(payload.get("expires_in") or 0)
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat() if expires_in else None
    store.save_social_connection(
        "TikTok",
        cipher.encrypt(access_token.encode("utf-8")).decode("ascii"),
        cipher.encrypt(refresh_token.encode("utf-8")).decode("ascii"),
        payload.get("open_id"),
        scopes,
        expires_at,
    )
    return {"connected": True, "platform": "TikTok", "open_id_present": bool(payload.get("open_id")), "scopes": scopes.split(","), "expires_at": expires_at}


def connection_status():
    record = store.get_social_connection_status("TikTok")
    if not record:
        return {"platform": "TikTok", "connected": False, "oauth_verified": False, "publishing_enabled": False}
    return {
        "platform": "TikTok",
        "connected": True,
        "oauth_verified": True,
        "open_id_present": bool(record.get("open_id")),
        "scopes": [scope for scope in (record.get("scopes") or "").split(",") if scope],
        "expires_at": record.get("expires_at"),
        "last_authorized_at": record.get("updated_at"),
        "publishing_enabled": False,
    }
