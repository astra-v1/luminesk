from pathlib import Path

import pytest

from luminesk.utils.docker import (
	DOCKER_SERVER_DIR,
	build_docker_container_name,
	build_docker_run_command,
	normalize_java_image,
	normalize_memory_limit,
)


class LaunchTarget:
	tag = "My Server!"
	path = Path("/srv/my server")
	jar_name = "server.jar"


def test_build_docker_container_name_sanitizes_tag() -> None:
	assert build_docker_container_name(" My Server! ") == "luminesk-my-server"


def test_normalize_memory_limit() -> None:
	assert normalize_memory_limit(" 512M ") == "512m"
	assert normalize_memory_limit(None) == "1g"

	for value in ("", "0", "-1g", "one-gigabyte", "1gb"):
		with pytest.raises(ValueError):
			normalize_memory_limit(value)


def test_normalize_java_image() -> None:
	assert normalize_java_image(None) == "eclipse-temurin:21-jre"
	assert normalize_java_image("17") == "eclipse-temurin:17-jre"
	assert normalize_java_image("ghcr.io/example/java:21") == "ghcr.io/example/java:21"

	for value in ("", "0", "java 21"):
		with pytest.raises(ValueError):
			normalize_java_image(value)


def test_build_docker_run_command_uses_memory_and_mount(monkeypatch) -> None:
	monkeypatch.setattr("luminesk.utils.docker.platform.system", lambda: "Linux")

	command = build_docker_run_command(
		LaunchTarget(),
		Path("/srv/my server/.luminesk/logs/my-server.log"),
		image="eclipse-temurin:17-jre",
		memory_limit="2g",
		loop=True,
	)

	assert command[:2] == ("docker", "run")
	assert "--memory" in command
	assert command[command.index("--memory") + 1] == "2g"
	assert "--network" in command
	assert command[command.index("--network") + 1] == "host"
	assert "--volume" in command
	mount_source = str(LaunchTarget.path.expanduser().resolve()).replace("\\", "/")
	assert command[command.index("--volume") + 1] == f"{mount_source}:{DOCKER_SERVER_DIR}"
	assert "LUMINESK_LOOP=1" in command
	assert "eclipse-temurin:17-jre" in command


def test_build_docker_run_command_publishes_default_ports_off_linux(monkeypatch) -> None:
	monkeypatch.setattr("luminesk.utils.docker.platform.system", lambda: "Windows")

	command = build_docker_run_command(
		LaunchTarget(),
		Path("/srv/my server/.luminesk/logs/my-server.log"),
		memory_limit="2g",
	)

	assert "--network" not in command
	assert "19132:19132/udp" in command
	assert "19132:19132/tcp" in command
