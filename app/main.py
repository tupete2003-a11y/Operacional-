import os
import logging
import secrets
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import store
from .agents import list_agents
from .orchestrator import submit_request
from .config import get_groq_api_key, get_groq_env_names
from .social import dashboard as social_dashboard, BOTS, PLATFORMS
from .social_workflow import generate_social_workflow, CONTENT_TYPES
from .llm import ask_agent

logger = logging.getLogger("automa_x.ai")

app = FastAPI(title="AUTOMA X API", description="Núcleo inicial do sistema multiagente AUTOMA X", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["X-API-Key", "Content-Type"])

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in {"/", "/health"}:
        return await call_next(request)
    expected = os.getenv("API_ACCESS_TOKEN", "")
    supplied = request.headers.get("X-API-Key", "")
    if not expected or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        return JSONResponse(status_code=401, content={"detail": "API key ausente ou inválida"})
    return await call_next(request)

class ChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=10000)

class SocialDraftRequest(BaseModel):
    bot_id: str = Field(pattern="^BOT_0[1-5]$")
    objective: str = Field(min_length=5, max_length=4000)
    platform: str = Field(default="Instagram", max_length=40)

class SocialWorkflowRequest(BaseModel):
    objective: str = Field(min_length=5, max_length=4000)
    platforms: list[str] = Field(default_factory=lambda: list(PLATFORMS), min_length=1, max_length=5)
    content_types: list[str] = Field(default_factory=lambda: list(CONTENT_TYPES), min_length=1, max_length=5)

class ApprovalRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")

@app.on_event("startup")
def startup():
    if not os.getenv("API_ACCESS_TOKEN"):
        raise RuntimeError("API_ACCESS_TOKEN precisa estar configurado")
    store.init_db()

@app.get("/")
def root():
    return {"project": "AUTOMA X", "status": "RUNNING", "health": "/health"}

@app.get("/health")
def health():
    return {"status": "ok"}

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

@app.get("/memory")
def memory():
    return {"recent_messages": store.get_messages()}


@app.get("/social/dashboard")
def social_home():
    return social_dashboard()

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
