from __future__ import annotations

import re

from collections import deque
from pathlib import Path
from typing import Callable

from luminesk.core.config import ManagedServer


CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1a\x1c-\x1f\x7f]")
DEFAULT_TAIL_MAX_BYTES = 512 * 1024
MAX_LOG_LINE_BYTES = 16 * 1024


def find_latest_log_path(server: ManagedServer) -> Path | None:
	log_directory = server.path / ".luminesk" / "logs"
	if not log_directory.is_dir():
		return None

	log_files = sorted(
		(
			path
			for path in log_directory.iterdir()
			if path.is_file() and path.suffix == ".log"
		),
		key=lambda path: path.stat().st_mtime,
		reverse=True,
	)
	return log_files[0] if log_files else None


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
				if len(raw_line) > MAX_LOG_LINE_BYTES:
					raw_line = raw_line[:MAX_LOG_LINE_BYTES] + b"... [truncated]"
				lines.append(normalizer(decode_log_bytes(raw_line)))
	except OSError as exc:
		return [f"Failed to read log: {exc}"]

	return list(lines)
