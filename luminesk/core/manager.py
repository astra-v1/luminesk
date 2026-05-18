from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import signal
import shutil
import subprocess
import time

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

import httpx

from rich.console import Console
from rich.progress import (
	BarColumn,
	DownloadColumn,
	Progress,
	SpinnerColumn,
	TextColumn,
	TimeRemainingColumn,
	TransferSpeedColumn,
)

from luminesk.core.config import CORE_CACHE_DIR, ManagedServer, UserConfig, utc_now
from luminesk.core.messages import t
from luminesk.core.registry import CoreProvider, registry
from luminesk.utils.downloads import get_latest_download_info
from luminesk.utils.download_models import CoreDownloadInfo
from luminesk.utils.errors import format_error
from luminesk.utils.http import request_with_retries, stream_with_retries
from luminesk.utils.tmux import build_tmux_session_name, tmux_session_exists


RESTART_DELAY_SECONDS = 5
MAX_CORE_DOWNLOAD_BYTES = 512 * 1024 * 1024
SHA256_HEX_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
CORE_DOWNLOAD_TIMEOUT = httpx.Timeout(
	timeout=30.0,
	connect=10.0,
	read=30.0,
	write=30.0,
	pool=10.0,
)


class ServerManagerError(RuntimeError):
	pass


@dataclass(slots=True, frozen=True)
class ServerRuntimeView:
	server: ManagedServer
	status: str
	pid: int | None
	loop_enabled: bool
	tmux_session_name: str | None
	uptime: timedelta | None
	last_started_at: datetime | None
	last_stopped_at: datetime | None
	last_exit_code: int | None


@dataclass(slots=True, frozen=True)
class ResolvedServerTarget:
	server: ManagedServer
	resolved_by: Literal["tag", "pid"]
	value: str


@dataclass(slots=True, frozen=True)
class ServerSignalResult:
	target: ResolvedServerTarget
	signal_name: str
	server_pid: int | None
	loop_active: bool
	force: bool
	signaled_server: bool


@dataclass(slots=True, frozen=True)
class DownloadedCore:
	jar_path: Path
	version: str


@dataclass(slots=True, frozen=True)
class CachedCorePaths:
	cache_directory: Path
	jar_path: Path
	metadata_path: Path


def create_server(
	config: UserConfig,
	name: str,
	tag: str,
	directory: Path,
	core: CoreProvider,
	force: bool = False,
	console: Console | None = None,
) -> ManagedServer:
	normalized_directory = directory.expanduser().resolve()
	_ensure_registration_target_available(config, tag, normalized_directory)

	prepare_server_directory(normalized_directory, force=force)
	ensure_server_config_file(normalized_directory, core.config_file)
	downloaded_core = download_core(core, normalized_directory, console=console)

	server = ManagedServer(
		name=name,
		tag=tag,
		path=normalized_directory,
		core_id=core.id,
		core_version=downloaded_core.version,
		jar_name=downloaded_core.jar_path.name,
	)
	config.register_server(server)
	config.save()
	return server


def register_existing_server(
	config: UserConfig,
	name: str,
	tag: str,
	directory: Path,
	jar_path: Path,
) -> ManagedServer:
	normalized_directory = directory.expanduser().resolve()
	_ensure_registration_target_available(config, tag, normalized_directory)

	if not normalized_directory.exists():
		raise ServerManagerError(
			t("manager.directory_missing", directory=normalized_directory)
		)

	if not normalized_directory.is_dir():
		raise ServerManagerError(
			t("manager.path_not_server_directory", directory=normalized_directory)
		)

	resolved_jar_path = _resolve_server_jar_path(normalized_directory, jar_path)
	core_id = _detect_core_id(normalized_directory, resolved_jar_path)
	server = ManagedServer(
		name=name,
		tag=tag,
		path=normalized_directory,
		core_id=core_id,
		core_version=None,
		jar_name=resolved_jar_path.name,
	)
	config.register_server(server)
	config.save()
	return server


def prepare_server_directory(directory: Path, force: bool = False) -> Path:
	if directory.exists():
		if not directory.is_dir():
			if not force:
				raise ServerManagerError(
					t("manager.path_exists_not_directory", directory=directory)
				)
			directory.unlink()
		elif any(directory.iterdir()):
			if not force:
				raise ServerManagerError(
					t("manager.directory_not_empty", directory=directory)
				)
			shutil.rmtree(directory)

	directory.mkdir(parents=True, exist_ok=True)
	return directory


def ensure_server_config_file(directory: Path, config_file_name: str) -> Path:
	config_file_path = directory / config_file_name
	if not config_file_path.exists():
		config_file_path.write_text(
			t("manager.server_config_header"),
			encoding="utf-8",
		)
	return config_file_path


def download_core(
	core: CoreProvider,
	target_directory: Path,
	console: Console | None = None,
) -> DownloadedCore:
	target_directory.mkdir(parents=True, exist_ok=True)

	with httpx.Client(timeout=CORE_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
		download_info = get_latest_download_info(core, client=client)
		expected_sha256 = _fetch_download_sha256(client, download_info.url)
		cached_core = _restore_cached_core(
			core=core,
			download_info=download_info,
			target_directory=target_directory,
			expected_sha256=expected_sha256,
			console=console,
		)
		if cached_core is not None:
			return cached_core

		temp_path: Path | None = None
		try:
			with stream_with_retries(client, "GET", download_info.url) as response:
				file_name = _resolve_download_file_name(response, download_info.url, core)
				target_path = _resolve_download_target_path(target_directory, file_name)
				temp_path = _get_temporary_file_path(target_path)
				total_size = _parse_content_length(response.headers.get("content-length"))
				_validate_download_size(total_size)
				bytes_downloaded = 0
				sha256 = hashlib.sha256()

				progress = Progress(
					SpinnerColumn(),
					TextColumn("[progress.description]{task.description}"),
					BarColumn(),
					DownloadColumn(),
					TransferSpeedColumn(),
					TimeRemainingColumn(),
					console=console,
					transient=True,
				)

				with progress:
					task_id = progress.add_task(
						t("manager.download_progress", core_name=core.name),
						total=total_size,
					)
					with temp_path.open("wb") as file:
						for chunk in response.iter_bytes():
							if not chunk:
								continue
							bytes_downloaded += len(chunk)
							_validate_download_size(bytes_downloaded)
							sha256.update(chunk)
							file.write(chunk)
							progress.update(task_id, advance=len(chunk))

				actual_sha256 = sha256.hexdigest()
				if not hmac.compare_digest(actual_sha256, expected_sha256):
					_cleanup_path(temp_path)
					raise ServerManagerError(
						"Downloaded core SHA-256 mismatch: "
						f"expected {expected_sha256}, got {actual_sha256}."
					)

				temp_path.replace(target_path)
				_store_core_in_cache(core, download_info, target_path, expected_sha256)
				return DownloadedCore(jar_path=target_path, version=download_info.version)
		except ServerManagerError:
			if temp_path is not None:
				_cleanup_path(temp_path)
			raise
		except httpx.HTTPStatusError as exc:
			raise ServerManagerError(
				t(
					"manager.download_core_http",
					core_name=core.name,
					status_code=exc.response.status_code,
				)
			) from exc
		except httpx.RequestError as exc:
			raise ServerManagerError(
				t("manager.download_core_error", core_name=core.name, error=format_error(exc))
			) from exc


def resolve_server(
	config: UserConfig,
	tag: str | None = None,
	directory: Path | None = None,
) -> ManagedServer:
	if tag:
		server = config.get_server_by_tag(tag)
		if server is None:
			raise ServerManagerError(t("manager.server_not_found_by_tag", tag=tag))
		return server

	search_directory = (directory or Path.cwd()).expanduser().resolve()
	server = config.get_server_by_directory(search_directory)
	if server is None:
		raise ServerManagerError(
			t("manager.server_not_found_for_directory", directory=search_directory)
		)
	return server


def resolve_server_target(config: UserConfig, target: str) -> ResolvedServerTarget:
	sync_runtime_states(config)
	normalized_target = target.strip()
	server = config.get_server_by_tag(normalized_target)

	if server is not None:
		return ResolvedServerTarget(
			server=server,
			resolved_by="tag",
			value=normalized_target,
		)

	if normalized_target.isdigit():
		server = _find_server_by_pid(config, int(normalized_target))
		if server is None:
			raise ServerManagerError(
				t("manager.pid_not_owned", pid=normalized_target)
			)
		return ResolvedServerTarget(
			server=server,
			resolved_by="pid",
			value=normalized_target,
		)

	raise ServerManagerError(t("manager.server_not_found_by_tag", tag=normalized_target))


def sync_runtime_states(config: UserConfig) -> bool:
	changed = False

	for server in config.get_servers():
		server_pid_alive = _is_process_alive(server.runtime.pid)
		loop_active = bool(server.runtime.loop_enabled and server_pid_alive)

		if server_pid_alive:
			continue

		if loop_active:
			continue

		if (
			server.runtime.status != "stopped"
			or server.runtime.pid is not None
			or server.runtime.loop_enabled
		):
			config.mark_server_stopped(server.tag, exit_code=server.runtime.last_exit_code)
			changed = True

	if changed:
		config.save()

	return changed


def get_runtime_view(config: UserConfig, server: ManagedServer) -> ServerRuntimeView:
	sync_runtime_states(config)
	return _build_runtime_view(config, server)


def get_runtime_views(config: UserConfig) -> list[ServerRuntimeView]:
	sync_runtime_states(config)
	return [_build_runtime_view(config, server) for server in config.get_servers()]


def _build_runtime_view(config: UserConfig, server: ManagedServer) -> ServerRuntimeView:
	fresh_server = config.get_server_by_tag(server.tag) or server
	is_running = fresh_server.runtime.status == "running" and _is_process_alive(fresh_server.runtime.pid)
	loop_active = bool(fresh_server.runtime.loop_enabled and is_running)
	uptime = _get_uptime(fresh_server) if is_running else None
	tmux_session_name = _get_active_tmux_session_name(fresh_server) if is_running else None

	return ServerRuntimeView(
		server=fresh_server,
		status="running" if is_running else "stopped",
		pid=fresh_server.runtime.pid if is_running else None,
		loop_enabled=loop_active,
		tmux_session_name=tmux_session_name,
		uptime=uptime,
		last_started_at=fresh_server.runtime.last_started_at,
		last_stopped_at=fresh_server.runtime.last_stopped_at,
		last_exit_code=fresh_server.runtime.last_exit_code,
	)


def send_signal_to_server(
	config: UserConfig,
	target: str,
	sig: int,
	force: bool = False,
) -> ServerSignalResult:
	resolved_target = resolve_server_target(config, target)
	server = config.get_server_by_tag(resolved_target.server.tag) or resolved_target.server
	server_pid_alive = _is_process_alive(server.runtime.pid)
	loop_active = bool(server.runtime.loop_enabled and server_pid_alive)

	if not server_pid_alive and not loop_active:
		raise ServerManagerError(t("manager.server_not_running", tag=server.tag))

	signaled_server = False

	if force and loop_active:
		controller_pid = _get_parent_pid(server.runtime.pid)
		if controller_pid is None:
			raise ServerManagerError(
				t("manager.loop_controller_not_found", tag=server.tag)
			)
		_send_signal(controller_pid, sig)

	if server_pid_alive:
		_send_signal(server.runtime.pid, sig)
		signaled_server = True
	elif loop_active and not force:
		raise ServerManagerError(
			t("manager.loop_waiting_force", tag=server.tag)
		)

	return ServerSignalResult(
		target=resolved_target,
		signal_name=signal.Signals(sig).name,
		server_pid=server.runtime.pid if server_pid_alive else None,
		loop_active=loop_active,
		force=force,
		signaled_server=signaled_server,
	)


def upgrade_server_core(
	config: UserConfig,
	server: ManagedServer,
	console: Console | None = None,
) -> ManagedServer:
	resolved_server = _ensure_server_can_modify_core(config, server)

	if resolved_server.core_version is None:
		raise ServerManagerError(
			t("manager.manual_server_upgrade", tag=resolved_server.tag)
		)

	core = registry.get_by_id(resolved_server.core_id)
	if core is None:
		raise ServerManagerError(
			t("manager.core_not_in_registry", core_id=resolved_server.core_id)
		)

	downloaded_core = download_core(core, resolved_server.path, console=console)
	_remove_previous_managed_jar(resolved_server, downloaded_core.jar_path)
	resolved_server.core_version = downloaded_core.version
	resolved_server.jar_name = downloaded_core.jar_path.name
	config.save()
	return resolved_server


def change_server_core(
	config: UserConfig,
	server: ManagedServer,
	core: CoreProvider,
	console: Console | None = None,
) -> ManagedServer:
	resolved_server = _ensure_server_can_modify_core(config, server)
	downloaded_core = download_core(core, resolved_server.path, console=console)
	_remove_previous_managed_jar(resolved_server, downloaded_core.jar_path)
	ensure_server_config_file(resolved_server.path, core.config_file)
	resolved_server.core_id = core.id
	resolved_server.core_version = downloaded_core.version
	resolved_server.jar_name = downloaded_core.jar_path.name
	config.save()
	return resolved_server


def run_server(
	config: UserConfig,
	server: ManagedServer,
	loop: bool = False,
	console: Console | None = None,
) -> int:
	sync_runtime_states(config)
	runtime_view = get_runtime_view(config, server)

	if runtime_view.status == "running":
		raise ServerManagerError(
			t("manager.server_already_running", tag=server.tag, pid=runtime_view.pid)
		)

	java_bin = shutil.which("java")
	if java_bin is None:
		raise ServerManagerError(t("manager.java_not_in_path"))

	if not server.jar_path.is_file():
		raise ServerManagerError(
			t("manager.jar_not_found", jar_path=server.jar_path)
		)

	last_exit_code = 0

	while True:
		process = subprocess.Popen(
			[java_bin, "-jar", server.jar_name],
			cwd=server.path,
		)
		config.mark_server_started(
			server.tag,
			pid=process.pid,
			loop_enabled=loop,
		)
		config.save()

		if console is not None:
			console.print(
				t(
					"manager.launching_server",
					name=server.name,
					tag=server.tag,
					pid=process.pid,
				)
			)

		interrupted = False

		try:
			last_exit_code = process.wait()
		except KeyboardInterrupt:
			interrupted = True
			last_exit_code = _stop_process(process)

		config.mark_server_stopped(
			server.tag,
			exit_code=last_exit_code,
			preserve_loop=loop and not interrupted,
		)
		config.save()

		if interrupted:
			return 130

		if not loop:
			return last_exit_code

		if console is not None:
			console.print(
				t(
					"manager.loop_restart",
					exit_code=last_exit_code,
					delay=RESTART_DELAY_SECONDS,
				)
			)

		time.sleep(RESTART_DELAY_SECONDS)


def format_timedelta(value: timedelta | None) -> str:
	if value is None:
		return "-"

	total_seconds = int(value.total_seconds())
	hours, remainder = divmod(total_seconds, 3600)
	minutes, seconds = divmod(remainder, 60)
	return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _ensure_registration_target_available(
	config: UserConfig,
	tag: str,
	directory: Path,
) -> None:
	if config.get_server_by_tag(tag) is not None:
		raise ServerManagerError(t("manager.tag_in_use", tag=tag))

	for registered_server in config.get_servers():
		if registered_server.path == directory:
			raise ServerManagerError(
				t(
					"manager.directory_already_registered",
					directory=directory,
					tag=registered_server.tag,
				)
			)


def _resolve_server_jar_path(directory: Path, jar_path: Path) -> Path:
	resolved_jar_path = jar_path.expanduser()
	if not resolved_jar_path.is_absolute():
		resolved_jar_path = (directory / resolved_jar_path).resolve()
	else:
		resolved_jar_path = resolved_jar_path.resolve()

	try:
		resolved_jar_path.relative_to(directory)
	except ValueError as exc:
		raise ServerManagerError(
			t(
				"manager.jar_must_be_inside_directory",
				jar_path=resolved_jar_path,
				directory=directory,
			)
		) from exc

	if not resolved_jar_path.exists():
		raise ServerManagerError(
			t("manager.core_file_missing", jar_path=resolved_jar_path)
		)

	if not resolved_jar_path.is_file():
		raise ServerManagerError(t("manager.path_not_file", path=resolved_jar_path))

	if resolved_jar_path.suffix.lower() != ".jar":
		raise ServerManagerError(
			t("manager.file_not_jar", file_name=resolved_jar_path.name)
		)

	return resolved_jar_path


def _detect_core_id(directory: Path, jar_path: Path) -> str:
	for core in registry.get_all():
		config_file = directory / core.config_file
		if core.config_file != "server.properties" and config_file.exists():
			return core.id

	jar_name = jar_path.name.lower()

	if "powernukkitx" in jar_name or jar_name.startswith("pnx"):
		return "pnx"

	if "nukkit-mot" in jar_name or "mot" in jar_name:
		return "nukkit-mot"

	if "nukkit" in jar_name:
		return "nukkit"

	return "custom"


def _ensure_server_can_modify_core(
	config: UserConfig,
	server: ManagedServer,
) -> ManagedServer:
	sync_runtime_states(config)
	resolved_server = config.get_server_by_tag(server.tag) or server
	runtime_view = get_runtime_view(config, resolved_server)

	if runtime_view.status == "running" or runtime_view.loop_enabled:
		raise ServerManagerError(
			t(
				"manager.server_must_be_stopped_for_core_change",
				tag=resolved_server.tag,
			)
		)

	return resolved_server


def _remove_previous_managed_jar(server: ManagedServer, new_jar_path: Path) -> None:
	previous_jar_path = server.jar_path
	if (
		server.core_version is not None
		and previous_jar_path != new_jar_path
		and previous_jar_path.exists()
	):
		previous_jar_path.unlink()


def _find_server_by_pid(config: UserConfig, pid: int) -> ManagedServer | None:
	for server in config.get_servers():
		if server.runtime.pid == pid:
			return server

	return None


def _get_active_tmux_session_name(server: ManagedServer) -> str | None:
	session_name = build_tmux_session_name(server.tag)
	if tmux_session_exists(session_name):
		return session_name
	return None


def _get_parent_pid(pid: int | None) -> int | None:
	if pid is None:
		return None

	proc_status_path = Path(f"/proc/{pid}/status")
	try:
		if proc_status_path.is_file():
			for line in proc_status_path.read_text(encoding="utf-8").splitlines():
				if line.startswith("PPid:"):
					return int(line.split(":", 1)[1].strip())
	except (OSError, ValueError):
		pass

	try:
		result = subprocess.run(
			["ps", "-o", "ppid=", "-p", str(pid)],
			capture_output=True,
			text=True,
			timeout=3,
			check=False,
		)
	except OSError:
		return None

	if result.returncode != 0:
		return None

	try:
		return int(result.stdout.strip())
	except ValueError:
		return None


def _restore_cached_core(
	core: CoreProvider,
	download_info: CoreDownloadInfo,
	target_directory: Path,
	expected_sha256: str,
	console: Console | None = None,
) -> DownloadedCore | None:
	cache_paths = _get_cached_core_paths(core, download_info)

	if not cache_paths.jar_path.is_file():
		return None

	file_name = _read_cached_file_name(cache_paths.metadata_path)
	if file_name is None:
		return None

	cached_sha256 = _read_cached_sha256(cache_paths.metadata_path)
	if cached_sha256 is None or not hmac.compare_digest(cached_sha256, expected_sha256):
		return None

	if not _file_sha256_matches(cache_paths.jar_path, expected_sha256):
		return None

	target_path = _resolve_download_target_path(target_directory, file_name)

	try:
		_copy_cached_jar(cache_paths.jar_path, target_path)
	except OSError:
		return None

	if console is not None:
		console.print(
			t(
				"manager.using_cached_core",
				core_name=core.name,
				version=download_info.version,
			)
		)

	return DownloadedCore(jar_path=target_path, version=download_info.version)


def _store_core_in_cache(
	core: CoreProvider,
	download_info: CoreDownloadInfo,
	source_path: Path,
	sha256: str,
) -> None:
	cache_paths = _get_cached_core_paths(core, download_info)
	temp_cache_path = _get_temporary_file_path(cache_paths.jar_path)
	temp_metadata_path = _get_temporary_file_path(cache_paths.metadata_path)

	try:
		cache_paths.cache_directory.mkdir(parents=True, exist_ok=True)
		shutil.copy2(source_path, temp_cache_path)
		temp_cache_path.replace(cache_paths.jar_path)
		temp_metadata_path.write_text(
			json.dumps(
				{
					"file_name": source_path.name,
					"sha256": sha256,
					"source_url": download_info.url,
				},
				ensure_ascii=True,
				indent=2,
			),
			encoding="utf-8",
		)
		temp_metadata_path.replace(cache_paths.metadata_path)
	except OSError:
		_cleanup_path(temp_cache_path)
		_cleanup_path(temp_metadata_path)


def _get_cached_core_paths(
	core: CoreProvider,
	download_info: CoreDownloadInfo,
) -> CachedCorePaths:
	version_key = _sanitize_cache_component(download_info.version)
	url_hash = hashlib.sha256(download_info.url.encode("utf-8")).hexdigest()[:12]
	cache_key = f"{version_key}-{url_hash}"
	cache_directory = CORE_CACHE_DIR / core.id

	return CachedCorePaths(
		cache_directory=cache_directory,
		jar_path=cache_directory / f"{cache_key}.jar",
		metadata_path=cache_directory / f"{cache_key}.json",
	)


def _sanitize_cache_component(value: str) -> str:
	sanitized_value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
	return sanitized_value.strip(".-") or "latest"


def _read_cached_file_name(metadata_path: Path) -> str | None:
	payload = _read_cached_metadata(metadata_path)
	if not isinstance(payload, dict):
		return None

	file_name = payload.get("file_name")
	if not isinstance(file_name, str):
		return None

	normalized_file_name = Path(file_name).name
	if normalized_file_name != file_name or not normalized_file_name.endswith(".jar"):
		return None

	return normalized_file_name


def _read_cached_sha256(metadata_path: Path) -> str | None:
	payload = _read_cached_metadata(metadata_path)
	if not isinstance(payload, dict):
		return None

	sha256 = payload.get("sha256")
	if not isinstance(sha256, str):
		return None

	normalized_sha256 = sha256.strip().lower()
	return normalized_sha256 if SHA256_HEX_RE.fullmatch(normalized_sha256) else None


def _read_cached_metadata(metadata_path: Path) -> dict[str, object] | None:
	if not metadata_path.is_file():
		return None

	try:
		payload = json.loads(metadata_path.read_text(encoding="utf-8"))
	except (OSError, json.JSONDecodeError):
		return None

	return payload if isinstance(payload, dict) else None


def _file_sha256_matches(path: Path, expected_sha256: str) -> bool:
	sha256 = hashlib.sha256()
	try:
		with path.open("rb") as file:
			for chunk in iter(lambda: file.read(1024 * 1024), b""):
				sha256.update(chunk)
	except OSError:
		return False

	return hmac.compare_digest(sha256.hexdigest(), expected_sha256)


def _copy_cached_jar(source_path: Path, target_path: Path) -> None:
	target_path.parent.mkdir(parents=True, exist_ok=True)
	temp_target_path = _get_temporary_file_path(target_path)
	_cleanup_path(temp_target_path)
	shutil.copy2(source_path, temp_target_path)
	temp_target_path.replace(target_path)


def _get_temporary_file_path(path: Path) -> Path:
	return path.with_name(f".{path.name}.part")


def _cleanup_path(path: Path) -> None:
	try:
		path.unlink()
	except FileNotFoundError:
		pass
	except OSError:
		pass


def _resolve_download_file_name(
	response: httpx.Response,
	download_url: str,
	core: CoreProvider,
) -> str:
	content_disposition = response.headers.get("content-disposition")
	if content_disposition:
		file_name = _extract_file_name_from_content_disposition(content_disposition)
		if file_name:
			return _require_safe_download_file_name(file_name)

	response_url = str(response.url)
	parsed_url = urlparse(response_url or download_url)
	file_name = Path(unquote(parsed_url.path)).name
	if file_name.endswith(".jar") and _is_safe_download_file_name(file_name):
		return file_name

	return f"{core.id}.jar"


def _extract_file_name_from_content_disposition(header_value: str) -> str | None:
	utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", header_value, flags=re.IGNORECASE)
	if utf8_match:
		return unquote(utf8_match.group(1).strip().strip('"'))

	plain_match = re.search(r'filename="?([^";]+)"?', header_value, flags=re.IGNORECASE)
	if plain_match:
		return plain_match.group(1).strip()

	return None


def _parse_content_length(raw_value: str | None) -> int | None:
	if raw_value is None:
		return None

	try:
		content_length = int(raw_value)
	except ValueError:
		return None

	return content_length if content_length >= 0 else None


def _resolve_download_target_path(target_directory: Path, file_name: str) -> Path:
	root = target_directory.expanduser().resolve()
	target_path = (root / _require_safe_download_file_name(file_name)).resolve()

	try:
		target_path.relative_to(root)
	except ValueError as exc:
		raise ServerManagerError(
			f"Download target escapes the server directory: {target_path}"
		) from exc

	return target_path


def _require_safe_download_file_name(file_name: str) -> str:
	decoded_file_name = unquote(file_name).strip()
	if not _is_safe_download_file_name(decoded_file_name):
		raise ServerManagerError(f"Unsafe download filename: {file_name!r}")
	return decoded_file_name


def _is_safe_download_file_name(file_name: str) -> bool:
	if not file_name or file_name in {".", ".."}:
		return False

	if "/" in file_name or "\\" in file_name:
		return False

	path = Path(file_name)
	if path.is_absolute() or path.name != file_name:
		return False

	return path.suffix.lower() == ".jar"


def _validate_download_size(size: int | None) -> None:
	if size is None:
		return

	if size > MAX_CORE_DOWNLOAD_BYTES:
		max_mib = MAX_CORE_DOWNLOAD_BYTES // (1024 * 1024)
		raise ServerManagerError(f"Core download exceeds the {max_mib} MiB safety limit.")


def _fetch_download_sha256(client: httpx.Client, download_url: str) -> str:
	checksum_url = f"{download_url}.sha256"
	try:
		response = request_with_retries(
			client,
			"GET",
			checksum_url,
			raise_for_status=True,
			retry_on_status=True,
		)
	except httpx.HTTPStatusError as exc:
		raise ServerManagerError(
			f"Missing SHA-256 checksum sidecar for core download: {checksum_url}"
		) from exc
	except httpx.RequestError as exc:
		raise ServerManagerError(
			f"Failed to fetch SHA-256 checksum from {checksum_url}: {format_error(exc)}"
		) from exc

	return _parse_sha256_checksum(response.text, checksum_url)


def _parse_sha256_checksum(payload: str, source: str = "checksum response") -> str:
	match = SHA256_HEX_RE.search(payload)
	if match is None:
		raise ServerManagerError(f"No SHA-256 checksum found in {source}.")
	return match.group(0).lower()


def _is_process_alive(pid: int | None) -> bool:
	if pid is None:
		return False

	try:
		os.kill(pid, 0)
	except ProcessLookupError:
		return False
	except PermissionError:
		return True
	except OSError:
		return False

	return True


def _send_signal(pid: int | None, sig: int) -> None:
	if pid is None:
		raise ServerManagerError(t("manager.pid_undefined"))

	try:
		os.kill(pid, sig)
	except ProcessLookupError as exc:
		raise ServerManagerError(t("manager.process_missing", pid=pid)) from exc
	except PermissionError as exc:
		raise ServerManagerError(
			t("manager.signal_permission_denied", pid=pid)
		) from exc


def _get_uptime(server: ManagedServer) -> timedelta | None:
	if server.runtime.last_started_at is None:
		return None

	return utc_now() - server.runtime.last_started_at


def _stop_process(process: subprocess.Popen[bytes]) -> int:
	if process.poll() is not None:
		return process.returncode or 0

	process.terminate()

	try:
		return process.wait(timeout=10)
	except subprocess.TimeoutExpired:
		process.kill()
		return process.wait()
