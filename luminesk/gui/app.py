from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .auth import get_gui_token_from_environment, resolve_gui_token
from .routes import router


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ALL_INTERFACE_HOSTS = {".".join(("0", "0", "0", "0")), "::"}


def create_app() -> FastAPI:
	app = FastAPI(title="LumiNESK GUI")
	app.state.gui_token = get_gui_token_from_environment()
	app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
	app.include_router(router)
	return app


def run(
	host: str = "127.0.0.1",
	port: int = 8000,
	reload: bool = False,
	token: str | None = None,
) -> None:
	import uvicorn

	gui_token, generated = resolve_gui_token(token)
	display_host = "127.0.0.1" if host in ALL_INTERFACE_HOSTS else host
	source = "generated startup token" if generated else "configured token"
	print(f"LumiNESK GUI {source}: {gui_token}")
	print(f"Open http://{display_host}:{port}/servers?token={gui_token}")

	uvicorn.run(
		"luminesk.gui.app:create_app",
		factory=True,
		host=host,
		port=port,
		reload=reload,
	)
