from pathlib import Path

from luminesk.utils.logs import read_log_tail


def test_read_log_tail_seeks_near_file_end(tmp_path: Path) -> None:
	log_path = tmp_path / "server.log"
	log_path.write_text("\n".join(f"line-{index}" for index in range(1000)), encoding="utf-8")

	lines = read_log_tail(log_path, limit=3, max_bytes=128)

	assert lines == ["line-997", "line-998", "line-999"]


def test_read_log_tail_truncates_long_lines(tmp_path: Path) -> None:
	log_path = tmp_path / "server.log"
	log_path.write_bytes(b"a" * (20 * 1024))

	lines = read_log_tail(log_path, limit=1)

	assert lines[0].endswith("... [truncated]")
