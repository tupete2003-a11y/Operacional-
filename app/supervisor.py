"""AUTOMA X autonomous supervisor: safe, persistent operational auditing.

This service performs non-destructive health checks on a schedule. It never
changes secrets, deploys code, publishes externally, spends money, or deletes data.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from . import store
from .config import get_groq_api_key
from .social import BOTS, PLATFORMS

logger = logging.getLogger("automa_x.supervisor")
INTERVAL_SECONDS = max(300, min(3600, int(os.getenv("AUTOMA_X_SUPERVISOR_INTERVAL_SECONDS", "900"))))
_lock = threading.Lock()
_started = False
_last_audit = None


def _now():
    return datetime.now(timezone.utc).isoformat()


def run_audit():
    """Run a read-only system audit and persist its report in the existing message log."""
    global _last_audit
    checks = {}
    try:
        checks["database_connected"] = bool(store.check_connection())
        checks["database_backend"] = store.backend()
    except Exception as exc:
        checks["database_connected"] = False
        checks["database_error_type"] = type(exc).__name__

    checks["groq_key_configured"] = bool(get_groq_api_key())
    checks["registered_bots"] = [bot["id"] for bot in BOTS]
    checks["registered_bot_count"] = len(BOTS)
    checks["registered_platforms"] = list(PLATFORMS)
    checks["external_publishing_enabled"] = False

    try:
        tasks = store.list_tasks()
        approvals = store.list_approvals()
        checks["tasks_total"] = len(tasks)
        checks["tasks_in_progress"] = sum(1 for item in tasks if item.get("status") == "IN_PROGRESS")
        checks["approvals_pending"] = sum(1 for item in approvals if item.get("status") == "PENDING")
    except Exception as exc:
        checks["operational_records_readable"] = False
        checks["records_error_type"] = type(exc).__name__
    else:
        checks["operational_records_readable"] = True

    issues = []
    if not checks.get("database_connected"):
        issues.append("Banco de dados indisponível ou não verificável.")
    if checks.get("database_backend") != "postgresql":
        issues.append("Armazenamento não é PostgreSQL.")
    if not checks.get("groq_key_configured"):
        issues.append("Credencial Groq não detectada; presença não comprova resposta real.")
    if checks.get("registered_bot_count") != 5:
        issues.append("Quantidade de bots diferente de cinco.")
    if not checks.get("operational_records_readable"):
        issues.append("Não foi possível ler tarefas e aprovações.")

    report = {
        "timestamp": _now(),
        "supervisor": "AUTOMA_X_SUPERVISOR",
        "mode": "authorized_autonomous_read_only_audit",
        "status": "ATTENTION" if issues else "HEALTHY",
        "checks": checks,
        "issues": issues,
        "next_action": "Diagnóstico humano ou execução de teste específico; nenhuma ação externa foi executada.",
        "safety": {
            "secrets_modified": False,
            "data_deleted": False,
            "deployment_triggered": False,
            "external_publication": False,
            "financial_action": False
        }
    }
    _last_audit = report
    try:
        store.add_message("supervisor", json.dumps(report, ensure_ascii=False))
    except Exception:
        logger.exception("Não foi possível persistir o relatório do supervisor")
    logger.info("Auditoria do supervisor concluída: %s", report["status"])
    return report


def get_status():
    recent = []
    try:
        for item in reversed(store.get_messages(100)):
            if item.get("role") != "supervisor":
                continue
            try:
                recent.append(json.loads(item.get("content", "{}")))
            except (TypeError, ValueError):
                continue
            if len(recent) >= 5:
                break
    except Exception:
        logger.exception("Não foi possível carregar o histórico do supervisor")
    return {
        "enabled": True,
        "mode": "authorized_autonomous_read_only_audit",
        "interval_seconds": INTERVAL_SECONDS,
        "last_audit": recent[0] if recent else _last_audit,
        "recent_audits": recent,
        "capabilities": [
            "auditoria periódica da API, banco, credencial presente, bots, tarefas e aprovações",
            "registro persistente dos resultados no histórico operacional"
        ],
        "requires_external_executor_for": [
            "alterações de código no GitHub",
            "deploy e rollback",
            "correções que alterem dados ou configurações",
            "integrações OAuth e publicação em redes sociais"
        ],
        "safety": {
            "secrets_modified": False,
            "external_publication": False,
            "destructive_actions": False
        }
    }


def _background_loop():
    while True:
        try:
            run_audit()
        except Exception:
            logger.exception("Falha na auditoria automática do supervisor")
        time.sleep(INTERVAL_SECONDS)


def start_background_supervisor():
    """Start one daemon audit loop per API process."""
    global _started
    with _lock:
        if _started:
            return
        thread = threading.Thread(
            target=_background_loop,
            name="automa-x-supervisor",
            daemon=True
        )
        thread.start()
        _started = True
        logger.info("Supervisor autônomo iniciado; intervalo=%ss", INTERVAL_SECONDS)
