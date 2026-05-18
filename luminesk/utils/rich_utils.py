from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from rich.panel import Panel
from rich.text import Text

from luminesk.core.messages import t

if TYPE_CHECKING:
	from rich_gradient import ColorType

RGBColor = tuple[int, int, int]


def _load_gradient():
	try:
		from rich_gradient import Gradient
	except ImportError as exc:
		raise RuntimeError(t("rich.gradient.missing")) from exc

	return Gradient


def _to_hex_palette(colors: Sequence[RGBColor]) -> list[ColorType]:
	if not colors:
		raise ValueError(t("rich.gradient.empty"))

	return [f"#{red:02x}{green:02x}{blue:02x}" for red, green, blue in colors]


@dataclass
class AnimatedGradientText:
	text: str
	palette: Sequence[RGBColor] = (
		(255, 187, 0),
		(255, 140, 0),
		(255, 255, 255),
		(255, 140, 0),
		(255, 187, 0),
	)
	speed: float = 0.03
	bold: bool = True
	frame: int = field(default=0, init=False)

	def set_text(self, text: str) -> None:
		self.text = text

	def __rich__(self):
		Gradient = _load_gradient()
		content = Text(self.text, style="bold" if self.bold else "")
		rendered = Gradient(content, colors=_to_hex_palette(self.palette))

		if hasattr(rendered, "phase"):
			rendered.phase = self.frame * self.speed

		self.frame += 1
		return rendered

def info_panel(message: str, title: str | None = None) -> Panel:
	return Panel(
		message,
		title=title or t("panel.info_title"),
		border_style="cyan",
		expand=False
	)


def error_panel(message: str, title: str | None = None) -> Panel:
	return Panel(
		message,
		title=title or t("panel.error_title"),
		border_style="red",
		expand=False
	)


def success_panel(message: str, title: str | None = None) -> Panel:
	return Panel(
		message,
		title=title or t("panel.success_title"),
		border_style="green",
		expand=False
	)
