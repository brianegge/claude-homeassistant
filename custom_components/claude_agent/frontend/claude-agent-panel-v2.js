import { CloudClientAdapter } from "./cloud-client.js";

class ClaudeAgentPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
      this._client = new CloudClientAdapter(hass);
      this._render();
      this._loadInfo();
    }
  }

  get hass() {
    return this._hass;
  }

  _render() {
    this.innerHTML = `
      <style>
        .container {
          padding: 16px;
        }
        .row {
          display: flex;
          gap: 12px;
          align-items: center;
          flex-wrap: wrap;
        }
        .main {
          display: flex;
          gap: 16px;
          margin-top: 12px;
        }
        .pane {
          flex: 1 1 0;
          min-width: 0;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .divider {
          width: 1px;
          background: var(--divider-color, #2f2f2f);
        }
        .status {
          color: var(--secondary-text-color);
        }
        .capability {
          margin-top: 8px;
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .warnings {
          margin-top: 8px;
          font-size: 12px;
          color: var(--error-color);
        }
        .chat-log {
          flex: 1 1 auto;
          min-height: 240px;
          max-height: 420px;
          overflow: auto;
          padding: 12px;
          border: 1px solid var(--divider-color, #2f2f2f);
          border-radius: 8px;
          background: linear-gradient(135deg, rgba(255, 255, 255, 0.02), rgba(0, 0, 0, 0.08));
        }
        .chat-bubble {
          max-width: 85%;
          padding: 10px 12px;
          border-radius: 12px;
          margin-bottom: 10px;
          white-space: pre-wrap;
          font-family: var(--primary-font-family, sans-serif);
          font-size: 13px;
          line-height: 1.4;
        }
        .chat-bubble.user {
          margin-left: auto;
          background: rgba(3, 169, 244, 0.15);
          border: 1px solid rgba(3, 169, 244, 0.35);
        }
        .chat-bubble.assistant {
          margin-right: auto;
          background: rgba(255, 255, 255, 0.06);
          border: 1px solid rgba(255, 255, 255, 0.12);
        }
        .chat-bubble.typing {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 8px 12px;
        }
        .typing-dots {
          display: inline-flex;
          gap: 4px;
        }
        .typing-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.6);
          animation: typingPulse 1.2s infinite ease-in-out;
        }
        .typing-dot:nth-child(2) {
          animation-delay: 0.2s;
        }
        .typing-dot:nth-child(3) {
          animation-delay: 0.4s;
        }
        @keyframes typingPulse {
          0%, 80%, 100% {
            opacity: 0.2;
            transform: translateY(0);
          }
          40% {
            opacity: 1;
            transform: translateY(-2px);
          }
        }
        .chat-composer {
          display: flex;
          gap: 8px;
          align-items: flex-end;
        }
        .chat-composer textarea {
          flex: 1 1 auto;
          width: 100%;
          min-height: 80px;
          font-family: var(--code-font-family, monospace);
          font-size: 12px;
          padding: 8px;
          box-sizing: border-box;
        }
        textarea {
          width: 100%;
          min-height: 280px;
          font-family: var(--code-font-family, monospace);
          font-size: 12px;
          padding: 8px;
          box-sizing: border-box;
        }
        .path {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
        .section-title {
          font-size: 12px;
          color: var(--secondary-text-color);
          text-transform: uppercase;
          letter-spacing: 0.08em;
          margin-bottom: 8px;
        }
        @media (max-width: 900px) {
          .main {
            flex-direction: column;
          }
          .divider {
            width: auto;
            height: 1px;
          }
        }
      </style>
      <ha-card header="Claude Agent">
        <div class="container">
          <div class="row">
            <mwc-button raised id="load">Load automations.yaml</mwc-button>
            <mwc-button outlined id="save">Save automations.yaml</mwc-button>
            <mwc-button raised id="generate">Generate</mwc-button>
            <span class="path" id="path"></span>
          </div>
          <div class="capability" id="capability"></div>
          <div class="warnings" id="warnings"></div>
          <div class="main">
            <div class="pane">
              <div class="row">
                <div class="section-title">Chat</div>
                <mwc-button outlined id="new-automation">New automation</mwc-button>
              </div>
              <div class="chat-log" id="chat-log" aria-live="polite"></div>
              <div class="chat-composer">
                <textarea
                  id="prompt"
                  placeholder="Describe the automation changes you want."
                ></textarea>
                <mwc-button raised id="send">Send</mwc-button>
              </div>
              <div class="status" id="status">Ready.</div>
            </div>
            <div class="divider" aria-hidden="true"></div>
            <div class="pane">
              <div class="section-title">Config Preview</div>
              <textarea id="content" placeholder="Automations YAML will appear here"></textarea>
              <div class="row">
                <mwc-button outlined id="save-preview">Save to config</mwc-button>
              </div>
            </div>
          </div>
        </div>
      </ha-card>
    `;

    this._statusEl = this.querySelector("#status");
    this._capabilityEl = this.querySelector("#capability");
    this._warningsEl = this.querySelector("#warnings");
    this._pathEl = this.querySelector("#path");
    this._contentEl = this.querySelector("#content");
    this._promptEl = this.querySelector("#prompt");
    this._chatLogEl = this.querySelector("#chat-log");
    this._typingEl = null;
    this._pendingRequest = false;
    this._sendButton = this.querySelector("#send");
    this._generateButton = this.querySelector("#generate");

    this._startDevReload();

    this.querySelector("#load").addEventListener("click", () => {
      this._loadAutomations();
    });
    this.querySelector("#save").addEventListener("click", () => {
      this._saveAutomations();
    });
    this.querySelector("#save-preview").addEventListener("click", () => {
      this._saveAutomations();
    });
    this.querySelector("#generate").addEventListener("click", () => {
      this._sendPrompt();
    });
    this.querySelector("#send").addEventListener("click", () => {
      this._sendPrompt();
    });
    this.querySelector("#new-automation").addEventListener("click", () => {
      this._startNewAutomation();
    });
    this._promptEl.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        this._sendPrompt();
      }
    });
  }

  async _loadInfo() {
    try {
      const info = await this._hass.connection.sendMessagePromise({
        type: "claude_agent/get_info",
      });
      this._pathEl.textContent = info.automations_path || "";
      await this._loadStatus();
    } catch (err) {
      this._setStatus(`Info error: ${err.message || err}`);
    }
  }

  async _loadStatus() {
    try {
      const status = await this._hass.callApi("GET", "claude_agent/status");
      const cli = status.cli || {};
      const registries = status.registries || {};
      const cliText = cli.available
        ? `CLI: OK${cli.path ? ` (${cli.path})` : ""}`
        : `CLI: missing${cli.error ? ` (${cli.error})` : ""}`;
      const regText = `Registry: ${registries.source || "n/a"} ` +
        `(entities=${registries.entities ?? 0}, devices=${registries.devices ?? 0}, areas=${registries.areas ?? 0})`;
      this._capabilityEl.textContent = `${cliText} | ${regText}`;
      if (!cli.available) {
        this._warningsEl.textContent =
          "Claude Code CLI not found. Set cli_path in the integration settings.";
      }
    } catch (err) {
      this._warningsEl.textContent = `Status check failed: ${err.message || err}`;
    }
  }

  async _loadAutomations() {
    this._setStatus("Loading automations.yaml...");
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "claude_agent/get_automations",
      });
      this._contentEl.value = result.content || "";
      this._pathEl.textContent = result.path || "";
      this._setStatus(
        result.exists ? "Loaded." : "File not found (new file will be created)."
      );
    } catch (err) {
      this._setStatus(`Load error: ${err.message || err}`);
    }
  }

  async _saveAutomations() {
    this._setStatus("Saving automations.yaml...");
    try {
      const content = this._contentEl.value || "";
      const result = await this._hass.connection.sendMessagePromise({
        type: "claude_agent/write_automations",
        content,
      });
      this._setStatus(result.ok ? "Saved." : "Save failed.");
      if (result.path) {
        this._pathEl.textContent = result.path;
      }
    } catch (err) {
      this._setStatus(`Save error: ${err.message || err}`);
    }
  }

  async _sendPrompt() {
    if (this._pendingRequest) {
      this._setStatus("Please wait for the current response.");
      return;
    }
    const prompt = (this._promptEl?.value || "").trim();
    if (!prompt) {
      this._setStatus("Please enter a prompt before generating.");
      return;
    }

    this._pendingRequest = true;
    this._setSendDisabled(true);
    this._setStatus("Generating updates...");
    this._appendChatMessage("user", prompt);
    this._setTyping(true);
    this._promptEl.value = "";
    try {
      const result = await this._client.generate(prompt);
      if (result.updated_yaml) {
        this._contentEl.value = result.updated_yaml;
      }
      if (result.path) {
        this._pathEl.textContent = result.path;
      }
      const warnings = result.warnings || [];
      const summary = result.summary ? ` ${result.summary}` : "";
      const hasYaml = Boolean(result.updated_yaml);
      if (warnings.length) {
        const status = hasYaml
          ? `Generated (not saved).${summary}`
          : `Response received.${summary}`;
        const warningText = `\n${warnings.join("\n")}`;
        this._setStatus(status);
        this._warningsEl.textContent = warnings.join("; ");
        if (hasYaml) {
          this._appendChatMessage("assistant", `${status}${warningText}`);
        } else {
          this._appendChatMessage("assistant", `${result.summary || status}${warningText}`);
        }
      } else {
        const status = hasYaml
          ? `Generated (not saved).${summary}`
          : `Response received.${summary}`;
        this._setStatus(status);
        this._warningsEl.textContent = "";
        if (hasYaml) {
          this._appendChatMessage("assistant", status.trim());
        } else {
          this._appendChatMessage("assistant", result.summary || status.trim());
        }
      }
    } catch (err) {
      const rawError = err?.message || err?.error || err;
      const errorMessage = `Generate error: ${typeof rawError === "string" ? rawError : JSON.stringify(rawError)}`;
      this._setStatus(errorMessage);
      this._appendChatMessage("assistant", errorMessage);
    } finally {
      this._setTyping(false);
      this._pendingRequest = false;
      this._setSendDisabled(false);
    }
  }

  _appendChatMessage(role, text) {
    if (!this._chatLogEl) {
      return;
    }
    if (role === "assistant" && this._typingEl) {
      this._typingEl.className = "chat-bubble assistant";
      this._typingEl.textContent = text;
      this._typingEl = null;
      this._chatLogEl.scrollTop = this._chatLogEl.scrollHeight;
      return;
    }
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${role}`;
    bubble.textContent = text;
    this._chatLogEl.appendChild(bubble);
    this._chatLogEl.scrollTop = this._chatLogEl.scrollHeight;
  }

  _startNewAutomation() {
    if (this._chatLogEl) {
      this._chatLogEl.textContent = "";
    }
    if (this._client) {
      this._client.resetSession();
    }
    if (this._warningsEl) {
      this._warningsEl.textContent = "";
    }
    if (this._promptEl) {
      this._promptEl.value = "";
    }
    this._setTyping(false);
    this._setStatus("New automation context started.");
    this._loadAutomations();
  }

  _setTyping(active) {
    if (!this._chatLogEl) {
      return;
    }
    if (active) {
      if (this._typingEl) {
        return;
      }
      const bubble = document.createElement("div");
      bubble.className = "chat-bubble assistant typing";
      bubble.innerHTML = `
        <span class="typing-dots" aria-label="Assistant typing">
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
          <span class="typing-dot"></span>
        </span>
      `;
      this._chatLogEl.appendChild(bubble);
      this._chatLogEl.scrollTop = this._chatLogEl.scrollHeight;
      this._typingEl = bubble;
      return;
    }
    if (this._typingEl) {
      this._typingEl.remove();
      this._typingEl = null;
    }
  }

  _setSendDisabled(disabled) {
    if (this._sendButton) {
      this._sendButton.disabled = disabled;
    }
    if (this._generateButton) {
      this._generateButton.disabled = disabled;
    }
  }

  _startDevReload() {
    if (this._reloadInterval) {
      return;
    }
    const host = window.location.hostname;
    if (host !== "localhost" && host !== "127.0.0.1") {
      return;
    }
    const scriptUrl = new URL(import.meta.url, window.location.href);
    const hashText = (text) => {
      let hash = 5381;
      for (let i = 0; i < text.length; i += 1) {
        hash = (hash * 33) ^ text.charCodeAt(i);
      }
      return hash >>> 0;
    };
    const poll = async () => {
      try {
        const resp = await fetch(
          `${scriptUrl.href}?t=${Date.now()}`,
          { cache: "no-store" }
        );
        if (!resp.ok) {
          return;
        }
        const text = await resp.text();
        const signature = hashText(text);
        if (this._lastReloadSignature === undefined) {
          this._lastReloadSignature = signature;
          return;
        }
        if (this._lastReloadSignature !== signature) {
          window.location.reload();
        }
      } catch (err) {
        // Ignore transient reload errors in dev.
      }
    };
    this._reloadInterval = window.setInterval(poll, 1500);
    poll();
  }

  _setStatus(message) {
    if (this._statusEl) {
      this._statusEl.textContent = message;
    }
  }
}

if (!customElements.get("claude-agent-panel")) {
  customElements.define("claude-agent-panel", ClaudeAgentPanel);
}
