"""Entry point: web dashboard (FastAPI + WebSocket + HTML5 Canvas)."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("web.main:app", host="127.0.0.1", port=8000, reload=False)