import assert from "node:assert/strict";

const registry = new Map();

globalThis.HTMLElement = class {
  attachShadow() {
    this.shadowRoot = {
      innerHTML: "",
      getElementById: () => null,
    };
  }
};
globalThis.customElements = {
  define: (name, value) => registry.set(name, value),
  get: (name) => registry.get(name),
};
globalThis.window = { customCards: [] };
globalThis.document = { createElement: () => ({}) };
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: { language: "en-US" },
});

await import("../custom_components/openclaw/www/openclaw-chat-card.js");

const Card = registry.get("openclaw-chat-card");
assert.ok(Card, "chat card should register itself");

const calls = [];
const card = new Card();
card._config = {
  ha_tts_engine: "tts.openai_tts",
  voice_output_media_player: "media_player.bedroom_speaker",
};
card._hass = {
  states: {},
  callService: async (...args) => calls.push(args),
};
card._waitForMediaPlayerPlayback = async () => {};

assert.equal(await card._speakViaMediaPlayer("Hello from OpenClaw"), true);
assert.deepEqual(calls, [
  [
    "tts",
    "speak",
    {
      media_player_entity_id: "media_player.bedroom_speaker",
      message: "Hello from OpenClaw",
      cache: true,
    },
    { entity_id: "tts.openai_tts" },
  ],
]);

const invalidCard = new Card();
invalidCard._config = {
  ha_tts_engine: "openai_tts",
  voice_output_media_player: "bedroom_speaker",
};
invalidCard._hass = { callService: async () => assert.fail("must not call service") };

assert.equal(await invalidCard._speakViaMediaPlayer("Hello"), false);
assert.equal(invalidCard._lastHaTtsAttempt, "ha_tts_engine_must_be_a_tts_entity");
