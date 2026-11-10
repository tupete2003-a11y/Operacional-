# AUTOMA X — Auditoria e plano de integração das redes sociais

**Escopo:** AUTOMA X. Não altera projetos ou serviços externos a este repositório.  
**Estado da auditoria:** 10/11/2026.  
**Segurança:** publicações externas permanecem desativadas; nenhuma credencial é solicitada ou armazenada neste documento.

## Resultado da auditoria do código existente

- O backend FastAPI registra Instagram, TikTok, Facebook, YouTube e Kwai em `app/social.py`.
- O painel exibe as cinco plataformas, mas os estados são inicializados como desconectados.
- `app/main.py` informa explicitamente que as plataformas não estão conectadas e que a publicação externa está desativada.
- `app/social_workflow.py` produz rascunhos e fluxo de aprovação; não executa publicação nas redes.
- Não foram encontrados fluxos OAuth, callbacks de autorização, armazenamento/renovação de tokens por plataforma, endpoints de envio de mídia ou workers de publicação agendada.
- Os arquivos de verificação de domínio TikTok e suas rotas HTTP existem. Isso, isoladamente, não comprova aprovação do aplicativo nem autorização da conta.
- O agendamento atual grava itens na agenda, mas não os envia às redes.

## Arquitetura técnica necessária

1. Criar um módulo de integração independente por plataforma.
2. Implementar OAuth com `state` aleatório, validação de callback e proteção contra CSRF.
3. Guardar tokens e metadados de conexão no backend, criptografados em repouso; nunca no navegador ou em logs.
4. Implementar renovação/expiração de tokens e desconexão/revogação.
5. Expor diagnóstico de conexão que informe somente conectado, escopos autorizados, expiração e último teste — nunca valores de tokens.
6. Criar fila de publicação agendada com idempotência, tentativas limitadas, backoff e registro de status.
7. Manter aprovação humana obrigatória antes de qualquer publicação pública até autorização explícita posterior.
8. Criar testes com mocks e ambiente de sandbox antes de conectar contas reais.

## Checklist por plataforma

### TikTok
- [ ] Criar aplicativo no TikTok for Developers.
- [ ] Adicionar Content Posting API e configurar Direct Post.
- [ ] Configurar URL de redirecionamento OAuth.
- [ ] Solicitar e obter aprovação dos escopos necessários, incluindo `video.publish`.
- [ ] Autorizar a conta TikTok e testar consulta de informações do criador.
- [ ] Testar envio e consulta de status.
- [ ] Solicitar auditoria do aplicativo para liberar visibilidade pública; clientes não auditados podem ficar restritos a publicações privadas.

Documentação: https://developers.tiktok.com/docs/en/content-posting-api-get-started  
Portal: https://developers.tiktok.com/

### Instagram
- [ ] Confirmar conta profissional elegível (Empresa ou Criador).
- [ ] Criar aplicativo Meta e habilitar o produto/API aplicável ao tipo de login escolhido.
- [ ] Configurar OAuth, URLs de retorno e permissões de publicação.
- [ ] Concluir App Review e verificações exigidas pela Meta.
- [ ] Testar publicação de mídia compatível e consulta de status.

Documentação: https://developers.facebook.com/docs/instagram-platform/  
Portal: https://developers.facebook.com/

### Facebook
- [ ] Criar/configurar aplicativo Meta.
- [ ] Confirmar uma Página administrada pela conta autorizadora.
- [ ] Configurar Facebook Login e permissões de leitura/publicação de Página.
- [ ] Concluir App Review/Business Verification quando exigidos.
- [ ] Testar publicação somente na Página autorizada.

Documentação: https://developers.facebook.com/docs/pages-api/  
Portal: https://developers.facebook.com/

### YouTube
- [ ] Criar projeto no Google Cloud e habilitar YouTube Data API v3.
- [ ] Configurar tela de consentimento OAuth e URI de redirecionamento.
- [ ] Solicitar os escopos mínimos necessários para upload.
- [ ] Autorizar o canal e testar upload privado/não listado.
- [ ] Verificar quota e requisitos de auditoria aplicáveis ao projeto.

Documentação: https://developers.google.com/youtube/v3  
Portal: https://console.cloud.google.com/

### Kwai
- [ ] Confirmar disponibilidade de acesso à plataforma oficial de desenvolvedores para a conta/região.
- [ ] Confirmar produto de publicação de vídeos, requisitos de parceria e permissões disponíveis.
- [ ] Obter credenciais e documentação diretamente no portal oficial.
- [ ] Implementar somente endpoints e escopos oficialmente concedidos.
- [ ] Testar em ambiente autorizado antes de liberar qualquer publicação.

Portal oficial: https://open.kuaishou.com/

## Variáveis de ambiente — nomes propostos, ainda não configurados

As credenciais só devem ser adicionadas ao serviço AUTOMA X no Render depois de cada aplicativo ser criado e aprovado. Não enviar segredos por chat.

- TikTok: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`
- Meta (Instagram/Facebook): `META_APP_ID`, `META_APP_SECRET`
- YouTube/Google: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- Kwai: nomes a confirmar conforme documentação e credenciais oficialmente fornecidas.

Também será necessário definir uma chave de criptografia de tokens, armazenada apenas no Render, e as URLs de callback finais após a implementação.

## Critérios de conclusão

Uma rede só poderá aparecer como **Conectada** depois de um OAuth real concluído e de uma chamada de diagnóstico bem-sucedida. Uma rede só poderá aparecer como **Publicação habilitada** depois de permissões, revisão e teste apropriado confirmados. A simples presença de Client ID/Secret não comprova conexão.

**Estado atual:** nenhuma das cinco redes foi autenticada pelo AUTOMA X; nenhuma publicação externa foi executada.
