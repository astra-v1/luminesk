from __future__ import annotations

from typing import Final


DEFAULT_LANGUAGE = "en"

MESSAGE_CATALOGS: Final[dict[str, dict[str, str]]] = {
	"en": {
		"common.empty": "-",
		"common.ok": "OK",
		"common.fail": "FAIL",
		"common.running": "running",
		"common.stopped": "stopped",
		"common.loop": "loop",
		"common.docker_container": "docker: {container_name}",
		"common.unknown": "unknown",
		"common.default_server_name": "{core_name} Server",
		"common.error_prefix": "Error: {error}",
		"panel.info_title": "Info",
		"panel.error_title": "Error",
		"panel.success_title": "Success",
		"label.component": "Component",
		"label.status": "Status",
		"label.description": "Description",
		"label.name": "Name",
		"label.tag": "Tag",
		"label.core": "Core",
		"label.core_version": "Core Version",
		"label.jar": "JAR",
		"label.path": "Path",
		"label.server": "Server",
		"label.action": "Action",
		"label.signal": "Signal",
		"label.pid": "PID",
		"label.server_pid": "Server PID",
		"label.memory_limit": "Memory Limit",
		"label.uptime": "Uptime",
		"label.last_start": "Last Start",
		"label.last_stop": "Last Stop",
		"label.version": "Version",
		"rich.gradient.missing": "rich-gradient is not installed. Install it with `uv add rich-gradient`.",
		"rich.gradient.empty": "Gradient must contain at least one color.",
		"config.validation.tag_empty": "Server tag must not be empty.",
		"config.validation.text_empty": "Server text fields must not be empty.",
		"config.server.not_found": "Server with tag '{tag}' was not found.",
		"downloads.unsupported_provider_type": "Unsupported core provider type '{type_name}' for '{core_id}'.",
		"maven.fetch_xml_http": "Failed to fetch XML from {url}: HTTP {status_code}",
		"maven.fetch_xml_error": "Failed to fetch XML from {url}: {error}",
		"maven.invalid_xml": "Invalid XML at {url}",
		"maven.xml_too_large": "Maven metadata at {url} is larger than the safety limit.",
		"maven.versioning_missing": "Maven metadata is missing the versioning section.",
		"maven.latest_version_missing": "Failed to determine the latest core version.",
		"maven.snapshot_versioning_missing": "Snapshot metadata is missing the versioning section.",
		"maven.snapshot_classifier_missing": "Snapshot metadata does not contain a JAR with classifier '{classifier}'.",
		"maven.snapshot_version_missing": "Failed to determine the snapshot artifact version.",
		"maven.group_id_missing": "Core '{core_id}' is missing group_id.",
		"maven.artifact_id_missing": "Core '{core_id}' is missing artifact_id.",
		"maven.url_missing": "Core '{core_id}' is missing url.",
		"jenkins.artifacts_missing": "Jenkins did not return artifacts for core '{core_id}'.",
		"jenkins.fetch_json_http": "Failed to fetch JSON from {url}: HTTP {status_code}",
		"jenkins.fetch_json_error": "Failed to fetch JSON from {url}: {error}",
		"jenkins.invalid_json": "Invalid JSON at {url}",
		"jenkins.no_jar_artifacts": "No JAR artifacts were found in the Jenkins build.",
		"jenkins.classifier_missing": "No JAR with classifier '{classifier}' was found in the Jenkins build.",
		"jenkins.primary_jar_missing": "No primary JAR artifact was found in the Jenkins build.",
		"jenkins.url_missing": "Core '{core_id}' is missing url.",
		"github.assets_missing": "The GitHub release does not contain assets for core '{core_id}'.",
		"github.fetch_release_http": "Failed to fetch GitHub release from {url}: HTTP {status_code}",
		"github.fetch_release_error": "Failed to fetch GitHub release from {url}: {error}",
		"github.invalid_json": "Invalid JSON at {url}",
		"github.asset_missing": "No GitHub release asset matched pattern '{pattern}'.",
		"github.asset_ambiguous": "Pattern '{pattern}' is ambiguous: found {count} matches.",
		"github.invalid_url": "Invalid GitHub URL: '{url}'.",
		"docker.not_found": "Docker was not found in PATH. Run `nesk doctor`.",
		"docker.stop_failed": "Docker failed to stop the container.",
		"docker.kill_failed": "Docker failed to kill the container.",
		"docker.send_command_failed": "Docker failed to send the console command.",
		"docker.send_command_timeout": "Timed out while sending the console command. The server may be restarting.",
		"docker.invalid_memory_limit": "Invalid Docker memory limit '{memory_limit}'. Use values like 512m, 1g, or bytes.",
		"launcher.docker_container_exists": "Docker container '{container_name}' is already running.",
		"launcher.docker_run_failed": "Docker failed to start the container (exit {exit_code}): {error}",
		"doctor.docker_missing": "Docker was not found. Docker-backed server runtime requires Docker.",
		"doctor.docker_detected": "Docker detected",
		"doctor.component.docker": "Docker",
		"doctor.component.java_runtime": "Java Runtime",
		"doctor.component.java_version": "Java Version",
		"doctor.java_missing": "Java was not found. Install Java 21+.",
		"doctor.unknown_version": "Unknown version",
		"doctor.java_too_old": "Version is too old: {version_line}. Java 21+ is required.",
		"doctor.source_ok": "200 OK",
		"doctor.source_name": "{core_name} Source",
		"manager.directory_missing": "Directory '{directory}' does not exist.",
		"manager.path_not_server_directory": "Path '{directory}' is not a server directory.",
		"manager.path_exists_not_directory": "Path '{directory}' already exists and is not a directory. Use --force to overwrite it.",
		"manager.directory_not_empty": "Directory '{directory}' is not empty. Use --force to overwrite it.",
		"manager.server_config_header": "# This file will be generated automatically when the server starts for the first time.\n",
		"manager.download_core_http": "Failed to download core '{core_name}': HTTP {status_code}",
		"manager.download_core_error": "Failed to download core '{core_name}': {error}",
		"manager.download_progress": "Downloading {core_name}",
		"manager.server_not_found_by_tag": "Server with tag '{tag}' was not found.",
		"manager.server_not_found_for_directory": "No server was found for directory '{directory}'. Pass --tag.",
		"manager.pid_not_owned": "PID {pid} does not belong to any LumiNESK server.",
		"manager.server_not_running": "Server '{tag}' is not running.",
		"manager.loop_controller_not_found": "Could not determine the loop controller process for server '{tag}'.",
		"manager.loop_waiting_force": "Server '{tag}' is in loop mode and currently waiting to restart. Use --force to stop it permanently.",
		"manager.manual_server_upgrade": "Server '{tag}' has no managed core version metadata. Use `change_core` instead of `upgrade_core`.",
		"manager.core_not_in_registry": "Core '{core_id}' was not found in the LumiNESK registry.",
		"manager.server_already_running": "Server '{tag}' is already running (PID {pid}).",
		"manager.java_not_in_path": "Java was not found in PATH. Run `nesk doctor`.",
		"manager.jar_not_found": "Core JAR was not found: '{jar_path}'. Recreate the server or download the core again.",
		"manager.launching_server": "[cyan]Starting[/] server [bold]{name}[/bold] ([cyan]{tag}[/cyan], PID {pid})",
		"manager.loop_restart": "[yellow]Server exited with code {exit_code}. Restarting in {delay} seconds.[/yellow]",
		"manager.tag_in_use": "Tag '{tag}' is already in use.",
		"manager.directory_already_registered": "Directory '{directory}' is already registered as server '{tag}'.",
		"manager.jar_must_be_inside_directory": "JAR '{jar_path}' must be inside server directory '{directory}'.",
		"manager.core_file_missing": "Core file '{jar_path}' does not exist.",
		"manager.path_not_file": "Path '{path}' is not a file.",
		"manager.file_not_jar": "File '{file_name}' is not a JAR archive.",
		"manager.server_must_be_stopped_for_core_change": "Server '{tag}' must be stopped before changing or upgrading the core.",
		"manager.server_must_be_stopped_for_delete": "Server '{tag}' must be stopped before it can be deleted from LumiNESK.",
		"manager.using_cached_core": "[cyan]Using cached core[/] [bold]{core_name}[/bold] [dim]({version})[/dim]",
		"manager.pid_undefined": "Process PID is not defined.",
		"manager.process_missing": "Process with PID {pid} no longer exists.",
		"manager.signal_permission_denied": "Permission denied while sending a signal to process PID {pid}.",
		"cli.version.banner": "LumiNESK v{version} by Taskov1ch. License: GPL-3.0.",
		"cli.option.version": "Show the LumiNESK version.",
		"cli.command.doctor": "Run system diagnostics for Nukkit-compatible cores.",
		"cli.doctor.checking_requirements": "Checking system requirements...",
		"cli.doctor.checking_java": "Checking Java...",
		"cli.doctor.checking_docker": "Checking Docker...",
		"cli.doctor.checking_sources": "Checking download sources...",
		"cli.doctor.critical_error": "[bold]Critical error![/]\nServer operations cannot continue.",
		"cli.doctor.success": "Diagnostics finished. No critical issues were found.",
		"cli.command.cores": "List available cores.",
		"cli.cores.title": "Available Cores",
		"cli.cores.tip": "\n[bold]Tip:[/] use [cyan]nesk doctor[/cyan] to verify repository availability.",
		"cli.command.create": "Create a new server.",
		"cli.create.option.name": "Server name (not MOTD).",
		"cli.create.option.directory": "Path to the directory where the server will be created.",
		"cli.create.option.core": "Core used to create the server.",
		"cli.create.option.tag": "LumiNESK server tag.",
		"cli.create.option.force": "Force overwrite the existing directory.",
		"cli.create.option.memory": "Docker memory limit for background launch.",
		"cli.create.prompt.core": "Enter the core to use for server creation",
		"cli.create.prompt.name": "Enter the server name",
		"cli.create.prompt.tag": "Enter the server tag for quick access with `nesk start <tag>`",
		"cli.create.prompt.directory": "Enter the path to the directory where the server will be created",
		"cli.create.core_not_found": "Core [red]{core_id}[/red] was not found in the registry. Check available cores with `nesk cores`.",
		"cli.create.success_title": "[bold]Server created[/]",
		"cli.command.start": "Start a server.",
		"cli.start.option.loop": "Restart the server automatically when it stops.",
		"cli.start.option.tag": "Server tag.",
		"cli.command.upgrade_core": "Upgrade the server core to the latest available version.",
		"cli.upgrade.option.tag": "Server tag.",
		"cli.upgrade.success_title": "[bold]Core upgraded[/]",
		"cli.command.change_core": "Change the server core.",
		"cli.change.option.tag": "Server tag.",
		"cli.change.option.core": "New server core.",
		"cli.change.prompt.core": "Enter the new server core",
		"cli.change.success_title": "[bold]Core changed[/]",
		"cli.command.stop": "Gracefully stop a server by tag or PID.",
		"cli.stop.argument.target": "Server tag or server process PID.",
		"cli.stop.option.force": "Stop loop mode together with the server.",
		"cli.command.kill": "Force-kill a server by tag or PID.",
		"cli.kill.argument.target": "Server tag or server process PID.",
		"cli.kill.option.force": "Stop loop mode together with the server.",
		"cli.command.delete": "Delete a stopped server from LumiNESK without touching server files.",
		"cli.delete.argument.target": "LumiNESK server tag.",
		"cli.delete.success_title": "[bold]Server deleted from LumiNESK[/]",
		"cli.command.list": "List servers and their status.",
		"cli.list.option.tag": "Filter by tag.",
		"cli.list.option.status": "Filter by status: running or stopped.",
		"cli.list.option.core": "Filter by core.",
		"cli.list.no_servers": "No servers yet. Use `nesk create`.",
		"cli.list.no_matches": "No servers matched the selected filters.",
		"cli.list.title": "LumiNESK Servers",
		"cli.version.only_version": "Show only the numeric version.",
		"cli.control.loop_warning": "Server [cyan]{tag}[/cyan] is running in loop mode. It will restart automatically. Use `--force` if you need to stop it permanently.",
		"cli.status.invalid": "Allowed values for --status: running, stopped.",
	},
}

_current_language = DEFAULT_LANGUAGE


def normalize_language(language: str | None) -> str:
	if language is None:
		return DEFAULT_LANGUAGE

	normalized_language = language.strip().lower()
	if normalized_language in MESSAGE_CATALOGS:
		return normalized_language

	return DEFAULT_LANGUAGE


def set_language(language: str | None) -> str:
	global _current_language

	_current_language = normalize_language(language)
	return _current_language


def t(key: str, /, **kwargs: object) -> str:
	catalog = MESSAGE_CATALOGS.get(_current_language, MESSAGE_CATALOGS[DEFAULT_LANGUAGE])
	template = catalog.get(key) or MESSAGE_CATALOGS[DEFAULT_LANGUAGE].get(key)

	if template is None:
		raise KeyError(f"Unknown message key: {key}")

	if not kwargs:
		return template

	return template.format(**kwargs)
