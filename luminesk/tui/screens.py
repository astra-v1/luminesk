from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static

from luminesk.core import doctor as dr
from luminesk.core import manager as srv
from luminesk.core.messages import t
from luminesk.utils.tmux import build_tmux_session_name

from .formatting import (
	build_doctor_summary,
	build_selection_text,
	build_server_snapshot_text,
	format_timestamp,
	render_runtime_status,
)
from .models import FormField


LIVE_CONSOLE_MAX_LINES = 500


class InputFormScreen(ModalScreen[dict[str, str] | None]):
	BINDINGS = [
		Binding("escape", "cancel", t("common.close")),
		Binding("ctrl+s", "submit", t("common.save"), show=False),
	]

	def __init__(
		self,
		title: str,
		fields: list[FormField],
		description: str = "",
		submit_label: str = t("common.apply"),
	) -> None:
		super().__init__()
		self._title = title
		self._fields = fields
		self._description = description
		self._submit_label = submit_label

	def compose(self) -> ComposeResult:
		with Container(id="dialog"):
			yield Static(self._title, id="dialog-title")
			if self._description:
				yield Static(self._description, id="dialog-description")

			for field in self._fields:
				yield Static(field.label, classes="dialog-label")
				yield Input(
					value=field.value,
					placeholder=field.placeholder,
					id=f"field-{field.name}",
				)

			with Horizontal(classes="dialog-buttons"):
				yield Button(self._submit_label, id="submit", variant="primary")
				yield Button(t("common.cancel"), id="cancel")

	def on_mount(self) -> None:
		if self._fields:
			self.query_one(f"#field-{self._fields[0].name}", Input).focus()

	def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "submit":
			self.action_submit()
			return
		if event.button.id == "cancel":
			self.action_cancel()

	def action_submit(self) -> None:
		self.dismiss(self._collect_values())

	def action_cancel(self) -> None:
		self.dismiss(None)

	def _collect_values(self) -> dict[str, str]:
		return {
			field.name: self.query_one(f"#field-{field.name}", Input).value.strip()
			for field in self._fields
		}


class DoctorResultsScreen(ModalScreen[None]):
	BINDINGS = [
		Binding("escape", "close", t("common.close")),
		Binding("enter", "close", t("common.close"), show=False),
	]

	def __init__(self, results: list[dr.DiagnosticResult]) -> None:
		super().__init__()
		self._results = results

	def compose(self) -> ComposeResult:
		with Container(id="doctor-dialog"):
			yield Static(t("tui.doctor.report_title"), id="doctor-title")
			yield Static(build_doctor_summary(self._results), id="doctor-summary")
			yield DataTable(id="doctor-table")
			with Horizontal(id="doctor-buttons"):
				yield Button(t("common.close"), id="close", variant="primary")

	def on_mount(self) -> None:
		table = self.query_one("#doctor-table", DataTable)
		table.cursor_type = "row"
		table.add_columns(t("label.component"), t("label.status"), t("label.description"))
		for item in self._results:
			table.add_row(
				item.name,
				"OK" if item.status else "FAIL",
				item.message,
			)
		self.query_one("#close", Button).focus()

	def on_button_pressed(self, event: Button.Pressed) -> None:
		if event.button.id == "close":
			self.action_close()

	def action_close(self) -> None:
		self.dismiss(None)


class HomeScreen(Screen):
	def __init__(self) -> None:
		super().__init__()
		self._table_signature: tuple[tuple[str, ...], ...] = ()
		self._suppress_table_events = False

	BINDINGS = [
		Binding("enter", "open_selected_server", t("common.open")),
		Binding("r", "refresh_servers", t("common.refresh")),
		Binding("d", "run_doctor", t("common.doctor")),
		Binding("c", "show_create_server", t("common.create")),
		Binding("g", "show_register_server", t("common.register")),
		Binding("q", "quit", t("common.quit")),
	]

	def compose(self) -> ComposeResult:
		yield Header(show_clock=True)
		with Vertical(id="home-shell"):
			yield Static("", id="status-banner")
			yield Static("", id="progress-banner")
			with Horizontal(id="home-content"):
				with Vertical(id="home-main"):
					with Container(classes="card fill-card"):
						yield Static(t("label.servers"), classes="card-title")
						yield DataTable(id="servers-table")
				with Vertical(id="home-side"):
					with Container(classes="card", id="selection-card"):
						yield Static(t("label.current_selection"), classes="card-title")
						yield Static(id="selection-summary", classes="copy-block")
					with Container(classes="card", id="actions-card"):
						with Vertical(id="action-stack"):
							yield Button(t("tui.home.open_server"), id="open-server", variant="primary")
							yield Button(t("tui.home.create_server"), id="create")
							yield Button(t("tui.home.register_existing"), id="register")
							yield Button(t("common.doctor"), id="doctor")
							yield Button(t("common.refresh"), id="refresh")
			with Container(classes="card", id="home-activity-card"):
				yield Static(t("label.recent_activity"), classes="card-title")
				with VerticalScroll(id="home-activity-pane"):
					yield Static(id="home-activity-log", classes="copy-block")
		yield Footer()

	def on_mount(self) -> None:
		table = self.query_one("#servers-table", DataTable)
		table.cursor_type = "row"
		table.zebra_stripes = True
		table.add_columns(
			t("label.tag"),
			t("label.name"),
			t("label.core"),
			t("label.status"),
			t("label.pid"),
			t("label.uptime"),
			t("tui.home.servers_table.last_start"),
		)
		table.focus()
		self.app.call_after_refresh(self.app._sync_visible_screen)

	def on_button_pressed(self, event: Button.Pressed) -> None:
		action_map = {
			"open-server": self.action_open_selected_server,
			"create": self.action_show_create_server,
			"register": self.action_show_register_server,
			"doctor": self.action_run_doctor,
			"refresh": self.action_refresh_servers,
		}
		handler = action_map.get(event.button.id or "")
		if handler is not None:
			handler()

	def on_data_table_row_highlighted(self, event) -> None:
		if self.app.busy or self._suppress_table_events:
			return
		self.app.select_row(getattr(event, "cursor_row", getattr(event, "row_index", -1)))

	def on_data_table_row_selected(self, event) -> None:
		if self.app.busy or self._suppress_table_events:
			return
		self.app.select_row(getattr(event, "cursor_row", getattr(event, "row_index", -1)))
		self.app.open_selected_server()

	def action_open_selected_server(self) -> None:
		self.app.open_selected_server()

	def action_refresh_servers(self) -> None:
		if self.app.busy:
			self.app._set_status(t("common.wait_current_operation"))
			return
		self.app.refresh_servers()

	def action_run_doctor(self) -> None:
		self.app.run_doctor()

	def action_show_create_server(self) -> None:
		self.app.show_create_server()

	def action_show_register_server(self) -> None:
		self.app.show_register_server()

	def action_quit(self) -> None:
		self.app.request_quit()

	def sync(
		self,
		views: list[srv.ServerRuntimeView],
		selected_tag: str | None,
		status_message: str,
		progress_message: str,
		busy: bool,
		activity: Text,
	) -> None:
		table = self.query_one("#servers-table", DataTable)
		selected_index = 0
		rows: list[tuple[str, ...]] = []
		for index, view in enumerate(views):
			if selected_tag == view.server.tag:
				selected_index = index
			rows.append(
				(
					view.server.tag,
					view.server.name,
					view.server.core_id,
					render_runtime_status(view),
					str(view.pid or "-"),
					srv.format_timedelta(view.uptime),
					format_timestamp(view.last_started_at),
				)
			)

		rows_signature = tuple(rows)
		if rows_signature != self._table_signature:
			self._suppress_table_events = True
			table.clear()
			for row in rows_signature:
				table.add_row(*row)
			self._table_signature = rows_signature
			self._suppress_table_events = False

		if views:
			selected_index = min(selected_index, len(views) - 1)
			if table.cursor_row != selected_index:
				self._suppress_table_events = True
				table.move_cursor(row=selected_index, column=0)
				self._suppress_table_events = False

		selected_view = next((view for view in views if view.server.tag == selected_tag), None)
		self.query_one("#selection-summary", Static).update(build_selection_text(selected_view))
		self.query_one("#status-banner", Static).update(Text(status_message))
		self.query_one("#progress-banner", Static).update(Text(progress_message))
		self.query_one("#home-activity-log", Static).update(activity)

		self.query_one("#open-server", Button).disabled = busy or selected_view is None
		self.query_one("#create", Button).disabled = busy
		self.query_one("#register", Button).disabled = busy
		self.query_one("#doctor", Button).disabled = busy
		self.query_one("#refresh", Button).disabled = busy
		table.disabled = busy


class ServerScreen(Screen):
	BINDINGS = [
		Binding("escape", "go_back", t("common.back")),
		Binding("r", "refresh_servers", t("common.refresh")),
		Binding("s", "start_server", t("common.start_stop")),
		Binding("l", "start_server_loop", t("common.loop")),
		Binding("x", "stop_server", t("common.stop")),
		Binding("k", "kill_server", t("common.kill")),
		Binding("u", "upgrade_core", t("common.upgrade")),
		Binding("m", "show_change_core", t("common.change")),
		Binding("a", "attach_to_session", t("common.attach")),
		Binding("q", "quit", t("common.quit")),
	]

	def __init__(self, server_tag: str) -> None:
		super().__init__()
		self.server_tag = server_tag

	def compose(self) -> ComposeResult:
		yield Header(show_clock=True)
		with Vertical(id="server-shell"):
			yield Static("", id="status-banner")
			yield Static("", id="progress-banner")
			with Horizontal(id="server-content"):
				with Container(id="server-info-column"):
					with Container(classes="card fill-card", id="server-details-card"):
						yield Static(t("label.server_snapshot"), classes="card-title")
						yield Static(id="server-details", classes="copy-block")
				with Container(id="server-console-column"):
					with Container(classes="card fill-card", id="server-console-card"):
						yield Static(t("label.live_console"), classes="card-title")
						yield Static("", id="server-log-meta", classes="section-copy")
						yield RichLog(
							id="server-console",
							auto_scroll=True,
							highlight=True,
							markup=False,
							max_lines=LIVE_CONSOLE_MAX_LINES,
						)
						yield Input(
							placeholder=t("tui.server.command_placeholder"),
							id="server-command-input",
						)
		yield Footer()

	def on_mount(self) -> None:
		if self.app.console_refresh_interval > 0:
			self.set_interval(self.app.console_refresh_interval, self.app._poll_live_console)
		self.app.call_after_refresh(self.app._sync_visible_screen)

	def action_go_back(self) -> None:
		self.app.go_home()

	def action_refresh_servers(self) -> None:
		if self.app.busy:
			self.app._set_status(t("common.wait_current_operation"))
			return
		self.app.refresh_servers()

	def action_start_server(self) -> None:
		self.app.start_server()

	def action_start_server_loop(self) -> None:
		self.app.start_server_loop()

	def action_stop_server(self) -> None:
		self.app.stop_server()

	def action_kill_server(self) -> None:
		self.app.kill_server()

	def action_upgrade_core(self) -> None:
		self.app.upgrade_core()

	def action_show_change_core(self) -> None:
		self.app.show_change_core()

	def action_attach_to_session(self) -> None:
		self.app.attach_to_session()

	def action_quit(self) -> None:
		self.app.request_quit()

	def on_input_submitted(self, event: Input.Submitted) -> None:
		if event.input.id != "server-command-input":
			return
		command = event.value.strip()
		if not command:
			return
		if self.app.submit_server_command(command):
			event.input.value = ""

	def sync(
		self,
		view: srv.ServerRuntimeView | None,
		status_message: str,
		progress_message: str,
		busy: bool,
		log_path: Path | None,
	) -> None:
		self.query_one("#status-banner", Static).update(Text(status_message))
		self.query_one("#progress-banner", Static).update(Text(progress_message))
		self.query_one("#server-details", Static).update(build_server_snapshot_text(view))
		self.query_one("#server-log-meta", Static).update(
			t("tui.server.log_meta", log_path=log_path)
			if log_path is not None
			else t("tui.server.log_meta_missing")
		)
		command_input = self.query_one("#server-command-input", Input)
		session_name = None if view is None else (view.tmux_session_name or build_tmux_session_name(view.server.tag))
		command_input.disabled = (
			busy
			or view is None
			or view.status != "running"
			or (session_name is not None and not self.app._session_exists(session_name))
		)

		if view is None:
			command_input.placeholder = t("tui.server.unavailable")
			return

		if busy:
			command_input.placeholder = t("tui.server.commands_locked")
			return

		if view.status != "running":
			command_input.placeholder = t("tui.server.stopped_placeholder")
			return

		command_input.placeholder = t("tui.server.command_placeholder")

		if session_name is not None and not self.app._session_exists(session_name):
			command_input.placeholder = t("tui.server.tmux_missing")
			return
