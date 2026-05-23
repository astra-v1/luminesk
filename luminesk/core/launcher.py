from __future__ import annotations

import subprocess
import sys
import threading

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from luminesk.core.config import UserConfig
from luminesk.core.messages import t
from rich.console import Console

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
	send_docker_command,
)
from luminesk.utils.rich_utils import accent, ansi_text


class ServerLaunchTarget(Protocol):
	tag: str
	path: Path
	jar_name: str
	memory_limit: str
	java_image: str


@dataclass(slots=True, frozen=True)
class DetachedLaunchResult:
	container_id: str
	container_name: str
	command: tuple[str, ...]
	attach_command: tuple[str, ...]
	log_path: Path
	memory_limit: str
	java_image: str


def build_log_path(server: ServerLaunchTarget, now: datetime | None = None) -> Path:
	timestamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
	return server.path / ".luminesk" / "logs" / f"{server.tag}-{timestamp}.log"


def launch_server_detached(
	server: ServerLaunchTarget,
	loop: bool = False,
	*,
	memory_limit: str | None = None,
	image: str | None = None,
	config: UserConfig | None = None,
	console: Console | None = None,
) -> DetachedLaunchResult:
	docker_bin = get_docker_binary()
	resolved_image = image or getattr(server, "java_image", DEFAULT_DOCKER_IMAGE)
	ensure_docker_image(resolved_image, docker_bin=docker_bin, console=console)
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
		image=resolved_image,
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
		java_image=resolved_image,
	)


def follow_container_logs(
	container_name: str,
	*,
	config: UserConfig,
	server_tag: str,
) -> int:
	docker_bin = get_docker_binary()
	process = subprocess.Popen(
		[docker_bin, "logs", "--follow", container_name],
		stdin=subprocess.DEVNULL,
	)
	_start_console_forwarder(container_name)

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


def _start_console_forwarder(container_name: str) -> threading.Thread | None:
	if not sys.stdin.isatty():
		return None

	def _forward() -> None:
		for line in sys.stdin:
			command = line.rstrip("\n")
			try:
				send_docker_command(container_name, command)
			except RuntimeError:
				if not docker_container_is_running(container_name):
					break
				continue

	thread = threading.Thread(target=_forward, name=f"luminesk-console-{container_name}")
	thread.daemon = True
	thread.start()
	return thread


def ensure_docker_image(
	image: str,
	*,
	docker_bin: str | None = None,
	console: Console | None = None,
) -> None:
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

	status_message = None
	if console is not None:
		status_message = ansi_text(
			t(
				"launcher.docker_pull_start",
				image=accent(image, bold=True),
			)
		)

	if status_message is None:
		pull_result = subprocess.run(
			[resolved_docker_bin, "pull", image],
			check=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.PIPE,
			text=True,
			encoding="utf-8",
			errors="replace",
		)
	else:
		with console.status(status_message, spinner="dots"):
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
