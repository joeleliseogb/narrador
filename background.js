/** Service worker: voz RHVoice + descarga de subtítulos. */
const NATIVE_HOST = "com.narrador.youtube";
let nativeOk = false;
let nativeEngine = null;
let nativeEngines = [];
let nativeRhvoiceSpanish = null;
let nativeRhvoiceInstallHint = null;

const UA =
  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

function langMatches(code, pref) {
  const c = String(code || "")
    .toLowerCase()
    .replace("_", "-");
  const p = String(pref || "es")
    .split("-")[0]
    .toLowerCase();
  return c === p || c.startsWith(`${p}-`);
}

async function checkNative(force) {
  if (nativeOk && !force) return true;
  try {
    const r = await chrome.runtime.sendNativeMessage(NATIVE_HOST, { action: "ping" });
    nativeOk = Boolean(r?.ok);
    nativeEngine = r?.engine || null;
    nativeEngines = r?.engines || [];
    nativeRhvoiceSpanish = r?.rhvoiceSpanish;
    nativeRhvoiceInstallHint = r?.rhvoiceInstallHint || null;
    return nativeOk;
  } catch {
    nativeOk = false;
    return false;
  }
}

async function nativeSpeak(msg) {
  return chrome.runtime.sendNativeMessage(NATIVE_HOST, {
    action: "speak",
    text: msg.text,
    lang: msg.lang || "es-ES",
    rate: msg.rate ?? 1.0,
    pitch: msg.pitch ?? 1.0,
    volume: msg.volume ?? 1.0,
    voice: msg.voice || "local:mateo",
    engine: msg.engine || msg.ttsEngine || "local",
  });
}

async function nativeDownloadVideo(msg) {
  return chrome.runtime.sendNativeMessage(NATIVE_HOST, {
    action: "download_translated_video",
    videoId: msg.videoId,
    voice: msg.voice || "",
    rate: msg.rate ?? 1.0,
    volume: msg.volume ?? 1.0,
    pitch: msg.pitch ?? 1.0,
    ttsEngine: msg.ttsEngine || "edge",
    audioOnly: Boolean(msg.audioOnly),
    exportVolume: msg.exportVolume ?? 0.0,
    cues: msg.cues || [],
  });
}

async function nativeListVoices(lang, engine) {
  return chrome.runtime.sendNativeMessage(NATIVE_HOST, {
    action: "list_voices",
    lang: lang || "es-ES",
    engine: engine || "all",
  });
}

async function nativeCancel() {
  try {
    await chrome.runtime.sendNativeMessage(NATIVE_HOST, { action: "cancel" });
  } catch {
    /* */
  }
}

async function fetchCaptionFromTrackBase(baseUrl, meta) {
  if (!baseUrl) return null;
  let base = baseUrl.replace(/&fmt=[^&]+/gi, "").replace(/&tlang=[^&]+/gi, "");
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
            count: data.events.length,
          };
        }
      }
      if (body.includes("<text") || body.includes("<p ") || body.includes("WEBVTT")) {
        return {
          xml: body,
          languageCode: meta?.languageCode,
          translated: Boolean(meta?.translated),
          sourceLanguageCode: meta?.sourceLanguageCode,
          count: (body.match(/<text[\s>]/g) || []).length,
        };
      }
    } catch {
      /* */
    }
  }
  return null;
}

async function fetchTranscriptViaInnertube(videoId, langPref) {
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

  const translatable = tracks.filter(
    (t) => !langMatches(t.languageCode, pref) && t.isTranslatable !== false
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
    if (hit) return hit;
  }

  const sameLang = tracks.filter((t) => langMatches(t.languageCode, pref));
  const ordered = [...sameLang].sort(
    (a, b) => (a.kind === "asr" ? 1 : 0) - (b.kind === "asr" ? 1 : 0)
  );
  for (const track of ordered) {
    const hit = await fetchCaptionFromTrackBase(track.baseUrl, {
      languageCode: track.languageCode || pref,
      translated: false,
      sourceLanguageCode: track.languageCode,
    });
    if (hit) return hit;
  }

  return null;
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "CHECK_NATIVE") {
    checkNative(Boolean(message.force)).then((ok) => {
      sendResponse({
        native: ok,
        engine: nativeEngine,
        engines: nativeEngines,
        rhvoiceSpanish: nativeRhvoiceSpanish,
        rhvoiceInstallHint: nativeRhvoiceInstallHint,
      });
    });
    return true;
  }

  if (message.type === "LIST_NATIVE_VOICES") {
    checkNative(true)
      .then((ok) => {
        if (!ok) return { ok: false, voices: [] };
        return nativeListVoices(message.lang, message.engine || message.ttsEngine || "all");
      })
      .then((resp) => sendResponse(resp || { ok: false, voices: [] }))
      .catch(() => sendResponse({ ok: false, voices: [] }));
    return true;
  }

  if (message.type === "NATIVE_SPEAK") {
    checkNative(true)
      .then((ok) => {
        if (!ok) throw new Error("native host missing");
        return nativeSpeak(message);
      })
      .then((resp) =>
        sendResponse({
          ok: Boolean(resp?.ok),
          engine: resp?.engine || nativeEngine,
          blocking: Boolean(resp?.blocking),
          durationMs: resp?.durationMs || 0,
          generateMs: resp?.generateMs || 0,
          error: resp?.error || null,
        })
      )
      .catch((err) =>
        sendResponse({
          ok: false,
          engine: null,
          error: err?.message || "native host error",
        })
      );
    return true;
  }

  if (message.type === "NATIVE_CANCEL") {
    nativeCancel().then(() => sendResponse({ ok: true }));
    return true;
  }

  if (message.type === "NATIVE_DOWNLOAD_VIDEO") {
    nativeDownloadVideo(message)
      .then((r) => {
        const err = chrome.runtime.lastError;
        sendResponse(r || { ok: false, error: err?.message });
      })
      .catch((err) => sendResponse({ ok: false, error: err.message }));
    return true;
  }

  if (message.type === "SAVE_DEBUG_HTML") {
    chrome.runtime.sendNativeMessage(
      NATIVE_HOST,
      { action: "save_debug_html", html: message.html },
      (r) => {
        const err = chrome.runtime.lastError;
        sendResponse(r || { ok: false, error: err?.message });
      }
    );
    return true;
  }

  if (message.type === "FETCH_TRANSCRIPT") {
    fetchTranscriptViaInnertube(message.videoId, message.lang)
      .then((payload) =>
        sendResponse({
          ok: Boolean(payload?.xml || payload?.events?.length),
          payload,
          count: payload?.count || 0,
        })
      )
      .catch((err) =>
        sendResponse({ ok: false, error: err?.message || "fetch failed" })
      );
    return true;
  }

  if (message.type === "FETCH_URL") {
    fetch(message.url, { credentials: "include" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => sendResponse({ ok: Boolean(data), data }))
      .catch(() => sendResponse({ ok: false, data: null }));
    return true;
  }
});

checkNative(true);
setInterval(() => checkNative(true), 15000);
