# Sentinel Clone

Local AI agent platform built with Flask (backend) + React/TypeScript (frontend). Features streaming chat via SSE, tool use (file ops, terminal), project/task management, and isolated workspaces.

This build uses a **deterministic stub LLM** that simulates token-by-token streaming without requiring a GPU. To swap in a real model, replace `backend/services/llm_engine.py` with the GPU-based implementation and add `torch`, `transformers`, `accelerate` to `requirements.txt`.

---

## Prerequisites

- **Python 3.10+** with pip
- **Node.js 16+** with npm

---

## Quick Start (Development)

### 1. Backend (Terminal 1)

```bash
cd backend
python -m venv venv

# Windows:
venv\Scripts\activate
# Linux/Mac:
# source venv/bin/activate

pip install -r ../requirements.txt
python app.py
```

Backend starts on **http://localhost:5000**. On first run, seed data (demo project + task) is created automatically.

### 2. Frontend (Terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Frontend starts on **http://localhost:5173**.

### 3. Open Browser

Navigate to **http://localhost:5173**

You should see a sidebar with a "Demo Project" task. Click it to see the 4-step SDD workflow. Click "Start" on the first step to see the streaming chat in action.

---

## Project Structure

```
sentinel-rebuild/
├── requirements.txt                    # Python dependencies
├── backend/
│   ├── app.py                          # Flask entry point (port 5000)
│   ├── config.py                       # Storage dir, debug settings
│   ├── routes/
│   │   ├── projects.py                 # /api/projects
│   │   ├── tasks.py                    # /api/tasks
│   │   ├── chats.py                    # /api/chats (SSE streaming)
│   │   └── files.py                    # /api/tasks/{id}/files, /file, /command
│   └── services/
│       ├── llm_engine.py               # Stub LLM (swap for GPU version)
│       ├── agent_service.py            # Agent loop, tool calling, chat persistence
│       ├── tool_service.py             # ListFiles, ReadFile, WriteFile, Glob, RunCommand
│       ├── workspace_service.py        # Git worktree / file copy workspace isolation
│       ├── task_service.py             # Task CRUD, plan parsing
│       ├── project_service.py          # Project CRUD
│       ├── storage.py                  # JSON file persistence
│       └── seed_data.py                # Demo data on first run
├── frontend/
│   ├── package.json                    # React app dependencies
│   ├── vite.config.ts                  # Dev server + proxy to backend
│   └── src/
│       ├── api/client.ts               # API client wrapper
│       ├── types.ts                    # TypeScript interfaces
│       ├── pages/
│       │   ├── Home.tsx                # Projects & tasks list
│       │   └── TaskDetail.tsx          # Chat, files, terminal tabs
│       └── components/
│           ├── Chat/ChatPanel.tsx       # Streaming chat UI
│           ├── FilesTab.tsx            # File browser
│           ├── TerminalPanel.tsx        # In-browser terminal
│           ├── Sidebar.tsx             # Navigation sidebar
│           ├── NewTaskModal.tsx         # Task creation modal
│           └── StatusPill.tsx          # Task status indicator
└── storage/                            # Runtime data (gitignored)
    ├── projects/                       # {project_id}.json
    ├── tasks/                          # {task_id}.json
    ├── chats/{task_id}/               # {chat_id}.json
    └── workspaces/{task_id}/          # Isolated task workspaces
```

---

## Production Build

### Frontend Build

```bash
cd frontend
npm run build
```

This produces a `dist/` folder with optimized static assets.

### Serving in Production

**Option A: Flask serves frontend (simplest)**

Add to `app.py`:
```python
from flask import send_from_directory
import os

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_frontend(path):
    dist_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
    if path and os.path.exists(os.path.join(dist_dir, path)):
        return send_from_directory(dist_dir, path)
    return send_from_directory(dist_dir, 'index.html')
```

Then run with a production WSGI server:
```bash
pip install gunicorn  # Linux
gunicorn -w 1 -k gevent --timeout 600 app:app --bind 0.0.0.0:5000
```

> **Important**: Use a single worker (`-w 1`) or gevent worker to support SSE streaming. Standard multi-process workers will buffer responses.

**Option B: Nginx reverse proxy**

```nginx
server {
    listen 80;

    # Frontend static files
    location / {
        root /path/to/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;

        # Critical for SSE streaming:
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        chunked_transfer_encoding off;
        add_header X-Accel-Buffering no;
    }
}
```

---

## Swapping in a Real LLM

1. Replace `backend/services/llm_engine.py` with the GPU-based implementation
2. Add to `requirements.txt`:
   ```
   transformers
   torch
   accelerate
   ```
3. Install PyTorch with CUDA: `pip install torch --index-url https://download.pytorch.org/whl/cu124`
4. Set `MODEL_PATH` in `llm_engine.py` to your model directory
5. Restart the backend

The interface is unchanged — `get_llm_engine()`, `stream_chat()`, `count_tokens()`, `force_cancel()` — so the rest of the application works without modification.

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/projects` | List all projects |
| POST | `/api/projects` | Create project (`{name, path}`) |
| DELETE | `/api/projects/<id>` | Delete project (cascades) |
| GET | `/api/tasks` | List tasks (optional `?projectId=`) |
| POST | `/api/tasks` | Create task |
| GET | `/api/tasks/<id>` | Get task with plan steps |
| DELETE | `/api/tasks/<id>` | Delete task |
| POST | `/api/tasks/batch-delete` | Batch delete tasks |
| POST | `/api/tasks/<id>/pause` | Pause task (sendBeacon compatible) |
| PATCH | `/api/tasks/<id>` | Update task status/settings |
| POST | `/api/tasks/<id>/steps/<stepId>/start` | Start a step |
| GET | `/api/tasks/<id>/chats` | List chats for task |
| POST | `/api/tasks/<id>/chats` | Create new chat |
| GET | `/api/chats/<id>/stream` | SSE stream (`?taskId=&message=`) |
| POST | `/api/chats/<id>/cancel` | Cancel chat generation |
| POST | `/api/tasks/<id>/cancel-all` | Cancel all task chats |
| GET | `/api/tasks/<id>/files` | List files (`?path=.`) |
| GET | `/api/tasks/<id>/file` | Read file (`?path=`) |
| POST | `/api/tasks/<id>/file` | Write file (`{path, content}`) |
| POST | `/api/tasks/<id>/command` | Run command (`{command, cwd}`) |

---

## SSE Notes for Proxies

The chat streaming endpoint (`/api/chats/<id>/stream`) uses Server-Sent Events. If you place a reverse proxy in front of the backend, you **must** disable response buffering:

- **Nginx**: `proxy_buffering off; add_header X-Accel-Buffering no;`
- **Apache**: `ProxyPass ... disablereuse=On`
- **Vite dev server**: Already configured in `vite.config.ts`

The Flask response includes these headers:
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

---

## Environment Variables

None required for the stub LLM. For the GPU version:
- `CUDA_VISIBLE_DEVICES=0` — Select GPU device

## Ports

| Service | Port | URL |
|---------|------|-----|
| Backend (Flask) | 5000 | http://localhost:5000 |
| Frontend (Vite) | 5173 | http://localhost:5173 |
