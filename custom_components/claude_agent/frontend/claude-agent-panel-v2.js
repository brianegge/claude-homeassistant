class ClaudeAgentPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialized = true;
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
        .status {
          margin-top: 8px;
          color: var(--secondary-text-color);
        }
        .prompt {
          margin-top: 12px;
        }
        .prompt textarea {
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
      </style>
      <ha-card header="Claude Agent">
        <div class="container">
          <div class="row">
            <mwc-button raised id="load">Load automations.yaml</mwc-button>
            <mwc-button outlined id="save">Save automations.yaml</mwc-button>
            <mwc-button raised id="generate">Generate</mwc-button>
            <span class="path" id="path"></span>
          </div>
          <div class="prompt">
            <label for="prompt">Prompt</label>
            <textarea
              id="prompt"
              placeholder="Describe the automation changes you want."
            ></textarea>
          </div>
          <div class="status" id="status">Ready.</div>
          <textarea id="content" placeholder="Automations YAML will appear here"></textarea>
        </div>
      </ha-card>
    `;

    this._statusEl = this.querySelector("#status");
    this._pathEl = this.querySelector("#path");
    this._contentEl = this.querySelector("#content");
    this._promptEl = this.querySelector("#prompt");

    this.querySelector("#load").addEventListener("click", () => {
      this._loadAutomations();
    });
    this.querySelector("#save").addEventListener("click", () => {
      this._saveAutomations();
    });
    this.querySelector("#generate").addEventListener("click", () => {
      this._generateFromPrompt();
    });
  }

  async _loadInfo() {
    try {
      const info = await this._hass.connection.sendMessagePromise({
        type: "claude_agent/get_info",
      });
      this._pathEl.textContent = info.automations_path || "";
    } catch (err) {
      this._setStatus(`Info error: ${err.message || err}`);
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

  async _generateFromPrompt() {
    const prompt = (this._promptEl?.value || "").trim();
    if (!prompt) {
      this._setStatus("Please enter a prompt before generating.");
      return;
    }

    this._setStatus("Generating updates...");
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "claude_agent/chat",
        prompt,
      });
      this._contentEl.value = result.updated_yaml || "";
      if (result.path) {
        this._pathEl.textContent = result.path;
      }
      this._setStatus("Generated.");
    } catch (err) {
      this._setStatus(`Generate error: ${err.message || err}`);
    }
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
