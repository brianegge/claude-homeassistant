export class CloudClientAdapter {
  constructor(hass) {
    this._hass = hass;
  }

  async generate(prompt) {
    return this._hass.callApi("POST", "claude_agent/chat", { prompt });
  }
}
