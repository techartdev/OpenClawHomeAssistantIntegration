(async () => {
  try {
    if (!customElements.get("openclaw-chat-card")) {
      await import("/openclaw/openclaw-chat-card.js");
    }
  } catch (err) {
    console.error("OpenClaw: failed to load chat card bundle from /openclaw/openclaw-chat-card.js", err);
  }
})();
