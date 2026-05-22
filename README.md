<div align="center">

<img src="https://raw.githubusercontent.com/astra-v1/LumiNESK/main/assets/luminesk.png" width="420" alt="LumiNESK logo">

# LumiNESK
### Nukkit Engine Servers Kit

CLI manager for Minecraft servers based on **Nukkit-family** engines

[![PyPI - Version](https://img.shields.io/pypi/v/luminesk?style=for-the-badge)](https://pypi.org/project/luminesk/) [![GitHub Release](https://img.shields.io/github/v/release/astra-v1/LumiNESK?style=for-the-badge)](https://github.com/astra-v1/LumiNESK/releases/latest) [![Tests](https://img.shields.io/github/actions/workflow/status/astra-v1/LumiNESK/ci.yml?style=for-the-badge)](https://github.com/astra-v1/LumiNESK/actions)

</div>

---

# About the Project

**LumiNESK** is a tool for managing **[Minecraft Bedrock Edition](https://minecraft.wiki/w/Bedrock_Edition)** servers running on **[Nukkit](https://github.com/CloudburstMC/Nukkit)**-based engines.

The project is designed for:

- local server development
- small production deployments
- convenient management of multiple servers

LumiNESK is maintained as a **CLI** (command-line interface) tool.

Supported engines: [Nukkit](https://github.com/CloudburstMC/Nukkit), [PowerNukkitX](https://github.com/PowerNukkitX/PowerNukkitX), [Nukkit-MOT](https://github.com/MemoriesOfTime/Nukkit-MOT), [Lumi](https://github.com/koshakminedev/lumi).

---

# Features

- create servers
- start servers in **normal** and **loop mode**
- stop and force terminate servers
- manage server engines
- environment and provider diagnostics
- manage multiple servers
- update server engines

---

# Requirements

| Component | Version                        | Required |
|----------|--------------------------------|----------|
| Python   | **3.13+** (3.14 recommended)   | Not required if you don't install via pip |
| Java     | 21 by default                  | Provided by the selected Docker runtime image |
| Docker   | latest                         | Required for running servers |

---

# Installation

## Via [PyPI](https://pypi.org/project/luminesk/) (recommended)

```bash
pip install luminesk
```

```bash
uv pip install luminesk
```

```bash
pipx install luminesk
```

---

## Download prebuilt binaries

Prebuilt binaries are available in the [releases](https://github.com/astra-v1/LumiNESK/releases) section.
For Windows: [luminesk-windows-amd64.exe](https://github.com/astra-v1/LumiNESK/releases/latest/download/luminesk-windows-amd64.exe)
For Linux: [luminesk-linux-amd64](https://github.com/astra-v1/LumiNESK/releases/latest/download/luminesk-linux-amd64)
For macOS: [luminesk-darwin-arm64](https://github.com/astra-v1/LumiNESK/releases/latest/download/luminesk-darwin-arm64)

#### Example (Linux)

```bash
chmod +x luminesk-linux-amd64
luminesk-linux-amd64 --help
```

#### Example (Windows)

```bash
luminesk-windows-amd64 --help
```

#### Example (macOS)

```bash
chmod +x luminesk-darwin-arm64
luminesk-darwin-arm64 --help
```

---

# Installation from source

```bash
git clone https://github.com/astra-v1/LumiNESK
cd LumiNESK

uv venv
uv sync

uv run nesk --help # short alias for luminesk
```

## Building a binary

Uses **[Nuitka](https://nuitka.net/)**.

Linux/macOS:

```bash
nuitka --onefile --output-filename=luminesk \
  luminesk/__main__.py
```

Windows:

```bash
nuitka --onefile --output-filename=luminesk.exe ^
  luminesk/__main__.py
```

---

# Quick Start

Show help:

```bash
nesk --help
```

Check environment and sources:

```bash
nesk diagnostic
```

Create a server:

```bash
nesk create -n "My Server" -d ./servers/my -c nukkit -t my-server
# Parameters are optional - Wizard Setup will start if omitted
```

Start a server:

```bash
nesk start my-server
# or run inside the server directory
```

Stop a server:

```bash
nesk stop my-server
```

List servers:

```bash
nesk list
```

---

# Runtime

LumiNESK starts servers through **[Docker](https://www.docker.com/)**. Containers use `eclipse-temurin:21-jre` by default, mount the server directory into `/server`, use host networking on Linux and publish the default Bedrock port on Docker Desktop, and apply the server memory limit with Docker `--memory`.

Create a server with a custom background memory limit and Java runtime:

```bash
nesk create -n "My Server" -d ./servers/my -c nukkit -t my-server --memory 2g --java 21
```

`--java` accepts either a numeric version, such as `17` or `21`, or a full Docker image name, such as `eclipse-temurin:21-jre`.

Change Java for a stopped server:

```bash
nesk change-java --tag my-server --java eclipse-temurin:17-jre
```

Start and attach to logs immediately:

```bash
nesk start my-server
```

Start in the background:

```bash
nesk start my-server --detached
```

Follow container logs manually:

```bash
docker logs --follow luminesk-<server-tag>
```

--- 

# Core Registry

Core metadata is loaded from JSON. Set `LUMINESK_REGISTRY_URL` to a raw GitHub Gist JSON URL; LumiNESK caches the payload and can reuse the cached copy when the network is unavailable.

Expected shape:

```json
{
  "version": 1,
  "cores": [
    {
      "type": "maven",
      "id": "nukkit",
      "name": "Nukkit",
      "description": "Original Minecraft server core.",
      "url": "https://repo.opencollab.dev/maven-snapshots",
      "group_id": "cn.nukkit",
      "artifact_id": "nukkit",
      "is_snapshot": true
    }
  ]
}
```

---

# Roadmap

Planned features:

* [ ] Plugin manager and DevTools-like system (similar to PMMP)
* [ ] Remote server management (yes, SSH exists, but still)
* [x] Docker background launch
* [ ] Automatic and manual backups
* [ ] Cluster mode implementation
* [ ] One-line curl install script (for those who don't want Python/pip or manual binary downloads)
* ...and maybe more

---

# Warning
The project status of LumiNESK is currently **active development (Beta)**. The tool is well-suited for small private servers and plugin development; however, at this stage, it is **not recommended for large commercial projects (Production)** without prior testing. Use it at your own risk.


---

# License

The project is licensed under **GPL-3.0-or-later**.

See [LICENSE](https://github.com/astra-v1/LumiNESK/blob/main/LICENSE)
