from __future__ import annotations

import json
import os
import time

from pathlib import Path
from typing import Any, ClassVar

import httpx
from platformdirs import user_cache_dir
from pydantic import BaseModel, ConfigDict, ValidationError

from luminesk.core.messages import t


REGISTRY_URL_ENV = "LUMINESK_REGISTRY_URL"
REGISTRY_CACHE_FILE = Path(user_cache_dir("luminesk")) / "core-registry.json"
REGISTRY_CACHE_TTL_SECONDS = 300
REGISTRY_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class CoreProvider(BaseModel):
	model_config = ConfigDict(frozen=True)

	id: str
	name: str
	description: str
	url: str
	config_file: str = "server.properties"

	def get_availability_check_url(self) -> str:
		from luminesk.utils.downloads import get_availability_check_url

		return get_availability_check_url(self)

	def get_latest_download_url(self) -> str:
		from luminesk.utils.downloads import get_latest_download_url

		return get_latest_download_url(self)


class Maven(CoreProvider):
	group_id: str
	artifact_id: str
	classifier: str | None = None
	is_snapshot: bool = False


class Jenkins(CoreProvider):
	pass


class GitHubRelease(CoreProvider):
	release_file: str


class CoreRegistry:
	_cores: ClassVar[dict[str, CoreProvider] | None] = None

	@classmethod
	def get_all(cls) -> list[CoreProvider]:
		return list(cls._load_cores().values())

	@classmethod
	def get_by_id(cls, core_id: str) -> CoreProvider | None:
		return cls._load_cores().get(core_id.strip().lower())

	@classmethod
	def _load_cores(cls) -> dict[str, CoreProvider]:
		if cls._cores is None:
			cls._cores = _parse_registry_payload(_load_registry_payload())
		return cls._cores


def _load_registry_payload() -> dict[str, Any]:
	registry_url = os.environ.get(REGISTRY_URL_ENV, "").strip()
	if registry_url:
		cached_payload = _read_cached_registry(fresh_only=True)
		if cached_payload is not None:
			return cached_payload

		try:
			payload = _fetch_registry_payload(registry_url)
		except (httpx.HTTPError, ValueError, OSError):
			cached_payload = _read_cached_registry(fresh_only=False)
			if cached_payload is not None:
				return cached_payload
		else:
			_write_cached_registry(payload)
			return payload

	cached_payload = _read_cached_registry(fresh_only=False)
	if cached_payload is not None:
		return cached_payload

	raise RuntimeError(t("registry.url_missing", env_var=REGISTRY_URL_ENV))


def _fetch_registry_payload(url: str) -> dict[str, Any]:
	with httpx.Client(timeout=REGISTRY_HTTP_TIMEOUT, follow_redirects=True) as client:
		response = client.get(url)
		response.raise_for_status()
		payload = response.json()
	if not isinstance(payload, dict):
		raise ValueError(t("registry.invalid_payload"))
	return payload


def _read_cached_registry(*, fresh_only: bool) -> dict[str, Any] | None:
	try:
		if fresh_only:
			age_seconds = time.time() - REGISTRY_CACHE_FILE.stat().st_mtime
			if age_seconds > REGISTRY_CACHE_TTL_SECONDS:
				return None
		payload = json.loads(REGISTRY_CACHE_FILE.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None

	return payload if isinstance(payload, dict) else None


def _write_cached_registry(payload: dict[str, Any]) -> None:
	try:
		REGISTRY_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
		REGISTRY_CACHE_FILE.write_text(
			json.dumps(payload, ensure_ascii=True, indent=2),
			encoding="utf-8",
		)
	except OSError:
		return


def _parse_registry_payload(payload: dict[str, Any]) -> dict[str, CoreProvider]:
	raw_cores = payload.get("cores")
	if not isinstance(raw_cores, list):
		raise RuntimeError(t("registry.invalid_payload"))

	cores: dict[str, CoreProvider] = {}
	for raw_core in raw_cores:
		if not isinstance(raw_core, dict):
			raise RuntimeError(t("registry.invalid_payload"))
		core = _parse_core(raw_core)
		cores[core.id] = core
	return cores


def _parse_core(raw_core: dict[str, Any]) -> CoreProvider:
	provider_type = str(raw_core.get("type", "")).strip().lower()
	model_type: type[CoreProvider]
	if provider_type == "maven":
		model_type = Maven
	elif provider_type == "jenkins":
		model_type = Jenkins
	elif provider_type == "github_release":
		model_type = GitHubRelease
	else:
		raise RuntimeError(t("registry.unsupported_provider", provider_type=provider_type))

	try:
		core = model_type.model_validate(raw_core)
	except ValidationError as exc:
		raise RuntimeError(t("registry.invalid_core", error=str(exc))) from exc

	return core.model_copy(update={"id": core.id.strip().lower()})


registry = CoreRegistry()
