# AUTOMA X — núcleo Python inicial

Este repositório contém o protótipo executável do núcleo AGENT_00.

## O que está implementado
- API HTTP com FastAPI.
- Cadastro dos 30 agentes especialistas.
- AGENT_00 como ponto central de entrada.
- Roteamento inicial por palavras-chave.
- Criação e persistência de tarefas.
- Registro de aprovações para solicitações sensíveis.
- Histórico básico de mensagens.
- SQLite local para começar sem contratar PostgreSQL ou Redis.

## Limitação importante
Os 30 agentes estão cadastrados como perfis especializados, mas ainda não são 30 modelos de IA independentes em execução. Esta versão cria planos e distribui subtarefas. Para execução real, será necessário conectar um provedor de LLM, ferramentas autorizadas e workers. n8n, PostgreSQL e Redis ficam para uma etapa posterior.

## Executar
Requer Python 3.11 ou superior.

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Endpoints: `/`, `/health`, `/agents`, `/chat`, `/tasks`, `/approvals`, `/memory`. Documentação interativa em `/docs`.

## Segurança
Não exponha a API sem autenticação. Não adicione chaves de API ao Git. Este protótipo não envia mensagens, publica conteúdo, realiza pagamentos ou executa exclusões. Aprovação registrada não significa que uma ação externa tenha sido executada.
