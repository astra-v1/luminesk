from __future__ import annotations

import os
import signal
import threading

from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from rich.text import Text
from textual.app import App
from textual.widgets import RichLog

from luminesk.core import doctor as dr
from luminesk.core import manager as srv
from luminesk.core.config import ManagedServer, UserConfig
from luminesk.core.messages import set_language, t
from luminesk.core.registry import registry
from luminesk.tui.launcher import DetachedLaunchResult, launch_server_detached
from luminesk.utils.errors import format_error
from luminesk.utils.logs import find_latest_log_path, read_log_increment, read_log_tail
from luminesk.utils.tmux import (
	build_tmux_attach_command,
	build_tmux_session_name,
	send_tmux_command,
	tmux_session_exists,
)

from .formatting import build_doctor_summary, render_console_line
from .models import ActivityEntry, CreateServerRequest, FormField, RegisterServerRequest
from .screens import DoctorResultsScreen, HomeScreen, InputFormScreen, ServerScreen


T = TypeVar("T")


class LumiNESKTuiApp(App[tuple[str, ...] | None]):
	CSS_PATH = str(Path(__file__).resolve().parent / "styles" / "app.tcss")

	TITLE = t("tui.app.title")
	SUB_TITLE = t("tui.app.subtitle")

	def __init__(
		self,
		config_loader: Callable[[], UserConfig] | None = None,
		refresh_interval: float = 2.0,
		console_refresh_interval: float = 0.5,
		launcher: Callable[[ManagedServer, bool], DetachedLaunchResult] | None = None,
		session_exists: Callable[[str], bool] | None = None,
	) -> None:
		super().__init__()
		self._config_loader = config_loader or UserConfig.load
		self._refresh_interval = refresh_interval
		self.console_refresh_interval = console_refresh_interval
		self._launcher = launcher or launch_server_detached
		self._session_exists = session_exists or tmux_session_exists
		self._views: list[srv.ServerRuntimeView] = []
		self._selected_tag: str | None = None
		self._activity_entries: list[ActivityEntry] = []
		self._busy = False
		self._busy_message = ""
		self._status_message = ""
		self._progress_frames = ("|", "/", "-", "\\")
		self._progress_index = 0
		self._progress_timer = None
		self._live_log_tag: str | None = None
		self._live_log_path: Path | None = None
		self._live_log_position = 0

	@property
	def busy(self) -> bool:
		return self._busy

	def on_mount(self) -> None:
		self.push_screen(HomeScreen())
		self.call_after_refresh(self._initialize_ui)

	def _initialize_ui(self) -> None:
		self._status_message = ""
		self._push_log(t("tui.app.started"))
		self.refresh_servers()
		if self._refresh_interval > 0:
			self.set_interval(self._refresh_interval, self.refresh_servers)

	def request_quit(self) -> None:
		if not self._ensure_not_busy():
			return
		self.exit()

	def go_home(self) -> None:
		if not self._ensure_not_busy():
			return
		if isinstance(self.screen, ServerScreen):
			self._reset_live_console_state()
			self.pop_screen()
			self.call_after_refresh(self._sync_visible_screen)

	def open_selected_server(self) -> None:
		if not self._ensure_not_busy():
			return
		if not isinstance(self.screen, HomeScreen):
			return
		view = self._require_selected_view()
		if view is None:
			return
		self._reset_live_console_state()
		self.push_screen(ServerScreen(view.server.tag))
		self.call_after_refresh(self._sync_visible_screen)

	def select_row(self, row_index: int) -> None:
		if 0 <= row_index < len(self._views):
			self._selected_tag = self._views[row_index].server.tag
			if isinstance(self.screen, HomeScreen):
				self._sync_visible_screen()

	def refresh_servers(self) -> None:
		try:
			self._views = srv.get_runtime_views(self._load_config())
		except Exception as exc:
			self._set_status(t("tui.refresh.failed_status", error=format_error(exc)))
			self._push_log(t("tui.refresh.failed_log", error=format_error(exc)))
			return

		if self._views:
			available_tags = {view.server.tag for view in self._views}
			if self._selected_tag not in available_tags:
				self._selected_tag = self._views[0].server.tag
		else:
			self._selected_tag = None

		self._sync_visible_screen()

	def run_doctor(self) -> None:
		if not self._ensure_not_busy():
			return
		if not isinstance(self.screen, HomeScreen):
			self._set_status(t("tui.doctor.home_only"))
			return
		self._run_background(
			t("tui.doctor.running"),
			self._collect_diagnostics,
			self._on_doctor_complete,
		)

	def show_create_server(self) -> None:
		if not self._ensure_not_busy():
			return
		if not isinstance(self.screen, HomeScreen):
			self._set_status(t("tui.create.home_only"))
			return
		config = self._load_config()
		core_ids = registry.get_ids()
		core_id = core_ids[0] if core_ids else "nukkit"
		default_tag = f"{core_id}_server"
		default_name = t("common.default_server_name", core_name=core_id.title())
		description = t("tui.create.description", core_ids=", ".join(core_ids))
		screen = InputFormScreen(
			title=t("tui.create.title"),
			description=description,
			submit_label=t("common.create"),
			fields=[
				FormField("core_id", t("label.core_id"), core_id),
				FormField("name", t("label.name"), default_name),
				FormField("tag", t("label.tag"), default_tag),
				FormField(
					"directory",
					t("label.directory"),
					str(config.default_server_path.expanduser() / default_tag),
				),
			],
		)
		self.push_screen(screen, self._handle_create_form)

	def show_register_server(self) -> None:
		if not self._ensure_not_busy():
			return
		if not isinstance(self.screen, HomeScreen):
			self._set_status(t("tui.register.home_only"))
			return
		cwd = Path.cwd()
		default_name = cwd.name or t("common.manual_server_name")
		default_tag = default_name.lower().replace(" ", "_")
		screen = InputFormScreen(
			title=t("tui.register.title"),
			description=t("tui.register.description"),
			submit_label=t("common.register"),
			fields=[
				FormField("directory", t("label.server_directory"), str(cwd)),
				FormField("jar_path", t("label.jar_path"), "server.jar"),
				FormField("name", t("label.name"), default_name),
				FormField("tag", t("label.tag"), default_tag),
			],
		)
		self.push_screen(screen, self._handle_register_form)

	def start_server(self) -> None:
		if not self._ensure_server_page():
			return
		view = self._require_selected_view()
		if view is None:
			return
		if view.status == "running" or view.loop_enabled:
			self._stop_selected_server()
			return
		self._launch_selected_server(loop=False)

	def start_server_loop(self) -> None:
		if not self._ensure_server_page():
			return
		self._launch_selected_server(loop=True)

	def stop_server(self) -> None:
		if not self._ensure_server_page():
			return
		self._stop_selected_server()

	def kill_server(self) -> None:
		if not self._ensure_server_page():
			return
		view = self._require_selected_view()
		if view is None:
			return
		self._run_background(
			t("tui.kill.running", tag=view.server.tag),
			lambda: self._send_signal(view.server.tag, signal.SIGKILL, force=True),
			lambda result: self._on_signal_complete(result, t("tui.kill.complete")),
		)

	def upgrade_core(self) -> None:
		if not self._ensure_server_page():
			return
		view = self._require_selected_view()
		if view is None:
			return
		self._run_background(
			t("tui.upgrade.running", tag=view.server.tag),
			lambda: self._upgrade_server_core(view.server.tag),
			self._on_upgrade_complete,
		)

	def show_change_core(self) -> None:
		if not self._ensure_server_page():
			return
		view = self._require_selected_view()
		if view is None:
			return
		screen = InputFormScreen(
			title=t("tui.change.title", tag=view.server.tag),
			description=t("tui.change.description", core_ids=", ".join(registry.get_ids())),
			submit_label=t("common.change"),
			fields=[FormField("core_id", t("label.new_core"), view.server.core_id)],
		)
		self.push_screen(
			screen,
			lambda payload: self._handle_change_core_form(view.server.tag, payload),
		)

	def attach_to_session(self) -> None:
		if not self._ensure_server_page():
			return
		view = self._require_selected_view()
		if view is None:
			return
		attach_command = self._build_attach_command(view)
		if attach_command is None:
			self._set_status(t("tui.attach.unavailable_status"))
			self._push_log(
				t("tui.attach.unavailable_log", tag=view.server.tag),
				tag=view.server.tag,
			)
			return
		self._push_log(
			t("tui.attach.exit_log", command=" ".join(attach_command)),
			tag=view.server.tag,
		)
		self.exit(result=attach_command)

	def _sync_visible_screen(self) -> None:
		screen = self.screen
		if not getattr(screen, "is_mounted", False):
			return
		progress_message = self._get_progress_message()
		if isinstance(screen, HomeScreen):
			screen.sync(
				views=self._views,
				selected_tag=self._selected_tag,
				status_message=self._status_message,
				progress_message=progress_message,
				busy=self._busy,
				activity=self._build_activity_text(),
			)
			return
		if isinstance(screen, ServerScreen):
			view = self._find_view_by_tag(screen.server_tag)
			screen.sync(
				view=view,
				status_message=self._status_message,
				progress_message=progress_message,
				busy=self._busy,
				log_path=find_latest_log_path(view.server) if view is not None else None,
			)
			self._sync_server_console(screen, view)

	def _reset_live_console_state(self) -> None:
		self._live_log_tag = None
		self._live_log_path = None
		self._live_log_position = 0

	def _poll_live_console(self) -> None:
		screen = self.screen
		if not isinstance(screen, ServerScreen) or not getattr(screen, "is_mounted", False):
			return
		self._sync_server_console(screen, self._find_view_by_tag(screen.server_tag))

	def _sync_server_console(
		self,
		screen: ServerScreen,
		view: srv.ServerRuntimeView | None,
	) -> None:
		log_widget = screen.query_one("#server-console", RichLog)

		if view is None:
			log_widget.clear()
			log_widget.write(t("tui.log.runtime_missing"))
			self._reset_live_console_state()
			return

		log_path = find_latest_log_path(view.server)
		if log_path is None:
			if self._live_log_tag != view.server.tag or self._live_log_path is not None:
				log_widget.clear()
				log_widget.write(t("tui.log.not_created"))
				self._live_log_tag = view.server.tag
				self._live_log_path = None
				self._live_log_position = 0
			return

		try:
			current_size = log_path.stat().st_size
		except OSError as exc:
			log_widget.clear()
			log_widget.write(t("tui.log.read_failed", error=format_error(exc)))
			self._live_log_tag = view.server.tag
			self._live_log_path = log_path
			self._live_log_position = 0
			return

		log_changed = self._live_log_tag != view.server.tag or self._live_log_path != log_path
		log_truncated = current_size < self._live_log_position
		if log_changed or log_truncated:
			self._replace_console_tail(
				log_widget=log_widget,
				server_tag=view.server.tag,
				log_path=log_path,
				current_size=current_size,
			)
			return

		if current_size == self._live_log_position:
			return

		result = read_log_increment(log_path, self._live_log_position)
		if result.lines:
			for line in result.lines:
				log_widget.write(render_console_line(line), scroll_end=False)
			log_widget.scroll_end(animate=False)
		self._live_log_tag = view.server.tag
		self._live_log_path = log_path
		self._live_log_position = result.position

	def _replace_console_tail(
		self,
		log_widget: RichLog,
		server_tag: str,
		log_path: Path,
		current_size: int,
	) -> None:
		log_widget.clear()
		lines = read_log_tail(log_path, limit=120)
		if lines:
			for line in lines:
				log_widget.write(render_console_line(line), scroll_end=False)
			log_widget.scroll_end(animate=False)
		else:
			log_widget.write(t("tui.log.empty"))
		self._live_log_tag = server_tag
		self._live_log_path = log_path
		self._live_log_position = current_size

	def _load_config(self) -> UserConfig:
		return self._config_loader()

	def _build_activity_text(self, tag: str | None = None) -> Text:
		if tag is None:
			entries = self._activity_entries[-120:]
		else:
			entries = [
				entry
				for entry in self._activity_entries
				if entry.tag is None or entry.tag == tag
			][-120:]

		if not entries:
			return Text(t("tui.activity.empty"))

		lines = [
			f"[{entry.timestamp.astimezone().strftime('%H:%M:%S')}] {entry.message}"
			for entry in entries
		]
		return Text("\n".join(lines))

	def _push_log(self, message: str, tag: str | None = None) -> None:
		now = datetime.now().astimezone()
		for line in message.splitlines():
			self._activity_entries.append(ActivityEntry(timestamp=now, message=line, tag=tag))
		self._activity_entries = self._activity_entries[-240:]
		self._sync_visible_screen()

	def _set_status(self, message: str) -> None:
		self._status_message = message
		self._sync_visible_screen()

	def _get_progress_message(self) -> str:
		if not self._busy or not self._busy_message:
			return ""
		return f"{self._progress_frames[self._progress_index]} {self._busy_message}"

	def _find_view_by_tag(self, tag: str | None) -> srv.ServerRuntimeView | None:
		if tag is None:
			return None
		for view in self._views:
			if view.server.tag == tag:
				return view
		return None

	def _find_selected_view(self) -> srv.ServerRuntimeView | None:
		return self._find_view_by_tag(self._selected_tag)

	def _require_selected_view(self) -> srv.ServerRuntimeView | None:
		view = self._find_selected_view()
		if view is None:
			self._set_status(t("tui.selection.required_status"))
			self._push_log(t("tui.selection.required_log"))
		return view

	def _ensure_server_page(self) -> bool:
		if not self._ensure_not_busy():
			return False
		if isinstance(self.screen, ServerScreen):
			self._selected_tag = self.screen.server_tag
			return True
		self._set_status(t("tui.server_page.required"))
		return False

	def _set_busy(self, busy: bool, message: str = "") -> None:
		self._busy = busy
		self._busy_message = message if busy else ""
		self._progress_index = 0

		if busy:
			if self._progress_timer is None:
				self._progress_timer = self.set_interval(0.12, self._advance_progress)
		else:
			if self._progress_timer is not None:
				self._progress_timer.stop()
				self._progress_timer = None

		self._sync_visible_screen()

	def _advance_progress(self) -> None:
		if not self._busy or not self._busy_message:
			return
		self._progress_index = (self._progress_index + 1) % len(self._progress_frames)
		self._sync_visible_screen()

	def _ensure_not_busy(self) -> bool:
		if not self._busy:
			return True
		self._set_status(t("common.wait_current_operation"))
		return False

	def _run_background(
		self,
		start_message: str,
		work: Callable[[], T],
		on_complete: Callable[[T], None],
	) -> None:
		self._set_busy(True, start_message)
		self._set_status(start_message)
		self._push_log(start_message)

		def runner() -> None:
			try:
				result = work()
			except Exception as exc:
				self.call_from_thread(self._handle_background_error, exc)
				return
			self.call_from_thread(on_complete, result)

		threading.Thread(
			target=runner,
			name="luminesk-tui-worker",
			daemon=True,
		).start()

	def _handle_background_error(self, exc: Exception) -> None:
		self._set_busy(False)
		self._set_status(t("tui.background.error_status", error=format_error(exc)))
		self._push_log(t("tui.background.error_log", error=format_error(exc)))
		self.refresh_servers()

	def _stop_selected_server(self) -> None:
		view = self._require_selected_view()
		if view is None:
			return
		self._run_background(
			t("tui.stop.running", tag=view.server.tag),
			lambda: self._send_signal(view.server.tag, signal.SIGTERM, force=True),
			lambda result: self._on_signal_complete(result, t("tui.stop.complete")),
		)

	def _launch_selected_server(self, loop: bool) -> None:
		view = self._require_selected_view()
		if view is None:
			return
		try:
			config = self._load_config()
			server = config.get_server_by_tag(view.server.tag)
			if server is None:
				raise srv.ServerManagerError(
					t("tui.launch.not_found", tag=view.server.tag)
				)
			current_view = srv.get_runtime_view(config, server)
			if current_view.status == "running" or current_view.loop_enabled:
				raise srv.ServerManagerError(
					t("tui.launch.already_running", tag=server.tag)
				)
			launch_result = self._launcher(server, loop)
		except Exception as exc:
			self._set_status(t("tui.launch.failed_status", error=format_error(exc)))
			self._push_log(
				t("tui.launch.failed_log", tag=view.server.tag, error=format_error(exc)),
				tag=view.server.tag,
			)
			return

		mode = t("tui.launch.mode.loop") if loop else t("tui.launch.mode.single")
		self._set_status(
			t("tui.launch.created_status", session_name=launch_result.session_name, mode=mode)
		)
		self._push_log(
			t(
				"tui.launch.created_log",
				tag=view.server.tag,
				session_name=launch_result.session_name,
				mode=mode,
			),
			tag=view.server.tag,
		)
		self._push_log(
			t("tui.launch.attach_log", command=" ".join(launch_result.attach_command)),
			tag=view.server.tag,
		)
		self._push_log(
			t("tui.launch.log_path", path=launch_result.log_path),
			tag=view.server.tag,
		)
		self.refresh_servers()

	def _handle_create_form(self, payload: dict[str, str] | None) -> None:
		if payload is None:
			self._set_status(t("tui.create.cancelled"))
			return
		try:
			request = CreateServerRequest(
				name=self._read_required_field(payload, "name", t("label.name")),
				tag=self._read_required_field(payload, "tag", t("label.tag")),
				directory=Path(self._read_required_field(payload, "directory", t("label.directory"))),
				core_id=self._read_required_field(payload, "core_id", t("label.core_id")).lower(),
			)
		except ValueError as exc:
			self._set_status(str(exc))
			self._push_log(str(exc))
			return
		self._run_background(
			t("tui.create.running", tag=request.tag),
			lambda: self._create_server(request),
			self._on_create_complete,
		)

	def _handle_register_form(self, payload: dict[str, str] | None) -> None:
		if payload is None:
			self._set_status(t("tui.register.cancelled"))
			return
		try:
			request = RegisterServerRequest(
				name=self._read_required_field(payload, "name", t("label.name")),
				tag=self._read_required_field(payload, "tag", t("label.tag")),
				directory=Path(self._read_required_field(payload, "directory", t("label.directory"))),
				jar_path=Path(self._read_required_field(payload, "jar_path", t("label.jar_path"))),
			)
		except ValueError as exc:
			self._set_status(str(exc))
			self._push_log(str(exc))
			return
		self._run_background(
			t("tui.register.running", tag=request.tag),
			lambda: self._register_server(request),
			self._on_register_complete,
		)

	def _handle_change_core_form(
		self,
		tag: str,
		payload: dict[str, str] | None,
	) -> None:
		if payload is None:
			self._set_status(t("tui.change.cancelled"))
			return
		try:
			core_id = self._read_required_field(payload, "core_id", t("label.core")).lower()
		except ValueError as exc:
			self._set_status(str(exc))
			self._push_log(str(exc), tag=tag)
			return
		self._run_background(
			t("tui.change.running", tag=tag, core_id=core_id),
			lambda: self._change_server_core(tag, core_id),
			self._on_change_core_complete,
		)

	def _create_server(self, request: CreateServerRequest) -> ManagedServer:
		config = self._load_config()
		core = registry.get_by_id(request.core_id)
		if core is None:
			raise srv.ServerManagerError(
				t(
					"tui.core.not_found",
					core_id=request.core_id,
					core_ids=", ".join(registry.get_ids()),
				)
			)
		return srv.create_server(
			config=config,
			name=request.name,
			tag=request.tag,
			directory=request.directory,
			core=core,
			console=None,
		)

	def _register_server(self, request: RegisterServerRequest) -> ManagedServer:
		return srv.register_existing_server(
			config=self._load_config(),
			name=request.name,
			tag=request.tag,
			directory=request.directory,
			jar_path=request.jar_path,
		)

	def _upgrade_server_core(self, tag: str) -> ManagedServer:
		config = self._load_config()
		server = config.get_server_by_tag(tag)
		if server is None:
			raise srv.ServerManagerError(t("tui.launch.not_found", tag=tag))
		return srv.upgrade_server_core(config=config, server=server, console=None)

	def _change_server_core(self, tag: str, core_id: str) -> ManagedServer:
		config = self._load_config()
		server = config.get_server_by_tag(tag)
		if server is None:
			raise srv.ServerManagerError(t("tui.launch.not_found", tag=tag))
		core = registry.get_by_id(core_id)
		if core is None:
			raise srv.ServerManagerError(
				t(
					"tui.core.not_found",
					core_id=core_id,
					core_ids=", ".join(registry.get_ids()),
				)
			)
		return srv.change_server_core(
			config=config,
			server=server,
			core=core,
			console=None,
		)

	def _send_signal(
		self,
		tag: str,
		sig: signal.Signals,
		force: bool,
	) -> srv.ServerSignalResult:
		return srv.send_signal_to_server(
			config=self._load_config(),
			target=tag,
			sig=int(sig),
			force=force,
		)

	def _collect_diagnostics(self) -> list[dr.DiagnosticResult]:
		self.call_from_thread(self._update_busy_message, t("tui.doctor.check_java"))
		results = [dr.check_java(), dr.check_tmux()]
		self.call_from_thread(
			self._update_busy_message,
			t("tui.doctor.check_tmux_sources"),
		)
		results.extend(dr.check_download_sources())
		return results

	def _update_busy_message(self, message: str) -> None:
		if not self._busy:
			return
		self._busy_message = message
		self._sync_visible_screen()

	def _on_create_complete(self, server: ManagedServer) -> None:
		self._set_busy(False)
		self._selected_tag = server.tag
		self._set_status(t("tui.create.complete_status", tag=server.tag))
		self._push_log(
			t(
				"tui.create.complete_log",
				tag=server.tag,
				core_id=server.core_id,
				jar_name=server.jar_name,
				path=server.path,
			),
			tag=server.tag,
		)
		self.refresh_servers()

	def _on_register_complete(self, server: ManagedServer) -> None:
		self._set_busy(False)
		self._selected_tag = server.tag
		self._set_status(t("tui.register.complete_status", tag=server.tag))
		self._push_log(
			t(
				"tui.register.complete_log",
				tag=server.tag,
				core_id=server.core_id,
				jar_name=server.jar_name,
				path=server.path,
			),
			tag=server.tag,
		)
		self.refresh_servers()

	def _on_upgrade_complete(self, server: ManagedServer) -> None:
		self._set_busy(False)
		self._set_status(t("tui.upgrade.complete_status", tag=server.tag))
		self._push_log(
			t(
				"tui.upgrade.complete_log",
				tag=server.tag,
				version=server.core_version or t("common.unknown"),
			),
			tag=server.tag,
		)
		self.refresh_servers()

	def _on_change_core_complete(self, server: ManagedServer) -> None:
		self._set_busy(False)
		self._set_status(
			t("tui.change.complete_status", tag=server.tag, core_id=server.core_id)
		)
		self._push_log(
			t(
				"tui.change.complete_log",
				tag=server.tag,
				core_id=server.core_id,
				version=server.core_version or t("common.unknown"),
			),
			tag=server.tag,
		)
		self.refresh_servers()

	def _on_signal_complete(
		self,
		result: srv.ServerSignalResult,
		label: str,
	) -> None:
		self._set_busy(False)
		self._set_status(
			t("tui.signal.complete_status", tag=result.target.server.tag, label=label)
		)
		self._push_log(
			t(
				"tui.signal.complete_log",
				signal_name=result.signal_name,
				tag=result.target.server.tag,
				server_pid=result.server_pid or t("common.empty"),
			),
			tag=result.target.server.tag,
		)
		self.refresh_servers()

	def _on_doctor_complete(self, results: list[dr.DiagnosticResult]) -> None:
		self._set_busy(False)
		self._set_status(
			t("tui.doctor.complete_status", summary=build_doctor_summary(results))
		)
		for item in results:
			status = t("common.ok") if item.status else t("common.fail")
			self._push_log(
				t(
					"tui.doctor.complete_log",
					status=status,
					name=item.name,
					message=item.message,
				)
			)
		self.refresh_servers()
		self.push_screen(DoctorResultsScreen(results))

	@staticmethod
	def _read_required_field(
		payload: dict[str, str],
		key: str,
		label: str,
	) -> str:
		value = payload.get(key, "").strip()
		if not value:
			raise ValueError(t("tui.field.required", label=label))
		return value

	def _build_attach_command(
		self,
		view: srv.ServerRuntimeView | None,
	) -> tuple[str, ...] | None:
		if view is None or view.status != "running":
			return None
		session_name = view.tmux_session_name or build_tmux_session_name(view.server.tag)
		if not self._session_exists(session_name):
			return None
		return build_tmux_attach_command(session_name)

	def submit_server_command(self, command: str) -> bool:
		if not self._ensure_server_page():
			return False
		view = self._require_selected_view()
		if view is None:
			return False
		if view.status != "running":
			self._set_status(
				t("tui.command.server_not_running", tag=view.server.tag)
			)
			return False
		session_name = view.tmux_session_name or build_tmux_session_name(view.server.tag)
		if not self._session_exists(session_name):
			self._set_status(
				t("tui.command.tmux_missing", session_name=session_name)
			)
			return False
		try:
			send_tmux_command(session_name, command)
		except Exception as exc:
			self._set_status(t("tui.command.failed_status", error=format_error(exc)))
			self._push_log(
				t("tui.command.failed_log", command=command, error=format_error(exc)),
				tag=view.server.tag,
			)
			return False
		self._set_status(t("tui.command.sent_status", tag=view.server.tag, command=command))
		self._push_log(t("tui.command.sent_log", command=command), tag=view.server.tag)
		return True


def run_tui() -> None:
	set_language(UserConfig.load().language)
	attach_command = LumiNESKTuiApp().run()
	if attach_command:
		os.execvp(attach_command[0], attach_command)
