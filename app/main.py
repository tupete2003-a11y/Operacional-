import os
import logging
import secrets
import uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import store
from .agents import list_agents
from .orchestrator import submit_request
from .config import get_groq_api_key, get_groq_env_names
from .social import dashboard as social_dashboard, BOTS, PLATFORMS
from .social_workflow import generate_social_workflow, CONTENT_TYPES
from .llm import ask_agent
from . import supervisor

logger = logging.getLogger("automa_x.ai")

app = FastAPI(title="AUTOMA X API", description="Núcleo inicial do sistema multiagente AUTOMA X", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["X-API-Key", "Content-Type"])

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in {"/", "/health", "/health/ready", "/auth/check"}:
        return await call_next(request)
    expected = os.getenv("API_ACCESS_TOKEN", "").strip()
    supplied = request.headers.get("X-API-Key", "").strip()
    if not expected or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return JSONResponse(status_code=401, content={"detail": "API key ausente ou inválida"})
    return await call_next(request)

@app.get("/auth/check")
async def auth_check(request: Request):
    """Diagnóstico seguro: nunca revela a chave; informa somente presença e comprimentos."""
    raw_expected = os.getenv("API_ACCESS_TOKEN", "")
    raw_supplied = request.headers.get("X-API-Key", "")
    expected = raw_expected.strip()
    supplied = raw_supplied.strip()
    valid = bool(expected and supplied and secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")))
    return {
        "configured": bool(expected),
        "valid": valid,
        "header_received": bool(raw_supplied),
        "expected_length": len(expected),
        "received_length": len(supplied),
        "same_length": len(expected) == len(supplied),
        "environment_has_outer_whitespace": raw_expected != raw_expected.strip(),
        "header_has_outer_whitespace": raw_supplied != raw_supplied.strip(),
    }

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=10000)

class SocialDraftRequest(BaseModel):
    bot_id: str = Field(pattern="^BOT_0[1-5]$")
    objective: str = Field(min_length=5, max_length=4000)
    platform: str = Field(default="Instagram", max_length=40)

class SocialWorkflowRequest(BaseModel):
    test_mode: bool = False
    objective: str = Field(min_length=5, max_length=4000)
    platforms: list[str] = Field(default_factory=lambda: list(PLATFORMS), min_length=1, max_length=5)
    content_types: list[str] = Field(default_factory=lambda: list(CONTENT_TYPES), min_length=1, max_length=5)

class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")

class ScheduleRequest(BaseModel):
    scheduled_at: datetime
    platform: str = Field(min_length=2, max_length=40)
    format: str = Field(min_length=2, max_length=60)
    content: str = Field(min_length=3, max_length=4000)

@app.on_event("startup")
def startup():
    if not os.getenv("API_ACCESS_TOKEN"):
        raise RuntimeError("API_ACCESS_TOKEN precisa estar configurado")
    store.init_db()
    supervisor.start_background_supervisor()

@app.get("/")
def root():
    return FileResponse(Path(__file__).resolve().parent.parent / "public" / "index.html", media_type="text/html")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/health/ready")
def readiness():
    """Estado público mínimo para a tela inicial; não expõe segredos nem dados de usuários."""
    try:
        database_connected = store.check_connection()
    except Exception:
        database_connected = False
    storage_backend = store.backend()
    return {
        "status": "ready" if database_connected else "degraded",
        "api": "online",
        "database": {
            "backend": storage_backend,
            "connected": database_connected,
            "durable": storage_backend == "postgresql" and database_connected,
        },
        "ai": {"provider": "Groq", "configured": bool(get_groq_api_key())},
        "bots": {"registered": len(BOTS)},
        "social": {"platforms_registered": len(PLATFORMS), "connected": 0},
        "publishing": {"enabled": False},
    }

@app.get("/agents")
def agents():
    return {"total": 31, "orchestrator": {"id": "AGENT_00", "name": "OPERACIONAL", "role": "Coordenador central"}, "specialists": list_agents()}

@app.post("/chat")
def chat(payload: ChatRequest):
    store.add_message("user", payload.message)
    task = submit_request(payload.message)
    response = {"task_id": task["id"], "status": task["status"], "operational_agent": "AGENT_00", "agents_selected": task["plan"]["selected_agents"], "plan": task["plan"], "result": task["result"]}
    store.add_message("assistant", f"Plano {task['id']} criado com status {task['status']}.")
    return response

@app.get("/tasks")
def tasks():
    return {"tasks": store.list_tasks()}

@app.get("/tasks/{task_id}")
def task_detail(task_id: str):
    task = store.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return task

@app.get("/approvals")
def approvals():
    return {"approvals": store.list_approvals()}

@app.post("/approvals/{approval_id}")
def decide_approval(approval_id: str, payload: ApprovalRequest):
    status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    if not store.set_approval(approval_id, status):
        raise HTTPException(status_code=404, detail="Aprovação não encontrada")
    return {"approval_id": approval_id, "status": status, "note": "A decisão foi registrada. Nenhuma ação externa é executada por este protótipo."}

@app.get("/schedules")
def schedules():
    return {"schedules": store.list_schedules()}

@app.post("/schedules")
def create_schedule(payload: ScheduleRequest):
    if payload.platform not in PLATFORMS:
        raise HTTPException(status_code=422, detail="Plataforma não suportada.")
    if payload.scheduled_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Informe data e horário com fuso horário.")
    schedule_id = str(uuid.uuid4())
    scheduled_at = payload.scheduled_at.astimezone(timezone.utc).isoformat()
    store.create_schedule(schedule_id, scheduled_at, payload.platform, payload.format, payload.content.strip())
    return {"id": schedule_id, "scheduled_at": scheduled_at, "platform": payload.platform, "format": payload.format, "content": payload.content.strip(), "status": "PLANNED"}

@app.delete("/schedules/{schedule_id}")
def remove_schedule(schedule_id: str):
    if not store.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Item da agenda não encontrado.")
    return {"id": schedule_id, "deleted": True}

@app.get("/memory")
def memory():
    return {"recent_messages": store.get_messages()}


@app.get("/system/status")
def system_status():
    """Resumo operacional real; não executa publicações nem altera dados."""
    try:
        database_ok = store.check_connection()
        database_error = None
    except Exception as exc:
        database_ok = False
        database_error = type(exc).__name__

    provider_configured = bool(get_groq_api_key())
    storage_backend = store.backend()
    return {
        "api": {"status": "online", "version": app.version},
        "database": {
            "backend": storage_backend,
            "connected": database_ok,
            "durable_backend": storage_backend == "postgresql",
            "error_type": database_error,
        },
        "ai": {
            "provider": "Groq",
            "configured": provider_configured,
            "verified": None,
            "verification_endpoint": "/ai/status",
            "note": "configured indica apenas presença da chave; verified exige chamada real ao provedor.",
        },
        "bots": {
            "registered": len(BOTS),
            "ids": [bot["id"] for bot in BOTS],
            "execution_verified": False,
            "note": "Cadastro não equivale a execução validada de ponta a ponta.",
        },
        "social_platforms": [
            {"name": name, "connected": False, "publishing_enabled": False}
            for name in PLATFORMS
        ],
        "safety": {
            "external_publishing_enabled": False,
            "human_approval_required": True,
        },
    }


@app.get("/supervisor/status")
def supervisor_status():
    """Estado e histórico do supervisor autônomo; rota protegida por API key."""
    return supervisor.get_status()


@app.post("/supervisor/run")
def supervisor_run():
    """Executa imediatamente uma auditoria não destrutiva e registra o resultado."""
    try:
        return supervisor.run_audit()
    except Exception as exc:
        logger.exception("Falha ao executar auditoria do supervisor")
        raise HTTPException(status_code=500, detail="Falha na auditoria do supervisor: " + type(exc).__name__)


@app.get("/social/dashboard")
def social_home():
    return social_dashboard()

@app.get("/ai/status")
def ai_status():
    """Testa a resposta real da Groq sem salvar tarefas nem revelar credenciais."""
    if not get_groq_api_key():
        return {"provider": "Groq", "configured": False, "verified": False,
                "message": "GROQ_API_KEY não encontrada nas variáveis do serviço Render."}
    try:
        reply = ask_agent(
            {"id": "AI_HEALTH_CHECK", "name": "Verificação",
             "function": "Verifique a conectividade do provedor de IA."},
            "Responda somente com: AUTOMA X OK"
        )
        if not isinstance(reply, str) or not reply.strip():
            raise RuntimeError("A Groq respondeu sem conteúdo de texto.")
        # Any non-empty assistant response confirms the API round-trip.
        return {"provider": "Groq", "configured": True, "verified": True,
                "message": "Conexão real com a Groq confirmada.",
                "test_response_received": True}
    except Exception as exc:
        logger.warning("Verificação Groq falhou: %s", str(exc)[:400])
        key = get_groq_api_key()
        safe_detail = str(exc).replace(key, "[REDACTED]") if key else str(exc)
        return {"provider": "Groq", "configured": True, "verified": False,
                "message": safe_detail[:400]}


@app.get("/social/agents")
def social_agents():
    return {"total": len(BOTS), "agents": BOTS}

@app.post("/social/draft")
def social_draft(payload: SocialDraftRequest):
    if payload.bot_id not in ("BOT_02", "BOT_03"):
        raise HTTPException(status_code=400, detail="Este bot não é responsável por gerar conteúdo.")
    if not get_groq_api_key():
        raise HTTPException(status_code=503, detail="IA ainda não configurada. O painel funciona, mas adicione um provedor de IA ao serviço da API para gerar conteúdo.")
    bot = next(item for item in BOTS if item["id"] == payload.bot_id)
    agent = {"id": bot["id"], "name": bot["name"], "function": bot["description"] + " Responsabilidades: " + "; ".join(bot["responsibilities"])}
    prompt = "Plataforma: " + payload.platform + "\nObjetivo: " + payload.objective + "\nCrie um pacote de conteúdo pronto para revisão humana, com gancho, roteiro/legenda, descrição, hashtags e CTA. Não afirme que publicou."
    try:
        draft = ask_agent(agent, prompt)
        task_id = str(uuid.uuid4())
        approval_id = str(uuid.uuid4())
        created_at = store.now()
        task = {
            "id": task_id,
            "request": payload.objective,
            "status": "DRAFT_REVIEW",
            "plan": {"selected_agents": [bot["id"]], "platform": payload.platform, "workflow": "SOCIAL_CONTENT"},
            "result": {"draft": draft, "bot_id": bot["id"], "bot_name": bot["name"], "platform": payload.platform},
            "created_at": created_at
        }
        store.save_task(task)
        store.create_approval(approval_id, task_id, "Revisar rascunho de " + payload.platform + " · " + bot["name"])
        return {"task_id": task_id, "approval_id": approval_id, "bot_id": bot["id"], "bot_name": bot["name"], "platform": payload.platform, "draft": draft, "status": "DRAFT_REVIEW", "approval_required": True}
    except Exception as exc:
        logger.error("Falha ao gerar rascunho com IA: %s", str(exc)[:500])
        key = get_groq_api_key()
        safe_detail = str(exc).replace(key, "[REDACTED]") if key else str(exc)
        raise HTTPException(status_code=502, detail="Falha na geração: " + safe_detail[:500])


@app.post("/social/workflow")
def social_workflow(payload: SocialWorkflowRequest):
    unknown_platforms = sorted(set(payload.platforms) - set(PLATFORMS))
    if unknown_platforms:
        raise HTTPException(
            status_code=422,
            detail={"message": "Plataforma não suportada.", "invalid_platforms": unknown_platforms},
        )

    unknown_content_types = sorted(set(payload.content_types) - set(CONTENT_TYPES))
    if unknown_content_types:
        raise HTTPException(
            status_code=422,
            detail={"message": "Formato de conteúdo não suportado.", "invalid_content_types": unknown_content_types},
        )

    if len(set(payload.platforms)) != len(payload.platforms):
        raise HTTPException(status_code=422, detail="Não repita plataformas na mesma solicitação.")
    if len(set(payload.content_types)) != len(payload.content_types):
        raise HTTPException(status_code=422, detail="Não repita formatos na mesma solicitação.")

    if not get_groq_api_key():
        raise HTTPException(
            status_code=503,
            detail="IA ainda não configurada. Adicione GROQ_API_KEY nas variáveis do serviço da API.",
        )

    try:
        result = generate_social_workflow(payload.model_dump())
        return result
    except Exception as exc:
        logger.error("Falha no fluxo dos cinco bots: %s", str(exc)[:500])
        key = get_groq_api_key()
        safe_detail = str(exc).replace(key, "[REDACTED]") if key else str(exc)
        raise HTTPException(
            status_code=502,
            detail="Falha no fluxo dos cinco bots: " + safe_detail[:500],
        )

# Wrap the complete ASGI app so CORS handles browser preflight before API-key middleware.
app = CORSMiddleware(app, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
