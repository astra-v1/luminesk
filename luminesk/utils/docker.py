from __future__ import annotations

import re
import shutil
import subprocess
import platform

from pathlib import Path
from typing import Protocol

from luminesk.core.messages import t


DEFAULT_DOCKER_IMAGE = "eclipse-temurin:21-jre"
DEFAULT_DOCKER_MEMORY_LIMIT = "1g"
DOCKER_SERVER_DIR = "/server"
DOCKER_CONSOLE_PIPE = "/tmp/luminesk-console.pipe"

MEMORY_LIMIT_RE = re.compile(r"^[1-9][0-9]*(?:[bkmg])?$", re.IGNORECASE)

DOCKER_ENTRYPOINT_SCRIPT = f"""
set -o pipefail
mkdir -p .luminesk/logs
rm -f {DOCKER_CONSOLE_PIPE}
mkfifo {DOCKER_CONSOLE_PIPE}
chmod 600 {DOCKER_CONSOLE_PIPE}
trap 'rm -f {DOCKER_CONSOLE_PIPE}' EXIT

while true; do
	exec 3<> {DOCKER_CONSOLE_PIPE}
	java -jar "$LUMINESK_JAR_NAME" < {DOCKER_CONSOLE_PIPE} 2>&1 | tee -a "$LUMINESK_LOG_PATH"
	exit_code=${{PIPESTATUS[0]}}
	exec 3>&-

	if [ "${{LUMINESK_LOOP:-0}}" != "1" ]; then
		exit "$exit_code"
	fi

	printf '[LumiNESK] Server exited with code %s. Restarting in %s seconds.\\n' "$exit_code" "${{LUMINESK_RESTART_DELAY:-5}}" | tee -a "$LUMINESK_LOG_PATH"
	sleep "${{LUMINESK_RESTART_DELAY:-5}}"
done
""".strip()


class DockerLaunchTarget(Protocol):
	tag: str
	path: Path
	jar_name: str


def normalize_memory_limit(memory_limit: str | None) -> str:
	normalized = DEFAULT_DOCKER_MEMORY_LIMIT if memory_limit is None else memory_limit.strip().lower()
	if not MEMORY_LIMIT_RE.fullmatch(normalized):
		raise ValueError(
			t(
				"docker.invalid_memory_limit",
				memory_limit=memory_limit or "",
			)
		)
	return normalized


def get_docker_binary() -> str:
	docker_bin = shutil.which("docker")
	if docker_bin is None:
		raise RuntimeError(t("docker.not_found"))
	return docker_bin


def build_docker_container_name(tag: str) -> str:
	sanitized = "".join(
		char if char.isalnum() or char in {"-", "_"} else "-"
		for char in tag.strip().lower()
	).strip("-_")
	return f"luminesk-{sanitized or 'server'}"


def build_docker_logs_command(container_name: str) -> tuple[str, ...]:
	return ("docker", "logs", "--follow", container_name)


def build_docker_run_command(
	server: DockerLaunchTarget,
	log_path: Path,
	*,
	container_name: str | None = None,
	image: str = DEFAULT_DOCKER_IMAGE,
	loop: bool = False,
	memory_limit: str | None = None,
	restart_delay_seconds: int = 5,
) -> tuple[str, ...]:
	normalized_memory_limit = normalize_memory_limit(memory_limit)
	resolved_container_name = container_name or build_docker_container_name(server.tag)
	mount_source = _format_mount_source(server.path)
	return (
		"docker",
		"run",
		"--detach",
		"--interactive",
		"--name",
		resolved_container_name,
		"--memory",
		normalized_memory_limit,
		*_network_args(),
		"--workdir",
		DOCKER_SERVER_DIR,
		"--volume",
		f"{mount_source}:{DOCKER_SERVER_DIR}",
		"--env",
		f"LUMINESK_JAR_NAME={server.jar_name}",
		"--env",
		f"LUMINESK_LOG_PATH={_to_container_path(log_path)}",
		"--env",
		f"LUMINESK_LOOP={'1' if loop else '0'}",
		"--env",
		f"LUMINESK_RESTART_DELAY={restart_delay_seconds}",
		image,
		"bash",
		"-lc",
		DOCKER_ENTRYPOINT_SCRIPT,
	)


def docker_container_is_running(container_name: str) -> bool:
	try:
		result = _run_docker(
			("inspect", "--format", "{{.State.Running}}", container_name),
			check=False,
		)
	except RuntimeError:
		return False
	return result.returncode == 0 and result.stdout.strip().lower() == "true"


def get_docker_container_pid(container_name: str) -> int | None:
	try:
		result = _run_docker(
			("inspect", "--format", "{{.State.Pid}}", container_name),
			check=False,
		)
	except RuntimeError:
		return None
	if result.returncode != 0:
		return None

	try:
		pid = int(result.stdout.strip())
	except ValueError:
		return None

	return pid if pid > 0 else None


def get_docker_container_exit_code(container_name: str) -> int | None:
	try:
		result = _run_docker(
			("inspect", "--format", "{{.State.ExitCode}}", container_name),
			check=False,
		)
	except RuntimeError:
		return None
	if result.returncode != 0:
		return None

	try:
		return int(result.stdout.strip())
	except ValueError:
		return None


def remove_docker_container(container_name: str) -> None:
	try:
		_run_docker(("rm", "--force", container_name), check=False)
	except RuntimeError:
		return


def stop_docker_container(container_name: str, timeout_seconds: int = 10) -> None:
	result = _run_docker(
		("stop", "--time", str(timeout_seconds), container_name),
		check=False,
	)
	if result.returncode != 0:
		raise RuntimeError(result.stderr.strip() or t("docker.stop_failed"))


def kill_docker_container(container_name: str) -> None:
	result = _run_docker(("kill", container_name), check=False)
	if result.returncode != 0:
		raise RuntimeError(result.stderr.strip() or t("docker.kill_failed"))


def send_docker_command(container_name: str, command: str) -> None:
	try:
		result = _run_docker(
			(
				"exec",
				container_name,
				"bash",
				"-lc",
				f'printf "%s\\n" "$1" > {DOCKER_CONSOLE_PIPE}',
				"luminesk-send",
				command,
			),
			check=False,
			timeout=5,
		)
	except subprocess.TimeoutExpired as exc:
		raise RuntimeError(t("docker.send_command_timeout")) from exc
	if result.returncode != 0:
		raise RuntimeError(result.stderr.strip() or t("docker.send_command_failed"))


def _run_docker(
	args: tuple[str, ...],
	*,
	check: bool,
	timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
	docker_bin = get_docker_binary()
	return subprocess.run(
		[docker_bin, *args],
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		check=check,
		timeout=timeout,
	)


def _to_container_path(path: Path) -> str:
	name = path.name
	return f"{DOCKER_SERVER_DIR}/.luminesk/logs/{name}"


def _format_mount_source(path: Path) -> str:
	return str(path.expanduser().resolve()).replace("\\", "/")


def _network_args() -> tuple[str, ...]:
	if platform.system().lower() == "linux":
		return ("--network", "host")

	return (
		"--publish",
		"19132:19132/udp",
		"--publish",
		"19132:19132/tcp",
	)
