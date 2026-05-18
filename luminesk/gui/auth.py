from __future__ import annotations

import os
import secrets

from urllib.parse import urlparse

from fastapi import HTTPException, Request
from starlette.responses import Response


GUI_TOKEN_ENV = "LUMINESK_GUI_TOKEN"
GUI_TOKEN_COOKIE = "luminesk_gui_token"
GUI_TOKEN_QUERY = "token"
GUI_TOKEN_HEADER = "x-luminesk-token"

UNSAFE_HTTP_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def resolve_gui_token(explicit_token: str | None = None) -> tuple[str, bool]:
	token = (explicit_token or os.environ.get(GUI_TOKEN_ENV) or "").strip()
	if token:
		os.environ[GUI_TOKEN_ENV] = token
		return token, False

	token = secrets.token_urlsafe(32)
	os.environ[GUI_TOKEN_ENV] = token
	return token, True


def get_gui_token_from_environment() -> str:
	token = (os.environ.get(GUI_TOKEN_ENV) or "").strip()
	if token:
		return token

	token, _ = resolve_gui_token()
	return token


def require_gui_auth(request: Request) -> None:
	expected_token = str(getattr(request.app.state, "gui_token", ""))
	provided_token = _extract_request_token(request)
	if not expected_token or not provided_token or not secrets.compare_digest(expected_token, provided_token):
		raise HTTPException(status_code=401, detail="Valid LumiNESK GUI token is required.")

	request.state.gui_token = expected_token

	if request.method.upper() in UNSAFE_HTTP_METHODS:
		_require_same_origin(request)


def attach_gui_auth_cookie(response: Response, request: Request) -> Response:
	if getattr(request.state, "gui_auth_via_query", False):
		response.set_cookie(
			GUI_TOKEN_COOKIE,
			str(getattr(request.app.state, "gui_token", "")),
			httponly=True,
			samesite="strict",
			secure=request.url.scheme == "https",
		)
	return response


def _extract_request_token(request: Request) -> str | None:
	authorization = request.headers.get("authorization", "")
	if authorization.lower().startswith("bearer "):
		return authorization[7:].strip()

	header_token = request.headers.get(GUI_TOKEN_HEADER)
	if header_token:
		return header_token.strip()

	query_token = request.query_params.get(GUI_TOKEN_QUERY)
	if query_token:
		request.state.gui_auth_via_query = True
		return query_token.strip()

	if not request.url.path.startswith("/api/"):
		cookie_token = request.cookies.get(GUI_TOKEN_COOKIE)
		if cookie_token:
			return cookie_token.strip()

	return None


def _require_same_origin(request: Request) -> None:
	host = request.headers.get("host", "").lower()
	if not host:
		return

	origin = request.headers.get("origin")
	if origin:
		origin_host = urlparse(origin).netloc.lower()
		if origin_host and origin_host != host:
			raise HTTPException(status_code=403, detail="Cross-origin GUI request rejected.")
		return

	referer = request.headers.get("referer")
	if referer:
		referer_host = urlparse(referer).netloc.lower()
		if referer_host and referer_host != host:
			raise HTTPException(status_code=403, detail="Cross-origin GUI request rejected.")
