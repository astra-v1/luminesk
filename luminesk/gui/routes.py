from __future__ import annotations

import json
import signal
import subprocess

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from luminesk.core import manager as srv
from luminesk.tui.launcher import launch_server_detached
from luminesk.utils.logs import find_latest_log_path, normalize_log_line_raw, read_log_tail
from luminesk.utils.tmux import build_tmux_session_name, send_tmux_command, tmux_session_exists

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
async def start_server(tag: str) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	view = srv.get_runtime_view(config, server)
	if view.status == "running":
		return _json_error(f"Server '{server.tag}' is already running.", status_code=409)

	try:
		launch_result = launch_server_detached(server)
	except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
		return _json_error(str(exc), status_code=400)

	return JSONResponse(
		{
			"ok": True,
			"message": f"Server '{server.tag}' started.",
			"session_name": launch_result.session_name,
			"log_path": str(launch_result.log_path),
		}
	)


@router.post("/api/servers/{tag}/stop")
async def stop_server(tag: str) -> JSONResponse:
	return _signal_server(tag, signal.SIGTERM)


@router.post("/api/servers/{tag}/kill")
async def kill_server(tag: str) -> JSONResponse:
	return _signal_server(tag, signal.SIGKILL)


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

	session_name = view.tmux_session_name or build_tmux_session_name(server.tag)
	if not tmux_session_exists(session_name):
		return _json_error(
			f"tmux session '{session_name}' was not found. Console is unavailable.",
			status_code=409,
		)

	try:
		send_tmux_command(session_name, command)
	except RuntimeError as exc:
		return _json_error(str(exc), status_code=400)

	return JSONResponse({"ok": True, "message": f"Command sent: {command}"})


def _signal_server(tag: str, sig: signal.Signals) -> JSONResponse:
	config = load_config()
	server = get_server_or_404(config, tag)
	try:
		result = srv.send_signal_to_server(
			config=config,
			target=server.tag,
			sig=int(sig),
			force=True,
		)
	except srv.ServerManagerError as exc:
		return _json_error(str(exc), status_code=400)

	action = "stopped" if sig == signal.SIGTERM else "killed"
	return JSONResponse(
		{
			"ok": True,
			"message": f"Server '{server.tag}' {action}.",
			"signal_name": result.signal_name,
		}
	)


def _json_error(message: str, status_code: int) -> JSONResponse:
	return JSONResponse({"ok": False, "error": message}, status_code=status_code)
