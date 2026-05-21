from __future__ import annotations

import json
import sqlite3
import time

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal

from platformdirs import user_cache_dir, user_config_dir
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from luminesk.core.messages import DEFAULT_LANGUAGE, normalize_language, t
from luminesk.utils.docker import DEFAULT_DOCKER_MEMORY_LIMIT, normalize_memory_limit


CONFIG_DIR = Path(user_config_dir("luminesk"))
CONFIG_DB_FILE = CONFIG_DIR / "state.sqlite3"
LEGACY_CONFIG_FILE = CONFIG_DIR / "config.json"
CACHE_DIR = Path(user_cache_dir("luminesk"))
CORE_CACHE_DIR = CACHE_DIR / "cores"

SQLITE_BUSY_TIMEOUT_MS = 30_000
SQLITE_LOCK_RETRY_ATTEMPTS = 8
SQLITE_LOCK_RETRY_DELAY_SECONDS = 0.05

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
	model_config = ConfigDict(arbitrary_types_allowed=True)

	language: str = DEFAULT_LANGUAGE
	default_server_path: Path = Path("./servers")
	servers: dict[str, ManagedServer] = Field(default_factory=dict)
	db_path: Path = Field(default_factory=lambda: CONFIG_DB_FILE, exclude=True)

	_loaded_tags: set[str] = PrivateAttr(default_factory=set)
	_deleted_tags: set[str] = PrivateAttr(default_factory=set)

	def model_post_init(self, _context: object) -> None:
		self._loaded_tags = set(self.servers)

	@field_validator("language", mode="before")
	@classmethod
	def normalize_language_value(cls, value: str | None) -> str:
		return normalize_language(value)

	@field_validator("default_server_path", mode="before")
	@classmethod
	def normalize_default_server_path(cls, value: Path | str) -> Path:
		return Path(value).expanduser()

	def save(self) -> None:
		conn = _connect(self.db_path)
		try:
			_initialize_database(conn)
			with _write_transaction(conn):
				_save_settings(conn, self)
				for tag in self._deleted_tags:
					conn.execute("DELETE FROM servers WHERE tag = ?", (tag,))

				for server in self.servers.values():
					if server.tag in self._loaded_tags:
						_upsert_server(conn, server)
					else:
						_insert_server(conn, server)

			self._loaded_tags = set(self.servers)
			self._deleted_tags.clear()
		finally:
			conn.close()

	def register_server(self, server: ManagedServer) -> None:
		self.servers[server.tag] = server
		self._deleted_tags.discard(server.tag)

	def unregister_server(self, tag: str) -> ManagedServer:
		server = self.get_server_by_tag(tag)
		if server is None:
			raise KeyError(t("config.server.not_found", tag=tag))
		deleted_server = self.servers.pop(server.tag)
		self._deleted_tags.add(server.tag)
		return deleted_server

	def get_server_by_tag(self, tag: str) -> ManagedServer | None:
		return self.servers.get(tag.strip().lower())

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
		if not CONFIG_DB_FILE.exists() and LEGACY_CONFIG_FILE.exists():
			legacy_config = _load_legacy_json_config(LEGACY_CONFIG_FILE)
			if legacy_config is not None:
				legacy_config.save()
				return legacy_config

		conn = _connect(CONFIG_DB_FILE)
		try:
			_initialize_database(conn)
			return _load_config_from_database(conn)
		finally:
			conn.close()


def _connect(db_path: Path) -> sqlite3.Connection:
	db_path.parent.mkdir(parents=True, exist_ok=True)
	conn = sqlite3.connect(
		db_path,
		timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
		isolation_level=None,
	)
	conn.row_factory = sqlite3.Row
	conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
	conn.execute("PRAGMA foreign_keys = ON")
	conn.execute("PRAGMA journal_mode = WAL")
	return conn


def _initialize_database(conn: sqlite3.Connection) -> None:
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS settings (
			key TEXT PRIMARY KEY,
			value TEXT NOT NULL
		)
		"""
	)
	conn.execute(
		"""
		CREATE TABLE IF NOT EXISTS servers (
			tag TEXT PRIMARY KEY,
			name TEXT NOT NULL,
			path TEXT NOT NULL,
			core_id TEXT NOT NULL,
			core_version TEXT,
			jar_name TEXT NOT NULL,
			memory_limit TEXT NOT NULL,
			created_at TEXT NOT NULL,
			status TEXT NOT NULL,
			pid INTEGER,
			loop_enabled INTEGER NOT NULL,
			docker_container_id TEXT,
			docker_container_name TEXT,
			docker_memory_limit TEXT,
			last_started_at TEXT,
			last_stopped_at TEXT,
			last_exit_code INTEGER
		)
		"""
	)
	conn.execute("CREATE INDEX IF NOT EXISTS idx_servers_path ON servers(path)")


@contextmanager
def _write_transaction(conn: sqlite3.Connection) -> Iterator[None]:
	for attempt in range(SQLITE_LOCK_RETRY_ATTEMPTS):
		try:
			conn.execute("BEGIN IMMEDIATE")
			break
		except sqlite3.OperationalError as exc:
			if not _is_sqlite_lock_error(exc) or attempt == SQLITE_LOCK_RETRY_ATTEMPTS - 1:
				raise
			time.sleep(SQLITE_LOCK_RETRY_DELAY_SECONDS * (attempt + 1))
	else:
		raise RuntimeError(t("config.sqlite.lock_timeout"))

	try:
		yield
	except Exception:
		conn.rollback()
		raise
	else:
		conn.commit()


def _is_sqlite_lock_error(error: sqlite3.OperationalError) -> bool:
	message = str(error).lower()
	return "locked" in message or "busy" in message


def _load_config_from_database(conn: sqlite3.Connection) -> UserConfig:
	settings = {
		row["key"]: row["value"]
		for row in conn.execute("SELECT key, value FROM settings")
	}
	servers = {
		server.tag: server
		for server in (
			_server_from_row(row)
			for row in conn.execute("SELECT * FROM servers ORDER BY tag")
		)
	}
	return UserConfig(
		language=settings.get("language", DEFAULT_LANGUAGE),
		default_server_path=settings.get("default_server_path", "./servers"),
		servers=servers,
		db_path=CONFIG_DB_FILE,
	)


def _save_settings(conn: sqlite3.Connection, config: UserConfig) -> None:
	conn.executemany(
		"""
		INSERT INTO settings(key, value)
		VALUES(?, ?)
		ON CONFLICT(key) DO UPDATE SET value = excluded.value
		""",
		[
			("language", config.language),
			("default_server_path", str(config.default_server_path)),
		],
	)


def _insert_server(conn: sqlite3.Connection, server: ManagedServer) -> None:
	try:
		conn.execute(_insert_server_sql(), _server_to_row(server))
	except sqlite3.IntegrityError as exc:
		raise RuntimeError(t("config.sqlite.server_conflict", tag=server.tag)) from exc


def _upsert_server(conn: sqlite3.Connection, server: ManagedServer) -> None:
	conn.execute(
		f"""
		{_insert_server_sql()}
		ON CONFLICT(tag) DO UPDATE SET
			name = excluded.name,
			path = excluded.path,
			core_id = excluded.core_id,
			core_version = excluded.core_version,
			jar_name = excluded.jar_name,
			memory_limit = excluded.memory_limit,
			created_at = excluded.created_at,
			status = excluded.status,
			pid = excluded.pid,
			loop_enabled = excluded.loop_enabled,
			docker_container_id = excluded.docker_container_id,
			docker_container_name = excluded.docker_container_name,
			docker_memory_limit = excluded.docker_memory_limit,
			last_started_at = excluded.last_started_at,
			last_stopped_at = excluded.last_stopped_at,
			last_exit_code = excluded.last_exit_code
		""",
		_server_to_row(server),
	)


def _insert_server_sql() -> str:
	return """
		INSERT INTO servers(
			tag,
			name,
			path,
			core_id,
			core_version,
			jar_name,
			memory_limit,
			created_at,
			status,
			pid,
			loop_enabled,
			docker_container_id,
			docker_container_name,
			docker_memory_limit,
			last_started_at,
			last_stopped_at,
			last_exit_code
		)
		VALUES(
			:tag,
			:name,
			:path,
			:core_id,
			:core_version,
			:jar_name,
			:memory_limit,
			:created_at,
			:status,
			:pid,
			:loop_enabled,
			:docker_container_id,
			:docker_container_name,
			:docker_memory_limit,
			:last_started_at,
			:last_stopped_at,
			:last_exit_code
		)
	"""


def _server_to_row(server: ManagedServer) -> dict[str, object]:
	payload = server.model_dump(mode="json")
	runtime = payload["runtime"]
	return {
		"tag": payload["tag"],
		"name": payload["name"],
		"path": payload["path"],
		"core_id": payload["core_id"],
		"core_version": payload["core_version"],
		"jar_name": payload["jar_name"],
		"memory_limit": payload["memory_limit"],
		"created_at": payload["created_at"],
		"status": runtime["status"],
		"pid": runtime["pid"],
		"loop_enabled": int(runtime["loop_enabled"]),
		"docker_container_id": runtime["docker_container_id"],
		"docker_container_name": runtime["docker_container_name"],
		"docker_memory_limit": runtime["docker_memory_limit"],
		"last_started_at": runtime["last_started_at"],
		"last_stopped_at": runtime["last_stopped_at"],
		"last_exit_code": runtime["last_exit_code"],
	}


def _server_from_row(row: sqlite3.Row) -> ManagedServer:
	return ManagedServer.model_validate(
		{
			"name": row["name"],
			"tag": row["tag"],
			"path": row["path"],
			"core_id": row["core_id"],
			"core_version": row["core_version"],
			"jar_name": row["jar_name"],
			"memory_limit": row["memory_limit"],
			"created_at": row["created_at"],
			"runtime": {
				"status": row["status"],
				"pid": row["pid"],
				"loop_enabled": bool(row["loop_enabled"]),
				"docker_container_id": row["docker_container_id"],
				"docker_container_name": row["docker_container_name"],
				"docker_memory_limit": row["docker_memory_limit"],
				"last_started_at": row["last_started_at"],
				"last_stopped_at": row["last_stopped_at"],
				"last_exit_code": row["last_exit_code"],
			},
		}
	)


def _load_legacy_json_config(path: Path) -> UserConfig | None:
	try:
		with path.open("r", encoding="utf-8") as file:
			data = json.load(file)
	except (OSError, json.JSONDecodeError):
		return None

	if not isinstance(data, dict):
		return None

	migrated_data = _migrate_legacy_config(data)
	return UserConfig.model_validate(migrated_data)


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
