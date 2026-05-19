from luminesk.core import doctor


class FakeCore:
	def __init__(self, core_id: str, name: str, url: str) -> None:
		self.id = core_id
		self.name = name
		self._url = url

	def get_availability_check_url(self) -> str:
		if self._url == "raise":
			raise RuntimeError("source unavailable")
		return self._url


def test_check_download_sources_preserves_registry_order(monkeypatch) -> None:
	cores = [
		FakeCore("first", "First", "https://example.com/first"),
		FakeCore("second", "Second", "https://example.com/second"),
	]

	def fake_check_source(client, core_name: str, check_url: str) -> doctor.DiagnosticResult:
		return doctor.DiagnosticResult(name=core_name, status=True, message=check_url)

	monkeypatch.setattr(doctor.registry, "get_all", lambda: cores)
	monkeypatch.setattr(doctor, "_check_source", fake_check_source)

	results = doctor.check_download_sources()

	assert [result.name for result in results] == ["First", "Second"]
	assert [result.message for result in results] == [
		"https://example.com/first",
		"https://example.com/second",
	]


def test_check_download_sources_wraps_source_errors(monkeypatch) -> None:
	monkeypatch.setattr(
		doctor.registry,
		"get_all",
		lambda: [FakeCore("broken", "Broken", "raise")],
	)

	result = doctor.check_download_sources()[0]

	assert result.name == "Broken Source"
	assert not result.status
	assert "source unavailable" in result.message
