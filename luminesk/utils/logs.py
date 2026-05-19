from __future__ import annotations

import re

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from luminesk.core.config import ManagedServer


CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]")
DEFAULT_TAIL_MAX_BYTES = 512 * 1024
MAX_LOG_LINE_BYTES = 16 * 1024


@dataclass(slots=True, frozen=True)
class LogReadResult:
	lines: list[str]
	position: int


def find_latest_log_path(server: ManagedServer) -> Path | None:
	log_directory = server.path / ".luminesk" / "logs"
	if not log_directory.is_dir():
		return None

	latest_path: Path | None = None
	latest_mtime = -1.0

	for path in log_directory.iterdir():
		if not path.is_file() or path.suffix != ".log":
			continue

		try:
			mtime = path.stat().st_mtime
		except OSError:
			continue

		if mtime > latest_mtime:
			latest_path = path
			latest_mtime = mtime

	return latest_path


def decode_log_bytes(payload: bytes) -> str:
	return payload.decode("utf-8", errors="replace")


def normalize_log_line(line: str) -> str:
	line = CONTROL_RE.sub("", line)
	return line.rstrip("\r\n")


def normalize_log_line_raw(line: str) -> str:
	return line.rstrip("\r\n")


def read_log_tail(
	log_path: Path,
	limit: int = 200,
	*,
	normalize: Callable[[str], str] | None = None,
	max_bytes: int = DEFAULT_TAIL_MAX_BYTES,
) -> list[str]:
	if limit <= 0 or max_bytes <= 0:
		return []

	normalizer = normalize or normalize_log_line
	lines: deque[str] = deque(maxlen=limit)
	try:
		with log_path.open("rb") as file:
			file.seek(0, 2)
			file_size = file.tell()
			if file_size > max_bytes:
				file.seek(-max_bytes, 2)
				file.readline()
			else:
				file.seek(0)

			for raw_line in file:
				lines.append(_normalize_raw_log_line(raw_line, normalizer))
	except OSError as exc:
		return [f"Failed to read log: {exc}"]

	return list(lines)


def read_log_increment(
	log_path: Path,
	position: int,
	*,
	normalize: Callable[[str], str] | None = None,
	max_bytes: int = DEFAULT_TAIL_MAX_BYTES,
) -> LogReadResult:
	if max_bytes <= 0:
		return LogReadResult(lines=[], position=position)

	normalizer = normalize or normalize_log_line
	start_position = max(0, position)

	try:
		with log_path.open("rb") as file:
			file.seek(0, 2)
			file_size = file.tell()
			if start_position > file_size:
				start_position = 0

			if file_size - start_position > max_bytes:
				file.seek(-max_bytes, 2)
				file.readline()
			else:
				file.seek(start_position)

			lines: list[str] = []
			while raw_line := file.readline():
				lines.append(_normalize_raw_log_line(raw_line, normalizer))
			return LogReadResult(lines=lines, position=file.tell())
	except OSError as exc:
		return LogReadResult(
			lines=[f"Failed to read log: {exc}"],
			position=position,
		)


def _normalize_raw_log_line(
	raw_line: bytes,
	normalizer: Callable[[str], str],
) -> str:
	if len(raw_line) > MAX_LOG_LINE_BYTES:
		raw_line = raw_line[:MAX_LOG_LINE_BYTES] + b"... [truncated]"
	return normalizer(decode_log_bytes(raw_line))
