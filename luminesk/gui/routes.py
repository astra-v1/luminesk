from __future__ import annotations

import json
import subprocess

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from luminesk.core import manager as srv
from luminesk.tui.launcher import launch_server_detached
from luminesk.utils.logs import find_latest_log_path, normalize_log_line_raw, read_log_tail
from luminesk.utils.docker import (
	build_docker_container_name,
	docker_container_is_running,
	normalize_memory_limit,
	send_docker_command,
)

from .auth import attach_gui_auth_cookie, require_gui_auth
from .constants import LOG_TAIL_LIMIT
from .services import get_server_or_404, load_config
from .views import render_server_page, render_servers_page, serialize_server_view


router = APIRouter(dependencies=[Depends(require_gui_auth)])


@router.get("/", include_in_schema=False)
async def root(request: Request) -> RedirectResponse:
	response = RedirectResponse(url="/servers", status_code=303)
	return attach_gui_auth_cookie(response, request)


@router.get("/servers", response_class=HTMLResponse)
async def servers_page(request: Request) -> HTMLResponse:
	config = load_config()
	views = srv.get_runtime_views(config)
	return render_servers_page(request, views)


@router.get("/servers/{tag}", response_class=HTMLResponse)
async def server_page(request: Request, tag: str) -> HTMLResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)
	return render_server_page(request, view)


@router.get("/api/servers/{tag}")
async def server_snapshot(tag: str) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)
	return JSONResponse(
		{
			"ok": True,
			"server": serialize_server_view(view),
			"updated_at": datetime.now().astimezone().isoformat(),
		}
	)


@router.get("/api/servers/{tag}/console")
async def server_console(tag: str, lines: int = LOG_TAIL_LIMIT) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)
	limit = max(20, min(lines, 500))
	log_path = find_latest_log_path(server)
	log_lines = [] if log_path is None else read_log_tail(
		log_path,
		limit=limit,
		normalize=normalize_log_line_raw,
	)

	return JSONResponse(
		{
			"ok": True,
			"server": serialize_server_view(view),
			"log": {
				"path": str(log_path) if log_path is not None else None,
				"lines": log_lines,
				"empty": not log_lines,
			},
			"updated_at": datetime.now().astimezone().isoformat(),
		}
	)


@router.post("/api/servers/{tag}/start")
async def start_server(tag: str, request: Request) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)
	if view.status == "running":
		return _json_error(f"Server '{server.tag}' is already running.", status_code=409)

	try:
		memory_limit = await _read_optional_memory_limit(request)
		if memory_limit is not None:
			server.memory_limit = memory_limit
			config.save()
		launch_result = launch_server_detached(server, config=config)
	except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
		return _json_error(str(exc), status_code=400)

	return JSONResponse(
		{
			"ok": True,
			"message": f"Server '{server.tag}' started.",
			"container_name": launch_result.container_name,
			"memory_limit": launch_result.memory_limit,
			"log_path": str(launch_result.log_path),
		}
	)


@router.post("/api/servers/{tag}/stop")
async def stop_server(tag: str) -> JSONResponse:
	return _control_server(tag, "stop")


@router.post("/api/servers/{tag}/kill")
async def kill_server(tag: str) -> JSONResponse:
	return _control_server(tag, "kill")


@router.post("/api/servers/{tag}/command")
async def send_server_command(tag: str, request: Request) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)

	try:
		payload = await request.json()
	except (json.JSONDecodeError, ValueError):
		return _json_error("Request body must be valid JSON.", status_code=400)

	command = str(payload.get("command", "")).strip() if isinstance(payload, dict) else ""
	if not command:
		return _json_error("Command must not be empty.", status_code=400)

	if view.status != "running":
		return _json_error(f"Server '{server.tag}' is not running.", status_code=409)

	container_name = view.docker_container_name or build_docker_container_name(server.tag)
	if not docker_container_is_running(container_name):
		return _json_error(
			f"Docker container '{container_name}' was not found. Console is unavailable.",
			status_code=409,
		)

	try:
		send_docker_command(container_name, command)
	except RuntimeError as exc:
		return _json_error(str(exc), status_code=400)

	return JSONResponse({"ok": True, "message": f"Command sent: {command}"})


def _control_server(tag: str, action: str) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	try:
		if action == "kill":
			result = srv.kill_server(config=config, target=server.tag, force=True)
		else:
			result = srv.stop_server(config=config, target=server.tag, force=True)
	except srv.ServerManagerError as exc:
		return _json_error(str(exc), status_code=400)

	message_action = "killed" if action == "kill" else "stopped"
	return JSONResponse(
		{
			"ok": True,
			"message": f"Server '{server.tag}' {message_action}.",
			"signal_name": result.signal_name,
		}
	)


def _json_error(message: str, status_code: int) -> JSONResponse:
	return JSONResponse({"ok": False, "error": message}, status_code=status_code)


async def _read_optional_memory_limit(request: Request) -> str | None:
	try:
		payload = await request.json()
	except (json.JSONDecodeError, ValueError):
		return None

	if not isinstance(payload, dict):
		return None

	raw_memory_limit = payload.get("memory_limit")
	if raw_memory_limit is None:
		return None

	return normalize_memory_limit(str(raw_memory_limit))
