from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from luminesk.core import manager as srv
from luminesk.utils.logs import find_latest_log_path, normalize_log_line_raw, read_log_tail
from luminesk.utils.docker import build_docker_container_name, docker_container_is_running

from .auth import attach_gui_auth_cookie
from .constants import LOG_TAIL_LIMIT


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def render_servers_page(
	request: Request,
	views: list[srv.ServerRuntimeView],
):
	total = len(views)
	running = sum(1 for view in views if view.status == "running")
	stopped = total - running
	server_rows = [_build_server_row(view) for view in views]

	response = templates.TemplateResponse(
		request,
		"servers.html",
		{
			"title": "Servers",
			"total": total,
			"running": running,
			"stopped": stopped,
			"servers": server_rows,
		},
	)
	return attach_gui_auth_cookie(response, request)


def render_server_page(
	request: Request,
	view: srv.ServerRuntimeView,
):
	server = view.server
	log_path = find_latest_log_path(server)
	console_text = (
		"\n".join(read_log_tail(log_path, limit=LOG_TAIL_LIMIT, normalize=normalize_log_line_raw))
		if log_path is not None
		else "Log file has not been created yet."
	)
	container_name = view.docker_container_name or build_docker_container_name(server.tag)
	command_available = view.status == "running" and docker_container_is_running(container_name)
	command_hint = _command_hint(view, command_available)

	response = templates.TemplateResponse(
		request,
		"server.html",
		{
			"title": server.name,
			"server": _build_server_detail(view),
			"command_available": command_available,
			"command_hint": command_hint,
			"console_text": console_text,
			"log_tail_limit": LOG_TAIL_LIMIT,
			"log_path_display": str(log_path) if log_path is not None else "No log file yet",
		},
	)
	return attach_gui_auth_cookie(response, request)


def serialize_server_view(view: srv.ServerRuntimeView) -> dict[str, object]:
	server = view.server
	return {
		"tag": server.tag,
		"name": server.name,
		"core_id": server.core_id,
		"core_version": server.core_version,
		"jar_name": server.jar_name,
		"memory_limit": server.memory_limit,
		"path": str(server.path),
		"status": view.status,
		"status_label": _status_text(view),
		"pid": view.pid,
		"loop_enabled": view.loop_enabled,
		"docker_container_name": view.docker_container_name,
		"uptime": srv.format_timedelta(view.uptime),
		"last_started_at": view.last_started_at.astimezone().isoformat() if view.last_started_at else None,
		"last_stopped_at": view.last_stopped_at.astimezone().isoformat() if view.last_stopped_at else None,
		"last_exit_code": view.last_exit_code,
	}


def _build_server_row(view: srv.ServerRuntimeView) -> dict[str, str]:
	server = view.server
	return {
		"name": server.name,
		"tag": server.tag,
		"path_name": server.path.name,
		"core_id": server.core_id,
		"core_version": server.core_version or "unknown",
		"memory_limit": server.memory_limit,
		"status_label": _status_text(view),
		"status_class": _status_class(view),
		"pid": str(view.pid or "-"),
		"uptime": srv.format_timedelta(view.uptime),
		"last_started_at": _format_datetime(view.last_started_at),
	}


def _build_server_detail(view: srv.ServerRuntimeView) -> dict[str, str]:
	server = view.server
	return {
		"name": server.name,
		"tag": server.tag,
		"core_id": server.core_id,
		"core_version": server.core_version or "unknown",
		"jar_name": server.jar_name,
		"memory_limit": server.memory_limit,
		"path": str(server.path),
		"status_label": _status_text(view),
		"status_class": _status_class(view),
		"pid": str(view.pid or "-"),
		"uptime": srv.format_timedelta(view.uptime),
		"last_started_at": _format_datetime(view.last_started_at),
		"last_stopped_at": _format_datetime(view.last_stopped_at),
		"docker_container_name": view.docker_container_name or "-",
	}


def _status_text(view: srv.ServerRuntimeView) -> str:
	parts = ["Running" if view.status == "running" else "Stopped"]
	if view.loop_enabled:
		parts.append("loop")
	if view.docker_container_name:
		parts.append(view.docker_container_name)
	return " / ".join(parts)


def _status_class(view: srv.ServerRuntimeView) -> str:
	return "running" if view.status == "running" else "stopped"


def _format_datetime(value: datetime | None) -> str:
	if value is None:
		return "-"
	return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _command_hint(view: srv.ServerRuntimeView, command_available: bool) -> str:
	if view.status != "running":
		return "Start the server to use the console."
	if command_available:
		return "Console commands are available while the Docker container is active."
	return "This server is not running inside an active Docker container, so commands are unavailable."
