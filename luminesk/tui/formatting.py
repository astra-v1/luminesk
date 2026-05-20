from __future__ import annotations

from datetime import datetime

from rich.style import Style
from rich.text import Text

from luminesk.core import doctor as dr
from luminesk.core import manager as srv
from luminesk.core.messages import t
from luminesk.utils.logs import normalize_log_line


def render_runtime_status(view: srv.ServerRuntimeView) -> str:
	suffixes: list[str] = []
	if view.status == "running":
		if view.loop_enabled:
			suffixes.append(t("common.loop"))
		if view.docker_container_name is not None:
			suffixes.append(
				t("common.docker_container", container_name=view.docker_container_name)
			)
		return (
			f"{t('common.running')} ({', '.join(suffixes)})"
			if suffixes
			else t("common.running")
		)
	if view.docker_container_name is not None:
		suffixes.append(t("common.docker_container", container_name=view.docker_container_name))
	return (
		f"{t('common.stopped')} ({', '.join(suffixes)})"
		if suffixes
		else t("common.stopped")
	)


def format_timestamp(value: datetime | None) -> str:
	if value is None:
		return t("common.empty")
	return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def build_selection_text(view: srv.ServerRuntimeView | None) -> Text:
	if view is None:
		return Text(t("tui.selection.empty"))

	lines = [
		t("tui.selection.title", name=view.server.name, tag=view.server.tag),
		f"{t('label.core')}: {view.server.core_id}",
		f"{t('label.memory_limit')}: {view.server.memory_limit}",
		f"{t('label.status')}: {render_runtime_status(view)}",
		f"{t('label.jar')}: {view.server.jar_name}",
		f"{t('label.last_start')}: {format_timestamp(view.last_started_at)}",
	]
	return Text("\n".join(lines))


def build_server_snapshot_text(view: srv.ServerRuntimeView | None) -> Text:
	if view is None:
		return Text(t("tui.snapshot.unavailable"))

	lines = [
		f"{t('label.tag')}: {view.server.tag}",
		f"{t('label.name')}: {view.server.name}",
		f"{t('label.core')}: {view.server.core_id}",
		f"{t('label.core_version')}: {view.server.core_version or t('common.manual_unknown')}",
		f"{t('label.jar')}: {view.server.jar_name}",
		f"{t('label.memory_limit')}: {view.server.memory_limit}",
		f"{t('label.status')}: {render_runtime_status(view)}",
		f"{t('label.pid')}: {view.pid or t('common.empty')}",
		f"{t('label.uptime')}: {srv.format_timedelta(view.uptime)}",
		f"{t('label.last_start')}: {format_timestamp(view.last_started_at)}",
		f"{t('label.last_stop')}: {format_timestamp(view.last_stopped_at)}",
		f"{t('label.last_exit_code')}: {view.last_exit_code if view.last_exit_code is not None else t('common.empty')}",
		f"{t('label.docker_container')}: {view.docker_container_name or t('common.empty')}",
		f"{t('label.path')}: {view.server.path}",
	]
	return Text("\n".join(lines))


def build_doctor_summary(results: list[dr.DiagnosticResult]) -> str:
	ok_count = sum(1 for item in results if item.status)
	fail_count = len(results) - ok_count
	critical_failed = any(item.critical and not item.status for item in results)
	return t(
		"tui.doctor.summary",
		ok_count=ok_count,
		fail_count=fail_count,
		critical_fail=t("common.yes") if critical_failed else t("common.no"),
	)


def render_console_line(line: str) -> Text:
	text = Text.from_ansi(normalize_log_line(line))
	text.no_wrap = False
	if not text.spans and text.plain.strip().startswith("["):
		text.stylize(Style(color="bright_black"))
	return text
