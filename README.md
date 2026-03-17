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

LumiNESK combines:

- **CLI** (command-line interface)
- **TUI** (interactive terminal interface)
- **Web GUI** (browser-based interface)

Supported engines: [Nukkit](https://github.com/CloudburstMC/Nukkit), [PowerNukkitX](https://github.com/PowerNukkitX/PowerNukkitX), [Nukkit-MOT](https://github.com/MemoriesOfTime/Nukkit-MOT), [Lumi](https://github.com/koshakminedev/lumi).

---

# Features

- create and register servers
- start servers in **normal** and **loop mode**
- stop and force terminate servers
- manage server engines
- environment and provider diagnostics
- TUI interface with live console
- Web GUI for monitoring
- manage multiple servers
- update server engines

---

# Requirements

| Component | Version                        | Required |
|----------|--------------------------------|----------|
| Python   | **3.13+** (3.14 recommended)   | Not required if you don’t install via pip |
| Java     | 21+                            | Required for running servers |
| tmux     | latest                         | Optional (only for TUI/GUI usage) |

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

Uses **[PyInstaller](https://pypi.org/project/pyinstaller/)**.

Linux/macOS:

```bash
pyinstaller --onefile --name luminesk \
  --add-data "luminesk/gui/templates:luminesk/gui/templates" \
  --add-data "luminesk/gui/static:luminesk/gui/static" \
  --add-data "luminesk/tui/styles:luminesk/tui/styles" \
  luminesk/__main__.py
```

Windows:

```bash
pyinstaller --onefile --name luminesk ^
  --add-data "luminesk\\gui\\templates;luminesk\\gui\\templates" ^
  --add-data "luminesk\\gui\\static;luminesk\\gui\\static" ^
  --add-data "luminesk\\tui\\styles;luminesk\\tui\\styles" ^
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
nesk doctor
```

Create a server:

```bash
nesk create -n "My Server" -d ./servers/my -c nukkit -t my_server
# Parameters are optional — Wizard Setup will start if omitted
```

Start a server:

```bash
nesk start -t my_server
# or run inside the server directory
```

Stop a server:

```bash
nesk stop -t my_server
# or run inside the server directory
```

List servers:

```bash
nesk list
```

---

# Working with tmux

LumiNESK uses **[tmux](https://github.com/tmux/tmux/wiki)** to manage server consoles in TUI/GUI mode.

Attach to a console:

```bash
tmux attach-session -t luminesk-<server-tag>
```

---

# Roadmap

Planned features:

* [ ] Plugin manager and DevTools-like system (similar to PMMP)
* [ ] Remote server management (yes, SSH exists, but still)
* [ ] Docker support
* [ ] Automatic and manual backups
* [ ] Cluster mode implementation
* [ ] One-line curl install script (for those who don’t want Python/pip or manual binary downloads)
* ...and maybe more

---

# License

The project is licensed under **GPL-3.0-or-later**.

See [LICENSE](https://github.com/astra-v1/LumiNESK/blob/main/LICENSE)
