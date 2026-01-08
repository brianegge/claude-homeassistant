export class CloudClientAdapter {
  constructor(hass) {
    this._hass = hass;
    this._sessionId = null;
    this._storageKey = "claude-agent-session-id";
    this._loadSession();
  }

  async generate(prompt) {
    const payload = { prompt };
    if (this._sessionId) {
      payload.session_id = this._sessionId;
    }
    const result = await this._hass.callApi("POST", "claude_agent/chat", payload);
    if (result && result.session_id) {
      this._sessionId = result.session_id;
      this._saveSession();
    }
    return result;
  }

  resetSession() {
    this._sessionId = null;
    this._saveSession();
  }

  _loadSession() {
    try {
      const stored = window.localStorage.getItem(this._storageKey);
      if (stored) {
        this._sessionId = stored;
      }
    } catch (err) {
      // Ignore storage errors in restricted contexts.
    }
  }

  _saveSession() {
    try {
      if (this._sessionId) {
        window.localStorage.setItem(this._storageKey, this._sessionId);
      } else {
        window.localStorage.removeItem(this._storageKey);
      }
    } catch (err) {
      // Ignore storage errors in restricted contexts.
    }
  }
}
