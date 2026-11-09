"""Read-only persistence verification after a production API redeploy.

Finds the labeled live smoke-test task created by the preceding run and verifies
that PostgreSQL still returns the completed five-agent task and its pending
approval after the service restart. It does not create, approve, reject, or
delete records.
"""
import json
import os
import urllib.error
import urllib.request

BASE_URL = os.getenv("AUTOMA_X_API_URL", "https://automa-x-api.onrender.com").rstrip("/")
TOKEN = os.getenv("API_ACCESS_TOKEN", "")
EXPECTED_BOTS = ["BOT_02", "BOT_03", "BOT_01", "BOT_04", "BOT_05"]
TEST_PREFIX = "AUTOMA X LIVE SMOKE TEST - conteúdo interno de validação; não publicar"


def request(path):
    if not TOKEN:
        raise RuntimeError("API_ACCESS_TOKEN não foi disponibilizado ao teste.")
    req = urllib.request.Request(
        BASE_URL + path,
        headers={"X-API-Key": TOKEN, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {path} retornou HTTP {exc.code}.") from exc


def main():
    ready = request("/health/ready")
    database = ready.get("database", {})
    bots = ready.get("bots", {})
    if ready.get("status") != "ready":
        raise RuntimeError("API não está pronta após a publicação.")
    if database.get("backend") != "postgresql" or database.get("connected") is not True or database.get("durable") is not True:
        raise RuntimeError("PostgreSQL durável não foi confirmado após a publicação.")
    if bots.get("registered") != 5:
        raise RuntimeError("A API não registrou exatamente cinco bots após a publicação.")
    if ready.get("publishing", {}).get("enabled") is not False:
        raise RuntimeError("A publicação externa deveria permanecer desativada.")

    tasks = request("/tasks").get("tasks", [])
    matches = [
        task for task in tasks
        if str(task.get("request", "")).startswith(TEST_PREFIX)
        and task.get("status") == "DRAFT_REVIEW"
    ]
    if not matches:
        raise RuntimeError("A tarefa de teste anterior não foi encontrada após a reinicialização.")
    task = matches[0]
    result = task.get("result") or {}
    outputs = result.get("outputs") or {}
    stages = result.get("stages") or []
    if set(outputs.keys()) != set(EXPECTED_BOTS):
        raise RuntimeError("Os cinco resultados não foram preservados na ordem esperada.")
    if [stage.get("bot_id") for stage in stages] != EXPECTED_BOTS:
        raise RuntimeError("A sequência de etapas não foi preservada.")
    if any(stage.get("status") != "COMPLETED" for stage in stages):
        raise RuntimeError("Uma etapa do fluxo não está marcada como concluída.")

    approval_id = result.get("approval_id")
    approvals = request("/approvals").get("approvals", [])
    approval = next(
        (item for item in approvals if item.get("id") == approval_id and item.get("task_id") == task.get("id")),
        None,
    )
    if not approval or approval.get("status") != "PENDING":
        raise RuntimeError("A aprovação pendente não foi preservada após a reinicialização.")

    print(json.dumps({
        "result": "PASS",
        "api_after_redeploy": "PASS",
        "postgresql_connected": "PASS",
        "postgresql_durable": "PASS",
        "five_bot_task_survived_redeploy": "PASS",
        "pending_approval_survived_redeploy": "PASS",
        "external_publishing_enabled": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
