# Conclave

Multi-expert deliberation rooms. Experts take the floor in round-robin, stream thoughts, critique each other, and stay until they converge — or you pause to direct.

![Conclave UI](docs/conclave-ui.png)

## Stack

- **API:** FastAPI + LangGraph + LangChain + SQLite (`apps/api`)
- **Web:** React + Vite + Tailwind + Framer Motion (`apps/web`)
- **Connectors:** BYOK API keys (OpenAI / Anthropic / Google) — not ChatGPT/Claude chat logins

## Layout (maintainable)

```
apps/api/src/conclave/
  api/         # HTTP routes + serializers
  domain/      # schemas, converge, files, mask, diff
  runtime/     # LangChain providers + ReAct turn
  services/    # room_runner, event bus, message helpers
  db/          # SQLAlchemy models + session

apps/web/src/
  app/         # useConclaveApp hook
  features/
    experts/ | conversations/ | thread/ | files/ | shell/
  shared/
    ui/        # Avatar, Modal
    lib/api.ts # typed REST + SSE client
```

## Quick start

### 1. API

```powershell
cd apps\api
python -m pip install -e ".[dev]"
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m uvicorn conclave.main:app --reload --port 8000
```

### 2. Web

```powershell
cd apps\web
npm install
npm run dev
```

Open http://127.0.0.1:5173

Or use the helper scripts from the repo root:

```powershell
.\scripts\dev-api.ps1
.\scripts\dev-web.ps1
```

## Using Conclave

1. **Add experts** (left sidebar) with a developer API key + model.
2. **New conversation** — set a topic, seat 2+ experts (order = chair order).
3. **Start** — round-robin runs until they converge.
4. **Pause to direct** — inject guidance, attach files, edit the shared doc, then Resume.
5. Attach `.md` / `.txt` / `.csv` / `.json` files; experts can read them and co-edit the shared document.
6. When experts update the shared document, the thread shows a **diff** of what changed. The converged solution renders as Markdown.

## Data

Local data lives in `Conclave/data/` (SQLite + per-conversation files). Gitignored — includes API keys.

## Tests

```powershell
cd apps\api
$env:PYTHONPATH = (Resolve-Path .\src).Path
python -m pytest
```
