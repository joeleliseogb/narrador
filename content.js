(function () {
  "use strict";

  const DEFAULTS = {
    enabled: true,
    rate: 1.0,
    pitch: 1.0,
    volume: 1.0,
    voiceURI: "",
    lang: "es-ES",
    autoEnableCC: false,
    autoSync: true,
    maxSyncRate: 2.0,
    pauseWhileLoadingSubs: true,
    catchUpMode: "playthrough",
    minVideoRate: 0.65,
    ttsEngine: "local",
    muteVideoWhileNarrating: true,
    /** Volumen del vídeo mientras narra (0.15 = 15 %). */
    videoDuckVolume: 0.15,
  };

  const VIDEO_DUCK_VOLUME_DEFAULT = 0.15;

  const SYNC_INTERVAL_MS = 50;
  const SEEK_THRESHOLD_MS = 500;
  const SCENE_START_TOLERANCE_MS = 220;
  /** Si el hueco entre escenas es menor que esto, narrar la siguiente sin reanudar el vídeo. */
  const SCENE_CHAIN_GAP_MS = 2800;
  const CHARS_PER_SEC = 7;
  const WORDS_PER_SEC = 2.0;
  const SPEECH_DURATION_MARGIN = 1.15;
  const DOM_STABLE_MS = 700;
  const DOM_STABLE_POLLS = 4;
  const DOM_MAX_WAIT_MS = 1200;

  let settings = { ...DEFAULTS };
  let cues = [];
  let captionStatus = "idle";
  let lastVideoId = null;
  let syncTimer = null;
  let uiTimer = null;
  let voiceUnlocked = false;
  let lastSpokenLine = "";
  let lastSpokenIndex = -1;
  let lastVideoTimeMs = 0;
  let currentSpeakingIndex = -1;
  let widget = null;
  let isSpeaking = false;
  let voiceCount = 0;
  let pageVoices = [];
  let useNative = false;
  let nativeEngine = null;
  let nativeEngines = [];
  let speakTimer = null;
  let pendingDomText = "";
  let domLastSpokenText = "";
  let domDebounceTimer = null;
  let domClearTimer = null;
  let domTextSince = 0;
  let domSceneStartVideoMs = 0;
  let domStablePolls = 0;
  let debugSyncLine = "";
  let downloadingFor = null;
  let downloadStartedAt = 0;
  let lastSceneKey = "";
  let pauseForLoadActive = false;
  let wasPlayingBeforeLoad = false;
  let lastSpeakError = "";
  let pendingSpeakIndex = -1;
  let pendingSpeakTimer = null;
  let savedYouTubeRate = null;
  let downloadAttemptNum = 0;
  let downloadRawSegments = 0;
  let lastSyncAt = 0;
  let pauseForSpeechActive = false;
  let wasPlayingBeforeSpeech = false;
  let ttsLatencyMs = 1800;
  let speakRequestAt = 0;
  let downloadRetryTimer = null;
  let savedVideoMuted = null;
  let savedVideoVolume = null;
  let syncSeekInProgress = false;
  let speakEpoch = 0;
  let narrationArmed = false;
  let captionSourceLang = "";
  let captionTranslated = false;

  const LANG_LABELS = {
    es: "español",
    en: "inglés",
    zh: "chino",
    ja: "japonés",
    ko: "coreano",
    fr: "francés",
    de: "alemán",
    pt: "portugués",
  };

  function langPrefCode() {
    return (settings.lang || "es-ES").split("-")[0].toLowerCase();
  }

  function langMatches(code, pref) {
    const c = String(code || "")
      .toLowerCase()
      .replace("_", "-");
    const p = String(pref || langPrefCode())
      .split("-")[0]
      .toLowerCase();
    return c === p || c.startsWith(`${p}-`);
  }

  function trackMatchesLang(track, pref) {
    return langMatches(track?.languageCode || track?.lang, pref);
  }

  function langLabel(code) {
    const base = String(code || "")
      .split("-")[0]
      .toLowerCase();
    return LANG_LABELS[base] || base;
  }

  function ttsLangForCaptions() {
    const code = (captionSourceLang || settings.lang || "es-ES").split("-")[0].toLowerCase();
    if (code === "es") return "es-ES";
    if (code === "en") return "en-US";
    if (code === "pt") return "pt-BR";
    return settings.lang || "es-ES";
  }

  function captionLangHint() {
    if (!captionSourceLang) return "";
    const pref = langPrefCode();
    const src = langLabel(captionSourceLang);
    if (captionTranslated) return ` · ${src} (traducidos)`;
    if (!langMatches(captionSourceLang, pref)) {
      return ` · ${src} (popup: ${langLabel(pref)})`;
    }
    return ` · ${src}`;
  }

  /** Idioma que YouTube muestra (traducción CC activa) o el del popup. */
  function getCaptionTargetLang() {
    const pref = langPrefCode();
    const player = document.getElementById("movie_player");
    if (player?.getOption) {
      try {
        const trans = player.getOption("captions", "translationLanguage");
        const code =
          trans?.languageCode ||
          trans?.language ||
          (typeof trans === "string" ? trans : "");
        if (code) return String(code).split("-")[0].toLowerCase();
      } catch {
        /* */
      }
    }
    return pref;
  }

  function textLooksLikeLang(text, pref) {
    const sample = String(text || "")
      .slice(0, 2500)
      .toLowerCase();
    if (!sample.trim()) return false;
    if (pref === "es") {
      if (/[áéíóúñ¿¡]/.test(sample)) return true;
      const es = (sample.match(/\b(el|la|los|las|que|de|en|un|una|por|con)\b/g) || [])
        .length;
      const en = (sample.match(/\b(the|and|that|with|for|will|you|your)\b/g) || [])
        .length;
      if (es >= 4 && es > en * 1.1) return true;
      if (en >= 6 && en > es * 1.3) return false;
      return es >= 2;
    }
    if (pref === "en") {
      return (sample.match(/\b(the|and|that|with|for)\b/g) || []).length >= 3;
    }
    return true;
  }

  function captionListMatchesLang(list, pref) {
    if (!list?.length) return false;
    const sample = list
      .slice(0, 40)
      .map((c) => c.text)
      .join(" ");
    return textLooksLikeLang(sample, pref);
  }

  function pickVisibleCaptionLine(lines, pref) {
    if (!lines?.length) return lines?.[0] || "";
    if (lines.length === 1) return lines[0];
    if (pref === "es") {
      const esLine = lines.find((l) => textLooksLikeLang(l, "es"));
      if (esLine) return esLine;
      const noCjk = lines.filter((l) => !/[\u3040-\u30ff\u4e00-\u9fff\u3400-\u4dbf]/.test(l));
      const noEn = noCjk.find((l) => !textLooksLikeLang(l, "en"));
      if (noEn) return noEn;
      if (noCjk.length) return noCjk[0];
    }
    if (pref === "en") {
      const enLine = lines.find((l) => textLooksLikeLang(l, "en"));
      if (enLine) return enLine;
    }
    return lines[0];
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  async function fetchCaptionsFromUrl(baseUrl) {
    try {
      const url = buildCaptionUrl(baseUrl);
      const resp = await fetch(url, { credentials: "include" });
      if (!resp.ok) return null;
      return await resp.json();
    } catch {
      return null;
    }
  }

  function resetDomCaptionState() {
    pendingDomText = "";
    domLastSpokenText = "";
    domTextSince = 0;
    domSceneStartVideoMs = 0;
    domStablePolls = 0;
    lastSceneKey = "";
    if (domDebounceTimer) clearTimeout(domDebounceTimer);
    if (domClearTimer) clearTimeout(domClearTimer);
    domDebounceTimer = null;
    domClearTimer = null;
  }

  function finishDownload(success) {
    downloadingFor = null;
    downloadAttemptNum = 0;
    if (success && cues.length > 0) {
      clearDownloadRetry();
      captionStatus = "ready";
      const video = getVideoElement();
      if (video) {
        lastSpokenIndex = findLastCueIndexBefore(video.currentTime * 1000) - 1;
      }
      lastSceneKey = "";
      resetDomCaptionState();
    } else if (cues.length === 0) {
      captionStatus = "error";
      scheduleDownloadRetry(getVideoId());
    }
    resumeVideoAfterLoad();
    updateUI();
    if (captionStatus === "ready" && cues.length > 0) {
      setTimeout(() => syncNarration(), 80);
    }
  }

  function pauseVideoForLoad() {
    if (settings.pauseWhileLoadingSubs === false) return;
    const video = getVideoElement();
    if (!video || video.ended) return;
    wasPlayingBeforeLoad = !video.paused;
    if (wasPlayingBeforeLoad) {
      video.pause();
      pauseForLoadActive = true;
    }
  }

  function resumeVideoAfterLoad() {
    if (!pauseForLoadActive) return;
    pauseForLoadActive = false;
    const video = getVideoElement();
    const shouldResume = wasPlayingBeforeLoad;
    wasPlayingBeforeLoad = false;
    if (!video || !shouldResume) return;
    lastSpokenIndex = findLastCueIndexBefore(video.currentTime * 1000) - 1;
    lastSceneKey = "";
    video.play().catch(() => {});
  }

  function updateBrowserVoices() {
    if (typeof speechSynthesis !== "undefined") {
      const list = speechSynthesis.getVoices() || [];
      pageVoices = list.map((v) => ({
        name: v.name,
        lang: v.lang,
        voiceURI: v.voiceURI,
        voiceType: "browser",
        neural: v.name.includes("Google") || v.name.includes("Natural") || v.name.includes("Neural")
      }));
      voiceCount = pageVoices.length;
      updateUI();
    }
  }

  if (typeof speechSynthesis !== "undefined") {
    speechSynthesis.addEventListener("voiceschanged", updateBrowserVoices);
    // Poll/fetch initial voices
    setTimeout(updateBrowserVoices, 100);
    setTimeout(updateBrowserVoices, 1000);
  }

  function speakBrowserTts(text, cueIndex, rateOverride) {
    if (typeof speechSynthesis === "undefined") return false;
    speechSynthesis.cancel();

    let effectiveRate = rateOverride ?? settings.rate;
    const u = new SpeechSynthesisUtterance(text);
    u.rate = effectiveRate;
    u.pitch = settings.pitch;
    u.volume = settings.volume;
    u.lang = ttsLangForCaptions();

    const voices = speechSynthesis.getVoices();
    const voiceURI = settings.voiceURI;
    if (voiceURI) {
      const cleanURI = voiceURI.replace(/^browser:/, "");
      const selected = voices.find((v) => v.voiceURI === cleanURI || v.voiceURI === voiceURI);
      if (selected) u.voice = selected;
    } else {
      const prefix = u.lang.split("-")[0];
      const selected = voices.find((v) => v.lang.startsWith(prefix) && v.localService) ||
                       voices.find((v) => v.lang.startsWith(prefix)) ||
                       voices[0];
      if (selected) u.voice = selected;
    }

    u.onstart = () => {
      setSpeaking(true, cueIndex);
    };
    u.onend = u.onerror = (e) => {
      setSpeaking(false, -1, true);
    };

    speechSynthesis.speak(u);
    return true;
  }

  function checkNativeHost(force) {
    return new Promise((resolve) => {
      let resolved = false;
      const timer = setTimeout(() => {
        if (!resolved) {
          resolved = true;
          useNative = false;
          resolve(false);
        }
      }, 800);

      try {
        if (!chrome.runtime || !chrome.runtime.sendMessage) {
          clearTimeout(timer);
          resolved = true;
          useNative = false;
          resolve(false);
          return;
        }
        chrome.runtime.sendMessage({ type: "CHECK_NATIVE", force: Boolean(force) }, (resp) => {
          if (resolved) return;
          clearTimeout(timer);
          resolved = true;

          if (chrome.runtime.lastError) {
            useNative = false;
            resolve(false);
            return;
          }
          useNative = Boolean(resp?.native);
          nativeEngine = resp?.engine || null;
          nativeEngines = Array.isArray(resp?.engines) ? resp.engines : nativeEngine ? [nativeEngine] : [];
          if (useNative) voiceCount = 1;
          updateUI();
          resolve(useNative);
        });
      } catch (e) {
        if (!resolved) {
          clearTimeout(timer);
          resolved = true;
          useNative = false;
          resolve(false);
        }
      }
    });
  }

  function injectPageSpeech() {
    if (document.getElementById("narrador-page-bridge")) return;

    const script = document.createElement("script");
    script.id = "narrador-page-bridge";
    script.textContent = `
      (function () {
        if (window.__narradorSpeechReady) return;
        window.__narradorSpeechReady = true;

        function pickVoice(voiceURI, lang) {
          var voices = speechSynthesis.getVoices();
          if (voiceURI) {
            var selected = voices.find(function (v) { return v.voiceURI === voiceURI; });
            if (selected) return selected;
          }
          var prefix = (lang || "es").split("-")[0];
          return (
            voices.find(function (v) { return v.lang.startsWith(prefix) && v.localService; }) ||
            voices.find(function (v) { return v.lang.startsWith(prefix); }) ||
            voices[0] ||
            null
          );
        }

        function sendVoices() {
          var voices = speechSynthesis.getVoices().map(function (v) {
            return { name: v.name, lang: v.lang, voiceURI: v.voiceURI };
          });
          window.dispatchEvent(new CustomEvent("narrador-voices", { detail: voices }));
        }

        window.addEventListener("narrador-speak", function (e) {
          var d = e.detail;
          speechSynthesis.cancel();
          var u = new SpeechSynthesisUtterance(d.text);
          u.rate = d.rate;
          u.pitch = d.pitch;
          u.volume = d.volume;
          u.lang = d.lang;
          var voice = pickVoice(d.voiceURI, d.lang);
          if (voice) u.voice = voice;
          u.onstart = function () {
            window.dispatchEvent(new CustomEvent("narrador-speaking", { detail: true }));
          };
          u.onend = u.onerror = function () {
            window.dispatchEvent(new CustomEvent("narrador-speaking", { detail: false }));
          };
          speechSynthesis.speak(u);
        });

        window.addEventListener("narrador-cancel", function () {
          speechSynthesis.cancel();
          window.dispatchEvent(new CustomEvent("narrador-speaking", { detail: false }));
        });

        window.addEventListener("narrador-request-voices", sendVoices);
        speechSynthesis.addEventListener("voiceschanged", sendVoices);
        sendVoices();
      })();
    `;

    (document.head || document.documentElement).appendChild(script);
    script.remove();
  }

  const SPANISH_LOCAL = new Set(["mateo", "carlos", "tomas", "leticia", "spanish", "sp_es", "seba"]);

  function loadSettings() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(DEFAULTS, (stored) => {
        settings = { ...DEFAULTS, ...stored };
        const prefix = settings.ttsEngine === "local" ? "local:" : settings.ttsEngine === "edge" ? "edge:" : "";
        if (prefix && settings.voiceURI && !settings.voiceURI.startsWith(prefix)) {
          settings.voiceURI = "";
          chrome.storage.sync.set({ voiceURI: "" });
        }
        if (!settings.voiceURI && settings.ttsEngine === "local") {
          settings.voiceURI = "local:mateo";
          chrome.storage.sync.set({ voiceURI: "local:mateo" });
        }
        if (
          settings.ttsEngine === "local" &&
          (settings.lang || "es").startsWith("es") &&
          settings.voiceURI &&
          !SPANISH_LOCAL.has(settings.voiceURI.replace(/^local:/, "").toLowerCase())
        ) {
          settings.voiceURI = "local:mateo";
          chrome.storage.sync.set({ voiceURI: "local:mateo" });
        }
        const visible = (stored.visibleVoices || []).filter(
          (k) => String(k).startsWith("edge:") || String(k).startsWith("local:") || String(k).startsWith("browser:") || !String(k).includes(":")
        );
        if (visible.length !== (stored.visibleVoices || []).length) {
          settings.visibleVoices = visible;
          chrome.storage.sync.set({ visibleVoices: visible });
        }
        resolve(settings);
      });
    });
  }

  function requestVoices() {
    window.dispatchEvent(new CustomEvent("narrador-request-voices"));
  }

  function setSpeaking(active, index, quiet = false) {
    const wasSpeaking = isSpeaking;
    isSpeaking = active;
    if (active) currentSpeakingIndex = index;
    else currentSpeakingIndex = -1;
    updateUI();
    if (wasSpeaking && !active && !quiet) {
      setTimeout(() => syncNarration(), 0);
    }
  }

  function estimateSpeechSec(text, rate = 1) {
    const words = text.trim().split(/\s+/).filter(Boolean).length;
    const byChars = text.length / CHARS_PER_SEC;
    const byWords = words / WORDS_PER_SEC;
    return (Math.max(byChars, byWords * 0.9) / Math.max(0.5, rate)) * SPEECH_DURATION_MARGIN;
  }

  function isPartialCaption(shorter, longer) {
    if (!shorter || !longer) return false;
    const a = shorter.trim();
    const b = longer.trim();
    return b.startsWith(a) || a.startsWith(b);
  }

  function isPlaythrough() {
    return settings.catchUpMode === "playthrough";
  }

  function shouldSceneLock() {
    return (
      settings.catchUpMode === "pause" &&
      settings.autoSync !== false &&
      useNative &&
      captionStatus === "ready" &&
      cues.length > 0
    );
  }

  function scheduleDownloadRetry(videoId) {
    if (downloadRetryTimer || downloadingFor) return;
    downloadRetryTimer = setTimeout(() => {
      downloadRetryTimer = null;
      if (
        getVideoId() === videoId &&
        captionStatus !== "ready" &&
        captionStatus !== "loading" &&
        settings.enabled
      ) {
        downloadingFor = null;
        downloadCaptions(videoId);
      }
    }, 6000);
  }

  function clearDownloadRetry() {
    if (downloadRetryTimer) {
      clearTimeout(downloadRetryTimer);
      downloadRetryTimer = null;
    }
  }

  function narrationVideoVolume() {
    if (settings.muteVideoWhileNarrating === false) return null;
    const v = settings.videoDuckVolume ?? VIDEO_DUCK_VOLUME_DEFAULT;
    return Math.min(1, Math.max(0, Number(v)));
  }

  function muteVideoForNarration() {
    const duck = narrationVideoVolume();
    if (duck === null) return;
    const video = getVideoElement();
    if (!video || savedVideoVolume !== null) return;
    savedVideoMuted = video.muted;
    savedVideoVolume = video.volume;
    if (video.muted) video.muted = false;
    video.volume = duck;
  }

  function restoreVideoMute() {
    const video = getVideoElement();
    if (!video || savedVideoVolume === null) return;
    video.volume = savedVideoVolume;
    video.muted = savedVideoMuted;
    savedVideoVolume = null;
    savedVideoMuted = null;
  }

  function resumeVideoAfterSpeech() {
    if (!pauseForSpeechActive) return;
    pauseForSpeechActive = false;
    const video = getVideoElement();
    const should = wasPlayingBeforeSpeech;
    wasPlayingBeforeSpeech = false;
    if (video && should && settings.enabled) {
      video.play().catch(() => {});
    }
  }

  function snapVideoToMs(targetMs) {
    const video = getVideoElement();
    if (!video || video.ended) return;
    const startSec = targetMs / 1000;
    if (Math.abs(video.currentTime - startSec) <= 0.04) {
      lastVideoTimeMs = targetMs;
      return;
    }
    syncSeekInProgress = true;
    try {
      video.currentTime = startSec;
      lastVideoTimeMs = targetMs;
    } catch {
      syncSeekInProgress = false;
    }
  }

  function prepareSceneNarration(cue) {
    const video = getVideoElement();
    if (!video || video.ended) return;

    muteVideoForNarration();
    if (isPlaythrough()) {
      pauseForSpeechActive = false;
      if (video.paused && settings.enabled) {
        video.play().catch(() => {});
      }
      return;
    }

    if (!pauseForSpeechActive) {
      wasPlayingBeforeSpeech = !video.paused;
    }
    video.pause();
    pauseForSpeechActive = true;
    snapVideoToMs(cue.startMs);
  }

  function pauseVideoForSpeech() {
    if (settings.autoSync === false) return;
    if (isPlaythrough()) return;
    if (!shouldSceneLock() && settings.catchUpMode !== "pause") return;
    const video = getVideoElement();
    if (!video || video.ended || pauseForSpeechActive) return;
    wasPlayingBeforeSpeech = !video.paused;
    if (wasPlayingBeforeSpeech || !video.paused) {
      video.pause();
      pauseForSpeechActive = true;
    }
  }

  function clearSpeechPauseState() {
    pauseForSpeechActive = false;
    wasPlayingBeforeSpeech = false;
  }

  function getNextSceneIndex(timeMs) {
    const next = lastSpokenIndex + 1;
    if (next >= cues.length) return -1;
    if (cues[next].startMs > timeMs + SCENE_START_TOLERANCE_MS) return -1;
    return next;
  }

  function getTargetSceneIndex(timeMs) {
    if (shouldSceneLock()) return getNextSceneIndex(timeMs);

    const liveIdx = findLastCueIndexBefore(timeMs);
    if (liveIdx < 0) return -1;
    if (liveIdx > lastSpokenIndex) return liveIdx;

    const next = lastSpokenIndex + 1;
    if (next < cues.length && cues[next].startMs <= timeMs + SCENE_START_TOLERANCE_MS) {
      return next;
    }
    return -1;
  }

  function isSceneStale(sceneIdx, timeMs) {
    if (sceneIdx < 0 || shouldSceneLock()) return false;
    const liveIdx = findLastCueIndexBefore(timeMs);
    return liveIdx > sceneIdx + 1;
  }

  function narrationRateForCue(cue, timeMs, sceneIdx) {
    if (shouldSceneLock()) {
      return settings.ttsEngine === "local" ? 1.0 : settings.rate ?? 1.0;
    }
    return rateForCueWindow(cue, timeMs, sceneIdx);
  }

  function tryChainNextScene() {
    if (!shouldSceneLock() || !settings.enabled) return false;

    let nextIdx = lastSpokenIndex + 1;
    while (nextIdx < cues.length) {
      const nextCue = cues[nextIdx];
      if (!nextCue?.text?.trim()) {
        lastSpokenIndex = nextIdx;
        nextIdx += 1;
        continue;
      }

      const prevCue = cues[lastSpokenIndex];
      const video = getVideoElement();
      const nowMs = video ? video.currentTime * 1000 : 0;
      const timelineGap =
        nextCue.startMs - (prevCue?.endMs ?? prevCue?.startMs ?? nextCue.startMs);
      const untilNext = nextCue.startMs - nowMs;

      if (timelineGap <= SCENE_CHAIN_GAP_MS || untilNext <= 400) {
        narrationArmed = true;
        pauseForSpeechActive = true;
        prepareSceneNarration(nextCue);
        speakSceneCue(nextCue, nextIdx, nextCue.startMs);
        return true;
      }

      if (video && untilNext > 900) {
        snapVideoToMs(Math.max(nowMs, nextCue.startMs - 80));
      }
      return false;
    }
    return false;
  }

  function finishSpeechCycle() {
    narrationArmed = false;
    if (tryChainNextScene()) {
      updateUI();
      return;
    }
    restoreVideoMute();
    resumeVideoAfterSpeech();
    setSpeaking(false, -1, true);
    updateUI();
    setTimeout(() => syncNarration(), 0);
  }

  function clearPendingSpeakTimer() {
    if (pendingSpeakTimer) {
      clearTimeout(pendingSpeakTimer);
      pendingSpeakTimer = null;
    }
  }

  function resetPendingSpeak(reason) {
    clearPendingSpeakTimer();
    pendingSpeakIndex = -1;
    if (reason) lastSpeakError = reason;
    finishSpeechCycle();
  }

  function sceneKeyFor(cue) {
    return `${cue.startMs}|${cue.endMs}|${cue.text}`;
  }

  function speak(text, cueIndex, rateOverride) {
    if (!text.trim()) return false;

    let effectiveRate = rateOverride ?? settings.rate;
    if (shouldSceneLock() && cueIndex >= 0 && settings.ttsEngine === "local") {
      effectiveRate = 1.0;
    }

    if (speakTimer) {
      clearTimeout(speakTimer);
      speakTimer = null;
    }

    if (useNative && settings.ttsEngine !== "browser") {
      const epoch = ++speakEpoch;
      const ttsEngine = settings.ttsEngine || "local";
      const voiceURI =
        settings.voiceURI ||
        (ttsEngine === "local" ? "local:mateo" : "");
      pendingSpeakIndex = cueIndex;
      speakRequestAt = Date.now();
      clearPendingSpeakTimer();
      pendingSpeakTimer = setTimeout(() => {
        if (pendingSpeakIndex < 0 || epoch !== speakEpoch) return;
        resetPendingSpeak("Tiempo de espera agotado — reintentando…");
      }, 120000);
      if (cueIndex >= 0 && !shouldSceneLock()) pauseVideoForSpeech();
      setSpeaking(true, cueIndex, true);
      chrome.runtime.sendMessage(
        {
          type: "NATIVE_SPEAK",
          text,
          lang: ttsLangForCaptions(),
          rate: effectiveRate,
          pitch: settings.pitch,
          volume: settings.volume,
          voice: voiceURI,
          engine: ttsEngine,
          ttsEngine,
        },
        (resp) => {
          if (epoch !== speakEpoch) return;
          clearPendingSpeakTimer();
          pendingSpeakIndex = -1;
          const roundTripMs = Date.now() - speakRequestAt;
          if (roundTripMs > 200) {
            ttsLatencyMs = Math.round(ttsLatencyMs * 0.65 + roundTripMs * 0.35);
          }
          if (chrome.runtime.lastError) {
            lastSpeakError =
              chrome.runtime.lastError.message ||
              "Sin conexión al motor nativo (recarga la página)";
            finishSpeechCycle();
            checkNativeHost(true);
            return;
          }
          if (resp?.engine) nativeEngine = resp.engine;
          if (!resp?.ok) {
            lastSpeakError = resp?.error || "Error al generar voz";
            finishSpeechCycle();
            return;
          }

          if (cueIndex >= 0 && !shouldSceneLock() && settings.catchUpMode !== "pause") {
            const video = getVideoElement();
            const nowMs = video ? video.currentTime * 1000 : 0;
            if (isSceneStale(cueIndex, nowMs)) {
              lastSpokenIndex = cueIndex;
              debugSyncLine = `Escena ${cueIndex + 1} omitida (retraso ${Math.round(roundTripMs / 1000)}s)`;
              chrome.runtime.sendMessage({ type: "NATIVE_CANCEL" });
              finishSpeechCycle();
              return;
            }
          }

          lastSpeakError = "";
          if (cueIndex >= 0 && cues[cueIndex]) {
            lastSpokenLine = text;
            lastSceneKey = sceneKeyFor(cues[cueIndex]);
          }

          const genMs = resp?.generateMs || 0;
          debugSyncLine =
            cueIndex >= 0
              ? `${nativeEngine || settings.ttsEngine} · ${genMs ? genMs + "ms gen · " : ""}${Math.round(roundTripMs)}ms · escena ${cueIndex + 1}`
              : debugSyncLine;

          if (resp?.blocking || useNative) {
            if (cueIndex >= 0) lastSpokenIndex = cueIndex;
            finishSpeechCycle();
            return;
          }

          const ms = Math.max(
            700,
            resp?.durationMs || estimateSpeechSec(text, effectiveRate) * 1000
          );
          speakTimer = setTimeout(() => {
            speakTimer = null;
            if (cueIndex >= 0) lastSpokenIndex = cueIndex;
            finishSpeechCycle();
          }, ms);
          updateUI();
        }
      );
      return true;
    }

    if (cueIndex >= 0) lastSpokenIndex = cueIndex;
    speakBrowserTts(text, cueIndex, effectiveRate);
    if (cueIndex >= 0 && cues[cueIndex]) {
      lastSpokenLine = text;
      lastSceneKey = sceneKeyFor(cues[cueIndex]);
    }
    const ms = Math.max(700, estimateSpeechSec(text, effectiveRate) * 1000);
    speakTimer = setTimeout(() => {
      speakTimer = null;
      finishSpeechCycle();
    }, ms);
    updateUI();
    return true;
  }

  function cancelSpeech() {
    speakEpoch += 1;
    narrationArmed = false;
    if (speakTimer) {
      clearTimeout(speakTimer);
      speakTimer = null;
    }
    clearPendingSpeakTimer();
    pendingSpeakIndex = -1;
    if (useNative && settings.ttsEngine !== "browser") {
      chrome.runtime.sendMessage({ type: "NATIVE_CANCEL" });
    } else {
      if (typeof speechSynthesis !== "undefined") {
        speechSynthesis.cancel();
      }
      window.dispatchEvent(new CustomEvent("narrador-cancel"));
    }
    resumeVideoAfterSpeech();
    restoreVideoMute();
    setSpeaking(false, -1, true);
  }

  function getVideoId() {
    return new URL(window.location.href).searchParams.get("v");
  }

  function getVideoElement() {
    return document.querySelector("video.html5-main-video");
  }

  function isVideoPlaying() {
    const video = getVideoElement();
    return video && !video.paused && !video.ended;
  }

  function getPlayerResponse() {
    if (window.ytInitialPlayerResponse?.captions) {
      return window.ytInitialPlayerResponse;
    }
    try {
      const raw = window.ytplayer?.config?.args?.player_response;
      if (raw) return JSON.parse(raw);
    } catch {
      /* ignore */
    }
    return null;
  }

  function fetchCaptionTracksFromPage() {
    return new Promise((resolve) => {
      const timeout = setTimeout(() => resolve([]), 4000);

      function onMessage(ev) {
        if (ev.source !== window || ev.data?.type !== "NARRADOR_TRACKS") return;
        window.removeEventListener("message", onMessage);
        clearTimeout(timeout);
        resolve(ev.data.tracks || []);
      }

      window.addEventListener("message", onMessage);

      const script = document.createElement("script");
      script.textContent = `
        (function () {
          var pr = window.ytInitialPlayerResponse;
          if (!pr) {
            try {
              var cfg = window.ytcfg && window.ytcfg.data_ && window.ytcfg.data_.PLAYER_VARS;
              if (cfg && cfg.player_response) {
                pr = typeof cfg.player_response === "string"
                  ? JSON.parse(cfg.player_response)
                  : cfg.player_response;
              }
            } catch (e) {}
          }
          if (!pr) {
            try {
              var raw = window.ytplayer && window.ytplayer.config && window.ytplayer.config.args
                && window.ytplayer.config.args.player_response;
              if (raw) pr = typeof raw === "string" ? JSON.parse(raw) : raw;
            } catch (e) {}
          }
          if (!pr && window.ytcfg && window.ytcfg.data_) {
            try {
              var emb = window.ytcfg.data_.INNERTUBE_PLAYER_RESPONSE
                || (window.ytcfg.data_.PLAYER_VARS && window.ytcfg.data_.PLAYER_VARS.embedded_player_response);
              if (emb) pr = typeof emb === "string" ? JSON.parse(emb) : emb;
            } catch (e) {}
          }
          if (!pr && window.__INITIAL_PLAYER_RESPONSE__) {
            pr = window.__INITIAL_PLAYER_RESPONSE__;
          }
          var tracks = (pr && pr.captions && pr.captions.playerCaptionsTracklistRenderer
            && pr.captions.playerCaptionsTracklistRenderer.captionTracks) || [];
          window.postMessage({ type: "NARRADOR_TRACKS", tracks: tracks }, "*");
        })();
      `;
      (document.head || document.documentElement).appendChild(script);
      script.remove();
    });
  }

  function getCaptionTracks() {
    const pr = getPlayerResponse();
    return pr?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
  }

  async function listTimedTextTracks(videoId) {
    try {
      const resp = await fetch(
        `https://www.youtube.com/api/timedtext?v=${videoId}&type=list`,
        { credentials: "include" }
      );
      if (!resp.ok) return [];
      const xml = await resp.text();
      const doc = new DOMParser().parseFromString(xml, "text/xml");
      return Array.from(doc.querySelectorAll("track")).map((t) => ({
        lang: t.getAttribute("lang_code") || "",
        name: t.getAttribute("name") || "",
        kind: t.getAttribute("kind") || "",
      }));
    } catch {
      return [];
    }
  }

  async function fetchTimedTextJson(videoId, lang, kind, tlang) {
    let url = `https://www.youtube.com/api/timedtext?v=${videoId}&lang=${encodeURIComponent(lang)}&fmt=json3`;
    if (kind) url += `&kind=${encodeURIComponent(kind)}`;
    if (tlang) url += `&tlang=${encodeURIComponent(tlang)}`;
    const resp = await fetch(url, { credentials: "include" });
    if (!resp.ok) return null;
    const text = await resp.text();
    if (!text.trim()) return null;
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  async function fetchCaptionsFallback(videoId) {
    const pref = langPrefCode();
    const listed = await listTimedTextTracks(videoId);

    const same = listed.filter((t) => langMatches(t.lang, pref));
    const tries = same.length
      ? same
      : [
          { lang: pref, kind: "" },
          { lang: "es", kind: "" },
          { lang: "es-419", kind: "" },
        ];

    for (const t of tries) {
      for (const kind of ["", "asr"]) {
        const data = await fetchTimedTextJson(videoId, t.lang, kind || "");
        if (data?.events?.length) {
          return { events: data.events, languageCode: t.lang };
        }
      }
    }

    for (const t of listed) {
      if (langMatches(t.lang, pref)) continue;
      for (const kind of ["", "asr"]) {
        const data = await fetchTimedTextJson(videoId, t.lang, kind || "", pref);
        if (data?.events?.length) {
          return {
            events: data.events,
            languageCode: pref,
            translated: true,
            sourceLanguageCode: t.lang,
          };
        }
      }
    }
    return null;
  }

  function isFragmentedCaptionList(list) {
    if (!list || list.length < 8) return false;
    const short = list.filter((c) => (c.text || "").length <= 2).length;
    return short / list.length >= 0.42;
  }

  function coalesceFragmentedCues(list) {
    if (!isFragmentedCaptionList(list)) return list;

    const out = [];
    let buf = null;

    for (const c of list) {
      const piece = (c.text || "").trim();
      if (!piece) continue;

      if (!buf) {
        buf = { ...c, text: piece };
        continue;
      }

      const gap = c.startMs - buf.endMs;
      const joinable = gap < 1400 && buf.text.length < 120;
      if (joinable) {
        const glue =
          /\s$/.test(buf.text) ||
          /^\s/.test(piece) ||
          /^[\s.,;:!?'"-]/.test(piece)
            ? ""
            : piece.length === 1 && buf.text.length >= 1 && !/\s$/.test(buf.text)
              ? ""
              : " ";
        buf.text = (buf.text + glue + piece).replace(/\s+/g, " ").trim();
        buf.endMs = Math.max(buf.endMs, c.endMs);
        continue;
      }

      out.push({
        ...buf,
        index: out.length,
        durMs: buf.endMs - buf.startMs,
      });
      buf = { ...c, text: piece };
    }

    if (buf) {
      out.push({
        ...buf,
        index: out.length,
        durMs: buf.endMs - buf.startMs,
      });
    }
    return out.length ? out : list;
  }

  function scoreCaptionList(list, payload) {
    if (!list || list.length < 3) return 0;
    const n = list.length;
    const avgLen = list.reduce((s, c) => s + (c.text || "").length, 0) / n;
    const shortRatio = list.filter((c) => (c.text || "").length <= 2).length / n;
    const spaced = list.filter((c) => /\s/.test(c.text || "")).length / n;
    let score =
      shortRatio > 0.5
        ? avgLen * Math.sqrt(n) * 0.15
        : avgLen * Math.sqrt(n) * (0.45 + spaced * 0.55);
    const code = payload?.languageCode || payload?.lang;
    const pref = langPrefCode();
    if (payload?.fromPanel) score *= 4;
    if (code && langMatches(code, pref)) score *= 2.5;
    else if (payload?.translated && langMatches(code, pref)) score *= 2.5;
    else if (code) score *= 0.02;
    if (!captionListMatchesLang(list, pref)) score *= 0.001;
    return score;
  }

  function parseCaptionPayload(payload) {
    let list = [];
    if (payload?.events?.length) {
      list = parseJson3Events(payload.events);
    } else if (typeof payload?.xml === "string" && payload.xml.trim()) {
      list = parseSrv3Xml(payload.xml);
    } else if (Array.isArray(payload?.cues) && payload.cues.length) {
      list = payload.cues;
    }
    if (!list.length) return [];
    list = coalesceFragmentedCues(list);
    return list;
  }

  function applyCaptionData(payload) {
    const list = parseCaptionPayload(payload);

    if (list.length) {
      downloadRawSegments = list.length;
      cues = dedupeCues(mergeSceneCues(list));
      captionStatus = "ready";
      const video = getVideoElement();
      if (video) {
        lastSpokenIndex = findLastCueIndexBefore(video.currentTime * 1000) - 1;
      }
      resetDomCaptionState();
      return;
    }
    captionStatus = "none";
  }

  function pickCaptionTrack(tracks) {
    if (!tracks.length) return null;
    const pref = langPrefCode();
    const sameLang = tracks.filter((t) => trackMatchesLang(t, pref));
    if (!sameLang.length) return null;
    return (
      sameLang.find((t) => t.kind !== "asr") ||
      sameLang.find((t) => t.kind === "asr") ||
      sameLang[0]
    );
  }

  async function fetchCaptionFromTrackBase(baseUrl, meta) {
    if (!baseUrl) return null;
    const UA =
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
    let base = baseUrl
      .replace(/&fmt=[^&]+/gi, "")
      .replace(/&tlang=[^&]+/gi, "");
    const sep = base.includes("?") ? "&" : "?";
    if (meta?.tlang) {
      base = `${base}${sep}tlang=${encodeURIComponent(meta.tlang)}`;
    }
    const urls = [
      `${base}${base.includes("?") ? "&" : "?"}fmt=srv3`,
      `${base}${base.includes("?") ? "&" : "?"}fmt=vtt`,
      `${base}${base.includes("?") ? "&" : "?"}fmt=json3`,
    ];
    for (const url of urls) {
      try {
        const capResp = await fetch(url, {
          credentials: "include",
          headers: { "User-Agent": UA },
        });
        if (!capResp.ok) continue;
        const body = await capResp.text();
        if (!body?.trim()) continue;
        if (body[0] === "{") {
          const data = JSON.parse(body);
          if (data?.events?.length) {
            return {
              events: data.events,
              languageCode: meta?.languageCode,
              translated: Boolean(meta?.translated),
              sourceLanguageCode: meta?.sourceLanguageCode,
            };
          }
        }
        if (body.includes("<text") || body.includes("<p ") || body.includes("WEBVTT")) {
          return {
            xml: body,
            languageCode: meta?.languageCode,
            translated: Boolean(meta?.translated),
            sourceLanguageCode: meta?.sourceLanguageCode,
          };
        }
      } catch {
        /* next format */
      }
    }
    return null;
  }

  async function fetchTracksForLang(tracks, pref) {
    const translatable = tracks.filter(
      (t) => !trackMatchesLang(t, pref) && t.isTranslatable !== false
    );
    const trOrdered = [...translatable].sort(
      (a, b) => (a.kind === "asr" ? 1 : 0) - (b.kind === "asr" ? 1 : 0)
    );
    for (const track of trOrdered) {
      const hit = await fetchCaptionFromTrackBase(track.baseUrl, {
        tlang: pref,
        languageCode: pref,
        translated: true,
        sourceLanguageCode: track.languageCode,
      });
      if (hit) {
        const list = parseCaptionPayload(hit);
        if (captionListMatchesLang(list, pref)) return hit;
      }
    }

    const sameLang = tracks.filter((t) => trackMatchesLang(t, pref));
    const ordered = [...sameLang].sort(
      (a, b) => (a.kind === "asr" ? 1 : 0) - (b.kind === "asr" ? 1 : 0)
    );
    for (const track of ordered) {
      const hit = await fetchCaptionFromTrackBase(track.baseUrl, {
        languageCode: track.languageCode || pref,
        translated: false,
        sourceLanguageCode: track.languageCode,
      });
      if (hit) {
        const list = parseCaptionPayload(hit);
        if (captionListMatchesLang(list, pref)) return hit;
      }
    }
    return null;
  }

  function buildCaptionUrl(baseUrl) {
    if (baseUrl.includes("fmt=")) return baseUrl;
    return baseUrl + (baseUrl.includes("?") ? "&" : "?") + "fmt=json3";
  }

  function parseJson3Events(events) {
    const raw = [];

    for (const ev of events) {
      if (!ev.segs) continue;
      const piece = ev.segs
        .map((s) => s.utf8 || "")
        .join("")
        .replace(/\n/g, " ")
        .trim();
      if (!piece) continue;
      raw.push({
        tStartMs: ev.tStartMs || 0,
        dDurationMs: ev.dDurationMs,
        text: piece,
        wWinId: ev.wWinId,
        aAppend: ev.aAppend,
      });
    }

    const merged = [];
    let current = null;

    for (const ev of raw) {
      if (ev.aAppend && current && ev.wWinId === current.wWinId) {
        current.text += ev.text;
        if (ev.dDurationMs) current.dDurationMs = ev.dDurationMs;
      } else {
        if (current?.text?.trim()) merged.push(current);
        current = { ...ev };
      }
    }
    if (current?.text?.trim()) merged.push(current);

    const compacted = [];
    let micro = null;
    for (const ev of merged) {
      const t = (ev.text || "").trim();
      if (!t) continue;
      if (!micro) {
        micro = { ...ev, text: t };
        continue;
      }
      const gap = (ev.tStartMs || 0) - ((micro.tStartMs || 0) + (micro.dDurationMs || 0));
      if (t.length <= 2 && micro.text.length < 100 && gap < 600) {
        const glue = /\s$/.test(micro.text) || /^[\s.,;:!?'"-]/.test(t) ? "" : "";
        micro.text = (micro.text + glue + t).replace(/\s+/g, " ").trim();
        if (ev.dDurationMs) micro.dDurationMs = (ev.tStartMs - micro.tStartMs) + ev.dDurationMs;
      } else {
        compacted.push(micro);
        micro = { ...ev, text: t };
      }
    }
    if (micro) compacted.push(micro);

    return compacted
      .map((c, i) => {
        const startMs = c.tStartMs;
        const next = compacted[i + 1];
        let endMs = startMs + (c.dDurationMs || 0);
        if (next?.tStartMs > startMs) endMs = next.tStartMs;
        if (endMs <= startMs) endMs = startMs + 2500;
        return {
          index: i,
          startMs,
          endMs,
          durMs: endMs - startMs,
          text: c.text.replace(/\s+/g, " ").trim(),
        };
      })
      .filter((c) => c.text.length > 0);
  }

  function parseSrv3Xml(xmlText) {
    if (xmlText.includes("WEBVTT")) return parseVttCaptions(xmlText);
    if (/<text[\s>]/i.test(xmlText)) return parseXmlCaptions(xmlText);

    const doc = new DOMParser().parseFromString(xmlText, "text/xml");
    let nodes = doc.querySelectorAll("p");
    if (!nodes.length) return parseXmlCaptions(xmlText);

    const list = Array.from(nodes)
      .map((node, i) => {
        const startMs = parseInt(node.getAttribute("t") || "0", 10);
        const durMs = parseInt(node.getAttribute("d") || "2000", 10);
        const text = (node.textContent || "").replace(/\s+/g, " ").trim();
        return {
          index: i,
          startMs,
          endMs: startMs + durMs,
          durMs,
          text,
        };
      })
      .filter((c) => c.text.length > 0);

    for (let i = 0; i < list.length - 1; i++) {
      if (list[i].endMs <= list[i].startMs + 120) {
        list[i].endMs = list[i + 1].startMs;
        list[i].durMs = list[i].endMs - list[i].startMs;
      }
    }
    return list;
  }

  function parseVttCaptions(vttText) {
    const lines = vttText.replace(/\r/g, "").split("\n");
    const cuesOut = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i].trim();
      if (!line || line === "WEBVTT" || line.startsWith("NOTE")) {
        i += 1;
        continue;
      }
      if (line.includes("-->")) {
        const [startRaw, endRaw] = line.split("-->").map((s) => s.trim());
        const startMs = vttTimeToMs(startRaw);
        const endMs = vttTimeToMs(endRaw.split(" ")[0]);
        i += 1;
        const textLines = [];
        while (i < lines.length && lines[i].trim()) {
          textLines.push(lines[i].trim());
          i += 1;
        }
        const text = textLines.join(" ").replace(/\s+/g, " ").trim();
        if (text) {
          cuesOut.push({
            index: cuesOut.length,
            startMs,
            endMs: Math.max(endMs, startMs + 300),
            durMs: Math.max(endMs, startMs + 300) - startMs,
            text,
          });
        }
        continue;
      }
      i += 1;
    }
    return cuesOut;
  }

  function vttTimeToMs(raw) {
    const parts = (raw || "0").trim().split(":");
    let h = 0;
    let m = 0;
    let s = 0;
    if (parts.length === 3) {
      h = parseFloat(parts[0]) || 0;
      m = parseFloat(parts[1]) || 0;
      s = parseFloat(parts[2].replace(",", ".")) || 0;
    } else if (parts.length === 2) {
      m = parseFloat(parts[0]) || 0;
      s = parseFloat(parts[1].replace(",", ".")) || 0;
    } else {
      s = parseFloat(parts[0].replace(",", ".")) || 0;
    }
    return Math.round((h * 3600 + m * 60 + s) * 1000);
  }

  function mergeSceneCues(list) {
    if (list.length === 0) return list;
    const out = [];
    let buf = { ...list[0], text: list[0].text.trim() };

    for (let i = 1; i < list.length; i++) {
      const c = list[i];
      const gap = c.startMs - buf.endMs;
      const overlap = c.startMs < buf.endMs;
      const combined = buf.text.length + c.text.length + 1;

      if ((overlap || gap < 800) && combined < 220) {
        buf.text = (buf.text + " " + c.text).replace(/\s+/g, " ").trim();
        buf.endMs = Math.max(buf.endMs, c.endMs);
      } else {
        out.push({ ...buf, index: out.length, durMs: buf.endMs - buf.startMs });
        buf = { ...c, text: c.text.trim() };
      }
    }

    out.push({ ...buf, index: out.length, durMs: buf.endMs - buf.startMs });
    return out;
  }

  function mergePhraseCues(list) {
    return mergeSceneCues(list);
  }

  function dedupeCues(list) {
    const out = [];
    for (const cue of list) {
      const prev = out[out.length - 1];
      if (prev && prev.text === cue.text) {
        prev.endMs = Math.max(prev.endMs, cue.endMs);
        continue;
      }
      out.push({ ...cue, index: out.length });
    }
    return out;
  }

  function parseXmlCaptions(xmlText) {
    const doc = new DOMParser().parseFromString(xmlText, "text/xml");
    const nodes = doc.querySelectorAll("text");
    return Array.from(nodes)
      .map((node, i) => {
        const startSec = parseFloat(node.getAttribute("start") || "0");
        const durSec = parseFloat(node.getAttribute("dur") || "2");
        const text = (node.textContent || "").replace(/\s+/g, " ").trim();
        return {
          index: i,
          startMs: startSec * 1000,
          endMs: (startSec + durSec) * 1000,
          durMs: durSec * 1000,
          text,
        };
      })
      .filter((c) => c.text.length > 0);
  }

  async function fetchTranscriptDirect(videoId, langPref) {
    const UA =
      "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
    try {
      const watchUrl = `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`;
      const htmlResp = await fetch(watchUrl, { headers: { "User-Agent": UA } });
      if (!htmlResp.ok) return null;
      const html = await htmlResp.text();
      const apiKeyMatch = html.match(/"INNERTUBE_API_KEY"\s*:\s*"([^"]+)"/);
      if (!apiKeyMatch) return null;

      const playerResp = await fetch(
        `https://www.youtube.com/youtubei/v1/player?key=${encodeURIComponent(apiKeyMatch[1])}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", "User-Agent": UA },
          body: JSON.stringify({
            context: {
              client: {
                clientName: "ANDROID",
                clientVersion: "20.10.38",
                hl: langPref || "es",
              },
            },
            videoId,
          }),
        }
      );
      if (!playerResp.ok) return null;

      const player = await playerResp.json();
      const tracks =
        player?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
      if (!tracks.length) return null;

      const pref = (langPref || "es").split("-")[0].toLowerCase();
      return await fetchTracksForLang(tracks, pref);
    } catch {
      /* try next method */
    }
    return null;
  }

  function fetchTranscriptViaBackground(videoId, langPref) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(
        { type: "FETCH_TRANSCRIPT", videoId, lang: langPref },
        (resp) => {
          if (
            chrome.runtime.lastError ||
            !resp?.ok ||
            (!resp.payload?.xml && !resp.payload?.events?.length)
          ) {
            resolve(null);
            return;
          }
          resolve(resp.payload);
        }
      );
    });
  }


  function getPlayerResponseFromDOM() {
    const scripts = document.getElementsByTagName("script");
    for (const script of scripts) {
      const text = script.textContent;
      if (!text) continue;
      if (text.includes("ytInitialPlayerResponse")) {
        const match = text.match(/ytInitialPlayerResponse\s*=\s*({.+?});/);
        if (match) {
          try {
            return JSON.parse(match[1]);
          } catch (e) {}
        }
      }
    }
    return null;
  }

  async function downloadCaptionsViaPage(videoId, langPref) {
    const pr = getPlayerResponseFromDOM();
    if (!pr?.captions?.playerCaptionsTracklistRenderer?.captionTracks) return null;
    const tracks = pr.captions.playerCaptionsTracklistRenderer.captionTracks;
    
    function langMatches(tLang, pref) {
      const lc = (tLang || "").toLowerCase();
      return lc === pref || lc.indexOf(pref + "-") === 0;
    }
    
    const same = tracks.filter((t) => langMatches(t.languageCode || t.lang, langPref));
    same.sort((a, b) => (a.kind === "asr" ? 1 : 0) - (b.kind === "asr" ? 1 : 0));
    
    for (const track of same) {
      try {
        const url = track.baseUrl + (track.baseUrl.includes("?") ? "&" : "?") + "fmt=json3";
        const resp = await fetch(url, { credentials: "include" });
        if (resp.ok) {
          const data = await resp.json();
          if (data?.events?.length) {
            return {
              events: data.events,
              languageCode: track.languageCode || langPref,
              translated: false
            };
          }
        }
      } catch (e) {}
    }
    return null;
  }

  async function downloadCaptionsViaTranscriptPanel(videoId, langPref) {
    function sleep(ms) {
      return new Promise((r) => setTimeout(r, ms));
    }

    function openTranscript() {
      const sels = [
        'button[aria-label="Show transcript"]',
        'button[aria-label="Mostrar transcripción"]',
        'button[aria-label*="ranscript"]',
        'button[aria-label*="ranscripción"]',
      ];
      for (const sel of sels) {
        const b = document.querySelector(sel);
        if (b) {
          b.click();
          return true;
        }
      }
      return false;
    }

    openTranscript();

    for (let attempt = 0; attempt < 16; attempt++) {
      if (attempt > 0) await sleep(500 + attempt * 200);
      const nodes = document.querySelectorAll("ytd-transcript-segment-renderer");
      if (nodes.length < 3) continue;

      const segments = [];
      nodes.forEach((n) => {
        const te = n.querySelector(".segment-timestamp");
        const tx = n.querySelector("yt-formatted-string.segment-text, yt-formatted-string");
        const text = (tx?.textContent || "").replace(/\s+/g, " ").trim();
        if (!text) return;
        const p = (te?.textContent || "0:00").trim().split(":").map(Number);
        let startMs = 0;
        if (p.length === 3) startMs = (p[0] * 3600 + p[1] * 60 + p[2]) * 1000;
        else if (p.length === 2) startMs = (p[0] * 60 + p[1]) * 1000;
        segments.push({ startMs, endMs: startMs + 3000, text });
      });

      if (segments.length < 3) continue;
      for (let j = 0; j < segments.length - 1; j++) {
        segments[j].endMs = segments[j + 1].startMs;
      }
      
      const cues = segments.map((s, i) => ({
        index: i,
        startMs: s.startMs,
        endMs: s.endMs,
        durMs: s.endMs - s.startMs,
        text: s.text,
      }));

      return {
        cues,
        languageCode: langPref,
        translated: true,
        fromPanel: true,
      };
    }
    let debugHtml = "=== DOM PANELS DIAGNOSTIC ===\n\n";
    const panels = document.querySelectorAll("ytd-engagement-panel-section-list-renderer");
    debugHtml += `Found ${panels.length} engagement panels:\n`;
    panels.forEach((p, idx) => {
      debugHtml += `\n--- Panel ${idx} (target-id: ${p.getAttribute("target-id")}, visible: ${p.getAttribute("visibility")}) ---\n`;
      debugHtml += p.outerHTML.substring(0, 3000) + "\n";
    });
    const segments = document.querySelectorAll("*[class*='transcript'], *[id*='transcript']");
    debugHtml += `\nFound ${segments.length} transcript-related nodes:\n`;
    segments.forEach((s, idx) => {
      if (idx < 20) {
        debugHtml += `Node ${idx}: ${s.tagName} class="${s.className}" id="${s.id}" text="${(s.textContent || "").substring(0, 100).trim()}"\n`;
      }
    });
    chrome.runtime.sendMessage({ type: "SAVE_DEBUG_HTML", html: debugHtml });
    return null;
  }

  function getVisibleCaptionText() {
    const pref = getCaptionTargetLang();
    const segmentLines = Array.from(
      document.querySelectorAll(".ytp-caption-segment")
    )
      .map((s) => s.textContent.trim())
      .filter(Boolean);
    if (segmentLines.length) {
      return pickVisibleCaptionLine(segmentLines, pref);
    }

    const lines = [];
    const windows = document.querySelectorAll(
      ".ytp-caption-window-container .ytp-caption-window"
    );
    if (windows.length) {
      windows.forEach((win) => {
        const line = (win.innerText || win.textContent || "")
          .replace(/\s+/g, " ")
          .trim();
        if (line) lines.push(line);
      });
    }
    if (lines.length) return pickVisibleCaptionLine(lines, pref);

    const container = document.querySelector(".ytp-caption-window-container");
    if (container) {
      const full = (container.innerText || container.textContent || "")
        .replace(/\s+/g, " ")
        .trim();
      if (full) {
        const parts = full.split(/\s{2,}|\n/).map((p) => p.trim()).filter(Boolean);
        if (parts.length > 1) return pickVisibleCaptionLine(parts, pref);
        return full;
      }
    }
    return "";
  }

  function findCueIndexForTime(timeMs) {
    return findLastCueIndexBefore(timeMs);
  }

  function maybeHoldBeforeNextScene(timeMs) {
    if (!shouldSceneLock()) return;
    const video = getVideoElement();
    if (
      !video ||
      video.paused ||
      video.ended ||
      pauseForSpeechActive ||
      isSpeaking ||
      pendingSpeakIndex >= 0 ||
      narrationArmed
    ) {
      return;
    }
    const next = lastSpokenIndex + 1;
    if (next >= cues.length) return;
    const leadMs = cues[next].startMs - timeMs;
    if (leadMs > 0 && leadMs <= 350) {
      video.pause();
    }
  }

  function processTimedSync(timeMs) {
    if (pendingSpeakIndex >= 0 || isSpeaking || narrationArmed) return;

    const targetIdx = getTargetSceneIndex(timeMs);
    if (targetIdx < 0) return;

    const cue = cues[targetIdx];
    if (!cue?.text?.trim()) {
      lastSpokenIndex = targetIdx;
      return;
    }

    if (shouldSceneLock()) {
      narrationArmed = true;
      prepareSceneNarration(cue);
      speakSceneCue(cue, targetIdx, cue.startMs);
      return;
    }

    if (targetIdx > lastSpokenIndex + 1) {
      debugSyncLine = `Salto escenas → ${targetIdx + 1}/${cues.length} @ ${(cue.startMs / 1000).toFixed(0)}s`;
    }

    speakSceneCue(cue, targetIdx, timeMs);
  }

  function rateForCueWindow(cue, timeMs, sceneIdx) {
    if (settings.autoSync === false) return settings.rate;
    if (settings.catchUpMode === "pause" || settings.catchUpMode === "slowdown") {
      return settings.rate;
    }

    let maxRate = Math.max(settings.rate, settings.maxSyncRate || 2.0);
    if (settings.ttsEngine === "edge" || settings.ttsEngine === "browser") {
      maxRate = Math.min(maxRate, 1.25);
    }
    const remainingSec = Math.max(0.2, (cue.endMs - timeMs) / 1000);
    const neededSec = estimateSpeechSec(cue.text, 1);
    let rate = settings.rate;

    const lagSec = Math.max(0, (timeMs - cue.startMs) / 1000);
    const ttsSec = ttsLatencyMs / 1000;
    const effectiveRemaining = Math.max(0.15, remainingSec - ttsSec);

    if (neededSec > effectiveRemaining * 0.72) {
      rate = Math.min(maxRate, settings.rate * (neededSec / (effectiveRemaining * 0.68)));
    }

    if (lagSec > 0.4) {
      rate = Math.min(maxRate, rate * (1 + lagSec * 0.35));
    }

    if (sceneIdx > lastSpokenIndex + 1) {
      rate = Math.min(maxRate, rate * 1.15);
    }

    return Math.max(0.5, Math.min(maxRate, rate));
  }

  function speakSceneCue(cue, idx, timeMs) {
    if (!cue?.text?.trim()) return;

    if (isPlaythrough() && idx >= 0) {
      muteVideoForNarration();
      const video = getVideoElement();
      if (video?.paused && settings.enabled) {
        video.play().catch(() => {});
      }
    }

    if (idx < 0 && isSpeaking && lastSpokenLine) {
      if (isPartialCaption(cue.text, lastSpokenLine) && cue.text.length <= lastSpokenLine.length) {
        return;
      }
      if (isPartialCaption(lastSpokenLine, cue.text) && cue.text.length > lastSpokenLine.length) {
        return;
      }
    }

    const key = sceneKeyFor(cue);
    if (lastSceneKey === key && isSpeaking) return;

    const rate = narrationRateForCue(cue, timeMs, idx);
    debugSyncLine =
      idx >= 0
        ? `Sync ${idx + 1}/${cues.length} @ ${(cue.startMs / 1000).toFixed(1)}s · ×${rate.toFixed(1)}`
        : `Pantalla @ ${(timeMs / 1000).toFixed(1)}s · ×${rate.toFixed(1)}`;

    updateUI();
    speak(cue.text, idx, rate);
  }

  function getCatchUpCue(timeMs) {
    let idx = findCueIndexForTime(timeMs);
    if (idx < 0) idx = findLastCueIndexBefore(timeMs);
    if (idx < 0) return null;
    if (isSpeaking && currentSpeakingIndex >= 0 && cues[currentSpeakingIndex]) {
      return cues[currentSpeakingIndex];
    }
    return cues[idx];
  }

  function rememberNormalPlaybackRate(video) {
    if (savedYouTubeRate == null) {
      savedYouTubeRate = video.playbackRate > 0 ? video.playbackRate : 1;
    }
  }

  function restoreVideoPlaybackRate() {
    const video = getVideoElement();
    if (!video) return;
    const target = savedYouTubeRate ?? 1;
    if (Math.abs(video.playbackRate - target) > 0.02) {
      video.playbackRate = target;
    }
    savedYouTubeRate = null;
  }

  function applyVideoCatchUp(timeMs) {
    if (settings.catchUpMode !== "slowdown" || settings.autoSync === false) {
      restoreVideoPlaybackRate();
      return;
    }

    const video = getVideoElement();
    if (!video || video.paused || video.ended) return;

    const cue = getCatchUpCue(timeMs);
    if (!cue) {
      restoreVideoPlaybackRate();
      return;
    }

    const remainingSec = Math.max(0.12, (cue.endMs - timeMs) / 1000);
    const neededSec = estimateSpeechSec(cue.text, settings.rate);
    const lag = neededSec / remainingSec;
    const minRate = Math.max(0.25, Math.min(1, settings.minVideoRate ?? 0.65));

    if (lag > 1.05 || (isSpeaking && timeMs < cue.endMs + 120)) {
      const target = Math.max(minRate, Math.min(1, 1 / lag));
      rememberNormalPlaybackRate(video);
      if (Math.abs(video.playbackRate - target) > 0.03) {
        video.playbackRate = target;
      }
    } else {
      restoreVideoPlaybackRate();
    }
  }

  function domSpeakNow(video, text) {
    if (!text || text === domLastSpokenText) return;

    const timeMs = video.currentTime * 1000;
    const estMs = Math.max(2200, Math.min(6000, text.length * 52));
    const cue = {
      startMs: domSceneStartVideoMs || timeMs,
      endMs: (domSceneStartVideoMs || timeMs) + estMs,
      text,
    };

    domLastSpokenText = text;
    pendingDomText = text;
    speakSceneCue(cue, -1, timeMs);
  }

  function scheduleDomSpeak(video) {
    if (domDebounceTimer) clearTimeout(domDebounceTimer);

    domDebounceTimer = setTimeout(() => {
      domDebounceTimer = null;
      const latest = getVisibleCaptionText();
      if (!latest) return;
      if (latest.length < pendingDomText.length * 0.9) return;
      if (isSpeaking) return;
      domSpeakNow(video, latest);
    }, DOM_STABLE_MS);
  }

  function processDomCaptions() {
    const video = getVideoElement();
    if (!video || video.paused || video.ended) return;

    if (isSpeaking) return;

    const text = getVisibleCaptionText();

    if (!text) {
      domStablePolls = 0;
      if (domClearTimer) clearTimeout(domClearTimer);
      domClearTimer = setTimeout(() => {
        domClearTimer = null;
        pendingDomText = "";
        domLastSpokenText = "";
        domTextSince = 0;
        domSceneStartVideoMs = 0;
      }, 400);
      return;
    }

    if (domClearTimer) {
      clearTimeout(domClearTimer);
      domClearTimer = null;
    }

    if (text === domLastSpokenText) return;

    if (pendingDomText && text.length < pendingDomText.length && pendingDomText.startsWith(text)) {
      return;
    }

    if (text !== pendingDomText) {
      pendingDomText = text;
      domTextSince = Date.now();
      domSceneStartVideoMs = video.currentTime * 1000;
      domStablePolls = 1;
      scheduleDomSpeak(video);
      return;
    }

    domStablePolls += 1;
    if (domStablePolls >= DOM_STABLE_POLLS && !domDebounceTimer) {
      scheduleDomSpeak(video);
    }

    if (Date.now() - domTextSince >= DOM_MAX_WAIT_MS && text === pendingDomText && !domDebounceTimer) {
      scheduleDomSpeak(video);
    }
  }

  async function downloadCaptions(videoId) {
    if (downloadingFor === videoId) return;

    downloadingFor = videoId;
    downloadStartedAt = Date.now();
    downloadAttemptNum = 0;
    downloadRawSegments = 0;
    captionStatus = "loading";
    cues = [];
    lastSpokenIndex = -1;
    lastSceneKey = "";
    resetDomCaptionState();
    pauseVideoForLoad();
    updateUI();

    const langPref = getCaptionTargetLang();

    const timeoutPromise = (promise, ms) => {
      return new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), ms);
        promise.then(
          (val) => {
            clearTimeout(timer);
            resolve(val);
          },
          () => {
            clearTimeout(timer);
            resolve(null);
          }
        );
      });
    };

    try {
      for (let attempt = 0; attempt < 5; attempt++) {
        downloadAttemptNum = attempt + 1;
        updateUI();
        if (attempt > 0) await sleep(1200 * attempt);

        const [direct, bg, page, panel] = await Promise.all([
          timeoutPromise(fetchTranscriptDirect(videoId, langPref), 5000),
          timeoutPromise(fetchTranscriptViaBackground(videoId, langPref), 5000),
          timeoutPromise(downloadCaptionsViaPage(videoId, langPref), 5000),
          timeoutPromise(downloadCaptionsViaTranscriptPanel(videoId, langPref), 12000),
        ]);

        let bestList = null;
        let bestPayload = null;
        let bestScore = 0;

        for (const payload of [panel, direct, bg, page]) {
          if (!payload) continue;
          const normalized =
            payload.cues?.length
              ? payload
              : payload.xml != null
                ? { xml: payload.xml, languageCode: payload.languageCode, translated: payload.translated }
                : payload.events?.length
                  ? {
                      events: payload.events,
                      languageCode: payload.languageCode,
                      translated: payload.translated,
                    }
                  : payload;
          const list = parseCaptionPayload(normalized);
          if (!captionListMatchesLang(list, langPref)) continue;
          const score = scoreCaptionList(list, payload);
          if (list.length > 5 && score > bestScore) {
            const code = payload?.languageCode;
            if (code && !langMatches(code, langPref) && !payload?.translated) {
              continue;
            }
            bestScore = score;
            bestList = list;
            bestPayload = payload;
          }
        }

        if (bestList?.length) {
          captionSourceLang =
            bestPayload?.languageCode || langPref;
          captionTranslated = Boolean(bestPayload?.translated);
          downloadRawSegments = bestList.length;
          cues = dedupeCues(mergeSceneCues(bestList));
          captionStatus = "ready";
          const video = getVideoElement();
          if (video) {
            lastSpokenIndex = findLastCueIndexBefore(video.currentTime * 1000) - 1;
          }
          resetDomCaptionState();
          finishDownload(true);
          return;
        }
      }
    } catch (err) {
      console.warn("[Narrador] downloadCaptions:", err);
    }

    finishDownload(false);
  }

  function resetForNewVideo() {
    pauseForLoadActive = false;
    wasPlayingBeforeLoad = false;
    syncSeekInProgress = false;
    narrationArmed = false;
    speakEpoch += 1;
    clearDownloadRetry();
    clearSpeechPauseState();
    restoreVideoPlaybackRate();
    cues = [];
    captionStatus = "idle";
    captionSourceLang = "";
    captionTranslated = false;
    downloadAttemptNum = 0;
    downloadRawSegments = 0;
    lastSpokenIndex = -1;
    lastVideoTimeMs = 0;
    lastSpokenLine = "";
    resetDomCaptionState();
    debugSyncLine = "";
    cancelSpeech();
    updateUI();
  }

  function enableCaptionsIfNeeded() {
    if (!settings.autoEnableCC) return;
    const ccButton = document.querySelector(".ytp-subtitles-button");
    if (ccButton?.getAttribute("aria-pressed") === "false") ccButton.click();
  }

  function findCueIndexAtTime(timeMs) {
    return cues.findIndex((c) => timeMs >= c.startMs && timeMs < c.endMs);
  }

  function findLastCueIndexBefore(timeMs) {
    let idx = -1;
    for (let i = 0; i < cues.length; i++) {
      if (cues[i].startMs <= timeMs) idx = i;
      else break;
    }
    return idx;
  }

  function handleSeek(currentMs) {
    if (
      syncSeekInProgress ||
      pauseForSpeechActive ||
      pendingSpeakIndex >= 0 ||
      isSpeaking ||
      narrationArmed
    ) {
      lastVideoTimeMs = currentMs;
      return;
    }

    const jumped = Math.abs(currentMs - lastVideoTimeMs) > SEEK_THRESHOLD_MS;

    if (jumped) {
      speakEpoch += 1;
      lastSpokenIndex = findLastCueIndexBefore(currentMs) - 1;
      lastSceneKey = "";
      resetDomCaptionState();
      cancelSpeech();
      restoreVideoPlaybackRate();
    }
    lastVideoTimeMs = currentMs;
  }

  function syncNarration() {
    if (!settings.enabled) return;

    const now = Date.now();
    if (now - lastSyncAt < 45) return;
    lastSyncAt = now;

    const videoId = getVideoId();
    if (!videoId) return;

    if (videoId !== lastVideoId) {
      lastVideoId = videoId;
      resetForNewVideo();
      if (settings.autoEnableCC) enableCaptionsIfNeeded();
      downloadCaptions(videoId);
      return;
    }

    const video = getVideoElement();
    if (!video) return;

    bindVideoEvents();

    const timeMs = video.currentTime * 1000;
    handleSeek(timeMs);

    if (captionStatus === "loading") {
      if (settings.pauseWhileLoadingSubs !== false) {
        updateUI();
        return;
      }
    }

    if (video.paused || video.ended) {
      if (
        !pauseForSpeechActive &&
        pendingSpeakIndex < 0 &&
        !isSpeaking
      ) {
        updateUI();
        return;
      }
    }

    if (!useNative) {
      updateUI();
      return;
    }

    if (captionStatus === "ready" && cues.length > 0) {
      maybeHoldBeforeNextScene(timeMs);
      processTimedSync(timeMs);
      if (!shouldSceneLock()) {
        try {
          applyVideoCatchUp(timeMs);
        } catch (err) {
          console.warn("[Narrador] applyVideoCatchUp:", err);
        }
      } else {
        restoreVideoPlaybackRate();
      }
    } else if (
      captionStatus === "error" ||
      captionStatus === "none" ||
      captionStatus === "idle"
    ) {
      restoreVideoPlaybackRate();
      scheduleDownloadRetry(videoId);
    } else {
      restoreVideoPlaybackRate();
    }

    updateUI();
  }

  function startWatching() {
    if (syncTimer) clearInterval(syncTimer);
    syncTimer = setInterval(syncNarration, SYNC_INTERVAL_MS);
  }

  function bindVideoEvents() {
    const video = getVideoElement();
    if (!video || video.dataset.narradorBound) return;
    video.dataset.narradorBound = "1";
    video.addEventListener("seeked", () => {
      const t = video.currentTime * 1000;
      lastVideoTimeMs = t;

      if (syncSeekInProgress) {
        syncSeekInProgress = false;
        return;
      }

      if (pauseForSpeechActive || pendingSpeakIndex >= 0 || isSpeaking || narrationArmed) {
        return;
      }

      speakEpoch += 1;
      lastSpokenIndex = findLastCueIndexBefore(t) - 1;
      lastSceneKey = "";
      pendingSpeakIndex = -1;
      resetDomCaptionState();
      cancelSpeech();
      syncNarration();
    });
    video.addEventListener("play", () => {
      if (settings.enabled) syncNarration();
    });
  }

  function stopWatching() {
    if (syncTimer) {
      clearInterval(syncTimer);
      syncTimer = null;
    }
    cancelSpeech();
    updateUI();
  }

  function createWidget() {
    if (document.getElementById("narrador-yt-widget")) return;

    widget = document.createElement("div");
    widget.id = "narrador-yt-widget";
    widget.innerHTML = `
      <div class="narrador-panel">
        <button type="button" class="btn-minimize" title="Minimizar">−</button>
        <div class="narrador-header">
          <span class="narrador-dot"></span>
          <span>Narrador YouTube</span>
        </div>
        <div class="narrador-status">Cargando…</div>
        <div class="narrador-progress" hidden>
          <div class="narrador-progress-bar"></div>
        </div>
        <div class="narrador-last"></div>
        <div class="narrador-actions">
          <button type="button" class="btn-toggle">Activar</button>
          <button type="button" class="btn-test">Probar voz</button>
          <button type="button" class="btn-reload">Recargar subs</button>
        </div>
      </div>
      <button type="button" class="narrador-fab" title="Narrador YouTube">🔊</button>
    `;

    document.body.appendChild(widget);

    widget.querySelector(".btn-minimize").addEventListener("click", () => {
      widget.classList.add("collapsed");
    });

    widget.querySelector(".narrador-fab").addEventListener("click", () => {
      widget.classList.remove("collapsed");
    });

    widget.querySelector(".btn-toggle").addEventListener("click", () => {
      settings.enabled = !settings.enabled;
      chrome.storage.sync.set({ enabled: settings.enabled });
      if (settings.enabled) startWatching();
      else stopWatching();
      updateUI();
    });

    widget.querySelector(".btn-test").addEventListener("click", () => {
      voiceUnlocked = true;
      if (!useNative) requestVoices();
      speak("Voz activada. Narración sincronizada con el vídeo.", -1);
      updateUI();
    });

    widget.querySelector(".btn-reload").addEventListener("click", () => {
      const vid = getVideoId();
      if (vid) {
        downloadingFor = null;
        lastSpokenIndex = -1;
        lastSceneKey = "";
        cancelSpeech();
        downloadCaptions(vid);
      }
    });

    updateUI();
    if (uiTimer) clearInterval(uiTimer);
    uiTimer = setInterval(() => {
      updateUI();
    }, 500);
  }

  function captionDurationLabel() {
    if (!cues.length) return "";
    const endMs = cues[cues.length - 1]?.endMs || 0;
    if (endMs < 60000) return "";
    const min = Math.round(endMs / 60000);
    return ` (~${min} min)`;
  }

  function captionStatusLabel() {
    switch (captionStatus) {
      case "loading": {
        const sec = downloadStartedAt
          ? Math.floor((Date.now() - downloadStartedAt) / 1000)
          : 0;
        const attempt = downloadAttemptNum || 1;
        const partial =
          downloadRawSegments > 0
            ? ` · ${downloadRawSegments} segmentos`
            : cues.length > 0
              ? ` · ${cues.length} escenas`
              : "";
        if (settings.pauseWhileLoadingSubs !== false && pauseForLoadActive) {
          return `Pausado · descargando ${attempt}/5 (${sec}s)${partial}`;
        }
        return `Descargando subtítulos ${attempt}/5 (${sec}s)${partial}`;
      }
      case "ready":
        return shouldSceneLock()
          ? `✓ ${cues.length} escenas${captionDurationLabel()}${captionLangHint()} · sync bloqueada`
          : `✓ Listo · ${cues.length} escenas${captionDurationLabel()}${captionLangHint()} · sync por tiempo`;
      case "dom":
        return "Modo pantalla (fallback) · Recargar subs";
      case "none":
        return `Sin subtítulos en ${langLabel(langPrefCode())} — en YouTube: CC → idioma o traducir`;
      case "error":
        return "Error al descargar · pulsa Recargar subs";
      default:
        return "";
    }
  }

  function updateUI() {
    if (!widget) return;

    const dot = widget.querySelector(".narrador-dot");
    const status = widget.querySelector(".narrador-status");
    const progress = widget.querySelector(".narrador-progress");
    const progressBar = widget.querySelector(".narrador-progress-bar");
    const last = widget.querySelector(".narrador-last");
    const toggleBtn = widget.querySelector(".btn-toggle");
    const videoId = getVideoId();
    const meta = captionStatusLabel();

    dot.className = "narrador-dot";
    status.className = "narrador-status";

    if (!videoId) {
      status.textContent = "Abre un vídeo para usar el narrador.";
      if (progress) progress.hidden = true;
      toggleBtn.textContent = settings.enabled ? "ON" : "OFF";
      toggleBtn.classList.toggle("off", !settings.enabled);
      last.textContent = "";
      return;
    }

    if (!settings.enabled) {
      status.textContent = "Narrador desactivado.";
      toggleBtn.textContent = "Activar";
      toggleBtn.classList.add("off");
      last.textContent = "";
      return;
    }

    toggleBtn.textContent = "Desactivar";
    toggleBtn.classList.remove("off");
    dot.classList.add("on");

    if (isSpeaking) dot.classList.add("speaking");

    if (!useNative && settings.ttsEngine !== "browser") {
      status.classList.add("warn");
      status.textContent =
        "Motor Edge no conectado. Ejecuta native/install.sh y recarga la extensión.";
    } else if (captionStatus === "dom") {
      status.textContent = `Modo pantalla · ${meta}`;
    } else if (captionStatus === "loading") {
      status.textContent = meta;
      if (progress && progressBar) {
        progress.hidden = false;
        const pct = Math.min(
          95,
          Math.round(((downloadAttemptNum || 1) / 5) * 100)
        );
        progressBar.style.width = `${pct}%`;
      }
    } else if (captionStatus === "none" || captionStatus === "error") {
      status.classList.add("warn");
      status.textContent = meta;
    } else if (pendingSpeakIndex >= 0) {
      status.textContent = `Generando voz Edge… (~${Math.round(ttsLatencyMs / 1000)}s)`;
    } else if (isSpeaking || pauseForSpeechActive) {
      status.textContent = pauseForSpeechActive
        ? `Narrando · vídeo en pausa`
        : isPlaythrough()
          ? `Narrando · vídeo en marcha (audio del vídeo ~15 %)`
          : useNative
            ? `Narrando (${nativeEngine})…`
            : "Narrando…";
    } else if (lastSpeakError) {
      status.classList.add("warn");
      status.textContent = lastSpeakError;
    } else if (captionStatus === "ready" && !isVideoPlaying()) {
      status.textContent = `${meta} · pulsa Play en el vídeo`;
    } else if (isVideoPlaying()) {
      const scene =
        cues.length > 0
          ? ` · escena ${Math.min(lastSpokenIndex + 1, cues.length)}/${cues.length}`
          : "";
      status.textContent = `Sincronizado${scene} · ${meta}`;
    } else {
      status.textContent = `En pausa · ${meta}`;
    }

    if (progress && captionStatus !== "loading") {
      progress.hidden = true;
      if (progressBar) progressBar.style.width = captionStatus === "ready" ? "100%" : "0%";
    }

    const modeHint = shouldSceneLock()
      ? "sync escena"
      : isPlaythrough()
        ? "vídeo en marcha"
        : settings.catchUpMode === "pause"
          ? "pausa sync"
          : settings.catchUpMode === "speedup"
            ? "acelera voz"
            : "ralentiza vídeo";
    const sceneHint =
      captionStatus === "ready" && cues.length > 0
        ? `Escena ${Math.min(lastSpokenIndex + 1, cues.length)}/${cues.length}`
        : "";
    const motorHint = useNative
      ? `${settings.ttsEngine === "local" ? "RHVoice" : "Edge"} · ${nativeEngine || ""}`
      : "sin motor";

    last.textContent = lastSpokenLine
      ? `${debugSyncLine ? debugSyncLine + " · " : ""}«${lastSpokenLine.slice(0, 60)}${lastSpokenLine.length > 60 ? "…" : ""}»`
      : [debugSyncLine, sceneHint, modeHint, motorHint].filter(Boolean).join(" · ") || "";
  }

  window.addEventListener("narrador-voices", (e) => {
    pageVoices = Array.isArray(e.detail) ? e.detail : [];
    voiceCount = pageVoices.length;
    updateUI();
  });

  window.addEventListener("narrador-speaking", (e) => {
    if (!useNative) setSpeaking(Boolean(e.detail), currentSpeakingIndex);
  });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "GET_VOICES") {
      if (useNative && settings.ttsEngine !== "browser") {
        chrome.runtime.sendMessage(
          { type: "LIST_NATIVE_VOICES", lang: settings.lang, engine: settings.ttsEngine || "edge" },
          (resp) => {
            sendResponse({
              native: true,
              engine: nativeEngine,
              voices: resp?.voices || [],
            });
          }
        );
        return true;
      }
      updateBrowserVoices();
      sendResponse({ native: false, voices: pageVoices });
      return true;
    }

    if (message.type === "TEST_SPEAK") {
      voiceUnlocked = true;
      if (message.rate != null) settings.rate = message.rate;
      if (message.pitch != null) settings.pitch = message.pitch;
      if (message.volume != null) settings.volume = message.volume;
      if (message.lang) settings.lang = message.lang;
      if (message.voice != null) settings.voiceURI = message.voice;
      speak(message.text || "Prueba de voz.", -1);
      updateUI();
      sendResponse({ ok: true });
      return true;
    }
  });

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync") return;
    for (const key of Object.keys(changes)) {
      settings[key] = changes[key].newValue;
    }
    if ("enabled" in changes) {
      if (settings.enabled) startWatching();
      else stopWatching();
    }
    if ("ttsEngine" in changes) {
      const engine = settings.ttsEngine || "local";
      settings.voiceURI = engine === "local" ? "local:mateo" : "";
      chrome.storage.sync.set({ voiceURI: settings.voiceURI });
    }
    if ("lang" in changes && lastVideoId) {
      downloadCaptions(lastVideoId);
    }
    updateUI();
  });

  window.addEventListener("message", (e) => {
    if (e.source === window && e.data?.type === "NARRADOR_NAV") {
      const vid = getVideoId();
      if (vid && vid !== lastVideoId) {
        lastVideoId = null;
        downloadingFor = null;
      }
    }
  });

  function injectNavigateListener() {
    const script = document.createElement("script");
    script.textContent = `
      if (!window.__narradorNavHook) {
        window.__narradorNavHook = true;
        document.addEventListener("yt-navigate-finish", function () {
          window.postMessage({ type: "NARRADOR_NAV" }, "*");
        });
      }
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();
  }

  document.addEventListener("yt-navigate-finish", () => {
    const vid = getVideoId();
    if (vid && vid !== lastVideoId) {
      lastVideoId = null;
      downloadingFor = null;
    }
  });

  loadSettings().then(async () => {
    // injectPageSpeech(); // Bypassed to avoid CSP blocks - we now speak directly from content script
    // injectNavigateListener(); // Bypassed to avoid CSP blocks - replaced by direct document listener above
    await checkNativeHost(true);
    if (useNative) voiceUnlocked = true;
    createWidget();

    const videoId = getVideoId();
    if (videoId) {
      lastVideoId = videoId;
      if (settings.autoEnableCC) enableCaptionsIfNeeded();
      downloadCaptions(videoId);
    }

    if (settings.enabled) startWatching();

    setInterval(() => checkNativeHost(false), 5000);

    let lastUrl = location.href;
    setInterval(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        lastVideoId = null;
      }
      if (!document.getElementById("narrador-yt-widget")) createWidget();
    }, 1000);
  });
})();
