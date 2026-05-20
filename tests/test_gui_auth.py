from __future__ import annotations

import os

from fastapi.testclient import TestClient

from luminesk.core.config import ManagedServer, UserConfig
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


def test_gui_stop_and_kill_use_docker_actions(monkeypatch, tmp_path) -> None:
	monkeypatch.setenv("LUMINESK_GUI_TOKEN", "secret-token")
	server = ManagedServer(
		name="Test",
		tag="test",
		path=tmp_path,
		core_id="nukkit",
		jar_name="server.jar",
	)
	config = UserConfig(servers={server.tag: server})
	calls: list[str] = []

	def mark_running() -> None:
		config.mark_server_started(
			server.tag,
			pid=1234,
			docker_container_id="container-id",
			docker_container_name="luminesk-test",
			docker_memory_limit="1g",
		)

	monkeypatch.setattr(routes, "load_config", lambda: config)
	monkeypatch.setattr(routes.srv.UserConfig, "save", lambda self: None)
	monkeypatch.setattr(routes.srv, "docker_container_is_running", lambda _: True)
	monkeypatch.setattr(routes.srv, "get_docker_container_pid", lambda _: 1234)
	monkeypatch.setattr(routes.srv, "get_docker_container_exit_code", lambda _: 0)
	monkeypatch.setattr(routes.srv, "remove_docker_container", lambda _: calls.append("rm"))
	monkeypatch.setattr(routes.srv, "stop_docker_container", lambda name: calls.append(f"stop:{name}"))
	monkeypatch.setattr(routes.srv, "kill_docker_container", lambda name: calls.append(f"kill:{name}"))

	app = create_app()
	client = TestClient(app)

	mark_running()
	stop_response = client.post(
		"/api/servers/test/stop",
		headers={"X-LumiNESK-Token": "secret-token"},
	)
	mark_running()
	kill_response = client.post(
		"/api/servers/test/kill",
		headers={"X-LumiNESK-Token": "secret-token"},
	)

	assert stop_response.status_code == 200
	assert stop_response.json()["signal_name"] == "SIGTERM"
	assert kill_response.status_code == 200
	assert kill_response.json()["signal_name"] == "SIGKILL"
	assert calls == ["stop:luminesk-test", "rm", "kill:luminesk-test", "rm"]
