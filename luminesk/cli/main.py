from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from luminesk.core import diagnostic as dg
from luminesk.core import manager as srv
from luminesk.core.config import UserConfig
from luminesk.core.messages import set_language, t
from luminesk.core.registry import registry
from luminesk.main import __version__
from luminesk.utils.docker import (
	DEFAULT_DOCKER_MEMORY_LIMIT,
	DEFAULT_JAVA_VERSION,
	normalize_java_image,
	normalize_memory_limit,
)
from luminesk.utils.rich_utils import (
	accent,
	ansi_text,
	danger,
	emph,
	error_panel,
	format_kv,
	format_server,
	info_panel,
	muted,
	success,
	success_panel,
	warning,
)


NameOption = Annotated[str | None, Parameter(name=["--name", "-n"], help=t("cli.create.option.name"))]
DirectoryOption = Annotated[Path | None, Parameter(name=["--dir", "-d"], help=t("cli.create.option.directory"))]
CoreOption = Annotated[str | None, Parameter(name=["--core", "-c"], help=t("cli.create.option.core"))]
TagOption = Annotated[str | None, Parameter(name=["--tag", "-t"], help=t("cli.create.option.tag"))]
ForceOption = Annotated[bool, Parameter(name=["--force", "-f"], help=t("cli.create.option.force"))]
MemoryOption = Annotated[str, Parameter(name=["--memory", "-m"], help=t("cli.create.option.memory"))]
JavaOption = Annotated[str | None, Parameter(name=["--java", "-j"], help=t("cli.create.option.java"))]
StartTagArgument = Annotated[str | None, Parameter(help=t("cli.start.argument.tag"))]

app = App(
	name="luminesk",
	help="Nukkit Engine Servers Kit CLI manager.",
	version=t("cli.version.banner", version=__version__),
	version_flags=["--version", "-v"],
	default_parameter=Parameter(negative=""),
)
console = Console()


def _load_cli_config() -> UserConfig:
	try:
		config = UserConfig.load()
	except Exception as exc:
		console.print(error_panel(t("cli.config.load_failed", error=exc)))
		raise SystemExit(1) from exc
	set_language(config.language)
	return config


def _status_label(status: bool):
	label = t("common.ok") if status else t("common.fail")
	styled = success(label, bold=True) if status else danger(label, bold=True)
	return ansi_text(styled)


@app.command(name="diagnostic", alias="check")
def diagnostic() -> None:
	"""Check Nukkit-compatible core repositories."""
	_load_cli_config()
	results = []
	status_text = ansi_text(muted(t("cli.diagnostic.checking_sources")))
	with console.status(status_text, spinner="dots"):
		results.extend(dg.check_repositories())

	table = Table(header_style="bold")
	table.add_column(t("label.component"), no_wrap=True)
	table.add_column(t("label.status"), no_wrap=True)
	table.add_column(t("label.description"))

	for res in results:
		name_text = ansi_text(accent(res.name, bold=True))
		status_text = _status_label(res.status)
		message_text = ansi_text(success(res.message) if res.status else danger(res.message))
		table.add_row(name_text, status_text, message_text)

	console.print(table)

	if any(not res.status for res in results):
		console.print(error_panel(danger(t("cli.diagnostic.failure"), bold=True)))
		raise SystemExit(1)

	console.print(success_panel(success(t("cli.diagnostic.success"), bold=True)))


@app.command
def cores() -> None:
	"""List available cores."""
	_load_cli_config()
	lines = []

	for core in registry.get_all():
		bullet = success("*")
		name = accent(core.name, bold=True)
		description = muted(core.description)
		lines.append(f"{bullet} {name}\n{description}")

	tip = f"\n{emph('Tip:')} {t('cli.cores.tip', command=accent('nesk diagnostic', bold=True))}"
	lines.append(tip)

	console.print(
		Panel(
			ansi_text("\n\n".join(lines)),
			title=t("cli.cores.title"),
			border_style="cyan",
			padding=(1, 2),
		)
	)


@app.command
def create(
	*,
	name: NameOption = None,
	directory: DirectoryOption = None,
	core: CoreOption = None,
	tag: TagOption = None,
	force: ForceOption = False,
	memory: MemoryOption = DEFAULT_DOCKER_MEMORY_LIMIT,
	java: JavaOption = None,
) -> None:
	"""Create a new server."""
	config = _load_cli_config()
	wizard_mode = any(value is None for value in (name, directory, core, tag))

	if core is None:
		core = Prompt.ask(t("cli.create.prompt.core"), default="nukkit")

	selected_core = registry.get_by_id(core)
	if selected_core is None:
		console.print(
			error_panel(
				t(
					"cli.create.core_not_found",
					core_id=danger(core, bold=True),
					command=accent("nesk cores", bold=True),
				)
			)
		)
		raise SystemExit(1)

	if name is None:
		name = Prompt.ask(
			t("cli.create.prompt.name"),
			default=t("common.default_server_name", core_name=selected_core.name),
		)

	if tag is None:
		tag = Prompt.ask(t("cli.create.prompt.tag"), default=name.lower().replace(" ", "-"))

	if directory is None:
		default_directory = (config.default_server_path / tag).expanduser()
		directory = Path(
			Prompt.ask(
				t("cli.create.prompt.directory"),
				default=str(default_directory),
			)
		)

	if java is None:
		java = (
			Prompt.ask(t("cli.create.prompt.java"), default=DEFAULT_JAVA_VERSION)
			if wizard_mode
			else DEFAULT_JAVA_VERSION
		)

	try:
		memory_limit = normalize_memory_limit(memory)
		java_image = normalize_java_image(java)
		server = srv.create_server(
			config=config,
			name=name,
			tag=tag,
			directory=directory,
			core=selected_core,
			force=force,
			console=console,
			memory_limit=memory_limit,
			java_image=java_image,
		)
	except (srv.ServerManagerError, RuntimeError, ValueError) as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	create_details = [
		success(t("cli.create.success_title"), bold=True),
		format_kv(t("label.name"), server.name),
		format_kv(t("label.tag"), server.tag),
		format_kv(t("label.core"), selected_core.name),
		format_kv(t("label.core_version"), server.core_version or t("common.unknown")),
		format_kv(t("label.jar"), server.jar_name),
		format_kv(t("label.java"), server.java_image),
		format_kv(t("label.memory_limit"), server.memory_limit),
		format_kv(t("label.path"), server.path, dim_value=True),
	]
	console.print(success_panel("\n".join(create_details)))


@app.command
def start(
	tag: StartTagArgument = None,
	/,
	*,
	loop: Annotated[bool, Parameter(name=["--loop", "-l"], help=t("cli.start.option.loop"))] = False,
	detached: Annotated[
		bool,
		Parameter(
			name=["--detached", "--deatached", "-d"],
			help=t("cli.start.option.detached"),
		),
	] = False,
) -> None:
	"""Start a server."""
	config = _load_cli_config()

	try:
		server = srv.resolve_server(config=config, tag=tag, directory=Path.cwd())
		exit_code = srv.run_server(
			config=config,
			server=server,
			loop=loop,
			detached=detached,
			console=console,
		)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	raise SystemExit(exit_code)


@app.command
def attach(
	tag: Annotated[str | None, Parameter(help=t("cli.attach.argument.tag"))] = None,
) -> None:
	"""Attach to a running server and follow logs."""
	config = _load_cli_config()

	try:
		server = srv.resolve_server(config=config, tag=tag, directory=Path.cwd())
		exit_code = srv.attach_server(config=config, server=server)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	raise SystemExit(exit_code)


@app.command(name="upgrade-core", alias="upgrade_core")
def upgrade_core(
	*,
	tag: Annotated[str | None, Parameter(name=["--tag", "-t"], help=t("cli.upgrade.option.tag"))] = None,
) -> None:
	"""Upgrade the server core to the latest available version."""
	config = _load_cli_config()

	try:
		server = srv.resolve_server(config=config, tag=tag, directory=Path.cwd())
		updated_server = srv.upgrade_server_core(config=config, server=server, console=console)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	upgrade_details = [
		success(t("cli.upgrade.success_title"), bold=True),
		format_kv(
			t("label.server"),
			format_server(updated_server.name, updated_server.tag),
			value_color=None,
		),
		format_kv(t("label.core"), updated_server.core_id),
		format_kv(t("label.version"), updated_server.core_version or t("common.unknown")),
		format_kv(t("label.jar"), updated_server.jar_name),
	]
	console.print(success_panel("\n".join(upgrade_details)))


@app.command(name="change-core", alias="change_core")
def change_core(
	*,
	tag: Annotated[str | None, Parameter(name=["--tag", "-t"], help=t("cli.change.option.tag"))] = None,
	core: Annotated[str | None, Parameter(name=["--core", "-c"], help=t("cli.change.option.core"))] = None,
) -> None:
	"""Change the server core."""
	config = _load_cli_config()

	if core is None:
		core = Prompt.ask(t("cli.change.prompt.core"), default="nukkit")

	selected_core = registry.get_by_id(core)
	if selected_core is None:
		console.print(
			error_panel(
				t(
					"cli.create.core_not_found",
					core_id=danger(core, bold=True),
					command=accent("nesk cores", bold=True),
				)
			)
		)
		raise SystemExit(1)

	try:
		server = srv.resolve_server(config=config, tag=tag, directory=Path.cwd())
		updated_server = srv.change_server_core(
			config=config,
			server=server,
			core=selected_core,
			console=console,
		)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	change_details = [
		success(t("cli.change.success_title"), bold=True),
		format_kv(
			t("label.server"),
			format_server(updated_server.name, updated_server.tag),
			value_color=None,
		),
		format_kv(t("label.core"), updated_server.core_id),
		format_kv(t("label.version"), updated_server.core_version or t("common.unknown")),
		format_kv(t("label.path"), updated_server.path, dim_value=True),
		format_kv(t("label.jar"), updated_server.jar_name),
	]
	console.print(success_panel("\n".join(change_details)))


@app.command(name="change-java", alias="change_java")
def change_java(
	*,
	tag: Annotated[str | None, Parameter(name=["--tag", "-t"], help=t("cli.change_java.option.tag"))] = None,
	java: Annotated[str | None, Parameter(name=["--java", "-j"], help=t("cli.change_java.option.java"))] = None,
) -> None:
	"""Change the server Java Docker image."""
	config = _load_cli_config()

	if java is None:
		java = Prompt.ask(t("cli.change_java.prompt.java"), default=DEFAULT_JAVA_VERSION)

	try:
		server = srv.resolve_server(config=config, tag=tag, directory=Path.cwd())
		updated_server = srv.change_server_java(
			config=config,
			server=server,
			java=java,
		)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	java_details = [
		success(t("cli.change_java.success_title"), bold=True),
		format_kv(
			t("label.server"),
			format_server(updated_server.name, updated_server.tag),
			value_color=None,
		),
		format_kv(t("label.java"), updated_server.java_image),
	]
	console.print(success_panel("\n".join(java_details)))


@app.command
def stop(
	target: Annotated[str, Parameter(help=t("cli.stop.argument.target"))],
	/,
	*,
	force: Annotated[bool, Parameter(name=["--force", "-f"], help=t("cli.stop.option.force"))] = False,
) -> None:
	"""Gracefully stop a server by tag or PID."""
	_control_server(target=target, force=force, action_name="stop")


@app.command
def kill(
	target: Annotated[str, Parameter(help=t("cli.kill.argument.target"))],
	/,
	*,
	force: Annotated[bool, Parameter(name=["--force", "-f"], help=t("cli.kill.option.force"))] = False,
) -> None:
	"""Force-kill a server by tag or PID."""
	_control_server(target=target, force=force, action_name="kill")


@app.command
def delete(
	target: Annotated[str, Parameter(help=t("cli.delete.argument.target"))],
	/,
) -> None:
	"""Delete a stopped server from LumiNESK without touching server files."""
	config = _load_cli_config()

	try:
		server = srv.delete_server(config=config, target=target)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	delete_details = [
		success(t("cli.delete.success_title"), bold=True),
		format_kv(t("label.server"), format_server(server.name, server.tag), value_color=None),
		format_kv(t("label.path"), server.path, dim_value=True),
	]
	console.print(success_panel("\n".join(delete_details)))


@app.command(name="list")
def list_servers(
	*,
	tag: Annotated[str | None, Parameter(name=["--tag", "-t"], help=t("cli.list.option.tag"))] = None,
	status: Annotated[str | None, Parameter(name=["--status", "-s"], help=t("cli.list.option.status"))] = None,
	core: Annotated[str | None, Parameter(name=["--core", "-c"], help=t("cli.list.option.core"))] = None,
) -> None:
	"""List servers and their status."""
	config = _load_cli_config()
	try:
		status_filter = _normalize_status_filter(status)
	except ValueError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	views = srv.get_runtime_views(config)

	filtered_views = [
		view
		for view in views
		if (tag is None or view.server.tag == tag.strip().lower())
		and (status_filter is None or view.status == status_filter)
		and (core is None or view.server.core_id == core.strip().lower())
	]

	if not views:
		console.print(info_panel(t("cli.list.no_servers")))
		return

	if not filtered_views:
		console.print(info_panel(t("cli.list.no_matches")))
		return

	table = Table(title=t("cli.list.title"), header_style="bold")
	table.add_column(t("label.tag"), no_wrap=True)
	table.add_column(t("label.name"))
	table.add_column(t("label.core"), no_wrap=True)
	table.add_column(t("label.java"), no_wrap=True)
	table.add_column(t("label.status"), no_wrap=True)
	table.add_column(t("label.pid"), no_wrap=True, justify="right")
	table.add_column(t("label.uptime"), no_wrap=True)
	table.add_column(t("label.last_start"), no_wrap=True)
	table.add_column(t("label.last_stop"), no_wrap=True)
	table.add_column(t("label.path"), overflow="fold")

	for view in filtered_views:
		pid_value = str(view.pid) if view.pid is not None else t("common.empty")
		pid_text = muted(pid_value) if view.pid is None else pid_value

		uptime_value = srv.format_timedelta(view.uptime)
		uptime_text = muted(uptime_value) if view.uptime is None else uptime_value

		last_started = _format_datetime(view.last_started_at)
		last_started_text = (
			muted(last_started) if view.last_started_at is None else last_started
		)

		last_stopped = _format_datetime(view.last_stopped_at)
		last_stopped_text = (
			muted(last_stopped) if view.last_stopped_at is None else last_stopped
		)

		table.add_row(
			ansi_text(accent(view.server.tag, bold=True)),
			ansi_text(emph(view.server.name)),
			ansi_text(accent(view.server.core_id)),
			ansi_text(accent(view.server.java_image)),
			_format_status(view.status, view.loop_enabled, view.docker_container_name),
			ansi_text(pid_text),
			ansi_text(uptime_text),
			ansi_text(last_started_text),
			ansi_text(last_stopped_text),
			ansi_text(muted(str(view.server.path))),
		)

	console.print(table)


def _control_server(
	target: str,
	force: bool,
	action_name: str,
) -> None:
	config = _load_cli_config()

	try:
		if action_name == "kill":
			result = srv.kill_server(config=config, target=target, force=force)
		else:
			result = srv.stop_server(config=config, target=target, force=force)
	except srv.ServerManagerError as exc:
		console.print(error_panel(str(exc)))
		raise SystemExit(1) from exc

	if result.loop_active and not force:
		console.print(
			info_panel(
				t(
					"cli.control.loop_warning",
					tag=accent(result.target.server.tag, bold=True),
					force_flag=warning("--force", bold=True),
				)
			)
		)

	details = [
		format_kv(t("label.action"), action_name, bold_value=True),
		format_kv(
			t("label.server"),
			format_server(result.target.server.name, result.target.server.tag),
			value_color=None,
		),
		format_kv(t("label.signal"), result.signal_name),
	]

	if result.signaled_server and result.server_pid is not None:
		details.append(format_kv(t("label.server_pid"), result.server_pid))

	console.print(success_panel("\n".join(details)))


def _normalize_status_filter(status: str | None) -> str | None:
	if status is None:
		return None

	normalized_status = status.strip().lower()
	if normalized_status not in {"running", "stopped"}:
		raise ValueError(t("cli.status.invalid"))
	return normalized_status


def _format_status(
	status: str,
	loop_enabled: bool,
	docker_container_name: str | None = None,
) -> Text:
	suffixes = []
	if loop_enabled:
		suffixes.append(warning(t("common.loop")))
	if docker_container_name is not None:
		suffixes.append(
			accent(
				t("common.docker_container", container_name=docker_container_name)
			)
		)
	suffix = f" ({', '.join(suffixes)})" if suffixes else ""
	if status == "running":
		return ansi_text(success(t("common.running"), bold=True) + suffix)
	return ansi_text(danger(t("common.stopped"), bold=True) + suffix)


def _format_datetime(value: datetime | None) -> str:
	if value is None:
		return t("common.empty")

	return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
