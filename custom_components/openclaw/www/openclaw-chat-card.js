/**
 * OpenClaw Chat Card — Lovelace custom card for Home Assistant.
 *
 * Features:
 * - Message history with timestamps
 * - Streaming AI response display (typing indicator)
 * - Markdown rendering
 * - File/image attachment support
 * - Voice input (WebSpeech / MediaRecorder)
 * - Voice mode toggle (continuous conversation)
 *
 * Communication: uses HA WebSocket API → openclaw.send_message service
 * + subscribes to openclaw_message_received events.
 */

const CARD_VERSION = "0.3.6";

// Max time (ms) to show the thinking indicator before falling back to an error
const THINKING_TIMEOUT_MS = 120_000;

// Session storage key prefix for message persistence across dashboard navigations
const STORAGE_PREFIX = "openclaw_chat_";

// ─── Minimal Markdown renderer ──────────────────────────────────────────────
// Handles: **bold**, *italic*, `code`, ```code blocks```, [links](url), headers
function renderMarkdown(text) {
  if (!text) return "";
  let html = text
    // Code blocks (``` ... ```)
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>')
    // Inline code
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    // Bold
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Links
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    // Headers
    .replace(/^### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/^# (.+)$/gm, "<h2>$1</h2>")
    // Line breaks
    .replace(/\n/g, "<br>");
  return html;
}

// ─── Card class ─────────────────────────────────────────────────────────────

class OpenClawChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._messages = [];
    this._isProcessing = false;
    this._isVoiceMode = false;
    this._recognition = null;
    this._eventUnsubscribe = null;
    this._thinkingTimer = null;
    this._historySyncRetryTimer = null;
    this._wakeWordEnabled = false;
    this._wakeWord = "hey openclaw";
    this._voiceStatus = "";
    this._voiceRetryTimer = null;
    this._voiceRetryCount = 0;
    this._voiceNetworkErrorCount = 0;
    this._pendingResponses = 0;
    this._speechLangOverride = null;
    this._integrationBrowserVoiceLanguage = null;
    this._integrationVoiceLanguage = null;
    this._integrationTtsLanguage = null;
    this._allowBraveWebSpeechIntegration = false;
    this._voiceProviderIntegration = "browser";
    this._preferredAssistSttEngine = null;
    this._voiceBackendBlocked = false;
    this._voiceStopRequested = false;
    this._assistRecordingActive = false;
    this._assistAudioStream = null;
    this._assistAudioContext = null;
    this._assistAudioSource = null;
    this._assistAudioWorkletNode = null;
    this._assistAudioProcessor = null;
    this._assistAudioSilenceGain = null;
    this._assistAudioChunks = [];
    this._assistInputSampleRate = 16000;
    this._assistAutoStopTimer = null;
    this._lastAssistantEventSignature = null;
  }

  // ── HA card interface ───────────────────────────────────────────────

  static getConfigElement() {
    return document.createElement("openclaw-chat-card-editor");
  }

  static getStubConfig() {
    return {};
  }

  setConfig(config) {
    this._config = {
      title: config.title || "OpenClaw Chat",
      height: config.height || "500px",
      show_timestamps: config.show_timestamps !== false,
      show_voice_button: config.show_voice_button !== false,
      show_clear_button: config.show_clear_button !== false,
      allow_brave_webspeech: config.allow_brave_webspeech === true,
      voice_provider: config.voice_provider || null,
      session_id: config.session_id || null,
      ...config,
    };
    // Restore messages from sessionStorage if available
    this._restoreMessages();
    this._render();
  }

  set hass(hass) {
    const firstSet = !this._hass;
    this._hass = hass;
    if (firstSet) {
      this._subscribeToEvents();
      this._syncHistoryFromBackend();
      this._loadIntegrationSettings();
    }
    this._render();
  }

  _getGatewayConnectionState() {
    const statusEntity = this._hass?.states?.["sensor.openclaw_status"];
    const binaryEntity = this._hass?.states?.["binary_sensor.openclaw_connected"];
    const status = String(statusEntity?.state || "").toLowerCase();
    const connected = String(binaryEntity?.state || "").toLowerCase() === "on";

    if (connected || status === "online") {
      return { label: "Online", css: "online" };
    }
    if (status === "offline" || String(binaryEntity?.state || "").toLowerCase() === "off") {
      return { label: "Offline", css: "offline" };
    }

    return { label: "Unknown", css: "unknown" };
  }

  getCardSize() {
    return 6;
  }

  connectedCallback() {
    this._subscribeToEvents();
    this._syncHistoryFromBackend();
    this._loadIntegrationSettings();
    this._render();
  }

  disconnectedCallback() {
    this._unsubscribeEvents();
    this._stopVoiceRecognition();
    this._clearThinkingTimer();
    if (this._historySyncRetryTimer) {
      clearTimeout(this._historySyncRetryTimer);
      this._historySyncRetryTimer = null;
    }
    if (this._voiceRetryTimer) {
      clearTimeout(this._voiceRetryTimer);
      this._voiceRetryTimer = null;
    }
  }

  // ── Event subscription ──────────────────────────────────────────────

  async _subscribeToEvents() {
    if (!this._hass || this._eventUnsubscribe) return;

    try {
      this._eventUnsubscribe = await this._hass.connection.subscribeEvents(
        (event) => this._handleOpenClawEvent(event),
        "openclaw_message_received"
      );
    } catch (err) {
      console.error("OpenClaw: Failed to subscribe to events:", err);
    }
  }

  _unsubscribeEvents() {
    if (this._eventUnsubscribe) {
      this._eventUnsubscribe();
      this._eventUnsubscribe = null;
    }
  }

  _handleOpenClawEvent(event) {
    const data = event.data;
    if (!data || !data.message) return;

    // Check if this event is for our session
    const sessionId = this._getSessionId();
    if (data.session_id && data.session_id !== sessionId) return;

    const signature = `${sessionId}|${data.timestamp || ""}|${String(data.message)}`;
    if (signature === this._lastAssistantEventSignature) {
      return;
    }
    this._lastAssistantEventSignature = signature;

    const thinkingIdx = this._messages.findIndex((m) => m._thinking);
    if (thinkingIdx >= 0) {
      this._messages[thinkingIdx] = {
        role: "assistant",
        content: data.message,
        timestamp: data.timestamp || new Date().toISOString(),
      };
      if (this._pendingResponses > 0) {
        this._pendingResponses -= 1;
      }
    } else {
      this._addMessage("assistant", data.message);
    }

    this._isProcessing = this._pendingResponses > 0;
    if (!this._isProcessing) {
      this._clearThinkingTimer();
    } else {
      this._startThinkingTimer();
    }

    this._persistMessages();
    this._render();
    this._scrollToBottom();

    // In voice mode, speak the response
    if (this._isVoiceMode && this._recognition && data.message) {
      this._speak(data.message);
    }
  }

  _clearChat() {
    this._messages = [];
    this._isProcessing = false;
    this._pendingResponses = 0;
    this._clearThinkingTimer();
    this._persistMessages();
    this._render();
  }

  // ── Message persistence ──────────────────────────────────────────────

  _getStorageKey() {
    const session = this._getSessionId();
    return `${STORAGE_PREFIX}${session}`;
  }

  _getSessionId() {
    return this._config.session_id || "default";
  }

  _persistMessages() {
    try {
      const toSave = this._messages.filter((m) => !m._thinking);
      // Keep last 100 messages to avoid storage bloat
      const trimmed = toSave.slice(-100);
      sessionStorage.setItem(this._getStorageKey(), JSON.stringify(trimmed));
    } catch (e) {
      // sessionStorage full or unavailable — ignore
    }
  }

  _restoreMessages() {
    try {
      const stored = sessionStorage.getItem(this._getStorageKey());
      if (stored) {
        this._messages = JSON.parse(stored);
      }
    } catch (e) {
      // Corrupted data — start fresh
      this._messages = [];
    }
  }

  async _syncHistoryFromBackend(retries = 6) {
    if (!this._hass) return;

    const sessionId = this._getSessionId();

    try {
      let result;
      if (typeof this._hass.callWS === "function") {
        result = await this._hass.callWS({
          type: "openclaw/get_history",
          session_id: sessionId,
        });
      } else {
        result = await this._hass.connection.sendMessagePromise({
          type: "openclaw/get_history",
          session_id: sessionId,
        });
      }

      const serverMessages = Array.isArray(result?.messages) ? result.messages : [];
      if (!serverMessages.length) return;

      const validMessages = serverMessages.filter(
        (m) => m && (m.role === "user" || m.role === "assistant") && typeof m.content === "string"
      );
      if (!validMessages.length) return;

      const shouldReplace =
        validMessages.length > this._messages.length ||
        (validMessages.length === this._messages.length &&
          validMessages.length > 0 &&
          this._messages.length > 0 &&
          (validMessages[validMessages.length - 1].content !==
            this._messages[this._messages.length - 1].content ||
            validMessages[validMessages.length - 1].timestamp !==
              this._messages[this._messages.length - 1].timestamp));

      if (shouldReplace) {
        this._messages = validMessages;
        this._isProcessing = false;
        this._pendingResponses = 0;
        this._clearThinkingTimer();
        this._persistMessages();
        this._render();
        this._scrollToBottom();
      }
    } catch (err) {
      console.debug("OpenClaw: history sync skipped:", err);
      if (retries > 0) {
        if (this._historySyncRetryTimer) {
          clearTimeout(this._historySyncRetryTimer);
        }
        this._historySyncRetryTimer = setTimeout(() => {
          this._syncHistoryFromBackend(retries - 1);
        }, 1500);
      }
    }
  }

  async _loadIntegrationSettings(includePipeline = true) {
    if (!this._hass) return;

    try {
      let result;
      if (typeof this._hass.callWS === "function") {
        result = await this._hass.callWS({ type: "openclaw/get_settings" });
      } else {
        result = await this._hass.connection.sendMessagePromise({
          type: "openclaw/get_settings",
        });
      }

      this._wakeWordEnabled = this._coerceBoolean(result?.wake_word_enabled, false);
      this._wakeWord = (result?.wake_word || "hey openclaw").toString().trim().toLowerCase();
      this._allowBraveWebSpeechIntegration = !!result?.allow_brave_webspeech;
      this._voiceProviderIntegration =
        result?.voice_provider === "assist_stt" ? "assist_stt" : "browser";
      this._integrationBrowserVoiceLanguage =
        result?.browser_voice_language && result?.browser_voice_language !== "auto"
          ? this._normalizeSpeechLanguage(result.browser_voice_language)
          : null;
      this._integrationVoiceLanguage = result?.language
        ? this._normalizeSpeechLanguage(result.language)
        : null;

      if (includePipeline) {
        try {
        let pipelineResult;
        if (typeof this._hass.callWS === "function") {
          pipelineResult = await this._hass.callWS({ type: "assist_pipeline/pipeline/list" });
        } else {
          pipelineResult = await this._hass.connection.sendMessagePromise({
            type: "assist_pipeline/pipeline/list",
          });
        }

        const preferredPipelineId = pipelineResult?.preferred_pipeline;
        const pipelines = Array.isArray(pipelineResult?.pipelines)
          ? pipelineResult.pipelines
          : [];
        const preferredPipeline =
          pipelines.find((pipeline) => pipeline?.id === preferredPipelineId) || pipelines[0];
        this._preferredAssistSttEngine = preferredPipeline?.stt_engine || null;

        const sttLanguage = preferredPipeline?.stt_language || preferredPipeline?.language;
        const ttsLanguage =
          preferredPipeline?.tts_language || preferredPipeline?.language || preferredPipeline?.stt_language;

        if (sttLanguage) {
          this._integrationVoiceLanguage = this._normalizeSpeechLanguage(sttLanguage);
        }
        if (ttsLanguage) {
          this._integrationTtsLanguage = this._normalizeSpeechLanguage(ttsLanguage);
        }
        } catch (pipelineErr) {
          console.debug("OpenClaw: assist pipeline language detection skipped:", pipelineErr);
        }
      }
      this._render();
    } catch (err) {
      console.debug("OpenClaw: settings sync skipped:", err);
    }
  }

  // ── Thinking timer ──────────────────────────────────────────────────

  _startThinkingTimer() {
    if (this._thinkingTimer) return;
    this._thinkingTimer = setTimeout(() => {
      this._thinkingTimer = null;
      if (this._pendingResponses <= 0) return;
      const idx = this._messages.findIndex((m) => m._thinking);
      if (idx >= 0) {
        this._messages[idx] = {
          role: "assistant",
          content: "Response timed out. The model may still be processing — try again.",
          timestamp: new Date().toISOString(),
          _error: true,
        };
        this._pendingResponses = Math.max(0, this._pendingResponses - 1);
      }
      this._isProcessing = this._pendingResponses > 0;
      if (this._isProcessing) {
        this._startThinkingTimer();
      }
      this._persistMessages();
      this._render();
    }, THINKING_TIMEOUT_MS);
  }

  _clearThinkingTimer() {
    if (this._thinkingTimer) {
      clearTimeout(this._thinkingTimer);
      this._thinkingTimer = null;
    }
  }

  // ── Message handling ────────────────────────────────────────────────

  _addMessage(role, content) {
    this._messages.push({
      role,
      content,
      timestamp: new Date().toISOString(),
    });
    this._persistMessages();
  }

  async _sendMessage(text) {
    if (!text || !text.trim() || !this._hass) return;

    await this._subscribeToEvents();

    const message = text.trim();
    this._addMessage("user", message);

    // Add thinking indicator with timeout safeguard
    this._isProcessing = true;
    this._pendingResponses += 1;
    this._messages.push({
      role: "assistant",
      content: "",
      _thinking: true,
      timestamp: new Date().toISOString(),
    });
    this._startThinkingTimer();

    this._render();
    this._scrollToBottom();

    try {
      await this._hass.callService("openclaw", "send_message", {
        message: message,
        session_id: this._config.session_id || undefined,
      });

      setTimeout(() => {
        this._syncHistoryFromBackend(1);
      }, 1200);
    } catch (err) {
      console.error("OpenClaw: Failed to send message:", err);
      // Replace thinking with error
      let thinkingIdx = -1;
      for (let idx = this._messages.length - 1; idx >= 0; idx -= 1) {
        if (this._messages[idx]?._thinking) {
          thinkingIdx = idx;
          break;
        }
      }
      if (thinkingIdx >= 0) {
        this._messages[thinkingIdx] = {
          role: "assistant",
          content: `Error: ${err.message || "Failed to send message"}`,
          timestamp: new Date().toISOString(),
          _error: true,
        };
      }
      if (this._pendingResponses > 0) {
        this._pendingResponses -= 1;
      }
      this._isProcessing = this._pendingResponses > 0;
      if (!this._isProcessing) {
        this._clearThinkingTimer();
      }
      this._persistMessages();
      this._render();
    }
  }

  // ── Voice ───────────────────────────────────────────────────────────

  _normalizeSpeechLanguage(lang) {
    if (!lang) return "en-US";

    const cleaned = String(lang).trim().replace(/_/g, "-").toLowerCase();
    if (!cleaned) return "en-US";

    if (cleaned.includes("-")) {
      const [base, region] = cleaned.split("-", 2);
      if (base && region) {
        return `${base}-${region.toUpperCase()}`;
      }
    }

    const languageMap = {
      bg: "bg-BG",
      en: "en-US",
      de: "de-DE",
      fr: "fr-FR",
      es: "es-ES",
      it: "it-IT",
      pt: "pt-PT",
      ru: "ru-RU",
      nl: "nl-NL",
      pl: "pl-PL",
      tr: "tr-TR",
      uk: "uk-UA",
      cs: "cs-CZ",
      ro: "ro-RO",
      el: "el-GR",
    };

    return languageMap[cleaned] || `${cleaned}-${cleaned.toUpperCase()}`;
  }

  _coerceBoolean(value, fallback = false) {
    if (typeof value === "boolean") return value;
    if (typeof value === "number") return value !== 0;
    if (typeof value === "string") {
      const normalized = value.trim().toLowerCase();
      if (["true", "1", "yes", "on"].includes(normalized)) return true;
      if (["false", "0", "no", "off", ""].includes(normalized)) return false;
    }
    return fallback;
  }

  _getSpeechRecognitionLanguage() {
    if (this._speechLangOverride) {
      return this._speechLangOverride;
    }

    const configuredLang = this._config.voice_language;
    if (configuredLang) {
      return this._normalizeSpeechLanguage(configuredLang);
    }
    const provider = this._getVoiceProvider();
    if (provider === "browser" && this._integrationBrowserVoiceLanguage) {
      return this._normalizeSpeechLanguage(this._integrationBrowserVoiceLanguage);
    }
    const integrationLang = this._integrationVoiceLanguage;
    const hassLang =
      this._hass?.locale?.language || this._hass?.selectedLanguage || this._hass?.language;
    const browserLang = navigator.language;
    const preferred = configuredLang || integrationLang || hassLang || browserLang || "en-US";
    return this._normalizeSpeechLanguage(preferred);
  }

  _getSpeechSynthesisLanguage() {
    const configuredLang = this._config.voice_language;
    if (configuredLang) {
      return this._normalizeSpeechLanguage(configuredLang);
    }
    const provider = this._getVoiceProvider();
    if (provider === "browser" && this._integrationBrowserVoiceLanguage) {
      return this._normalizeSpeechLanguage(this._integrationBrowserVoiceLanguage);
    }
    const preferred =
      configuredLang ||
      this._integrationTtsLanguage ||
      this._integrationVoiceLanguage ||
      this._hass?.locale?.language ||
      this._hass?.selectedLanguage ||
      this._hass?.language ||
      navigator.language ||
      "en-US";
    return this._normalizeSpeechLanguage(preferred);
  }

  _isLikelyBraveBrowser() {
    const ua = (navigator.userAgent || "").toLowerCase();
    const uaDataBrands = navigator.userAgentData?.brands || [];
    const brandMatch = uaDataBrands.some((brand) =>
      String(brand?.brand || "")
        .toLowerCase()
        .includes("brave")
    );
    return brandMatch || ua.includes("brave") || !!navigator.brave;
  }

  _getVoiceProvider() {
    const configured = this._config.voice_provider;
    if (configured === "assist_stt" || configured === "browser") {
      return configured;
    }
    return this._voiceProviderIntegration || "browser";
  }

  _startVoiceRecognition() {
    const provider = this._getVoiceProvider();
    if (this._isVoiceMode && provider === "assist_stt") {
      this._voiceStatus =
        "Voice mode uses browser speech for continuous listening (Assist STT remains available for manual mic).";
      this._startBrowserVoiceRecognition();
      return;
    }
    if (provider === "assist_stt") {
      this._startAssistSttRecognition();
      return;
    }
    this._startBrowserVoiceRecognition();
  }

  async _startAssistSttRecognition() {
    if (!this._hass) return;

    if (this._isVoiceMode) {
      this._voiceStatus =
        "Continuous voice mode currently requires browser speech. Switch voice provider to browser or disable continuous mode.";
      this._render();
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      this._voiceStatus = "Microphone capture not supported by this browser.";
      this._render();
      return;
    }

    if (!this._preferredAssistSttEngine) {
      this._voiceStatus =
        "No Assist STT engine found in preferred voice pipeline. Configure Voice settings first.";
      this._render();
      return;
    }

    try {
      this._assistAudioChunks = [];
      this._assistAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this._assistAudioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000,
      });
      this._assistInputSampleRate = this._assistAudioContext.sampleRate || 16000;

      this._assistAudioSource = this._assistAudioContext.createMediaStreamSource(this._assistAudioStream);
      this._assistAudioSilenceGain = this._assistAudioContext.createGain();
      this._assistAudioSilenceGain.gain.value = 0;

      let usingWorklet = false;
      if (typeof AudioWorkletNode !== "undefined" && this._assistAudioContext.audioWorklet?.addModule) {
        try {
          const workletSource = `
            class OpenClawAssistCaptureProcessor extends AudioWorkletProcessor {
              process(inputs) {
                const input = inputs[0];
                const channel = input && input[0];
                if (channel && channel.length) {
                  this.port.postMessage(new Float32Array(channel));
                }
                return true;
              }
            }
            registerProcessor("openclaw-assist-capture", OpenClawAssistCaptureProcessor);
          `;
          const blob = new Blob([workletSource], { type: "application/javascript" });
          const moduleUrl = URL.createObjectURL(blob);
          try {
            await this._assistAudioContext.audioWorklet.addModule(moduleUrl);
          } finally {
            URL.revokeObjectURL(moduleUrl);
          }

          this._assistAudioWorkletNode = new AudioWorkletNode(
            this._assistAudioContext,
            "openclaw-assist-capture",
            {
              numberOfInputs: 1,
              numberOfOutputs: 1,
              channelCount: 1,
            }
          );
          this._assistAudioWorkletNode.port.onmessage = (event) => {
            const chunk = event.data;
            if (chunk && chunk.length) {
              this._assistAudioChunks.push(new Float32Array(chunk));
            }
          };

          this._assistAudioSource.connect(this._assistAudioWorkletNode);
          this._assistAudioWorkletNode.connect(this._assistAudioSilenceGain);
          usingWorklet = true;
        } catch (workletErr) {
          console.debug("OpenClaw: AudioWorklet capture unavailable, falling back", workletErr);
          this._assistAudioWorkletNode = null;
        }
      }

      if (!usingWorklet) {
        this._assistAudioProcessor = this._assistAudioContext.createScriptProcessor(4096, 1, 1);
        this._assistAudioProcessor.onaudioprocess = (event) => {
          const input = event.inputBuffer.getChannelData(0);
          this._assistAudioChunks.push(new Float32Array(input));
        };
        this._assistAudioSource.connect(this._assistAudioProcessor);
        this._assistAudioProcessor.connect(this._assistAudioSilenceGain);
      }

      this._assistAudioSilenceGain.connect(this._assistAudioContext.destination);

      this._assistRecordingActive = true;
      this._recognition = { engine: "assist_stt" };
      this._voiceStatus = "Listening with Home Assistant STT…";
      this._render();

      if (this._assistAutoStopTimer) {
        clearTimeout(this._assistAutoStopTimer);
      }
      this._assistAutoStopTimer = setTimeout(() => {
        this._stopAssistSttRecognition(true);
      }, 4500);
    } catch (err) {
      console.error("OpenClaw: failed to start Assist STT recording", err);
      this._voiceStatus = "Could not start microphone recording for Assist STT.";
      this._assistRecordingActive = false;
      this._recognition = null;
      this._render();
    }
  }

  async _stopAssistSttRecognition(processAudio) {
    if (this._assistAutoStopTimer) {
      clearTimeout(this._assistAutoStopTimer);
      this._assistAutoStopTimer = null;
    }

    if (this._assistAudioProcessor) {
      this._assistAudioProcessor.disconnect();
      this._assistAudioProcessor.onaudioprocess = null;
      this._assistAudioProcessor = null;
    }
    if (this._assistAudioWorkletNode) {
      this._assistAudioWorkletNode.disconnect();
      this._assistAudioWorkletNode.port.onmessage = null;
      this._assistAudioWorkletNode = null;
    }
    if (this._assistAudioSource) {
      this._assistAudioSource.disconnect();
      this._assistAudioSource = null;
    }
    if (this._assistAudioSilenceGain) {
      this._assistAudioSilenceGain.disconnect();
      this._assistAudioSilenceGain = null;
    }
    if (this._assistAudioStream) {
      for (const track of this._assistAudioStream.getTracks()) {
        track.stop();
      }
      this._assistAudioStream = null;
    }
    if (this._assistAudioContext) {
      try {
        await this._assistAudioContext.close();
      } catch (e) {
        // ignore
      }
      this._assistAudioContext = null;
    }

    this._assistRecordingActive = false;
    this._recognition = null;

    if (!processAudio) {
      this._voiceStatus = "";
      this._render();
      return;
    }

    if (!this._assistAudioChunks.length) {
      this._voiceStatus = "No speech detected. Tap mic and try again.";
      this._render();
      return;
    }

    this._voiceStatus = "Transcribing with Home Assistant STT…";
    this._render();

    try {
      const language = this._getSpeechRecognitionLanguage();
      const token = this._hass?.auth?.data?.access_token;

      let providerInfo = null;
      try {
        const providerResponse = await fetch(
          `/api/stt/${encodeURIComponent(this._preferredAssistSttEngine)}`,
          {
            method: "GET",
            headers: token ? { Authorization: `Bearer ${token}` } : {},
          }
        );
        if (providerResponse.ok) {
          providerInfo = await providerResponse.json();
        }
      } catch (providerErr) {
        console.debug("OpenClaw: Assist STT provider info fetch failed:", providerErr);
      }

      const negotiatedLanguage = this._pickAssistSttLanguage(language, providerInfo?.languages);
      const negotiatedSampleRate = this._pickAssistSttSampleRate(providerInfo?.sample_rates);
      const negotiatedChannel = this._pickAssistSttChannel(providerInfo?.channels);

      const wavBuffer = this._encodeWavFromChunks(
        this._assistAudioChunks,
        this._assistInputSampleRate,
        negotiatedSampleRate,
        negotiatedChannel
      );
      this._assistAudioChunks = [];

      const response = await fetch(
        `/api/stt/${encodeURIComponent(this._preferredAssistSttEngine)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "audio/wav",
            "X-Speech-Content":
              `format=wav; codec=pcm; sample_rate=${negotiatedSampleRate}; bit_rate=16; channel=${negotiatedChannel}; language=${negotiatedLanguage}`,
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: new Blob([wavBuffer], { type: "audio/wav" }),
        }
      );

      if (!response.ok) {
        this._voiceStatus = `Assist STT error (${response.status}).`;
        this._render();
        return;
      }

      const sttResult = await response.json();
      const transcript = String(sttResult?.text || "").trim();
      if (!transcript) {
        this._voiceStatus = "No speech recognized by Assist STT.";
        this._render();
        return;
      }

      this._voiceStatus = "Sending…";
      this._render();
      this._sendMessage(transcript);
    } catch (err) {
      console.error("OpenClaw: Assist STT transcription failed", err);
      this._voiceStatus = "Assist STT transcription failed.";
      this._render();
    }
  }

  _downsampleBuffer(input, inputSampleRate, outputSampleRate) {
    if (outputSampleRate >= inputSampleRate) {
      return input;
    }
    const sampleRateRatio = inputSampleRate / outputSampleRate;
    const outputLength = Math.round(input.length / sampleRateRatio);
    const outputBuffer = new Float32Array(outputLength);

    let outputOffset = 0;
    let inputOffset = 0;
    while (outputOffset < outputLength) {
      const nextInputOffset = Math.round((outputOffset + 1) * sampleRateRatio);
      let accumulator = 0;
      let count = 0;
      for (let idx = inputOffset; idx < nextInputOffset && idx < input.length; idx += 1) {
        accumulator += input[idx];
        count += 1;
      }
      outputBuffer[outputOffset] = count > 0 ? accumulator / count : 0;
      outputOffset += 1;
      inputOffset = nextInputOffset;
    }

    return outputBuffer;
  }

  _pickAssistSttLanguage(preferredLanguage, supportedLanguages) {
    if (!Array.isArray(supportedLanguages) || !supportedLanguages.length) {
      return preferredLanguage;
    }

    const preferred = String(preferredLanguage || "").toLowerCase();
    const supported = supportedLanguages.map((value) => String(value || "")).filter(Boolean);

    const exact = supported.find((value) => value.toLowerCase() === preferred);
    if (exact) return exact;

    const preferredBase = preferred.split("-")[0];
    if (preferredBase) {
      const baseExact = supported.find((value) => value.toLowerCase() === preferredBase);
      if (baseExact) return baseExact;

      const prefix = supported.find((value) => value.toLowerCase().startsWith(`${preferredBase}-`));
      if (prefix) return prefix;
    }

    return supported[0];
  }

  _pickAssistSttSampleRate(supportedSampleRates) {
    if (!Array.isArray(supportedSampleRates) || !supportedSampleRates.length) {
      return 16000;
    }

    const numericRates = supportedSampleRates
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0);

    if (!numericRates.length) return 16000;
    if (numericRates.includes(16000)) return 16000;
    return numericRates[0];
  }

  _pickAssistSttChannel(supportedChannels) {
    if (!Array.isArray(supportedChannels) || !supportedChannels.length) {
      return 1;
    }

    const asNumbers = supportedChannels
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value) && value > 0);
    if (asNumbers.length) {
      if (asNumbers.includes(1)) return 1;
      return asNumbers[0];
    }

    const normalized = supportedChannels.map((value) => String(value).toLowerCase());
    if (normalized.includes("channel_mono")) return 1;
    if (normalized.includes("channel_stereo")) return 2;

    return 1;
  }

  _encodeWavFromChunks(chunks, inputSampleRate, outputSampleRate = 16000, channels = 1) {
    let totalLength = 0;
    for (const chunk of chunks) {
      totalLength += chunk.length;
    }

    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    const downsampled = this._downsampleBuffer(merged, inputSampleRate, outputSampleRate);
    const frameCount = downsampled.length;
    const sampleCount = frameCount * channels;
    const bytesPerSample = 2;
    const blockAlign = channels * bytesPerSample;
    const byteRate = outputSampleRate * blockAlign;
    const buffer = new ArrayBuffer(44 + sampleCount * bytesPerSample);
    const view = new DataView(buffer);

    const writeString = (dataView, start, value) => {
      for (let idx = 0; idx < value.length; idx += 1) {
        dataView.setUint8(start + idx, value.charCodeAt(idx));
      }
    };

    writeString(view, 0, "RIFF");
    view.setUint32(4, 36 + sampleCount * bytesPerSample, true);
    writeString(view, 8, "WAVE");
    writeString(view, 12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, channels, true);
    view.setUint32(24, outputSampleRate, true);
    view.setUint32(28, byteRate, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, "data");
    view.setUint32(40, sampleCount * bytesPerSample, true);

    let wavOffset = 44;
    for (let idx = 0; idx < frameCount; idx += 1) {
      const sample = Math.max(-1, Math.min(1, downsampled[idx]));
      const pcm = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      for (let channelIndex = 0; channelIndex < channels; channelIndex += 1) {
        view.setInt16(wavOffset, pcm, true);
        wavOffset += 2;
      }
    }

    return buffer;
  }

  _startBrowserVoiceRecognition() {
    this._voiceBackendBlocked = false;
    this._voiceStopRequested = false;
    const allowBraveWebSpeech =
      this._config.allow_brave_webspeech || this._allowBraveWebSpeechIntegration;

    if (this._isLikelyBraveBrowser() && !allowBraveWebSpeech) {
      this._voiceStatus =
        "Voice input disabled on Brave by default due browser SpeechRecognition network failures. Use Chrome/Edge, or set allow_brave_webspeech: true in card config to force-enable experimental mode.";
      this._render();
      return;
    }

    if (!("webkitSpeechRecognition" in window) && !("SpeechRecognition" in window)) {
      console.warn("OpenClaw: Speech recognition not supported in this browser");
      this._render();
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    this._recognition = new SpeechRecognition();
    this._recognition.continuous = this._isVoiceMode;
    this._recognition.lang = this._getSpeechRecognitionLanguage();
    this._voiceStatus = this._isVoiceMode
      ? this._wakeWordEnabled
        ? `Listening (${this._recognition.lang}, wake word: ${this._wakeWord || "hey openclaw"})`
        : `Listening (${this._recognition.lang})`
      : `Listening (${this._recognition.lang})…`;

    this._recognition.onresult = (event) => {
      const result = event.results[event.results.length - 1];
      if (result.isFinal) {
        const text = result[0].transcript?.trim();
        if (!text) return;

        const requireWakeWord = this._wakeWordEnabled && this._isVoiceMode;

        if (requireWakeWord) {
          const wake = this._wakeWord || "hey openclaw";
          const lower = text.toLowerCase();
          const wakePos = lower.indexOf(wake);
          if (wakePos < 0) {
            this._voiceStatus = `Heard: \"${text}\" (waiting for wake word)`;
            this._render();
            return;
          }

          let command = text.slice(wakePos + wake.length).trim();
          command = command.replace(/^[,:;.!?\-]+\s*/, "");
          if (!command) {
            this._voiceStatus = "Wake word detected. Say command after wake word.";
            this._render();
            return;
          }
          this._voiceStatus = "Sending…";
          this._render();
          this._sendMessage(command);
          return;
        }

        this._voiceStatus = "Sending…";
        this._render();
        this._sendMessage(text);
      }
    };

    this._recognition.onerror = (event) => {
      const err = event?.error || "unknown";
      if (err === "aborted") {
        if (this._voiceStopRequested) {
          return;
        }
        console.debug("OpenClaw: Speech recognition aborted");
        return;
      }
      if (err === "no-speech") {
        this._voiceStatus = this._isVoiceMode
          ? "Listening… (no speech detected yet)"
          : "No speech detected. Tap mic and try again.";
        this._render();
        return;
      }
      if (err === "network") {
        console.warn("OpenClaw: Speech recognition network error");
      } else {
        console.error("OpenClaw: Speech recognition error:", err);
      }
      if (err === "network") {
        this._voiceNetworkErrorCount += 1;
        const browserLocale = this._normalizeSpeechLanguage(navigator.language || "en-US");
        if (!this._speechLangOverride && browserLocale !== this._recognition.lang) {
          this._speechLangOverride = browserLocale;
          this._voiceStatus =
            "Voice network error: browser speech service unavailable. Retrying with fallback locale…";
        } else {
          const braveLikely = this._isLikelyBraveBrowser();
          if (braveLikely && this._voiceNetworkErrorCount >= 2) {
            this._voiceBackendBlocked = true;
            this._voiceStatus =
              "Brave speech backend blocked (network error). Voice input is unavailable in this browser session. Use Chrome/Edge for voice, or continue with text input.";
          } else {
            this._voiceStatus =
              "Voice network error: browser speech service unavailable. Retrying…";
          }
        }
      } else if (err === "not-allowed") {
        this._voiceStatus = "Microphone access denied. Allow mic permission for this site.";
      } else if (err === "audio-capture") {
        this._voiceStatus = "No microphone available.";
      } else {
        this._voiceStatus = `Voice error: ${err}`;
      }

      if (["network", "audio-capture"].includes(err) && !this._voiceBackendBlocked) {
        this._scheduleVoiceRetry();
      }
      this._render();
    };

    this._recognition.onend = () => {
      if (this._voiceStopRequested) {
        this._voiceStopRequested = false;
        if (!this._isVoiceMode) {
          this._voiceStatus = "";
          this._render();
        }
        return;
      }

      if (this._isVoiceMode) {
        // Restart recognition in voice mode
        try {
          this._recognition.start();
        } catch (e) {
          // Ignore — may already be started
        }
      } else {
        this._voiceStatus = "";
        this._render();
      }
    };

    this._recognition.start();
    this._render();
  }

  _stopVoiceRecognition() {
    if (this._assistRecordingActive) {
      this._stopAssistSttRecognition(true);
    }

    if (this._recognition) {
      if (this._recognition.engine !== "assist_stt") {
        this._voiceStopRequested = true;
        this._recognition.abort();
      }
      this._recognition = null;
    }
    if (this._voiceRetryTimer) {
      clearTimeout(this._voiceRetryTimer);
      this._voiceRetryTimer = null;
    }
    this._voiceRetryCount = 0;
    this._voiceNetworkErrorCount = 0;
    this._isVoiceMode = false;
    this._voiceStatus = "";
  }

  _scheduleVoiceRetry() {
    if (this._voiceBackendBlocked) return;
    if (!this._isVoiceMode && !this._speechLangOverride) return;
    if (this._voiceRetryCount >= 6) {
      this._voiceStatus =
        "Voice retry stopped after repeated errors. Toggle voice mode to try again.";
      this._render();
      return;
    }

    if (this._voiceRetryTimer) {
      clearTimeout(this._voiceRetryTimer);
    }

    const delayMs = Math.min(1000 * (this._voiceRetryCount + 1), 6000);
    this._voiceRetryCount += 1;
    this._voiceStatus = `Voice reconnecting in ${Math.ceil(delayMs / 1000)}s…`;
    this._render();

    this._voiceRetryTimer = setTimeout(() => {
      this._voiceRetryTimer = null;
      if (!this._isVoiceMode) return;
      this._startVoiceRecognition();
    }, delayMs);
  }

  async _toggleVoiceMode() {
    await this._loadIntegrationSettings(false);
    this._isVoiceMode = !this._isVoiceMode;
    if (this._isVoiceMode) {
      this._startVoiceRecognition();
    } else {
      this._stopVoiceRecognition();
    }
    this._render();
  }

  _speak(text) {
    if (!("speechSynthesis" in window)) return;
    // Strip markdown for TTS
    const plain = text.replace(/[*_`#\[\]()]/g, "");
    const language = this._getSpeechSynthesisLanguage();

    const speakNow = () => {
      const utterance = new SpeechSynthesisUtterance(plain);
      utterance.lang = language;

      const voices = speechSynthesis.getVoices() || [];
      if (voices.length) {
        const exactVoice = voices.find(
          (voice) => String(voice.lang || "").toLowerCase() === language.toLowerCase()
        );
        const prefix = language.split("-")[0]?.toLowerCase();
        const languageVoice =
          exactVoice ||
          voices.find((voice) => String(voice.lang || "").toLowerCase().startsWith(`${prefix}-`));
        if (languageVoice) {
          utterance.voice = languageVoice;
        }
      }

      utterance.onerror = () => {
        this._voiceStatus = `TTS error for language ${language}`;
        this._render();
      };

      try {
        speechSynthesis.cancel();
      } catch (e) {
        // ignore
      }
      speechSynthesis.speak(utterance);
    };

    const loadedVoices = speechSynthesis.getVoices() || [];
    if (loadedVoices.length) {
      speakNow();
      return;
    }

    const handleVoicesChanged = () => {
      speechSynthesis.removeEventListener("voiceschanged", handleVoicesChanged);
      speakNow();
    };
    speechSynthesis.addEventListener("voiceschanged", handleVoicesChanged);
    setTimeout(() => {
      speechSynthesis.removeEventListener("voiceschanged", handleVoicesChanged);
      speakNow();
    }, 800);
  }

  // ── File attachments ────────────────────────────────────────────────

  _handleFileAttachment() {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.accept = "image/*,.pdf,.txt,.md,.json,.csv";
    input.onchange = (e) => {
      const files = Array.from(e.target.files);
      if (files.length > 0) {
        // TODO: Implement file upload via service call
        const names = files.map((f) => f.name).join(", ");
        this._addMessage("user", `📎 Attached: ${names}`);
        this._render();
      }
    };
    input.click();
  }

  // ── UI helpers ──────────────────────────────────────────────────────

  _scrollToBottom() {
    requestAnimationFrame(() => {
      const container = this.shadowRoot?.querySelector(".messages");
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    });
  }

  _formatTime(isoString) {
    if (!isoString) return "";
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

  // ── Render ──────────────────────────────────────────────────────────

  _render() {
    const config = this._config;
    const messages = this._messages;

    const messagesHtml = messages
      .map((msg) => {
        const isUser = msg.role === "user";
        const isThinking = msg._thinking;
        const isError = msg._error;

        let contentHtml;
        if (isThinking) {
          contentHtml = `<div class="thinking"><span></span><span></span><span></span></div>`;
        } else if (isError) {
          contentHtml = `<div class="error">${this._escapeHtml(msg.content)}</div>`;
        } else if (isUser) {
          contentHtml = this._escapeHtml(msg.content);
        } else {
          contentHtml = renderMarkdown(msg.content);
        }

        const timeHtml =
          config.show_timestamps && msg.timestamp
            ? `<div class="time">${this._formatTime(msg.timestamp)}</div>`
            : "";

        return `
          <div class="msg ${isUser ? "user" : "assistant"}">
            <div class="bubble">${contentHtml}</div>
            ${timeHtml}
          </div>`;
      })
      .join("");

    const voiceActive = this._recognition !== null;
    const gatewayState = this._getGatewayConnectionState();

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --oc-bg: var(--card-background-color, #1c1c1c);
          --oc-msg-user: var(--primary-color, #2563eb);
          --oc-msg-assistant: var(--secondary-background-color, #2a2a2a);
          --oc-text: var(--primary-text-color, #e6edf3);
          --oc-text-secondary: var(--secondary-text-color, #9ca3af);
          --oc-border: var(--divider-color, #333);
          --oc-radius: 12px;
        }
        ha-card {
          overflow: hidden;
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--oc-border);
        }
        .header h3 {
          margin: 0;
          font-size: 16px;
          font-weight: 500;
          color: var(--oc-text);
        }
        .header-title {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .gateway-status {
          font-size: 11px;
          border: 1px solid var(--oc-border);
          border-radius: 999px;
          padding: 2px 8px;
          color: var(--oc-text-secondary);
        }
        .gateway-status.online {
          color: #10b981;
        }
        .gateway-status.offline {
          color: #ef4444;
        }
        .header-actions {
          display: flex;
          gap: 8px;
        }
        .icon-btn {
          background: none;
          border: none;
          color: var(--oc-text-secondary);
          cursor: pointer;
          padding: 4px;
          border-radius: 6px;
          font-size: 20px;
          line-height: 1;
        }
        .icon-btn:hover { color: var(--oc-text); background: var(--oc-border); }
        .icon-btn.active { color: var(--oc-msg-user); }
        .messages {
          height: ${config.height || "500px"};
          overflow-y: auto;
          padding: 12px 16px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .msg {
          display: flex;
          flex-direction: column;
          max-width: 85%;
        }
        .msg.user {
          align-self: flex-end;
          align-items: flex-end;
        }
        .msg.assistant {
          align-self: flex-start;
          align-items: flex-start;
        }
        .bubble {
          padding: 10px 14px;
          border-radius: var(--oc-radius);
          font-size: 14px;
          line-height: 1.5;
          color: var(--oc-text);
          word-wrap: break-word;
          overflow-wrap: break-word;
        }
        .msg.user .bubble {
          background: var(--oc-msg-user);
          color: white;
          border-bottom-right-radius: 4px;
        }
        .msg.assistant .bubble {
          background: var(--oc-msg-assistant);
          border-bottom-left-radius: 4px;
        }
        .bubble code {
          background: rgba(0,0,0,0.3);
          padding: 1px 4px;
          border-radius: 4px;
          font-size: 13px;
        }
        .bubble pre {
          background: rgba(0,0,0,0.3);
          padding: 8px;
          border-radius: 6px;
          overflow-x: auto;
          margin: 4px 0;
        }
        .bubble pre code {
          background: none;
          padding: 0;
        }
        .bubble a { color: #60a5fa; }
        .time {
          font-size: 11px;
          color: var(--oc-text-secondary);
          margin-top: 2px;
          padding: 0 4px;
        }
        .error { color: #ef4444; }
        .thinking {
          display: flex;
          gap: 4px;
          padding: 4px 0;
        }
        .thinking span {
          width: 8px;
          height: 8px;
          background: var(--oc-text-secondary);
          border-radius: 50%;
          animation: bounce 1.4s infinite ease-in-out both;
        }
        .thinking span:nth-child(1) { animation-delay: -0.32s; }
        .thinking span:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce {
          0%, 80%, 100% { transform: scale(0); }
          40% { transform: scale(1); }
        }
        .input-area {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          padding: 12px 16px;
          border-top: 1px solid var(--oc-border);
        }
        .input-area textarea {
          flex: 1;
          resize: none;
          border: 1px solid var(--oc-border);
          border-radius: var(--oc-radius);
          background: var(--oc-bg);
          color: var(--oc-text);
          padding: 10px 14px;
          font-family: inherit;
          font-size: 14px;
          line-height: 1.4;
          min-height: 20px;
          max-height: 120px;
          outline: none;
        }
        .input-area textarea:focus {
          border-color: var(--oc-msg-user);
        }
        .send-btn {
          background: var(--oc-msg-user);
          color: white;
          border: none;
          border-radius: 50%;
          width: 40px;
          height: 40px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          font-size: 18px;
        }
        .send-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }
        .empty-state {
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--oc-text-secondary);
          font-size: 14px;
        }
        .voice-indicator {
          display: inline-block;
          width: 10px;
          height: 10px;
          background: #ef4444;
          border-radius: 50%;
          animation: pulse 1.5s infinite;
          margin-right: 4px;
        }
        .voice-status {
          padding: 4px 16px 0 16px;
          font-size: 12px;
          color: var(--oc-text-secondary);
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-title">
            <h3>${this._escapeHtml(config.title)}</h3>
            <span class="gateway-status ${gatewayState.css}">Gateway: ${gatewayState.label}</span>
          </div>
          <div class="header-actions">
            ${
              config.show_voice_button
                ? `<button class="icon-btn ${voiceActive ? "active" : ""}"
                     id="voice-btn"
                     title="${voiceActive ? "Stop voice" : "Voice input"}">
                     ${voiceActive ? '<span class="voice-indicator"></span>🎙️' : "🎙️"}
                   </button>
                   <button class="icon-btn ${this._isVoiceMode ? "active" : ""}"
                     id="voice-mode-btn"
                     title="Toggle voice mode (continuous)">
                     🔊
                   </button>`
                : ""
            }
            <button class="icon-btn" id="attach-btn" title="Attach file">📎</button>
            ${config.show_clear_button ? '<button class="icon-btn" id="clear-btn" title="Clear chat">🗑️</button>' : ''}
          </div>
        </div>

        <div class="messages" id="messages">
          ${
            messages.length === 0
              ? '<div class="empty-state">Send a message to start a conversation</div>'
              : messagesHtml
          }
        </div>

        ${this._voiceStatus ? `<div class="voice-status">${this._escapeHtml(this._voiceStatus)}</div>` : ""}

        <div class="input-area">
          <textarea
            id="input"
            rows="1"
            placeholder="Type a message..."
            ${this._isProcessing ? "disabled" : ""}
          ></textarea>
          <button class="send-btn" id="send-btn" ${this._isProcessing ? "disabled" : ""}>➤</button>
        </div>
      </ha-card>
    `;

    // ── Event listeners ────────────────────────────────────────────
    const input = this.shadowRoot.getElementById("input");
    const sendBtn = this.shadowRoot.getElementById("send-btn");
    const attachBtn = this.shadowRoot.getElementById("attach-btn");
    const voiceBtn = this.shadowRoot.getElementById("voice-btn");
    const voiceModeBtn = this.shadowRoot.getElementById("voice-mode-btn");

    if (input) {
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this._sendMessage(input.value);
          input.value = "";
        }
      });
      // Auto-resize textarea
      input.addEventListener("input", () => {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
      });
    }

    if (sendBtn) {
      sendBtn.addEventListener("click", () => {
        if (input) {
          this._sendMessage(input.value);
          input.value = "";
          input.style.height = "auto";
        }
      });
    }

    if (attachBtn) {
      attachBtn.addEventListener("click", () => this._handleFileAttachment());
    }

    if (voiceBtn) {
      voiceBtn.addEventListener("click", () => {
        if (this._recognition) {
          this._stopVoiceRecognition();
          this._render();
        } else {
          this._startVoiceRecognition();
        }
      });
    }

    if (voiceModeBtn) {
      voiceModeBtn.addEventListener("click", () => this._toggleVoiceMode());
    }

    const clearBtn = this.shadowRoot.getElementById("clear-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        if (confirm("Clear chat history?")) this._clearChat();
      });
    }

    this._scrollToBottom();
  }

  _escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }
}

// ── Card editor element ─────────────────────────────────────────────────────

class OpenClawChatCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  set hass(_hass) {
    // We don't need hass reference in the editor
  }

  _render() {
    const c = this._config;
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        .row { display: flex; align-items: center; padding: 8px 0; }
        .row label { flex: 1; font-size: 14px; color: var(--primary-text-color); }
        .row input[type="text"] {
          flex: 1;
          padding: 6px 10px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 6px;
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color);
          font-size: 14px;
        }
        .row input[type="checkbox"] {
          width: 18px; height: 18px;
        }
      </style>
      <div>
        <div class="row">
          <label for="title">Title</label>
          <input type="text" id="title" value="${this._esc(c.title || "OpenClaw Chat")}" />
        </div>
        <div class="row">
          <label for="height">Height</label>
          <input type="text" id="height" value="${this._esc(c.height || "500px")}" />
        </div>
        <div class="row">
          <label for="session_id">Session ID (optional)</label>
          <input type="text" id="session_id" value="${this._esc(c.session_id || "")}" />
        </div>
        <div class="row">
          <label for="show_timestamps">Show timestamps</label>
          <input type="checkbox" id="show_timestamps" ${c.show_timestamps !== false ? "checked" : ""} />
        </div>
        <div class="row">
          <label for="show_voice_button">Show voice button</label>
          <input type="checkbox" id="show_voice_button" ${c.show_voice_button !== false ? "checked" : ""} />
        </div>
        <div class="row">
          <label for="show_clear_button">Show clear button</label>
          <input type="checkbox" id="show_clear_button" ${c.show_clear_button !== false ? "checked" : ""} />
        </div>
      </div>
    `;

    // Bind events
    for (const id of ["title", "height", "session_id"]) {
      const el = this.shadowRoot.getElementById(id);
      if (el) {
        el.addEventListener("change", (e) => this._fireChanged(id, e.target.value));
      }
    }
    for (const id of ["show_timestamps", "show_voice_button", "show_clear_button"]) {
      const el = this.shadowRoot.getElementById(id);
      if (el) {
        el.addEventListener("change", (e) => this._fireChanged(id, e.target.checked));
      }
    }
  }

  _fireChanged(key, value) {
    this._config = { ...this._config, [key]: value };
    const event = new CustomEvent("config-changed", {
      detail: { config: this._config },
      bubbles: true,
      composed: true,
    });
    this.dispatchEvent(event);
  }

  _esc(str) {
    return String(str).replace(/"/g, "&quot;").replace(/</g, "&lt;");
  }
}

// ── Card registration ───────────────────────────────────────────────────────

if (!customElements.get("openclaw-chat-card-editor")) {
  customElements.define("openclaw-chat-card-editor", OpenClawChatCardEditor);
}

if (!customElements.get("openclaw-chat-card")) {
  customElements.define("openclaw-chat-card", OpenClawChatCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some((card) => card?.type === "openclaw-chat-card")) {
  window.customCards.push({
    type: "openclaw-chat-card",
    name: "OpenClaw Chat",
    description: "Chat interface for OpenClaw AI Assistant with streaming, voice, and file support.",
    preview: true,
  });
}

console.info(
  `%c OPENCLAW-CHAT-CARD %c v${CARD_VERSION} `,
  "color: white; background: #2563eb; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #2563eb; background: #e5e7eb; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);

console.info("OPENCLAW-CHAT-CARD source", import.meta.url);
