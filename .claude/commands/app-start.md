---
description: Liga o app (sobe serve.py em background, valida health, abre browser). Idempotente.
---

Execute o script `scripts/start.sh` no diretório do projeto. Ele cuida de:

1. Verificar se o app já está rodando (lê `.app-state.json` + ping `/api/health`); se já estiver, é no-op idempotente.
2. Subir `python3.12 scripts/serve.py` em background via `nohup`, redirecionando log para `.app-logs/serve.<timestamp>.log`.
3. Aguardar a API responder em `http://127.0.0.1:8000/api/health` (timeout 10s).
4. Salvar PID + URL + caminho do log em `.app-state.json` para o stop saber o que matar.
5. Tentar abrir o navegador no URL automaticamente (`open` no macOS).

Reporte ao usuário o resultado: URL para abrir, PID, e o comando `/app-stop` para derrubar quando terminar.

Se o script falhar, mostre o caminho do log e a primeira linha do erro.
