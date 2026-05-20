from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from luminesk.core import manager
from luminesk.core.config import ManagedServer, UserConfig
from luminesk.core.manager import (
	MAX_CORE_DOWNLOAD_BYTES,
	ServerManagerError,
	_extract_file_name_from_content_disposition,
	_parse_content_length,
	_parse_sha256_checksum,
	_read_cached_file_name,
	_require_safe_download_file_name,
	_resolve_download_file_name,
	_resolve_download_target_path,
	_sanitize_cache_component,
	_validate_download_size,
	format_timedelta,
)
from luminesk.core.registry import CoreProvider


def test_format_timedelta() -> None:
	assert format_timedelta(None) == "-"
	assert format_timedelta(timedelta(hours=1, minutes=2, seconds=3)) == "01:02:03"


def test_sanitize_cache_component() -> None:
	assert _sanitize_cache_component("  ..v1.0/rc1.. ") == "v1.0-rc1"
	assert _sanitize_cache_component("   ") == "latest"


def test_read_cached_file_name(tmp_path: Path) -> None:
	metadata_path = tmp_path / "meta.json"
	metadata_path.write_text('{"file_name": "core.jar"}', encoding="utf-8")
	assert _read_cached_file_name(metadata_path) == "core.jar"

	metadata_path.write_text('{"file_name": "dir/core.jar"}', encoding="utf-8")
	assert _read_cached_file_name(metadata_path) is None

	metadata_path.write_text('{"file_name": "core.zip"}', encoding="utf-8")
	assert _read_cached_file_name(metadata_path) is None


def test_extract_file_name_from_content_disposition() -> None:
	assert (
		_extract_file_name_from_content_disposition('attachment; filename="core.jar"')
		== "core.jar"
	)
	assert (
		_extract_file_name_from_content_disposition("attachment; filename*=UTF-8''Lumi%20Core.jar")
		== "Lumi Core.jar"
	)


def test_resolve_download_file_name_rejects_unsafe_content_disposition() -> None:
	response = httpx.Response(
		200,
		headers={"content-disposition": 'attachment; filename="../../outside.jar"'},
		request=httpx.Request("GET", "https://example.com/core.jar"),
	)

	with pytest.raises(ServerManagerError):
		_resolve_download_file_name(response, "https://example.com/core.jar", _dummy_core())


def test_require_safe_download_file_name() -> None:
	assert _require_safe_download_file_name("core.jar") == "core.jar"
	for file_name in ("../core.jar", r"..\core.jar", "/tmp/core.jar", "core.zip", ""):
		with pytest.raises(ServerManagerError):
			_require_safe_download_file_name(file_name)


def test_resolve_download_target_path_stays_in_directory(tmp_path: Path) -> None:
	assert _resolve_download_target_path(tmp_path, "core.jar") == (tmp_path / "core.jar").resolve()
	with pytest.raises(ServerManagerError):
		_resolve_download_target_path(tmp_path, "../outside.jar")


def test_parse_content_length() -> None:
	assert _parse_content_length(None) is None
	assert _parse_content_length("123") == 123
	assert _parse_content_length("nope") is None
	assert _parse_content_length("-1") is None


def test_validate_download_size() -> None:
	_validate_download_size(MAX_CORE_DOWNLOAD_BYTES)
	with pytest.raises(ServerManagerError):
		_validate_download_size(MAX_CORE_DOWNLOAD_BYTES + 1)


def test_parse_sha256_checksum() -> None:
	digest = "a" * 64
	assert _parse_sha256_checksum(f"{digest}  core.jar") == digest
	with pytest.raises(ServerManagerError):
		_parse_sha256_checksum("not a checksum")


def test_stop_server_stops_docker_container(monkeypatch, tmp_path: Path) -> None:
	config = _running_docker_config(tmp_path)
	calls: list[str] = []

	monkeypatch.setattr(manager.UserConfig, "save", lambda self: None)
	monkeypatch.setattr(manager, "docker_container_is_running", lambda _: True)
	monkeypatch.setattr(manager, "get_docker_container_pid", lambda _: 1234)
	monkeypatch.setattr(manager, "get_docker_container_exit_code", lambda _: 0)
	monkeypatch.setattr(manager, "remove_docker_container", lambda _: calls.append("rm"))
	monkeypatch.setattr(manager, "stop_docker_container", lambda name: calls.append(f"stop:{name}"))

	result = manager.stop_server(config=config, target="test", force=True)

	assert result.signal_name == "SIGTERM"
	assert calls == ["stop:luminesk-test", "rm"]
	assert config.get_server_by_tag("test").runtime.status == "stopped"


def test_kill_server_uses_cross_platform_docker_kill(monkeypatch, tmp_path: Path) -> None:
	config = _running_docker_config(tmp_path)
	calls: list[str] = []

	monkeypatch.setattr(manager.UserConfig, "save", lambda self: None)
	monkeypatch.setattr(manager, "docker_container_is_running", lambda _: True)
	monkeypatch.setattr(manager, "get_docker_container_pid", lambda _: 1234)
	monkeypatch.setattr(manager, "get_docker_container_exit_code", lambda _: 137)
	monkeypatch.setattr(manager, "remove_docker_container", lambda _: calls.append("rm"))
	monkeypatch.setattr(manager, "kill_docker_container", lambda name: calls.append(f"kill:{name}"))

	result = manager.kill_server(config=config, target="test", force=True)

	assert result.signal_name == "SIGKILL"
	assert calls == ["kill:luminesk-test", "rm"]
	assert config.get_server_by_tag("test").runtime.last_exit_code == 137


def _running_docker_config(tmp_path: Path) -> UserConfig:
	server = ManagedServer(
		name="Test",
		tag="test",
		path=tmp_path,
		core_id="nukkit",
		jar_name="server.jar",
	)
	config = UserConfig(servers={server.tag: server})
	config.mark_server_started(
		server.tag,
		pid=1234,
		docker_container_id="container-id",
		docker_container_name="luminesk-test",
		docker_memory_limit="1g",
	)
	return config


def _dummy_core() -> CoreProvider:
	return CoreProvider(
		id="dummy",
		name="Dummy",
		description="Dummy",
		url="https://example.com",
	)
