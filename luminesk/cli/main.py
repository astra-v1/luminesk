from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from cyclopts import App, Parameter
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

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
	AnimatedGradientText,
	error_panel,
	info_panel,
	success_panel,
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


def _status_label(status: bool) -> str:
	return f"[green]{t('common.ok')}[/]" if status else f"[red]{t('common.fail')}[/]"


@app.command(name="diagnostic", alias="check")
def diagnostic() -> None:
	"""Check Nukkit-compatible core repositories."""
	_load_cli_config()
	label = AnimatedGradientText(
		t("cli.diagnostic.checking_sources"),
		palette=(
			(80, 80, 80),
			(120, 120, 120),
			(180, 180, 180),
			(120, 120, 120),
			(80, 80, 80),
		),
	)

	results = []

	with Live(label, refresh_per_second=15, transient=True) as live:
		label.set_text(t("cli.diagnostic.checking_sources"))
		live.update(label)
		results.extend(dg.check_repositories())

	table = Table()
	table.add_column(t("label.component"), style="cyan", no_wrap=True)
	table.add_column(t("label.status"), no_wrap=True)
	table.add_column(t("label.description"))

	for res in results:
		table.add_row(res.name, _status_label(res.status), res.message)

	console.print(table)

	if any(not res.status for res in results):
		console.print(error_panel(t("cli.diagnostic.failure")))
		raise SystemExit(1)

	console.print(success_panel(t("cli.diagnostic.success")))


@app.command
def cores() -> None:
	"""List available cores."""
	_load_cli_config()
	lines = []

	for core in registry.get_all():
		lines.append(f"[green]* {core.name}[/green]\n[dim]{core.description}[/dim]")

	lines.append(t("cli.cores.tip"))

	console.print(
		Panel(
			"\n\n".join(lines),
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
		console.print(error_panel(t("cli.create.core_not_found", core_id=core)))
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

	console.print(
		success_panel(
			"\n".join(
				[
					t("cli.create.success_title"),
					f"{t('label.name')}: [cyan]{server.name}[/cyan]",
					f"{t('label.tag')}: [cyan]{server.tag}[/cyan]",
					f"{t('label.core')}: [cyan]{selected_core.name}[/cyan]",
					f"{t('label.core_version')}: [cyan]{server.core_version or t('common.unknown')}[/cyan]",
					f"{t('label.jar')}: [cyan]{server.jar_name}[/cyan]",
					f"{t('label.java')}: [cyan]{server.java_image}[/cyan]",
					f"{t('label.memory_limit')}: [cyan]{server.memory_limit}[/cyan]",
					f"{t('label.path')}: [dim]{server.path}[/dim]",
				]
			)
		)
	)


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

	console.print(
		success_panel(
			"\n".join(
				[
					t("cli.upgrade.success_title"),
					f"{t('label.server')}: [cyan]{updated_server.name}[/cyan] ([cyan]{updated_server.tag}[/cyan])",
					f"{t('label.core')}: [cyan]{updated_server.core_id}[/cyan]",
					f"{t('label.version')}: [cyan]{updated_server.core_version or t('common.unknown')}[/cyan]",
					f"{t('label.jar')}: [cyan]{updated_server.jar_name}[/cyan]",
				]
			)
		)
	)


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
		console.print(error_panel(t("cli.create.core_not_found", core_id=core)))
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

	console.print(
		success_panel(
			"\n".join(
				[
					t("cli.change.success_title"),
					f"{t('label.server')}: [cyan]{updated_server.name}[/cyan] ([cyan]{updated_server.tag}[/cyan])",
					f"{t('label.core')}: [cyan]{updated_server.core_id}[/cyan]",
					f"{t('label.version')}: [cyan]{updated_server.core_version or t('common.unknown')}[/cyan]",
					f"{t('label.path')}: [cyan]{updated_server.path}[/cyan]",
					f"{t('label.jar')}: [cyan]{updated_server.jar_name}[/cyan]",
				]
			)
		)
	)


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

	console.print(
		success_panel(
			"\n".join(
				[
					t("cli.change_java.success_title"),
					f"{t('label.server')}: [cyan]{updated_server.name}[/cyan] ([cyan]{updated_server.tag}[/cyan])",
					f"{t('label.java')}: [cyan]{updated_server.java_image}[/cyan]",
				]
			)
		)
	)


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

	console.print(
		success_panel(
			"\n".join(
				[
					t("cli.delete.success_title"),
					f"{t('label.server')}: [cyan]{server.name}[/cyan] ([cyan]{server.tag}[/cyan])",
					f"{t('label.path')}: [dim]{server.path}[/dim]",
				]
			)
		)
	)


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

	table = Table(title=t("cli.list.title"))
	table.add_column(t("label.tag"), style="cyan", no_wrap=True)
	table.add_column(t("label.name"), style="bold")
	table.add_column(t("label.core"), no_wrap=True)
	table.add_column(t("label.java"), no_wrap=True)
	table.add_column(t("label.status"), no_wrap=True)
	table.add_column(t("label.pid"), no_wrap=True, justify="right")
	table.add_column(t("label.uptime"), no_wrap=True)
	table.add_column(t("label.last_start"), no_wrap=True)
	table.add_column(t("label.last_stop"), no_wrap=True)
	table.add_column(t("label.path"), overflow="fold")

	for view in filtered_views:
		table.add_row(
			view.server.tag,
			view.server.name,
			view.server.core_id,
			view.server.java_image,
			_format_status(view.status, view.loop_enabled, view.docker_container_name),
			str(view.pid or t("common.empty")),
			srv.format_timedelta(view.uptime),
			_format_datetime(view.last_started_at),
			_format_datetime(view.last_stopped_at),
			str(view.server.path),
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
		console.print(info_panel(t("cli.control.loop_warning", tag=result.target.server.tag)))

	details = [
		f"{t('label.action')}: [cyan]{action_name}[/cyan]",
		f"{t('label.server')}: [cyan]{result.target.server.name}[/cyan] ([cyan]{result.target.server.tag}[/cyan])",
		f"{t('label.signal')}: [cyan]{result.signal_name}[/cyan]",
	]

	if result.signaled_server and result.server_pid is not None:
		details.append(f"{t('label.server_pid')}: [cyan]{result.server_pid}[/cyan]")

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
) -> str:
	suffixes = []
	if loop_enabled:
		suffixes.append(f"[yellow]{t('common.loop')}[/yellow]")
	if docker_container_name is not None:
		suffixes.append(f"[cyan]{t('common.docker_container', container_name=docker_container_name)}[/cyan]")
	suffix = f" [dim]({', '.join(suffixes)})[/dim]" if suffixes else ""
	if status == "running":
		return f"[green]{t('common.running')}[/green]{suffix}"
	return f"[red]{t('common.stopped')}[/red]{suffix}"


def _format_datetime(value: datetime | None) -> str:
	if value is None:
		return t("common.empty")

	return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")
