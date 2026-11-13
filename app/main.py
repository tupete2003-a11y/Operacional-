import os
import json
import logging
import secrets
import uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from . import store
from .orchestrator import submit_request
from .config import get_groq_api_key, get_groq_env_names
from .llm import ask_agent
from . import supervisor, tiktok_oauth
from .connections import get_connection_diagnostics
from . import model_studio, model_studio_media

logger = logging.getLogger("automa_x.ai")

app = FastAPI(title="AUTOMA X API", description="Núcleo inicial do sistema multiagente AUTOMA X", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["X-API-Key", "Content-Type"])

@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in {"/", "/health", "/health/ready", "/auth/check", "/tiktokF8RVDxj046UhqnrqC3RlbWjlDfEp6W4v.txt", "/tiktokjXdgJiHuOjywesokdDGiV2OhABLo9Ggw.txt", "/oauth/tiktok/callback"}:
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

class ModelStudioPlanRequest(BaseModel):
    objective: str = Field(min_length=5, max_length=4000)
    reference_id: str = Field(min_length=1, max_length=200)
    platform: str = Field(default="Instagram", max_length=40)
    composition: str = Field(default="group", max_length=40)
    style: str = Field(default="photorealistic", max_length=60)

class ModelStudioGenerateRequest(BaseModel):
    objective: str = Field(min_length=5, max_length=2000)
    composition: str = Field(default="group", max_length=40)
    style: str = Field(default="photorealistic", max_length=60)

class ModelStudioReviewRequest(BaseModel):
    decision: str = Field(pattern="^(APPROVE|REJECT)$")
    note: str = Field(default="", max_length=1000)

class SocialDraftRequest(BaseModel):
    bot_id: str = Field(pattern="^BOT_0[1-5]$")
    objective: str = Field(min_length=5, max_length=4000)
    platform: str = Field(default="Instagram", max_length=40)

class SocialWorkflowRequest(BaseModel):
    test_mode: bool = False
    objective: str = Field(min_length=5, max_length=4000)
    platforms: list[str] = Field(default_factory=lambda: list(model_studio.PLATFORMS), min_length=1, max_length=5)
    content_types: list[str] = Field(default_factory=lambda: ["photo"], min_length=1, max_length=5)

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

@app.get("/tiktokF8RVDxj046UhqnrqC3RlbWjlDfEp6W4v.txt", include_in_schema=False)
def tiktok_domain_verification():
    verification_file = Path(__file__).resolve().parent.parent / "public" / "tiktokF8RVDxj046UhqnrqC3RlbWjlDfEp6W4v.txt"
    return FileResponse(verification_file, media_type="text/plain")


@app.get("/tiktokjXdgJiHuOjywesokdDGiV2OhABLo9Ggw.txt", include_in_schema=False)
def tiktok_domain_verification_new():
    verification_file = Path(__file__).resolve().parent.parent / "public" / "tiktokjXdgJiHuOjywesokdDGiV2OhABLo9Ggw.txt"
    return FileResponse(verification_file, media_type="text/plain")


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
        "bots": {"registered": len(model_studio.MODEL_STUDIO_BOTS)},
        "social": {"platforms_registered": len(model_studio.PLATFORMS), "connected": 0},
        "publishing": {"enabled": False},
    }

@app.get("/agents")
def agents():
    return {"total": len(model_studio.MODEL_STUDIO_BOTS), "orchestrator": {"id": "BOT_05", "name": "Master Operational", "role": "Coordenação central do Model Studio"}, "specialists": model_studio.MODEL_STUDIO_BOTS}

@app.get("/model-studio/status")
def model_studio_status():
    return model_studio.dashboard()

@app.get("/model-studio/agents")
def model_studio_agents():
    return {"total": len(model_studio.MODEL_STUDIO_BOTS), "agents": model_studio.MODEL_STUDIO_BOTS}

@app.get("/model-studio/reference")
def model_studio_reference_status():
    return model_studio_media.reference_status()

@app.get("/model-studio/reference/image")
def model_studio_reference_image():
    try:
        reference = model_studio_media.get_reference()
        if not reference:
            raise HTTPException(status_code=404, detail="Referência ainda não cadastrada.")
        record, raw = reference
        return Response(content=raw, media_type=record["mime_type"], headers={"Cache-Control": "private, no-store"})
    except model_studio_media.ModelStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

@app.post("/model-studio/reference")
async def model_studio_upload_reference(file: UploadFile = File(...)):
    try:
        raw = await file.read(model_studio_media.MAX_IMAGE_BYTES + 1)
        result = model_studio_media.save_reference(raw)
        return {"status": "stored", **result}
    except model_studio_media.ModelStudioError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        await file.close()

@app.post("/model-studio/generate")
def model_studio_generate(payload: ModelStudioGenerateRequest):
    try:
        reference = model_studio_media.get_reference()
        if not reference:
            raise HTTPException(status_code=409, detail="Envie primeiro a foto de referência da modelo.")
        reference_record, reference_bytes = reference
        image_bytes, model_name = model_studio_media.generate_from_reference(
            reference_bytes, payload.objective, payload.composition, payload.style
        )
        result = model_studio_media.save_generated(
            image_bytes, reference_record["id"], payload.objective, model_name
        )
        return {"status": result["quality"]["status"], "reference_id": reference_record["id"], **result,
                "image_url": "/model-studio/images/" + result["image_id"],
                "identity_review": "A confirmação de que é a mesma modelo exige revisão visual humana."}
    except model_studio_media.ModelStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

@app.get("/model-studio/images/{image_id}/quality")
def model_studio_image_quality(image_id: str):
    loaded = model_studio_media.load_generated(image_id)
    if not loaded:
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    record, _ = loaded
    return {"image_id": image_id, "quality": json.loads(record["quality_json"]),
            "review_status": record.get("review_status", "PENDING"),
            "review_note": record.get("review_note")}

@app.post("/model-studio/images/{image_id}/review")
def model_studio_review_image(image_id: str, payload: ModelStudioReviewRequest):
    status = "APPROVED" if payload.decision == "APPROVE" else "REJECTED"
    if not store.review_model_generated_image(image_id, status, payload.note):
        raise HTTPException(status_code=404, detail="Imagem não encontrada.")
    return {"image_id": image_id, "review_status": status,
            "note": "Revisão humana registrada. Isso não executa publicação externa."}

@app.get("/model-studio/images/{image_id}")
def model_studio_get_image(image_id: str):
    try:
        loaded = model_studio_media.load_generated(image_id)
        if not loaded:
            raise HTTPException(status_code=404, detail="Imagem não encontrada.")
        record, raw = loaded
        return Response(content=raw, media_type=record["mime_type"], headers={"Cache-Control": "private, no-store"})
    except model_studio_media.ModelStudioError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

@app.post("/model-studio/plan")
def model_studio_plan(payload: ModelStudioPlanRequest):
    try:
        plan = model_studio.create_production_plan(payload.model_dump())
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "request": payload.objective,
            "status": plan["status"],
            "plan": {"selected_agents": plan["workflow"], "workflow": "MODEL_STUDIO", "platform": plan["platform"]},
            "result": plan,
            "created_at": store.now(),
        }
        store.save_task(task)
        return {"task_id": task_id, **plan}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
    if payload.platform not in model_studio.PLATFORMS:
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
            "registered": len(model_studio.MODEL_STUDIO_BOTS),
            "ids": [bot["id"] for bot in model_studio.MODEL_STUDIO_BOTS],
            "execution_verified": False,
            "note": "Cadastro não equivale a execução validada de ponta a ponta.",
        },
        "social_platforms": [
            {"name": name, "connected": False, "publishing_enabled": False}
            for name in model_studio.PLATFORMS
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



@app.post("/oauth/tiktok/start")
def tiktok_oauth_start(response: Response):
    """Inicia OAuth com state anti-CSRF; exige a chave da API no painel."""
    try:
        authorization_url, state = tiktok_oauth.begin_authorization()
    except tiktok_oauth.TikTokOAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    response.set_cookie(
        key="automa_tiktok_oauth_state",
        value=state,
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/oauth/tiktok",
    )
    return {"authorization_url": authorization_url, "expires_in": 600}


@app.get("/oauth/tiktok/callback", response_class=HTMLResponse)
def tiktok_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """Callback público do TikTok; state em cookie protege contra CSRF."""
    cookie_state = request.cookies.get("automa_tiktok_oauth_state", "")
    try:
        if error:
            raise tiktok_oauth.TikTokOAuthError("A autorização foi recusada ou cancelada no TikTok.")
        result = tiktok_oauth.complete_authorization(code, state, cookie_state)
        body = "<h2>Conta TikTok conectada</h2><p>OAuth concluído e tokens armazenados criptografados.</p><p>Publicação externa permanece desativada.</p>"
        response = HTMLResponse(body, status_code=200)
    except tiktok_oauth.TikTokOAuthError as exc:
        body = "<h2>Não foi possível conectar o TikTok</h2><p>" + str(exc) + "</p><p>Volte ao painel e tente novamente.</p>"
        response = HTMLResponse(body, status_code=400)
    except Exception:
        logger.exception("Falha inesperada no callback OAuth TikTok")
        response = HTMLResponse("<h2>Falha na conexão</h2><p>Ocorreu um erro interno. Nenhum segredo foi exibido.</p>", status_code=500)
    response.delete_cookie("automa_tiktok_oauth_state", path="/oauth/tiktok")
    return response


@app.get("/oauth/tiktok/status")
def tiktok_oauth_status():
    return tiktok_oauth.connection_status()

@app.get("/connections/diagnostics")
def connections_diagnostics():
    """Diagnóstico autenticado e somente leitura das integrações sociais."""
    return get_connection_diagnostics()


@app.get("/social/dashboard")
def social_home():
    # Compatibility alias: the primary dashboard is now Model Studio.
    return model_studio.dashboard()

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
    return {"total": len(model_studio.MODEL_STUDIO_BOTS), "agents": model_studio.MODEL_STUDIO_BOTS}

@app.post("/social/draft")
def social_draft(payload: SocialDraftRequest):
    raise HTTPException(status_code=410, detail="Fluxo antigo de campanhas desativado. Utilize /model-studio/plan.")


@app.post("/social/workflow")
def social_workflow(payload: SocialWorkflowRequest):
    raise HTTPException(status_code=410, detail="Fluxo antigo de campanhas substituído pelo AUTOMA X — MODEL STUDIO.")

# Wrap the complete ASGI app so CORS handles browser preflight before API-key middleware.
app = CORSMiddleware(app, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
