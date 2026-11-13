"""Persistent, approval-gated execution engine for AUTOMA X Model Studio.

BOT_05 coordinates BOT_01..BOT_04. Text steps retry a bounded number of times.
Paid image generation is never retried automatically and requires an explicit,
per-run approval. Human identity review remains mandatory; publishing is disabled.
"""
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import model_studio, model_studio_media, store
from .llm import ask_agent

logger = logging.getLogger("automa_x.model_studio_executor")
TEXT_STEP_MAX_ATTEMPTS = 2
POLL_SECONDS = 5
_worker_lock = threading.Lock()
_run_lock = threading.Lock()
_worker_started = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bot(bot_id: str) -> dict[str, str]:
    bots = {item["id"]: item for item in model_studio.MODEL_STUDIO_BOTS}
    return bots[bot_id]


def _run_payload(run: dict[str, Any]) -> dict[str, Any]:
    steps = store.get_agent_run_steps(run["id"])
    return {**run, "steps": steps, "publishing": {"enabled": False, "approval_required": True}}


def create_run(objective: str, composition: str = "group", style: str = "photorealistic") -> dict[str, Any]:
    """Queue a run against the currently active encrypted reference image."""
    clean_objective = str(objective or "").strip()
    if len(clean_objective) < 5:
        raise ValueError("Descreva o objetivo da fotografia com pelo menos 5 caracteres.")
    reference = model_studio_media.reference_status()
    if not reference.get("registered") or not reference.get("reference_id"):
        raise ValueError("Envie primeiro a foto de referência da modelo.")
    run_id = str(uuid.uuid4())
    created = _now()
    run = {
        "id": run_id,
        "objective": clean_objective,
        "composition": str(composition or "group")[:80],
        "style": str(style or "photorealistic")[:100],
        "reference_id": reference["reference_id"],
        "status": "QUEUED",
        "current_step": "BOT_01",
        "result": {
            "generation_approval_required": True,
            "publishing_enabled": False,
            "automatic_identity_recognition": False,
        },
        "error": None,
        "created_at": created,
        "updated_at": created,
    }
    store.save_agent_run(run)
    for bot_id, step_name in (
        ("BOT_01", "scene_plan"),
        ("BOT_02", "visual_research"),
        ("BOT_03", "image_generation"),
        ("BOT_04", "technical_and_identity_review"),
    ):
        store.save_agent_run_step({
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "bot_id": bot_id,
            "step_name": step_name,
            "status": "PENDING",
            "attempt": 0,
            "input": {"objective": clean_objective, "reference_id": reference["reference_id"]},
            "output": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
        })
    return get_run(run_id)


def get_run(run_id: str) -> dict[str, Any] | None:
    run = store.get_agent_run(run_id)
    return _run_payload(run) if run else None


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    return [_run_payload(run) for run in store.list_agent_runs(limit=max(1, min(int(limit), 100)))]


def executor_status() -> dict[str, Any]:
    runs = store.list_agent_runs(limit=100)
    counts: dict[str, int] = {}
    for run in runs:
        counts[run["status"]] = counts.get(run["status"], 0) + 1
    return {
        "enabled": True,
        "worker_started": _worker_started,
        "poll_seconds": POLL_SECONDS,
        "retry_policy": {"text_steps_max_attempts": TEXT_STEP_MAX_ATTEMPTS, "paid_image_generation_automatic_retries": 0},
        "status_counts": counts,
        "last_runs": [{"id": run["id"], "status": run["status"], "current_step": run["current_step"], "updated_at": run["updated_at"]} for run in runs[:8]],
        "capabilities": [
            "fila persistente de execuções",
            "coordenação sequencial dos bots BOT_01 a BOT_04 pelo BOT_05",
            "tentativas limitadas para etapas de texto com falha",
            "aprovação por execução antes da chamada paga de geração de imagem",
            "verificação técnica e espera por revisão humana da identidade",
        ],
        "safety": {"external_publishing": False, "paid_generation_requires_approval": True, "identity_review_human": True},
    }


def build_photo_prompt(run: dict[str, Any]) -> str:
    """Pass BOT_01 and BOT_02 outputs forward to BOT_03 as actual shared context."""
    results = run.get("result") or {}
    scene = (results.get("bot_01") or {}).get("content", "")
    visual = (results.get("bot_02") or {}).get("content", "")
    return (
        "Objetivo original do operador: " + str(run.get("objective", "")) +
        "\n\nBriefing do BOT_01 — Scene Planner:\n" + str(scene)[:3000] +
        "\n\nDireção visual do BOT_02 — Visual Research:\n" + str(visual)[:3000] +
        "\n\nSiga as decisões dos dois especialistas sem alterar a identidade visual da modelo."
    )


def _save_run(run: dict[str, Any], *, status: str | None = None, current_step: str | None = None,
              result: dict[str, Any] | None = None, error: str | None = None) -> dict[str, Any]:
    updated = {**run, "updated_at": _now()}
    if status is not None:
        updated["status"] = status
    if current_step is not None:
        updated["current_step"] = current_step
    if result is not None:
        updated["result"] = result
    updated["error"] = error[:1000] if error else None
    store.save_agent_run(updated)
    return updated


def _save_step(run_id: str, step_name: str, *, status: str, attempt: int,
               output: dict[str, Any] | None = None, error: str | None = None,
               started_at: str | None = None, completed_at: str | None = None) -> None:
    existing = store.get_agent_run_step(run_id, step_name)
    if not existing:
        raise RuntimeError("Etapa operacional não encontrada.")
    store.save_agent_run_step({
        **existing,
        "status": status,
        "attempt": attempt,
        "output": output if output is not None else existing.get("output"),
        "error": error[:1000] if error else None,
        "started_at": started_at if started_at is not None else existing.get("started_at"),
        "completed_at": completed_at,
    })


def _execute_text_step(run: dict[str, Any], step_name: str, bot_id: str, task: str) -> bool:
    step = store.get_agent_run_step(run["id"], step_name)
    if step and step["status"] == "SUCCEEDED":
        return True
    attempt = int((step or {}).get("attempt") or 0) + 1
    started = _now()
    _save_step(run["id"], step_name, status="RUNNING", attempt=attempt, error=None, started_at=started)
    try:
        response = ask_agent(_bot(bot_id), task)
        if not isinstance(response, str) or not response.strip():
            raise RuntimeError("O provedor de texto não retornou conteúdo.")
        output = {"content": response.strip()}
        _save_step(run["id"], step_name, status="SUCCEEDED", attempt=attempt, output=output, completed_at=_now())
        latest = store.get_agent_run(run["id"])
        results = dict(latest.get("result") or {})
        results[bot_id.lower()] = output
        _save_run(latest, result=results, error=None)
        return True
    except Exception as exc:
        retryable = attempt < TEXT_STEP_MAX_ATTEMPTS
        _save_step(run["id"], step_name, status="PENDING" if retryable else "FAILED",
                   attempt=attempt, error=f"{type(exc).__name__}: {str(exc)[:700]}", completed_at=_now())
        latest = store.get_agent_run(run["id"])
        _save_run(latest, status="QUEUED" if retryable else "FAILED", current_step=bot_id,
                  error=f"{bot_id}: {type(exc).__name__}; " + ("nova tentativa programada" if retryable else "limite de tentativas atingido"))
        logger.warning("Etapa %s falhou na tentativa %s: %s", bot_id, attempt, type(exc).__name__)
        return False


def _request_generation_approval(run: dict[str, Any]) -> None:
    latest = store.get_agent_run(run["id"])
    results = dict(latest.get("result") or {})
    if results.get("generation_approval_id"):
        approval_id = results["generation_approval_id"]
    else:
        approval_id = str(uuid.uuid4())
        store.create_approval(approval_id, run["id"], "OPENAI_IMAGE_GENERATION")
        results["generation_approval_id"] = approval_id
    _save_step(run["id"], "image_generation", status="WAITING_APPROVAL",
               attempt=int((store.get_agent_run_step(run["id"], "image_generation") or {}).get("attempt") or 0))
    _save_run(latest, status="WAITING_APPROVAL", current_step="BOT_03", result=results,
              error="Aguardando autorização explícita para uma chamada que pode gerar cobrança na API de imagens.")


def approve_generation(run_id: str, decision: str) -> dict[str, Any]:
    run = store.get_agent_run(run_id)
    if not run:
        raise LookupError("Execução não encontrada.")
    if run["status"] != "WAITING_APPROVAL":
        raise ValueError("Esta execução não está aguardando aprovação de geração.")
    results = dict(run.get("result") or {})
    approval_id = results.get("generation_approval_id")
    if not approval_id:
        raise RuntimeError("Registro de aprovação não encontrado.")
    if decision == "APPROVE":
        status = model_studio.provider_status()
        if not status.get("generation_enabled"):
            raise RuntimeError(status.get("reason") or "Provedor de imagem ou armazenamento seguro ainda não está configurado.")
        store.set_approval(approval_id, "APPROVED")
        results["generation_approved"] = True
        results["generation_approved_at"] = _now()
        _save_step(run_id, "image_generation", status="PENDING",
                   attempt=int((store.get_agent_run_step(run_id, "image_generation") or {}).get("attempt") or 0),
                   error=None, completed_at=None)
        _save_run(run, status="QUEUED", current_step="BOT_03", result=results, error=None)
    elif decision == "REJECT":
        store.set_approval(approval_id, "REJECTED")
        _save_step(run_id, "image_generation", status="SKIPPED",
                   attempt=int((store.get_agent_run_step(run_id, "image_generation") or {}).get("attempt") or 0),
                   output={"reason": "O operador recusou a chamada paga."}, completed_at=_now())
        results["generation_approved"] = False
        _save_run(run, status="REJECTED", current_step="BOT_03", result=results,
                  error="Geração recusada pelo operador; nenhum pedido de imagem foi enviado.")
    else:
        raise ValueError("Decisão inválida.")
    return get_run(run_id)


def retry_failed_run(run_id: str) -> dict[str, Any]:
    run = store.get_agent_run(run_id)
    if not run:
        raise LookupError("Execução não encontrada.")
    if run["status"] != "FAILED":
        raise ValueError("Somente execuções com falha podem ser retomadas.")
    steps = store.get_agent_run_steps(run_id)
    failed = next((step for step in steps if step["status"] == "FAILED"), None)
    if not failed:
        raise ValueError("Nenhuma etapa com falha foi localizada.")
    if failed["bot_id"] == "BOT_03":
        results = dict(run.get("result") or {})
        results.pop("generation_approval_id", None)
        results["generation_approved"] = False
        store.save_agent_run({**run, "result": results, "updated_at": _now(), "status": "WAITING_APPROVAL", "current_step": "BOT_03", "error": "Nova autorização necessária antes de repetir a geração paga."})
        _request_generation_approval(store.get_agent_run(run_id))
        return get_run(run_id)
    _save_step(run_id, failed["step_name"], status="PENDING", attempt=int(failed["attempt"] or 0), error=None, completed_at=None)
    _save_run(run, status="QUEUED", current_step=failed["bot_id"], error=None)
    return get_run(run_id)


def process_run(run_id: str) -> None:
    """Advance free planning/review steps until the paid-generation approval gate."""
    if not _run_lock.acquire(blocking=False):
        return
    try:
        run = store.get_agent_run(run_id)
        if not run or run["status"] != "QUEUED":
            return
        if not store.claim_agent_run(run_id):
            return
        run = store.get_agent_run(run_id)
        objective = run["objective"]
        common = (
            f"Objetivo: {objective}\nComposição: {run['composition']}\nEstilo: {run['style']}\n"
            "A referência da modelo está armazenada de forma criptografada; preserve aparência natural. "
            "Não alegue que viu ou comparou biometricamente a imagem."
        )
        scene_task = (
            "BOT_01 — Scene Planner. Monte um briefing executável de fotografia com cenário, "
            "figurino, pose, enquadramento, iluminação, direção de arte e cuidados para manter "
            "a aparência natural da modelo. Não invente dados externos.\n" + common
        )
        run = store.get_agent_run(run_id)
        if not _execute_text_step(run, "scene_plan", "BOT_01", scene_task):
            return
        run = store.get_agent_run(run_id)
        research_task = (
            "BOT_02 — Visual Research. A partir do briefing, proponha referências visuais, "
            "ambientes, paleta, textura, luz e composição. Você não possui navegação web neste "
            "fluxo: não alegue pesquisa externa, tendências atuais ou métricas; apresente isto "
            "como direção criativa interna e marque referências verificáveis como pendentes.\n"
            + common + "\nBriefing BOT_01:\n" +
            str((run.get("result") or {}).get("bot_01", {}).get("content", ""))[:7000]
        )
        if not _execute_text_step(run, "visual_research", "BOT_02", research_task):
            return
        run = store.get_agent_run(run_id)
        results = dict(run.get("result") or {})
        if not results.get("generation_approved"):
            _request_generation_approval(run)
            return

        step = store.get_agent_run_step(run_id, "image_generation")
        if not step or step["status"] != "SUCCEEDED":
            attempt = int((step or {}).get("attempt") or 0) + 1
            _save_step(run_id, "image_generation", status="RUNNING", attempt=attempt, error=None, started_at=_now())
            try:
                reference = model_studio_media.get_reference(run["reference_id"])
                if not reference:
                    raise model_studio_media.ModelStudioError("A referência desta execução não está mais ativa; envie novamente a referência.")
                reference_record, reference_bytes = reference
                image_bytes, model_name = model_studio_media.generate_from_reference(
                    reference_bytes, build_photo_prompt(run), run["composition"], run["style"]
                )
                generated = model_studio_media.save_generated(
                    image_bytes, reference_record["id"], objective, model_name
                )
                image_output = {**generated, "image_url": "/model-studio/images/" + generated["image_id"]}
                _save_step(run_id, "image_generation", status="SUCCEEDED", attempt=attempt,
                           output=image_output, completed_at=_now())
                run = store.get_agent_run(run_id)
                results = dict(run.get("result") or {})
                results["image"] = image_output
                results["generation_approved"] = True
                _save_run(run, result=results, error=None)
            except Exception as exc:
                # A network timeout can happen after the provider accepted a paid request.
                # Never retry a paid image request automatically; require a new approval.
                _save_step(run_id, "image_generation", status="FAILED", attempt=attempt,
                           error=f"{type(exc).__name__}: {str(exc)[:700]}", completed_at=_now())
                run = store.get_agent_run(run_id)
                _save_run(run, status="FAILED", current_step="BOT_03",
                          error="A geração falhou ou teve resultado incerto. Não haverá repetição automática para evitar cobrança duplicada.")
                logger.warning("Geração BOT_03 falhou; repetição automática bloqueada.")
                return

        run = store.get_agent_run(run_id)
        quality = (run.get("result") or {}).get("image", {}).get("quality") or {}
        bot4_task = (
            "BOT_04 — Identity Guardian. Interprete apenas os indicadores técnicos abaixo "
            "(resolução, contraste, detalhe e integridade). Não afirme semelhança facial ou "
            "identidade confirmada: isso depende de revisão humana da referência e do resultado. "
            "Liste pontos técnicos aprovados e pendências.\nIndicadores:\n"
            + json.dumps(quality, ensure_ascii=False)
        )
        if not _execute_text_step(run, "technical_and_identity_review", "BOT_04", bot4_task):
            return
        run = store.get_agent_run(run_id)
        results = dict(run.get("result") or {})
        results["human_review_required"] = True
        results["publishing_enabled"] = False
        _save_step(run_id, "technical_and_identity_review", status="WAITING_REVIEW",
                   attempt=int((store.get_agent_run_step(run_id, "technical_and_identity_review") or {}).get("attempt") or 1),
                   output={"analysis": results.get("bot_04", {}).get("content", ""), "human_identity_review_required": True},
                   completed_at=None)
        _save_run(run, status="WAITING_REVIEW", current_step="BOT_04", result=results,
                  error="Aguardando revisão visual humana da identidade e do resultado." )
    finally:
        _run_lock.release()


def record_identity_review(image_id: str, decision: str, note: str = "") -> dict[str, Any] | None:
    """Close the matching run only after the operator reviews the generated image."""
    for run in store.list_agent_runs(statuses=["WAITING_REVIEW"], limit=100):
        image = (run.get("result") or {}).get("image") or {}
        if image.get("image_id") != image_id:
            continue
        steps = store.get_agent_run_steps(run["id"])
        bot4 = next((step for step in steps if step["bot_id"] == "BOT_04"), None)
        if bot4:
            output = dict(bot4.get("output") or {})
            output["human_review"] = {"decision": decision, "note": (note or "")[:1000], "reviewed_at": _now()}
            _save_step(run["id"], "technical_and_identity_review", status="SUCCEEDED" if decision == "APPROVE" else "REJECTED",
                       attempt=int(bot4["attempt"] or 1), output=output, completed_at=_now())
        latest = store.get_agent_run(run["id"])
        results = dict(latest.get("result") or {})
        results["human_review"] = {"decision": decision, "note": (note or "")[:1000], "reviewed_at": _now()}
        final_status = "COMPLETED" if decision == "APPROVE" else "REJECTED"
        return _save_run(latest, status=final_status, current_step="BOT_05", result=results,
                         error=None if decision == "APPROVE" else "Imagem rejeitada na revisão humana.")
    return None


def _worker_loop() -> None:
    while True:
        try:
            for run in store.list_agent_runs(statuses=["QUEUED"], limit=10):
                process_run(run["id"])
        except Exception:
            logger.exception("Falha no worker de execução do Model Studio")
        time.sleep(POLL_SECONDS)


def start_background_executor() -> None:
    """Start one durable-queue poller per API process; DB claim prevents duplicate workers."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, name="automa-x-model-studio-executor", daemon=True)
        thread.start()
        _worker_started = True
        logger.info("Executor BOT_05 iniciado; fila consultada a cada %ss", POLL_SECONDS)
