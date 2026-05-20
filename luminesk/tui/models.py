from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(slots=True, frozen=True)
class FormField:
	name: str
	label: str
	value: str = ""
	placeholder: str = ""


@dataclass(slots=True, frozen=True)
class CreateServerRequest:
	name: str
	tag: str
	directory: Path
	core_id: str
	memory_limit: str


@dataclass(slots=True, frozen=True)
class ActivityEntry:
	timestamp: datetime
	message: str
	tag: str | None = None
