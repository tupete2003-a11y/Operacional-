# AUTOMA X — Arquitetura operacional

## Objetivo

Transformar o repositório existente em um centro de comando para operações de conteúdo e vendas digitais. Preservar o frontend, a API FastAPI, o Render, o GitHub, as credenciais existentes e os dados. Evoluir por etapas, sem reconstrução desnecessária.

## Princípios

1. O painel deve mostrar estados reais. "Configurado", "conectado", "testado" e "operacional" são estados diferentes.
2. Nenhuma chave secreta no JavaScript, no navegador, no GitHub ou nas respostas da API.
3. Tarefas, etapas, tentativas, aprovações e resultados devem ter histórico persistente.
4. Execuções devem ser idempotentes, rastreáveis, retomáveis e protegidas contra concorrência.
5. Publicação externa, mensagens, pagamentos, compras, exclusões e ações irreversíveis permanecem bloqueadas até autorização específica.
6. A operação diária deve ser automática; o proprietário acompanha resultados e resolve somente concessões de acesso que exijam autenticação humana.

## Agentes

- AGENT_00 — Orquestrador: interpreta objetivos, cria plano, delega, acompanha dependências e consolida resultados.
- BOT_01 — Scheduler AI: calendário editorial, fusos, horários sugeridos, conflitos e lembretes.
- BOT_02 — Trend Writer AI: pesquisa baseada em fontes acessíveis, análise de mercado, ideias, roteiros e textos. Não inventa métricas nem chama pesquisa não realizada de pesquisa ao vivo.
- BOT_03 — Publisher AI: adapta conteúdo por plataforma, prepara legendas, metadados e pacotes de publicação. Publicação real só por APIs oficiais e após aprovação.
- BOT_04 — Manager AI: qualidade, prioridades, dependências, prazos e detecção de falhas.
- BOT_05 — Master Operacional: supervisão dos bots, observabilidade, recuperação e relatório de estado.

## Arquitetura lógica desejada

```text
Painel Web responsivo
       |
       | HTTPS + sessão segura
       v
FastAPI / API Gateway
       |
       +-- Autenticação e autorização
       +-- API de estado e observabilidade
       +-- Gestor de provedores de IA
       +-- Orquestrador AGENT_00
                  |
                  +-- BOT_02 pesquisa e redação
                  +-- BOT_03 produção e adaptação
                  +-- BOT_04 revisão e coordenação
                  +-- BOT_01 agenda
                  +-- BOT_05 supervisão
       |
       +-- PostgreSQL (tarefas, eventos, agenda, aprovações)
       +-- Redis/Valkey (fila, locks, retries)
       +-- Worker de execução assíncrona
       +-- Adaptadores oficiais das plataformas
```

## Componentes e estado atual

| Componente | Estado observado | Próxima evolução |
|---|---|---|
| Frontend | Painel web existente | Conectar todos os módulos à API e remover estados fictícios |
| API FastAPI | Implantada no Render | Endpoints versionados, sessão segura e telemetria |
| Chave API | Token via cabeçalho X-API-Key | Manter compatibilidade e evoluir para sessão HttpOnly sem expor segredos |
| Groq | Adaptador existente | Verificação automática, limites, retries e interface multi-provedor |
| Cinco bots | Definições e fluxo sequencial existentes | Execução assíncrona, eventos, retomada, timeout e validação de saída |
| Tarefas | Persistidas por store | Estados detalhados, histórico de eventos e idempotência |
| Aprovações | Persistência básica | Aprovação ligada à versão exata do conteúdo e auditoria |
| Agenda | Persistência básica | Worker de agendamento, fuso horário, locks e reprogramação |
| Banco | SQLite ou PostgreSQL conforme DATABASE_URL | PostgreSQL para produção e migração validada |
| Fila | Ainda não confirmada | Redis/Valkey e worker separado |
| Redes sociais | Não conectadas | OAuth e APIs oficiais, uma plataforma por vez |
| Publicação | Desativada | Somente após conexão, escopos, revisão e aprovação humana |

## Segurança e autenticação

- Nunca registrar ou devolver tokens, chaves, cookies ou cabeçalhos secretos.
- Segredos de provedores ficam exclusivamente no ambiente seguro do backend.
- A autenticação atual por X-API-Key deve continuar funcionando até que uma migração de sessão esteja implantada e validada.
- Para sessão web futura: cookie Secure, HttpOnly, SameSite apropriado, expiração, logout, proteção CSRF e CORS restrito ao domínio real do painel.
- Não armazenar credenciais de API em localStorage na arquitetura final.
- Diagnósticos públicos limitam-se a /health. Diagnósticos detalhados exigem autenticação.

## Execução e recuperação

Cada execução deve criar um identificador único e registrar:
- solicitação, autor e horário;
- plano e agentes selecionados;
- etapa atual, início, fim e duração;
- tentativa, timeout, erro sanitizado e política de retry;
- artefatos produzidos e versão;
- aprovação vinculada à versão;
- resultado final e trilha de auditoria.

Regras:
- retry exponencial com jitter apenas para erros transitórios;
- não repetir ações externas não idempotentes sem reconciliação;
- lock por tarefa/campanha para impedir execuções concorrentes;
- retomada a partir da última etapa concluída;
- fila de falhas para intervenção técnica;
- limites de custo, tokens, duração e concorrência.

## Provedores de IA

Criar interface comum de provedores com:
- detecção de configuração;
- teste de conectividade sob demanda ou agendado;
- modelo, limites e tempo de resposta;
- classificação de erros e retries;
- fallback somente para outro provedor já configurado;
- proteção contra vazamento de chaves;
- relatório de disponibilidade sem alegar que uma chave configurada prova uma resposta real.

Groq permanece como provedor atual. Outros provedores só entram quando suas credenciais forem fornecidas por canal seguro e o proprietário autorizar a conexão.

## Dados e persistência

PostgreSQL é a fonte de verdade para produção. Redis/Valkey é infraestrutura de fila e lock, não substitui o banco. SQLite fica restrito a desenvolvimento ou ambiente com armazenamento persistente explicitamente configurado.

Antes de qualquer migração:
1. identificar o banco efetivamente ativo;
2. criar backup verificável;
3. migrar e comparar contagens;
4. testar leitura e gravação;
5. manter plano de reversão.

Não apagar nem sobrescrever dados existentes.

## Integrações sociais

Ordem sugerida: conectar uma rede de cada vez, usando OAuth oficial e escopos mínimos. O adaptador precisa separar:
- conta conectada;
- permissões concedidas;
- mídia pronta;
- publicação agendada;
- publicação confirmada pela plataforma;
- falha e reconciliação.

Instagram, TikTok, Facebook, YouTube e Kwai não devem ser exibidos como conectados sem confirmação oficial. Respeitar regras e limites de cada plataforma. Não usar scraping ou automação de navegador para contornar APIs.

## Operação autônoma

Automatizar no backend:
- health check da API e banco;
- verificação do provedor de IA sem criar tarefas comerciais;
- monitoramento de workers e fila;
- detecção de tarefas travadas;
- alertas de falhas e degradação;
- backup e verificação de restauração;
- reconciliação de agendamentos.

O painel deve apresentar último check, horário, resultado e detalhe seguro. Nenhum indicador verde pode ser baseado apenas em configuração.

## Etapas de implementação

### Fase 1 — Visibilidade e confiabilidade
- endpoint autenticado de status operacional;
- status real de banco, IA, bots e plataformas;
- logs estruturados e IDs de correlação;
- health checks sem efeitos colaterais.

### Fase 2 — Execução robusta
- worker e fila;
- máquina de estados de tarefas;
- idempotência, locks, retries e retomada;
- eventos persistentes e histórico no painel.

### Fase 3 — Segurança e administração
- autenticação por sessão segura;
- gestão de provedores no backend;
- papéis, permissões, auditoria e limites de uso.

### Fase 4 — Conteúdo e agenda
- estúdio de conteúdo completo;
- calendário persistente;
- revisão por versão;
- programação e notificações.

### Fase 5 — Redes sociais
- OAuth oficial;
- validação de escopos e contas;
- publicação controlada por aprovação;
- confirmação e reconciliação do resultado.

### Fase 6 — Operação contínua
- monitoramento, backups, métricas e alertas;
- relatórios automáticos;
- recuperação de falhas e otimização de custos.

## Limites de autonomia

A construção do código, deploys não destrutivos, diagnósticos e testes automatizados podem ser executados pelo agente. Concessões OAuth, login em contas pessoais, confirmação de termos das plataformas e inserção inicial de segredos podem exigir uma ação do proprietário, porque somente ele pode conceder legalmente esses acessos. Nenhuma senha ou chave deve ser enviada pelo chat.

## Critério de conclusão

O painel só será considerado operacional quando:
- autenticação funcionar sem expor segredos;
- API, banco e provedor forem verificados por chamadas reais;
- os cinco bots executarem um fluxo de ponta a ponta com histórico;
- tarefa, aprovação e agenda sobreviverem a reinicialização;
- worker recuperar falhas sem duplicar tarefas;
- integrações sociais mostrarem escopos e estado reais;
- publicação exigir aprovação explícita e gerar confirmação verificável.
