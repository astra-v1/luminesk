import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from luminesk.core import config


def test_managed_server_normalizes_tag(tmp_path: Path) -> None:
	server = config.ManagedServer(
		name="Test",
		tag=" MyTag ",
		path=tmp_path,
		core_id="nukkit",
		jar_name="server.jar",
	)
	assert server.tag == "mytag"


def test_managed_server_rejects_empty_name(tmp_path: Path) -> None:
	with pytest.raises(ValidationError):
		config.ManagedServer(
			name=" ",
			tag="ok",
			path=tmp_path,
			core_id="nukkit",
			jar_name="server.jar",
		)


def test_managed_server_normalizes_memory_limit(tmp_path: Path) -> None:
	server = config.ManagedServer(
		name="Test",
		tag="test",
		path=tmp_path,
		core_id="nukkit",
		jar_name="server.jar",
		memory_limit=" 2G ",
	)
	assert server.memory_limit == "2g"


def test_managed_server_normalizes_java_image(tmp_path: Path) -> None:
	server = config.ManagedServer(
		name="Test",
		tag="test",
		path=tmp_path,
		core_id="nukkit",
		jar_name="server.jar",
		java_image="17",
	)
	assert server.java_image == "eclipse-temurin:17-jre"


def test_get_server_by_directory_prefers_deepest_match(tmp_path: Path) -> None:
	root = tmp_path / "servers"
	server_a_path = root / "alpha"
	server_b_path = root / "alpha" / "beta"

	server_a = config.ManagedServer(
		name="Alpha",
		tag="alpha",
		path=server_a_path,
		core_id="nukkit",
		jar_name="server.jar",
	)
	server_b = config.ManagedServer(
		name="Beta",
		tag="beta",
		path=server_b_path,
		core_id="nukkit",
		jar_name="server.jar",
	)

	user_config = config.UserConfig(servers={server_a.tag: server_a, server_b.tag: server_b})
	match = user_config.get_server_by_directory(server_b_path / "world")
	assert match == server_b


def test_unregister_server_removes_only_registration(tmp_path: Path) -> None:
	server_dir = tmp_path / "server"
	server_dir.mkdir()
	server_file = server_dir / "server.jar"
	server_file.write_text("jar", encoding="utf-8")
	server = config.ManagedServer(
		name="Test",
		tag="Test",
		path=server_dir,
		core_id="nukkit",
		jar_name="server.jar",
	)
	user_config = config.UserConfig(servers={server.tag: server})

	deleted = user_config.unregister_server("test")

	assert deleted == server
	assert user_config.get_server_by_tag("test") is None
	assert server_file.is_file()


def test_migrate_legacy_config_creates_servers(tmp_path: Path) -> None:
	legacy_dir = tmp_path / "legacy"
	legacy_dir.mkdir()
	jar = legacy_dir / "core.jar"
	jar.write_text("test", encoding="utf-8")

	data = {"server_tags": {"Legacy": str(legacy_dir)}}
	migrated = config._migrate_legacy_config(data)

	assert "server_tags" not in migrated
	assert "servers" in migrated
	servers = migrated["servers"]
	assert "legacy" in servers
	assert servers["legacy"]["jar_name"] == "core.jar"


def test_save_writes_sqlite_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	config_dir = tmp_path / "config"
	config_db_file = config_dir / "state.sqlite3"
	monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
	monkeypatch.setattr(config, "CONFIG_DB_FILE", config_db_file)

	server = config.ManagedServer(
		name="Test",
		tag="test",
		path=tmp_path / "server",
		core_id="nukkit",
		jar_name="server.jar",
		java_image="17",
	)
	user_config = config.UserConfig(servers={server.tag: server}, db_path=config_db_file)
	user_config.save()

	assert config_db_file.is_file()
	loaded_config = config.UserConfig.load()
	assert loaded_config.language == config.DEFAULT_LANGUAGE
	assert loaded_config.get_server_by_tag("test").java_image == "eclipse-temurin:17-jre"


def test_initialize_database_adds_java_image_to_existing_servers(tmp_path: Path) -> None:
	db_path = tmp_path / "state.sqlite3"
	conn = sqlite3.connect(db_path)
	conn.row_factory = sqlite3.Row
	try:
		conn.execute(
			"""
			CREATE TABLE servers (
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
		conn.execute(
			"""
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
			VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			""",
			(
				"legacy",
				"Legacy",
				str(tmp_path / "legacy"),
				"nukkit",
				None,
				"server.jar",
				"1g",
				config.utc_now().isoformat(),
				"stopped",
				None,
				0,
				None,
				None,
				None,
				None,
				None,
				None,
			),
		)

		config._initialize_database(conn)
		loaded_config = config._load_config_from_database(conn)
	finally:
		conn.close()

	legacy_server = loaded_config.get_server_by_tag("legacy")
	assert legacy_server is not None
	assert legacy_server.java_image == "eclipse-temurin:21-jre"
