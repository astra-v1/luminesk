from __future__ import annotations

import os

from fastapi.testclient import TestClient

from luminesk.core.config import UserConfig
from luminesk.gui.app import create_app
from luminesk.gui import routes


def test_gui_api_requires_token(monkeypatch) -> None:
	monkeypatch.setenv("LUMINESK_GUI_TOKEN", "secret-token")
	app = create_app()
	client = TestClient(app)

	response = client.get("/api/servers/example")

	assert response.status_code == 401


def test_gui_rejects_cross_origin_post(monkeypatch) -> None:
	monkeypatch.setenv("LUMINESK_GUI_TOKEN", "secret-token")
	app = create_app()
	client = TestClient(app)

	response = client.post(
		"/api/servers/example/start",
		headers={
			"X-LumiNESK-Token": "secret-token",
			"Origin": "https://attacker.example",
			"Host": "testserver",
		},
	)

	assert response.status_code == 403


def test_gui_accepts_token_query_and_sets_cookie(monkeypatch) -> None:
	monkeypatch.setenv("LUMINESK_GUI_TOKEN", "secret-token")
	monkeypatch.setattr(routes, "load_config", lambda: UserConfig())
	app = create_app()
	client = TestClient(app)

	response = client.get("/servers?token=secret-token")

	assert response.status_code == 200
	assert "luminesk_gui_token" in response.cookies
	assert 'meta name="luminesk-gui-token" content="secret-token"' in response.text


def test_create_app_generates_token_when_missing(monkeypatch) -> None:
	monkeypatch.delenv("LUMINESK_GUI_TOKEN", raising=False)
	app = create_app()

	assert app.state.gui_token
	assert os.environ["LUMINESK_GUI_TOKEN"] == app.state.gui_token
