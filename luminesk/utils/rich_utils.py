from __future__ import annotations

from chromakitx import AnsiColor, Color, ColorFormattable, TextStyle
from rich.panel import Panel
from rich.text import Text

from luminesk.core.messages import t

ACCENT_COLOR = AnsiColor.Cyan
SUCCESS_COLOR = AnsiColor.Green
WARNING_COLOR = AnsiColor.Yellow
ERROR_COLOR = AnsiColor.Red
RESET_STYLE = TextStyle.RESET.format()


def style_text(
	text: str,
	*,
	color: ColorFormattable | None = None,
	background: ColorFormattable | None = None,
	bold: bool = False,
	dim: bool = False,
	underline: bool = False,
) -> str:
	if not text:
		return text

	parts: list[str] = []
	if bold:
		parts.append(TextStyle.BOLD.format())
	if dim:
		parts.append(TextStyle.DIM.format())
	if underline:
		parts.append(TextStyle.UNDERLINE.format())
	if color is not None:
		parts.append(str(Color(color)))
	if background is not None:
		parts.append(str(Color(background, is_background=True)))

	if not parts:
		return text

	return "".join(parts) + text + RESET_STYLE


def ansi_text(text: str) -> Text:
	return Text.from_ansi(text)


def accent(text: str, *, bold: bool = False) -> str:
	return style_text(text, color=ACCENT_COLOR, bold=bold)


def success(text: str, *, bold: bool = False) -> str:
	return style_text(text, color=SUCCESS_COLOR, bold=bold)


def warning(text: str, *, bold: bool = False) -> str:
	return style_text(text, color=WARNING_COLOR, bold=bold)


def danger(text: str, *, bold: bool = False) -> str:
	return style_text(text, color=ERROR_COLOR, bold=bold)


def muted(text: str) -> str:
	return style_text(text, dim=True)


def emph(text: str) -> str:
	return style_text(text, bold=True)


def format_kv(
	label: str,
	value: object,
	*,
	value_color: ColorFormattable | None = ACCENT_COLOR,
	dim_value: bool = False,
	bold_value: bool = False,
	label_dim: bool = True,
) -> str:
	label_text = style_text(label, dim=label_dim) if label_dim else label
	value_text = str(value)
	if value_color is not None or dim_value or bold_value:
		value_text = style_text(
			value_text,
			color=value_color,
			dim=dim_value,
			bold=bold_value,
		)
	return f"{label_text}: {value_text}"


def format_server(name: str, tag: str) -> str:
	return f"{accent(name, bold=True)} ({accent(tag)})"

def info_panel(message: str, title: str | None = None) -> Panel:
	panel_title = accent(title or t("panel.info_title"), bold=True)
	return Panel(
		ansi_text(message),
		title=ansi_text(panel_title),
		border_style="cyan",
		expand=False,
	)


def error_panel(message: str, title: str | None = None) -> Panel:
	panel_title = danger(title or t("panel.error_title"), bold=True)
	return Panel(
		ansi_text(message),
		title=ansi_text(panel_title),
		border_style="red",
		expand=False,
	)


def success_panel(message: str, title: str | None = None) -> Panel:
	panel_title = success(title or t("panel.success_title"), bold=True)
	return Panel(
		ansi_text(message),
		title=ansi_text(panel_title),
		border_style="green",
		expand=False,
	)
