from __future__ import annotations

import subprocess

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from luminesk.core.config import UserConfig
from luminesk.core.messages import t
from luminesk.utils.docker import (
	DEFAULT_DOCKER_IMAGE,
	build_docker_container_name,
	build_docker_logs_command,
	build_docker_run_command,
	docker_container_is_running,
	get_docker_container_exit_code,
	get_docker_binary,
	get_docker_container_pid,
	normalize_memory_limit,
	remove_docker_container,
)


class ServerLaunchTarget(Protocol):
	tag: str
	path: Path
	jar_name: str
	memory_limit: str


@dataclass(slots=True, frozen=True)
class DetachedLaunchResult:
	container_id: str
	container_name: str
	command: tuple[str, ...]
	attach_command: tuple[str, ...]
	log_path: Path
	memory_limit: str


def build_log_path(server: ServerLaunchTarget, now: datetime | None = None) -> Path:
	timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
	return server.path / ".luminesk" / "logs" / f"{server.tag}-{timestamp}.log"


def launch_server_detached(
	server: ServerLaunchTarget,
	loop: bool = False,
	*,
	memory_limit: str | None = None,
	image: str = DEFAULT_DOCKER_IMAGE,
	config: UserConfig | None = None,
) -> DetachedLaunchResult:
	docker_bin = get_docker_binary()
	ensure_docker_image(image, docker_bin=docker_bin)
	normalized_memory_limit = normalize_memory_limit(memory_limit or server.memory_limit)
	log_path = build_log_path(server)
	log_path.parent.mkdir(parents=True, exist_ok=True)

	container_name = build_docker_container_name(server.tag)
	if docker_container_is_running(container_name):
		raise RuntimeError(t("launcher.docker_container_exists", container_name=container_name))
	remove_docker_container(container_name)

	command = build_docker_run_command(
		server,
		log_path,
		container_name=container_name,
		image=image,
		loop=loop,
		memory_limit=normalized_memory_limit,
	)
	attach_command = build_docker_logs_command(container_name)

	with log_path.open("a", encoding="utf-8") as log_file:
		log_file.write(
			f"[{datetime.now().astimezone().isoformat()}] Launching Docker container {container_name}: "
			f"{' '.join(command)}\n"
		)
		result = subprocess.run(
			[docker_bin, *command[1:]],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			encoding="utf-8",
			errors="replace",
		)
		if result.stderr:
			log_file.write(result.stderr)
		if result.returncode != 0:
			error = result.stderr.strip() or f"exit code {result.returncode}"
			raise RuntimeError(
				t(
					"launcher.docker_run_failed",
					exit_code=result.returncode,
					error=error,
				)
			)

	container_id = result.stdout.strip()
	pid = get_docker_container_pid(container_name)
	loaded_config = config or UserConfig.load()
	registered_server = loaded_config.get_server_by_tag(server.tag)
	if registered_server is not None:
		registered_server.memory_limit = normalized_memory_limit
	loaded_config.mark_server_started(
		server.tag,
		pid=pid,
		loop_enabled=loop,
		docker_container_id=container_id,
		docker_container_name=container_name,
		docker_memory_limit=normalized_memory_limit,
	)
	loaded_config.save()

	return DetachedLaunchResult(
		container_id=container_id,
		container_name=container_name,
		command=command,
		attach_command=attach_command,
		log_path=log_path,
		memory_limit=normalized_memory_limit,
	)


def follow_container_logs(
	container_name: str,
	*,
	config: UserConfig,
	server_tag: str,
) -> int:
	docker_bin = get_docker_binary()
	process = subprocess.Popen([docker_bin, "logs", "--follow", container_name])

	try:
		logs_exit_code = process.wait()
	except KeyboardInterrupt:
		process.terminate()
		try:
			process.wait(timeout=3)
		except subprocess.TimeoutExpired:
			process.kill()
		return 130

	if docker_container_is_running(container_name):
		return logs_exit_code

	exit_code = get_docker_container_exit_code(container_name)
	remove_docker_container(container_name)
	config.mark_server_stopped(server_tag, exit_code=exit_code)
	config.save()
	return exit_code if exit_code is not None else logs_exit_code


def ensure_docker_image(image: str, *, docker_bin: str | None = None) -> None:
	resolved_docker_bin = docker_bin or get_docker_binary()
	inspect_result = subprocess.run(
		[resolved_docker_bin, "image", "inspect", image],
		check=False,
		stdout=subprocess.DEVNULL,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
	)
	if inspect_result.returncode == 0:
		return

	pull_result = subprocess.run(
		[resolved_docker_bin, "pull", image],
		check=False,
		stdout=subprocess.PIPE,
		stderr=subprocess.PIPE,
		text=True,
		encoding="utf-8",
		errors="replace",
	)
	if pull_result.returncode != 0:
		error = pull_result.stderr.strip() or pull_result.stdout.strip()
		raise RuntimeError(t("launcher.docker_pull_failed", image=image, error=error))
