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


def test_save_writes_config_atomically(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
	config_dir = tmp_path / "config"
	config_file = config_dir / "config.json"
	monkeypatch.setattr(config, "CONFIG_DIR", config_dir)
	monkeypatch.setattr(config, "CONFIG_FILE", config_file)

	user_config = config.UserConfig()
	user_config.save()

	assert config_file.is_file()
	assert not list(config_dir.glob("*.tmp"))
	assert config.UserConfig.load().language == config.DEFAULT_LANGUAGE
