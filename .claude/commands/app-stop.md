---
description: Desliga o app (derruba processos registrados em .app-state.json e limpa o arquivo).
---

Execute o script `scripts/stop.sh` no diretório do projeto. Ele cuida de:

1. Ler `.app-state.json` e iterar pelos processos registrados.
2. Mandar SIGTERM para cada PID. Aguardar 1s para shutdown gracioso.
3. Se algum sobrevivente, SIGKILL.
4. Apagar `.app-state.json`.
5. Como fallback defensivo (se o arquivo não existe), procura processos órfãos `serve.py` via `pgrep` e mata.

Idempotente: se nada está rodando, sai com mensagem informativa sem erro. Reporte ao usuário um resumo do que foi parado (`N/M processos parados`).
