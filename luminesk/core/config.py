from __future__ import annotations

import json
import os
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_dir, user_config_dir
from pydantic import BaseModel, Field, field_validator

from luminesk.core.messages import DEFAULT_LANGUAGE, normalize_language, t
from luminesk.utils.docker import DEFAULT_DOCKER_MEMORY_LIMIT, normalize_memory_limit


CONFIG_DIR = Path(user_config_dir("luminesk"))
CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = Path(user_cache_dir("luminesk"))
CORE_CACHE_DIR = CACHE_DIR / "cores"

ServerStatus = Literal["running", "stopped"]


def utc_now() -> datetime:
	return datetime.now(timezone.utc)


class ServerRuntime(BaseModel):
	status: ServerStatus = "stopped"
	pid: int | None = None
	loop_enabled: bool = False
	docker_container_id: str | None = None
	docker_container_name: str | None = None
	docker_memory_limit: str | None = None
	last_started_at: datetime | None = None
	last_stopped_at: datetime | None = None
	last_exit_code: int | None = None


class ManagedServer(BaseModel):
	name: str
	tag: str
	path: Path
	core_id: str
	core_version: str | None = None
	jar_name: str
	memory_limit: str = DEFAULT_DOCKER_MEMORY_LIMIT
	created_at: datetime = Field(default_factory=utc_now)
	runtime: ServerRuntime = Field(default_factory=ServerRuntime)

	@field_validator("tag")
	@classmethod
	def normalize_tag(cls, value: str) -> str:
		normalized_tag = value.strip().lower()
		if not normalized_tag:
			raise ValueError(t("config.validation.tag_empty"))
		return normalized_tag

	@field_validator("name", "core_id", "jar_name")
	@classmethod
	def validate_non_empty_text(cls, value: str) -> str:
		normalized_value = value.strip()
		if not normalized_value:
			raise ValueError(t("config.validation.text_empty"))
		return normalized_value

	@field_validator("path", mode="before")
	@classmethod
	def normalize_path(cls, value: Path | str) -> Path:
		return Path(value).expanduser().resolve()

	@field_validator("memory_limit", mode="before")
	@classmethod
	def normalize_server_memory_limit(cls, value: str | None) -> str:
		return normalize_memory_limit(value)

	@property
	def jar_path(self) -> Path:
		return self.path / self.jar_name


class UserConfig(BaseModel):
	language: str = DEFAULT_LANGUAGE
	default_server_path: Path = Path("./servers")
	auto_update: bool = True
	servers: dict[str, ManagedServer] = Field(default_factory=dict)

	@field_validator("language", mode="before")
	@classmethod
	def normalize_language_value(cls, value: str | None) -> str:
		return normalize_language(value)

	@field_validator("default_server_path", mode="before")
	@classmethod
	def normalize_default_server_path(cls, value: Path | str) -> Path:
		return Path(value).expanduser()

	def save(self) -> None:
		CONFIG_DIR.mkdir(parents=True, exist_ok=True)
		temp_path: Path | None = None
		try:
			with tempfile.NamedTemporaryFile(
				"w",
				encoding="utf-8",
				dir=CONFIG_DIR,
				prefix=f".{CONFIG_FILE.name}.",
				suffix=".tmp",
				delete=False,
			) as file:
				temp_path = Path(file.name)
				try:
					os.chmod(temp_path, 0o600)
				except OSError:
					pass
				file.write(self.model_dump_json(indent=4))
				file.flush()
				os.fsync(file.fileno())
			os.replace(temp_path, CONFIG_FILE)
			try:
				CONFIG_FILE.chmod(0o600)
			except OSError:
				pass
		finally:
			if temp_path is not None and temp_path.exists():
				try:
					temp_path.unlink()
				except OSError:
					pass

	def register_server(self, server: ManagedServer) -> None:
		self.servers[server.tag] = server

	def unregister_server(self, tag: str) -> ManagedServer:
		server = self.get_server_by_tag(tag)
		if server is None:
			raise KeyError(t("config.server.not_found", tag=tag))
		return self.servers.pop(server.tag)

	def get_server_by_tag(self, tag: str) -> ManagedServer | None:
		return self.servers.get(tag.strip().lower())

	def get_server_path_by_tag(self, tag: str) -> Path | None:
		server = self.get_server_by_tag(tag)
		return server.path if server else None

	def get_server_by_directory(self, directory: Path) -> ManagedServer | None:
		resolved_directory = directory.expanduser().resolve()
		best_match: ManagedServer | None = None

		for server in self.servers.values():
			try:
				if resolved_directory.is_relative_to(server.path):
					if best_match is None or len(server.path.parts) > len(best_match.path.parts):
						best_match = server
			except ValueError:
				continue

		return best_match

	def get_servers(self) -> list[ManagedServer]:
		return sorted(self.servers.values(), key=lambda server: server.tag)

	def mark_server_started(
		self,
		tag: str,
		pid: int | None,
		loop_enabled: bool = False,
		docker_container_id: str | None = None,
		docker_container_name: str | None = None,
		docker_memory_limit: str | None = None,
		started_at: datetime | None = None,
	) -> ManagedServer:
		server = self._require_server(tag)
		server.runtime.status = "running"
		server.runtime.pid = pid
		server.runtime.loop_enabled = loop_enabled
		server.runtime.docker_container_id = docker_container_id
		server.runtime.docker_container_name = docker_container_name
		server.runtime.docker_memory_limit = docker_memory_limit
		server.runtime.last_started_at = started_at or utc_now()
		server.runtime.last_exit_code = None
		return server

	def mark_server_stopped(
		self,
		tag: str,
		exit_code: int | None,
		preserve_loop: bool = False,
		stopped_at: datetime | None = None,
	) -> ManagedServer:
		server = self._require_server(tag)
		server.runtime.status = "stopped"
		server.runtime.pid = None
		if not preserve_loop:
			server.runtime.loop_enabled = False
		server.runtime.docker_container_id = None
		server.runtime.docker_container_name = None
		server.runtime.docker_memory_limit = None
		server.runtime.last_stopped_at = stopped_at or utc_now()
		server.runtime.last_exit_code = exit_code
		return server

	def _require_server(self, tag: str) -> ManagedServer:
		server = self.get_server_by_tag(tag)
		if server is None:
			raise KeyError(t("config.server.not_found", tag=tag))
		return server

	@classmethod
	def load(cls) -> "UserConfig":
		if not CONFIG_FILE.exists():
			new_config = cls()
			new_config.save()
			return new_config

		with CONFIG_FILE.open("r", encoding="utf-8") as file:
			data = json.load(file)

		migrated_data = _migrate_legacy_config(data)
		return cls.model_validate(migrated_data)


def _migrate_legacy_config(data: dict[str, object]) -> dict[str, object]:
	if "servers" in data or "server_tags" not in data:
		return data

	legacy_tags = data.get("server_tags")
	if not isinstance(legacy_tags, dict):
		return data

	servers: dict[str, object] = {}

	for raw_tag, raw_path in legacy_tags.items():
		if not isinstance(raw_tag, str) or not isinstance(raw_path, str):
			continue

		path = Path(raw_path).expanduser().resolve()
		jar_name = _guess_jar_name(path)
		server = ManagedServer(
			name=path.name or raw_tag,
			tag=raw_tag,
			path=path,
			core_id="unknown",
			jar_name=jar_name,
		)
		servers[server.tag] = server.model_dump(mode="json")

	migrated_data = dict(data)
	migrated_data.pop("server_tags", None)
	migrated_data["servers"] = servers
	return migrated_data


def _guess_jar_name(directory: Path) -> str:
	if directory.is_dir():
		jar_files = sorted(path.name for path in directory.glob("*.jar"))
		if jar_files:
			return jar_files[0]

	return "server.jar"
