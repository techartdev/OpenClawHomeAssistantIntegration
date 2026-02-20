(async () => {
  try {
    if (!customElements.get("openclaw-chat-card")) {
      const src = "/openclaw/openclaw-chat-card.js?v=0.1.42";
      console.info("OpenClaw loader importing", src);
      await import(src);
    }
  } catch (err) {
    console.error("OpenClaw: failed to load chat card bundle from /openclaw/openclaw-chat-card.js", err);
  }
})();
