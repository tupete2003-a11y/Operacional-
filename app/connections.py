"""Secure, read-only diagnostics for AUTOMA X social connection adapters."""
import os
from typing import Dict, List

PLATFORM_CONFIG = {
    "TikTok": {
        "adapter": "tiktok_content_posting",
        "credential_groups": {
            "app": ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI"],
            "account": [],
        },
        "required_next": [
            "Criar o app no TikTok for Developers",
            "Adicionar Content Posting API e solicitar os escopos necessários",
            "Configurar Client Key, Client Secret e Redirect URI no Render",
            "Autorizar a conta por OAuth e concluir a auditoria do TikTok",
        ],
        "docs_url": "https://developers.tiktok.com/doc/content-posting-api-get-started",
    },
    "Instagram": {
        "adapter": "meta_graph_instagram",
        "credential_groups": {
            "app": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
            "account": ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"],
        },
        "required_next": ["Configurar app Meta e produto Instagram API", "Autorizar conta profissional e conceder permissões", "Armazenar token e identificador da conta no Render"],
        "docs_url": "https://developers.facebook.com/docs/instagram-platform/",
    },
    "Facebook": {
        "adapter": "meta_pages",
        "credential_groups": {
            "app": ["META_APP_ID", "META_APP_SECRET", "META_REDIRECT_URI"],
            "account": ["FACEBOOK_PAGE_ACCESS_TOKEN", "FACEBOOK_PAGE_ID"],
        },
        "required_next": ["Configurar Facebook Pages API", "Autorizar uma Página administrada pela conta", "Armazenar token da Página e validar permissões"],
        "docs_url": "https://developers.facebook.com/docs/pages-api/",
    },
    "YouTube": {
        "adapter": "google_youtube",
        "credential_groups": {
            "app": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"],
            "account": ["YOUTUBE_REFRESH_TOKEN", "YOUTUBE_CHANNEL_ID"],
        },
        "required_next": ["Criar projeto no Google Cloud e ativar YouTube Data API v3", "Configurar OAuth 2.0 e autorizar o canal", "Armazenar refresh token no Render e verificar quota"],
        "docs_url": "https://developers.google.com/youtube/v3",
    },
    "Kwai": {
        "adapter": "kwai_open_platform",
        "credential_groups": {
            "app": ["KWAI_APP_ID", "KWAI_APP_SECRET", "KWAI_REDIRECT_URI"],
            "account": ["KWAI_ACCESS_TOKEN", "KWAI_ACCOUNT_ID"],
        },
        "required_next": ["Confirmar acesso e produto de publicação no portal oficial", "Registrar app e obter credenciais", "Autorizar conta e validar permissões de publicação"],
        "docs_url": "https://open.kuaishou.com/",
    },
}


def _configured_names(names: List[str]) -> List[str]:
    return [name for name in names if bool(os.getenv(name, "").strip())]


def get_connection_diagnostics() -> Dict:
    """Return presence-only metadata; never return secret values or token fragments."""
    from . import store
    storage_backend = store.backend()
    token_storage_durable = storage_backend == "postgresql"
    platforms = []
    for name, config in PLATFORM_CONFIG.items():
        groups = {
            group: {
                "required": len(keys),
                "configured": len(_configured_names(keys)),
                "missing": [key for key in keys if not os.getenv(key, "").strip()],
            }
            for group, keys in config["credential_groups"].items()
        }
        all_keys = [key for keys in config["credential_groups"].values() for key in keys]
        present = len(_configured_names(all_keys))
        complete = present == len(all_keys)
        app_ready = groups["app"]["configured"] == groups["app"]["required"]
        account_ready = groups["account"]["configured"] == groups["account"]["required"]
        oauth_record = None
        if name == "TikTok":
            try:
                from . import store
                oauth_record = store.get_social_connection_status("TikTok")
            except Exception:
                oauth_record = None
        oauth_connected = bool(oauth_record)
        status = "CONNECTED_OAUTH" if oauth_connected else (
            "CONFIGURED_PENDING_VALIDATION" if complete else (
                "APP_CONFIGURED_ACCOUNT_PENDING" if app_ready else "NOT_CONFIGURED"
            )
        )
        platforms.append({
            "name": name,
            "adapter": config["adapter"],
            "status": status,
            "credentials_present": present,
            "credentials_required": len(all_keys),
            "app_configured": app_ready,
            "account_credentials_present": oauth_connected or account_ready,
            "oauth_verified": oauth_connected,
            "oauth_scopes": [x for x in (oauth_record.get("scopes", "") if oauth_record else "").split(",") if x],
            "publishing_enabled": False,
            "missing_environment_variables": [key for key in all_keys if not os.getenv(key, "").strip()],
            "next_steps": config["required_next"],
            "documentation": config["docs_url"],
        })
    return {
        "project": "AUTOMA X",
        "diagnostics_mode": "READ_ONLY",
        "platforms": platforms,
        "secrets_exposed": False,
        "external_publishing_enabled": False,
        "token_storage": {"backend": storage_backend, "durable": token_storage_durable, "oauth_available": token_storage_durable},
        "note": "Variáveis presentes não comprovam OAuth, escopos, auditoria da plataforma nem publicação. Nenhum teste publica conteúdo.",
    }
