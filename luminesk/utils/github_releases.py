from __future__ import annotations

import fnmatch

from typing import Any

import httpx

from luminesk.core.messages import t
from luminesk.core.registry import GitHubRelease
from luminesk.utils.download_models import CoreDownloadInfo
from luminesk.utils.errors import format_error
from luminesk.utils.http import get_json_object_with_retries


def get_release_api_url(core: GitHubRelease) -> str:
	owner, repo = _parse_github_repo_url(core.url)
	return f"https://api.github.com/repos/{owner}/{repo}/releases/latest"


def get_latest_download_url(core: GitHubRelease, client: httpx.Client | None = None) -> str:
	return get_latest_download_info(core, client=client).url


def get_latest_download_info(
	core: GitHubRelease,
	client: httpx.Client | None = None,
) -> CoreDownloadInfo:
	if client is not None:
		return _get_latest_download_info(client, core)

	with httpx.Client(timeout=10.0, follow_redirects=True) as owned_client:
		return _get_latest_download_info(owned_client, core)


def _get_latest_download_info(
	client: httpx.Client,
	core: GitHubRelease,
) -> CoreDownloadInfo:
	release = _fetch_json(client, get_release_api_url(core))
	assets = release.get("assets")

	if not isinstance(assets, list) or not assets:
		raise ValueError(t("github.assets_missing", core_id=core.id))

	asset_url = _select_asset_download_url(assets, core.release_file)
	return CoreDownloadInfo(
		url=asset_url,
		version=_get_release_version(release),
	)


def _fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
	headers = {
		"Accept": "application/vnd.github+json",
		"User-Agent": "luminesk",
	}
	try:
		return get_json_object_with_retries(client, url, headers=headers)
	except httpx.HTTPStatusError as exc:
		raise ValueError(
			t("github.fetch_release_http", url=url, status_code=exc.response.status_code)
		) from exc
	except httpx.RequestError as exc:
		raise ValueError(t("github.fetch_release_error", url=url, error=format_error(exc))) from exc
	except ValueError as exc:
		raise ValueError(t("github.invalid_json", url=url)) from exc


def _select_asset_download_url(assets: list[Any], pattern: str) -> str:
	matches: list[str] = []

	for asset in assets:
		if not isinstance(asset, dict):
			continue

		name = asset.get("name")
		download_url = asset.get("browser_download_url")

		if not isinstance(name, str) or not isinstance(download_url, str):
			continue

		if fnmatch.fnmatch(name, pattern):
			matches.append(download_url)

	if not matches:
		raise ValueError(t("github.asset_missing", pattern=pattern))

	if len(matches) > 1:
		raise ValueError(t("github.asset_ambiguous", pattern=pattern, count=len(matches)))

	return matches[0]


def _get_release_version(release: dict[str, Any]) -> str:
	for key in ("tag_name", "name"):
		value = release.get(key)
		if isinstance(value, str) and value.strip():
			return value.strip()

	return "latest"


def _parse_github_repo_url(url: str) -> tuple[str, str]:
	normalized_url = url.strip().rstrip("/")
	prefix = "https://github.com/"
	if not normalized_url.startswith(prefix):
		raise ValueError(t("github.invalid_url", url=url))

	path = normalized_url.removeprefix(prefix)
	parts = [part for part in path.split("/") if part]
	if len(parts) < 2:
		raise ValueError(t("github.invalid_url", url=url))

	return parts[0], parts[1]
