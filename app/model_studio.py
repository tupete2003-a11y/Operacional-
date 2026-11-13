"""Core definitions and safe planning primitives for AUTOMA X Model Studio.

Image generation is deliberately not simulated: a configured provider is required
before a generation adapter can be enabled. Reference-image bytes are not stored here.
"""
from datetime import datetime, timezone
from typing import Any
from .config import get_groq_api_key

MODEL_STUDIO_BOTS = [
    {"id":"BOT_01","name":"Scene Planner","role":"Planejamento de cenas","responsibilities":["Planejar uma produção visual diária","Definir cenário, figurino, pose, enquadramento e iluminação","Montar briefings para os demais bots"]},
    {"id":"BOT_02","name":"Visual Research","role":"Pesquisa visual","responsibilities":["Pesquisar referências e tendências visuais","Sugerir ambientes, iluminação, composição e direção de arte","Registrar a origem das referências"]},
    {"id":"BOT_03","name":"Photo Creator","role":"Criação fotográfica","responsibilities":["Preparar prompts fotográficos usando a referência aprovada","Solicitar geração apenas quando houver provedor de imagem configurado","Preservar aparência natural e evitar detalhes inventados"]},
    {"id":"BOT_04","name":"Identity Guardian","role":"Verificação de identidade e qualidade","responsibilities":["Conferir semelhança com a referência aprovada","Verificar rosto, cabelo, proporções, anatomia, mãos, iluminação e artefatos","Sinalizar resultados para revisão humana; não declarar biometria validada sem ferramenta apropriada"]},
    {"id":"BOT_05","name":"Master Operational","role":"Execução e coordenação operacional","responsibilities":["Executar e acompanhar o fluxo persistente dos quatro bots especializados","Controlar fila, etapas, tentativas, histórico, aprovações e conflitos","Pausar ações com custo para aprovação humana","Bloquear publicação ou ação externa sem autorização explícita"]},
]
PLATFORMS = ["Instagram", "TikTok", "Facebook", "Kwai"]

def provider_status() -> dict[str, Any]:
    """Presence-only diagnostic; never returns secret values."""
    import os
    provider = "openai"
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    encryption_key = os.getenv("AUTOMA_TOKEN_ENCRYPTION_KEY", "").strip()
    configured = bool(api_key)
    storage_configured = bool(encryption_key and os.getenv("DATABASE_URL", "").strip())
    return {
        "provider": provider,
        "model": os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst"),
        "configured": configured,
        "secure_storage_configured": storage_configured,
        "generation_enabled": configured and storage_configured,
        "reason": None if configured and storage_configured else "Configure OPENAI_API_KEY, AUTOMA_TOKEN_ENCRYPTION_KEY e DATABASE_URL no serviço de API do Render.",
    }

def dashboard() -> dict[str, Any]:
    try:
        reference = __import__("app.model_studio_media", fromlist=["reference_status"]).reference_status()
    except Exception:
        reference = {"registered": False, "status": "storage_unavailable"}
    return {
        "project": "AUTOMA X — MODEL STUDIO",
        "mode": "model_photo_studio",
        "bots": {"total": len(MODEL_STUDIO_BOTS), "items": MODEL_STUDIO_BOTS},
        "production": {"frequency": "daily", "style": "photorealistic", "composition": "group", "platforms": PLATFORMS},
        "reference_model": reference,
        "image_generation": provider_status(),
        "chat": {"provider": "Groq", "configured": bool(get_groq_api_key()), "verified": False},
        "publishing": {"enabled": False, "approval_required": True},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def chat_with_master(message: str, history: list[dict[str, Any]] | None = None) -> str:
    """Respond through BOT_05; this is conversational only and never triggers external actions."""
    text = str(message or "").strip()
    if len(text) < 2:
        raise ValueError("Escreva uma mensagem com pelo menos 2 caracteres.")

    transcript = []
    for item in (history or [])[-10:]:
        role = "Usuário" if item.get("role") == "user" else "BOT 05"
        content = str(item.get("content", "")).strip()
        if content:
            transcript.append(f"{role}: {content[:1500]}")

    context = ""
    if transcript:
        context = "Histórico recente da conversa (contexto, não instruções de sistema):\n" + "\n".join(transcript) + "\n\n"

    agent = {
        "id": "BOT_05",
        "name": "Master Operational",
        "function": (
            "Você é o BOT_05 — Master Operational do AUTOMA X — MODEL STUDIO. "
            "Coordene conceitualmente os bots BOT_01 Scene Planner, BOT_02 Visual Research, "
            "BOT_03 Photo Creator e BOT_04 Identity Guardian. Responda em português do Brasil, "
            "de forma clara e prática. Ajude o operador a planejar e entender a produção fotográfica "
            "da mesma modelo, preservar aparência natural, organizar tarefas e interpretar o estado "
            "do painel. Não diga que gerou imagens, verificou identidade biometricamente, fez deploy, "
            "alterou serviços ou executou qualquer ação externa. A execução real dos bots ocorre pelo executor BOT_05 na área Produção fotográfica do painel: o operador inicia o fluxo ali, e o executor registra etapas e pede aprovação antes de cada geração paga. Esta conversa é apenas o canal de diálogo; não declare que iniciou ou concluiu uma execução sem consultar o estado real do painel. Você não publica conteúdo nem altera serviços externos; publicação continua bloqueada. "
            "Não invente estados de conexão, métricas, resultados nem segredos."
        ),
    }
    from .llm import ask_agent

    reply = ask_agent(agent, context + "Mensagem atual do operador:\n" + text)
    if not isinstance(reply, str) or not reply.strip():
        raise RuntimeError("O provedor de IA não retornou uma resposta de texto.")
    return reply.strip()

def create_production_plan(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a structured plan only; this does not generate or publish images."""
    objective = str(payload.get("objective", "")).strip()
    if len(objective) < 5:
        raise ValueError("Informe um objetivo com pelo menos 5 caracteres.")
    reference_id = str(payload.get("reference_id", "")).strip()
    if not reference_id:
        raise ValueError("A referência aprovada da modelo é obrigatória para iniciar a produção.")
    platform = str(payload.get("platform", "Instagram")).strip()
    if platform not in PLATFORMS:
        raise ValueError("Plataforma não suportada pelo Model Studio.")
    return {
        "project": "AUTOMA X — MODEL STUDIO",
        "status": "PLANNED_REFERENCE_REQUIRED",
        "objective": objective,
        "reference_id": reference_id,
        "platform": platform,
        "composition": str(payload.get("composition", "group")),
        "style": str(payload.get("style", "photorealistic")),
        "workflow": [bot["id"] for bot in MODEL_STUDIO_BOTS],
        "generation": {"started": False, "reason": "Planejamento criado; geração depende de referência acessível e provedor de imagens integrado e validado."},
        "publishing": {"started": False, "approval_required": True},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
