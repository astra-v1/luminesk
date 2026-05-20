(() => {
	const shell = document.querySelector(".shell");
	if (!shell) {
		return;
	}
	const serverTag = shell.dataset.serverTag;
	if (!serverTag) {
		return;
	}
	const logTailLimit = Number(shell.dataset.logTailLimit || "200");
	const feedbackNode = document.getElementById("action-feedback");
	const consoleNode = document.getElementById("console-output");
	const consoleStatusNode = document.getElementById("console-status");
	const consoleLogPathNode = document.getElementById("console-log-path");
	const commandForm = document.getElementById("command-form");
	const commandInput = document.getElementById("command-input");
	const memoryLimitInput = document.getElementById("memory-limit-input");
	const tokenMeta = document.querySelector("meta[name='luminesk-gui-token']");
	const guiToken = tokenMeta ? tokenMeta.content : "";

	if (!consoleNode || !consoleStatusNode || !consoleLogPathNode) {
		return;
	}

	const ANSI_PALETTE = {
		30: "var(--ansi-black)",
		31: "var(--ansi-red)",
		32: "var(--ansi-green)",
		33: "var(--ansi-yellow)",
		34: "var(--ansi-blue)",
		35: "var(--ansi-magenta)",
		36: "var(--ansi-cyan)",
		37: "var(--ansi-white)",
		90: "var(--ansi-bright-black)",
		91: "var(--ansi-bright-red)",
		92: "var(--ansi-bright-green)",
		93: "var(--ansi-bright-yellow)",
		94: "var(--ansi-bright-blue)",
		95: "var(--ansi-bright-magenta)",
		96: "var(--ansi-bright-cyan)",
		97: "var(--ansi-bright-white)"
	};

	function escapeHtml(value) {
		return value
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/\"/g, "&quot;")
			.replace(/'/g, "&#39;");
	}

	function stripNonSgrSequences(text) {
		return text
			.replace(/\x1b\][^\x07]*\x07/g, "")
			.replace(/\x1bP[^\x1b]*\x1b\\/g, "")
			.replace(/\x1b\[[0-9;?]*[A-DF-PR-TZcf-ntqry=><]/g, "");
	}

	function parseAnsiColor(code, isBackground) {
		if (ANSI_PALETTE[code]) {
			return ANSI_PALETTE[code];
		}
		if (code >= 40 && code <= 47) {
			return ANSI_PALETTE[code - 10];
		}
		if (code >= 100 && code <= 107) {
			return ANSI_PALETTE[code - 10];
		}
		return null;
	}

	function colorFrom256(index) {
		if (index < 16) {
			const basic = {
				0: "var(--ansi-black)",
				1: "var(--ansi-red)",
				2: "var(--ansi-green)",
				3: "var(--ansi-yellow)",
				4: "var(--ansi-blue)",
				5: "var(--ansi-magenta)",
				6: "var(--ansi-cyan)",
				7: "var(--ansi-white)",
				8: "var(--ansi-bright-black)",
				9: "var(--ansi-bright-red)",
				10: "var(--ansi-bright-green)",
				11: "var(--ansi-bright-yellow)",
				12: "var(--ansi-bright-blue)",
				13: "var(--ansi-bright-magenta)",
				14: "var(--ansi-bright-cyan)",
				15: "var(--ansi-bright-white)"
			};
			return basic[index] || null;
		}
		if (index >= 16 && index <= 231) {
			const value = index - 16;
			const r = Math.floor(value / 36);
			const g = Math.floor((value % 36) / 6);
			const b = value % 6;
			const toChannel = (v) => (v === 0 ? 0 : 55 + v * 40);
			return `rgb(${toChannel(r)}, ${toChannel(g)}, ${toChannel(b)})`;
		}
		if (index >= 232 && index <= 255) {
			const gray = 8 + (index - 232) * 10;
			return `rgb(${gray}, ${gray}, ${gray})`;
		}
		return null;
	}

	function applyAnsiCodes(codes, state) {
		if (codes.length === 0) {
			codes = [0];
		}
		for (let i = 0; i < codes.length; i += 1) {
			const code = codes[i];
			if (code === 0) {
				state.fg = null;
				state.bg = null;
				state.bold = false;
				state.dim = false;
				state.italic = false;
				state.underline = false;
				continue;
			}
			if (code === 1) {
				state.bold = true;
				continue;
			}
			if (code === 2) {
				state.dim = true;
				continue;
			}
			if (code === 3) {
				state.italic = true;
				continue;
			}
			if (code === 4) {
				state.underline = true;
				continue;
			}
			if (code === 22) {
				state.bold = false;
				state.dim = false;
				continue;
			}
			if (code === 23) {
				state.italic = false;
				continue;
			}
			if (code === 24) {
				state.underline = false;
				continue;
			}
			if (code === 39) {
				state.fg = null;
				continue;
			}
			if (code === 49) {
				state.bg = null;
				continue;
			}

			if (code === 38 || code === 48) {
				const mode = codes[i + 1];
				if (mode === 2 && codes.length >= i + 4) {
					const r = codes[i + 2];
					const g = codes[i + 3];
					const b = codes[i + 4];
					const color = `rgb(${r}, ${g}, ${b})`;
					if (code === 38) {
						state.fg = color;
					} else {
						state.bg = color;
					}
					i += 4;
					continue;
				}
				if (mode === 5 && codes.length >= i + 2) {
					const color = colorFrom256(codes[i + 2]);
					if (color) {
						if (code === 38) {
							state.fg = color;
						} else {
							state.bg = color;
						}
					}
					i += 2;
					continue;
				}
			}

			const color = parseAnsiColor(code);
			if (color) {
				if (code >= 40) {
					state.bg = color;
				} else {
					state.fg = color;
				}
			}
		}
	}

	function buildStyle(state) {
		const styles = [];
		if (state.fg) {
			styles.push(`color: ${state.fg}`);
		}
		if (state.bg) {
			styles.push(`background-color: ${state.bg}`);
		}
		if (state.bold) {
			styles.push("font-weight: 600");
		}
		if (state.dim) {
			styles.push("opacity: 0.75");
		}
		if (state.italic) {
			styles.push("font-style: italic");
		}
		if (state.underline) {
			styles.push("text-decoration: underline");
		}
		return styles.join("; ");
	}

	function ansiToHtml(rawText) {
		if (!rawText) {
			return "";
		}
		const text = stripNonSgrSequences(rawText);
		const matcher = /\x1b\[([0-9;]*)m/g;
		const state = {
			fg: null,
			bg: null,
			bold: false,
			dim: false,
			italic: false,
			underline: false
		};
		let lastIndex = 0;
		let result = "";
		let sawAnsi = false;
		let match = matcher.exec(text);
		while (match) {
			sawAnsi = true;
			const chunk = text.slice(lastIndex, match.index);
			if (chunk) {
				const style = buildStyle(state);
				const escaped = escapeHtml(chunk);
				result += style ? `<span style="${style}">${escaped}</span>` : escaped;
			}
			const codes = match[1]
				.split(";")
				.filter(Boolean)
				.map((value) => Number.parseInt(value, 10))
				.filter((value) => Number.isFinite(value));
			applyAnsiCodes(codes, state);
			lastIndex = matcher.lastIndex;
			match = matcher.exec(text);
		}
		const tail = text.slice(lastIndex);
		if (tail) {
			const style = buildStyle(state);
			const escaped = escapeHtml(tail);
			result += style ? `<span style="${style}">${escaped}</span>` : escaped;
		}
		return sawAnsi ? result : highlightLogLevels(text);
	}

	function highlightLogLevels(text) {
		const escaped = escapeHtml(text);
		return escaped.replace(
			/\[(INFO|WARN|WARNING|ERROR|DEBUG|TRACE)\]/g,
			(match, level) => {
				const upper = level.toUpperCase();
				let color = "var(--ansi-bright-blue)";
				if (upper === "WARN" || upper === "WARNING") {
					color = "var(--ansi-bright-yellow)";
				} else if (upper === "ERROR") {
					color = "var(--ansi-bright-red)";
				} else if (upper === "DEBUG") {
					color = "var(--ansi-bright-cyan)";
				} else if (upper === "TRACE") {
					color = "var(--ansi-bright-black)";
				}
				return `<span style="color: ${color}; font-weight: 600;">[${level}]</span>`;
			}
		);
	}

	function renderConsole(rawText) {
		consoleNode.innerHTML = ansiToHtml(rawText);
	}

	function showFeedback(message, tone) {
		if (!feedbackNode) {
			return;
		}
		feedbackNode.hidden = false;
		feedbackNode.className = `feedback ${tone}`;
		feedbackNode.textContent = message;
	}

	function authHeaders(headers = {}) {
		return {
			"X-LumiNESK-Token": guiToken,
			...headers
		};
	}

	async function runAction(action) {
		const body = action === "start" && memoryLimitInput
			? { memory_limit: memoryLimitInput.value.trim() }
			: {};
		const response = await fetch(`/api/servers/${serverTag}/${action}`,
			{
				method: "POST",
				headers: authHeaders({
					"Content-Type": "application/json"
				}),
				body: JSON.stringify(body)
			}
		);
		const payload = await response.json();
		if (!response.ok || !payload.ok) {
			showFeedback(payload.error || "Action failed.", "error");
			return;
		}
		showFeedback(payload.message, "success");
		setTimeout(() => window.location.reload(), 700);
	}

	async function refreshConsole() {
		const response = await fetch(`/api/servers/${serverTag}/console?lines=${logTailLimit}`, {
			headers: authHeaders()
		});
		if (!response.ok) {
			return;
		}
		const payload = await response.json();
		const text = payload.log.lines.length
			? payload.log.lines.join("\n")
			: "Log file has not been created yet.";
		renderConsole(text);
		consoleStatusNode.textContent = payload.server.status_label;
		consoleLogPathNode.textContent = payload.log.path || "No log file yet";
	}

	document.querySelectorAll("[data-action]").forEach((button) => {
		button.addEventListener("click", () => runAction(button.dataset.action));
	});

	if (commandForm && commandInput) {
		commandForm.addEventListener("submit", async (event) => {
			event.preventDefault();
			const command = commandInput.value.trim();
			if (!command) {
				showFeedback("Command must not be empty.", "error");
				return;
			}
			const response = await fetch(`/api/servers/${serverTag}/command`, {
				method: "POST",
				headers: authHeaders({
					"Content-Type": "application/json"
				}),
				body: JSON.stringify({ command })
			});
			const payload = await response.json();
			if (!response.ok || !payload.ok) {
				showFeedback(payload.error || "Command failed.", "error");
				return;
			}
			commandInput.value = "";
			showFeedback(payload.message, "success");
			refreshConsole();
		});
	}

	renderConsole(consoleNode.textContent || "");
	refreshConsole();
	setInterval(refreshConsole, 3000);
})();
