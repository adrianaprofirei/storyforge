"""FastAPI application: REST API + the built web UI + the in-process render queue.

    storyforge serve            -> http://127.0.0.1:8000

Binds to localhost by default (STORYFORGE_HOST): the API can read and write your projects and
start renders, and it has no authentication, so only expose it on a trusted network.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from storyforge.api.routes import router
from storyforge.config import REPO_ROOT
from storyforge.jobs.manager import get_manager, reset_manager
from storyforge.schemas import ValidationFailed

WEB_DIST = REPO_ROOT / "web" / "dist"

NO_UI = """<!doctype html><html><head><meta charset="utf-8"><title>StoryForge</title>
<style>body{font:16px system-ui;margin:3rem auto;max-width:42rem;padding:0 1rem;color:#222}
code{background:#eee;padding:.1rem .3rem;border-radius:4px}</style></head><body>
<h1>StoryForge API is running</h1>
<p>The web UI has not been built. Build it once with Node.js 20+:</p>
<pre><code>cd web
npm install
npm run build</code></pre>
<p>then reload this page. The API is available under <a href="/api/system">/api</a>
(interactive docs: <a href="/docs">/docs</a>).</p></body></html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_manager()  # start the job workers
    yield
    reset_manager()


def create_app() -> FastAPI:
    app = FastAPI(title="StoryForge", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.exception_handler(ValidationFailed)
    async def _validation(_req: Request, exc: ValidationFailed):
        return JSONResponse(status_code=422, content={"detail": {"errors": exc.errors}})

    @app.exception_handler(FileNotFoundError)
    async def _missing(_req: Request, exc: FileNotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    if (WEB_DIST / "index.html").is_file():
        if (WEB_DIST / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            if path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            f = (WEB_DIST / path).resolve()
            if path and WEB_DIST.resolve() in f.parents and f.is_file():
                return FileResponse(f)
            return FileResponse(WEB_DIST / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def no_ui():
            return HTMLResponse(NO_UI)

    return app


app = create_app()


def ui_built() -> bool:
    return Path(WEB_DIST / "index.html").is_file()
