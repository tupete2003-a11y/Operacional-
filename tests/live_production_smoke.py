"""Opt-in live smoke test. Creates one clearly labeled draft and pending approval; never publishes."""
import json
import os
import sys
import urllib.error
import urllib.request


BASE_URL = os.getenv("AUTOMA_X_API_URL", "https://automa-x-api.onrender.com").rstrip("/")
TOKEN = os.getenv("API_ACCESS_TOKEN", "")


def request(path, method="GET", payload=None):
    headers = {"X-API-Key": TOKEN, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} returned HTTP {exc.code}: {body[:500]}") from exc


def main():
    if not TOKEN:
        raise SystemExit("API_ACCESS_TOKEN is required; no live test was run.")

    # This request invokes all five configured bots through the real production Groq path.
    # It writes one labeled task and one pending approval. Publishing remains disabled.
    result = request("/social/workflow", "POST", {
        "objective": "AUTOMA X LIVE SMOKE TEST - conteúdo interno de validação; não publicar",
        "platforms": ["Instagram"],
        "content_types": ["text"],
    })

    task_id = result.get("task_id")
    approval_id = result.get("approval_id")
    expected_bots = {"BOT_05", "BOT_02", "BOT_03", "BOT_04", "BOT_01"}
    outputs = result.get("outputs") or {}
    if not task_id or not approval_id or set(outputs) != expected_bots:
        raise RuntimeError("Workflow returned incomplete bot outputs or missing task/approval IDs.")
    if result.get("status") != "DRAFT_REVIEW" or result.get("publishing_enabled") is not False:
        raise RuntimeError("Workflow did not preserve draft-only / approval-required safety state.")

    # Separate authenticated requests verify that task and approval records can be read back.
    task = request("/tasks/" + task_id)
    approvals = request("/approvals").get("approvals", [])
    matching = next((item for item in approvals if item.get("id") == approval_id), None)
    if task.get("status") != "DRAFT_REVIEW":
        raise RuntimeError("Persisted task could not be read back in DRAFT_REVIEW.")
    if not matching or matching.get("status") != "PENDING":
        raise RuntimeError("Pending approval could not be read back.")

    print(json.dumps({
        "result": "PASS",
        "task_id": task_id,
        "approval_id": approval_id,
        "bots_executed": sorted(outputs),
        "task_readback": "PASS",
        "approval_readback": "PASS",
        "publishing_enabled": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("LIVE_SMOKE_TEST_FAILED:", str(exc)[:1000], file=sys.stderr)
        raise
