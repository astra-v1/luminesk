import subprocess
import shutil
import httpx
import re

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel
from luminesk.core.messages import t
from luminesk.core.registry import CoreProvider, registry
from luminesk.utils.errors import format_error
from luminesk.utils.http import request_with_retries


DOWNLOAD_SOURCE_TIMEOUT = 10.0
MAX_DOWNLOAD_SOURCE_WORKERS = 4


class DiagnosticResult(BaseModel):
	name: str
	status: bool
	message: str
	critical: bool = False


def check_tmux() -> DiagnosticResult:
	tmux_bin = shutil.which("tmux")
	if not tmux_bin:
		return DiagnosticResult(
			name=t("doctor.component.tmux"),
			status=False,
			message=t("doctor.tmux_missing"),
			critical=False,
		)

	try:
		result = subprocess.run(
			[tmux_bin, "-V"],
			capture_output=True,
			text=True,
			timeout=5,
		)
		output = (result.stdout or result.stderr).strip() or t("doctor.tmux_detected")
		return DiagnosticResult(
			name=t("doctor.component.tmux"),
			status=result.returncode == 0,
			message=output,
			critical=False,
		)
	except Exception as exc:
		return DiagnosticResult(
			name=t("doctor.component.tmux"),
			status=False,
			message=t("common.error_prefix", error=format_error(exc)),
			critical=False,
		)

def check_java() -> DiagnosticResult:
	java_bin = shutil.which("java")
	if not java_bin:
		return DiagnosticResult(
			name=t("doctor.component.java_runtime"),
			status=False,
			message=t("doctor.java_missing"),
			critical=True
		)

	try:
		result = subprocess.run([java_bin, "-version"], capture_output=True, text=True, timeout=5)
		output = result.stderr or result.stdout
		version_line = output.splitlines()[0] if output else t("doctor.unknown_version")

		match = re.search(r'version "(.+?)"', output)

		if match:
			version_str = match.group(1)
			major_version = int(version_str.split(".")[0]) if version_str.split(".") else 0

			if major_version < 21:
				return DiagnosticResult(
					name=t("doctor.component.java_version"),
					status=False,
					message=t("doctor.java_too_old", version_line=version_line),
					critical=False,
				)

			return DiagnosticResult(
				name=t("doctor.component.java_runtime"),
				status=True,
				message=version_line,
			)

		return DiagnosticResult(
			name=t("doctor.component.java_runtime"),
			status=True,
			message=version_line,
		)

	except FileNotFoundError:
		return DiagnosticResult(
			name=t("doctor.component.java_runtime"),
			status=False,
			message=t("doctor.java_missing"),
			critical=True
		)

	except Exception as e:
		return DiagnosticResult(
			name=t("doctor.component.java_runtime"),
			status=False,
			message=t("common.error_prefix", error=format_error(e)),
			critical=False,
		)


def check_download_sources() -> list[DiagnosticResult]:
	cores = registry.get_all()
	if not cores:
		return []

	max_workers = min(MAX_DOWNLOAD_SOURCE_WORKERS, len(cores))
	with ThreadPoolExecutor(max_workers=max_workers) as executor:
		return list(executor.map(_check_download_source, cores))


def check_repositories() -> list[DiagnosticResult]:
	return check_download_sources()


def _check_download_source(core: CoreProvider) -> DiagnosticResult:
	try:
		check_url = core.get_availability_check_url()
		with httpx.Client(timeout=DOWNLOAD_SOURCE_TIMEOUT, follow_redirects=True) as client:
			return _check_source(client, core.name, check_url)
	except Exception as exc:
		return DiagnosticResult(
			name=t("doctor.source_name", core_name=core.name),
			status=False,
			message=t("common.error_prefix", error=format_error(exc)),
		)


def _check_source(client: httpx.Client, core_name: str, check_url: str) -> DiagnosticResult:
	try:
		response = request_with_retries(
			client,
			"HEAD",
			check_url,
			retry_on_status=True,
		)
		if response.status_code == 405:
			response = request_with_retries(
				client,
				"GET",
				check_url,
				retry_on_status=True,
			)

		if response.is_success:
			return DiagnosticResult(
				name=t("doctor.source_name", core_name=core_name),
				status=True,
				message=t("doctor.source_ok"),
			)

		return DiagnosticResult(
			name=t("doctor.source_name", core_name=core_name),
			status=False,
			message=f"HTTP {response.status_code}",
		)
	except Exception as exc:
		return DiagnosticResult(
			name=t("doctor.source_name", core_name=core_name),
			status=False,
			message=t("common.error_prefix", error=format_error(exc)),
		)
