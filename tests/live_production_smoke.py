"""Production smoke test: health, real Groq five-bot workflow, task/approval readback.

Creates exactly one clearly labeled draft task and one pending approval.
Never publishes, approves, rejects, or deletes anything.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.getenv("AUTOMA_X_API_URL", "https://automa-x-api.onrender.com").rstrip("/")
TOKEN = os.getenv("API_ACCESS_TOKEN", "")
EXPECTED_BOTS = ["BOT_02", "BOT_03", "BOT_01", "BOT_04", "BOT_05"]


def request(path, method="GET", payload=None, attempts=3):
    headers = {"X-API-Key": TOKEN, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(attempts):
        req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=100) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(10)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {body[:400]}") from exc
    raise RuntimeError(f"{method} {path} did not respond after retries: {last_error}")


def main():
    if not TOKEN:
        raise SystemExit("API_ACCESS_TOKEN is required; no live test was run.")

    health = request("/health")
    if health.get("status") != "ok":
        raise RuntimeError("FastAPI health endpoint did not return status=ok.")

    dashboard = request("/social/dashboard")
    if dashboard.get("ai_provider") != "Groq" or not dashboard.get("ai_provider_configured"):
        raise RuntimeError("Production dashboard does not confirm Groq configuration.")

    # This calls the real production Groq path. One test draft + approval are persisted.
    result = request("/social/workflow", "POST", {
        "objective": "AUTOMA X LIVE SMOKE TEST - conteúdo interno de validação; não publicar",
        "platforms": ["Instagram"],
        "content_types": ["text"],
    }, attempts=1)

    task_id = result.get("task_id")
    approval_id = result.get("approval_id")
    outputs = result.get("outputs") or {}
    stages = result.get("stages") or []
    if not task_id or not approval_id:
        raise RuntimeError("Workflow did not return task and approval identifiers.")
    if list(outputs.keys()) != EXPECTED_BOTS:
        raise RuntimeError("Five-bot output set/order is incomplete: " + ", ".join(outputs.keys()))
    if [stage.get("bot_id") for stage in stages] != EXPECTED_BOTS:
        raise RuntimeError("Five-bot stage execution order is incomplete.")
    if any(stage.get("status") != "COMPLETED" for stage in stages):
        raise RuntimeError("At least one bot stage did not complete.")
    if result.get("status") != "DRAFT_REVIEW" or result.get("publishing_enabled") is not False:
        raise RuntimeError("Draft-only / approval-required safety state was not preserved.")

    task = request("/tasks/" + task_id)
    approvals = request("/approvals").get("approvals", [])
    matching = next((item for item in approvals if item.get("id") == approval_id), None)
    if task.get("status") != "DRAFT_REVIEW":
        raise RuntimeError("Created task could not be read back.")
    if not matching or matching.get("status") != "PENDING":
        raise RuntimeError("Pending approval could not be read back.")

    print(json.dumps({
        "result": "PASS",
        "health": "PASS",
        "groq_dashboard_configured": "PASS",
        "five_real_bot_stages": "PASS",
        "task_create_and_readback": "PASS",
        "approval_create_and_readback": "PASS",
        "task_id": task_id,
        "approval_id": approval_id,
        "publishing_enabled": False,
        "restart_persistence": "NOT_TESTED_BY_THIS_RUN",
        "database_backend": "NOT_EXPOSED_BY_CURRENT_API",
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("LIVE_SMOKE_TEST_FAILED:", str(exc)[:800], file=sys.stderr)
        raise
