import json
import re
import os
import time
import urllib.error
import urllib.request
from .config import get_groq_api_key

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def ask_agent(agent, user_request):
    api_key = get_groq_api_key()
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não configurada")

    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    system_prompt = (
        "Você é um especialista dentro do sistema AUTOMA X. "
        "Responda em português do Brasil, com clareza e objetividade. "
        "Sua função é: " + agent["function"] + " "
        "Analise somente a solicitação recebida. Entregue: análise, recomendações, "
        "riscos/limitações e próximos passos. Não afirme que executou ações externas. "
        "Não envie mensagens, não faça compras, pagamentos, publicações, exclusões "
        "ou alterações em sistemas. Essas ações exigem aprovação humana."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request}
        ],
        "temperature": 0.3,
        "max_tokens": 700
    }
    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "AUTOMA-X/1.0 (backend integration)"
        },
        method="POST"
    )
    # A Groq pode aplicar limites temporários de tokens por minuto (HTTP 429).
    # Aguarda o tempo informado pelo provedor e repete a chamada até 3 vezes.
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                raw = exc.read().decode("utf-8", errors="replace")
                wait_seconds = 20.0
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        wait_seconds = max(1.0, float(retry_after))
                    except ValueError:
                        pass
                try:
                    parsed_retry = json.loads(raw)
                    error_obj = parsed_retry.get("error")
                    detail_retry = error_obj.get("message", "") if isinstance(error_obj, dict) else str(error_obj or "")
                    match = re.search(r"try again in ([0-9.]+)s", detail_retry, re.IGNORECASE)
                    if match:
                        wait_seconds = max(1.0, float(match.group(1)) + 1.0)
                except (ValueError, TypeError):
                    pass
                wait_seconds = min(wait_seconds, 60.0)
                time.sleep(wait_seconds)
                continue
            # Reprocessa a resposta final (ou outro HTTP error) no tratamento abaixo.
            if exc.code == 429:
                raw = exc.read().decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(raw)
                    error = parsed.get("error")
                    detail = error.get("message") if isinstance(error, dict) else str(error or raw)
                except ValueError:
                    detail = raw
                detail = str(detail).replace(api_key, "[REDACTED]")
                detail = re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", detail, flags=re.IGNORECASE)
                raise RuntimeError("Groq HTTP 429 após novas tentativas: " + " ".join(detail.split())[:350])
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError("Falha de conexão com Groq: " + str(reason)[:250])
        except (KeyError, IndexError, ValueError) as exc:
            raise RuntimeError("Resposta inesperada do provedor de IA: " + str(exc)[:200])

