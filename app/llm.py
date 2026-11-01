import json
import os
import urllib.error
import urllib.request

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

def ask_agent(agent, user_request):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
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
        "max_tokens": 900
    }
    request = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError("Groq HTTP " + str(exc.code) + ": " + detail)
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Falha de conexão com Groq: " + str(exc))
    except (KeyError, IndexError, ValueError) as exc:
        raise RuntimeError("Resposta inesperada do provedor de IA: " + str(exc))
