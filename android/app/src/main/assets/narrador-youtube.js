/**
 * Narrador YouTube — inyectado en WebView Android (puente NarradorAndroid).
 */
(function () {
  "use strict";
  if (window.__narradorAndroidLoaded) return;
  window.__narradorAndroidLoaded = true;

  var VIDEO_DUCK = 0.15;
  var DOM_STABLE_MS = 650;
  var lastSpoken = "";
  var domTimer = null;
  var speaking = false;
  var savedVolume = null;
  var pollTimer = null;

  function bridge() {
    return window.NarradorAndroid;
  }

  function enabled() {
    try {
      return bridge() && bridge().isEnabled();
    } catch (e) {
      return false;
    }
  }

  function langPref() {
    try {
      var s = JSON.parse(bridge().getSettings() || "{}");
      return (s.lang || "es-ES").split("-")[0].toLowerCase();
    } catch (e) {
      return "es";
    }
  }

  function getVideo() {
    return document.querySelector("video.html5-main-video") || document.querySelector("video");
  }

  function duckVideo(on) {
    var v = getVideo();
    if (!v) return;
    if (on) {
      if (savedVolume === null) savedVolume = v.volume;
      v.volume = VIDEO_DUCK;
    } else if (savedVolume !== null) {
      v.volume = savedVolume;
      savedVolume = null;
    }
  }

  function getVisibleCaptionText() {
    var segments = document.querySelectorAll(".ytp-caption-segment");
    if (segments.length) {
      var lines = [];
      segments.forEach(function (el) {
        var t = (el.textContent || "").trim();
        if (t) lines.push(t);
      });
      if (lines.length) return lines.join(" ");
    }
    var win = document.querySelector(".ytp-caption-window-container");
    if (win) {
      var t2 = (win.innerText || win.textContent || "").trim();
      if (t2) return t2.replace(/\s+/g, " ");
    }
    return "";
  }

  function pickSpanishLine(text) {
    var parts = text.split(/\n+/).map(function (p) {
      return p.trim();
    }).filter(Boolean);
    if (parts.length <= 1) return text;
    var pref = langPref();
    for (var i = 0; i < parts.length; i++) {
      if (/[áéíóúñ¿¡]/i.test(parts[i])) return parts[i];
    }
    return parts[parts.length - 1];
  }

  function speakText(text) {
    if (!enabled() || !text || text === lastSpoken || speaking) return;
    lastSpoken = text;
    speaking = true;
    duckVideo(true);
    var id = "u-" + Date.now();
    var rate = 1.0;
    try {
      var s = JSON.parse(bridge().getSettings() || "{}");
      rate = s.rate || 1.0;
    } catch (e) {}
    bridge().speak(text, langPref() + "-ES", rate, 1.0, 1.0, id);
  }

  window.NarradorHost = {
    onNativeSpeakDone: function () {
      speaking = false;
      duckVideo(false);
    },
  };

  function scheduleDomSpeak() {
    if (domTimer) clearTimeout(domTimer);
    domTimer = setTimeout(function () {
      domTimer = null;
      var raw = getVisibleCaptionText();
      if (!raw) return;
      var text = pickSpanishLine(raw);
      if (text.length < 2) return;
      speakText(text);
    }, DOM_STABLE_MS);
  }

  function observeCaptions() {
    var root = document.body;
    if (!root) return;
    var obs = new MutationObserver(function () {
      if (!enabled()) return;
      var t = getVisibleCaptionText();
      if (t && t !== lastSpoken) scheduleDomSpeak();
    });
    obs.observe(root, { subtree: true, childList: true, characterData: true });
  }

  function getVideoId() {
    try {
      return new URL(location.href).searchParams.get("v");
    } catch (e) {
      return null;
    }
  }

  function langMatches(code, pref) {
    var c = String(code || "").toLowerCase().replace("_", "-");
    return c === pref || c.indexOf(pref + "-") === 0;
  }

  function fetchTimedText(videoId, lang, kind, tlang) {
    var url =
      "https://www.youtube.com/api/timedtext?v=" +
      encodeURIComponent(videoId) +
      "&lang=" +
      encodeURIComponent(lang) +
      "&fmt=json3";
    if (kind) url += "&kind=" + encodeURIComponent(kind);
    if (tlang) url += "&tlang=" + encodeURIComponent(tlang);
    return fetch(url, { credentials: "include" })
      .then(function (r) {
        return r.ok ? r.text() : "";
      })
      .then(function (txt) {
        if (!txt || !txt.trim()) return null;
        try {
          return JSON.parse(txt);
        } catch (e) {
          return null;
        }
      });
  }

  var cues = [];
  var cueIndex = -1;

  function buildCues(events) {
    var out = [];
    (events || []).forEach(function (ev, i) {
      var text = (ev.segs || [])
        .map(function (s) {
          return s.utf8 || "";
        })
        .join("")
        .replace(/\n/g, " ")
        .trim();
      if (!text) return;
      out.push({
        startMs: ev.tStartMs || 0,
        endMs: (ev.tStartMs || 0) + (ev.dDurationMs || 2000),
        text: text,
        index: out.length,
      });
    });
    return out;
  }

  function loadCaptions(videoId) {
    var pref = langPref();
    return fetchTimedText(videoId, pref, "", "")
      .then(function (data) {
        if (data && data.events && data.events.length) {
          return { events: data.events, lang: pref };
        }
        return fetchTimedText(videoId, "es", "", "").then(function (d2) {
          if (d2 && d2.events && d2.events.length) return { events: d2.events, lang: "es" };
          return fetchTimedText(videoId, "en", "asr", pref).then(function (d3) {
            if (d3 && d3.events && d3.events.length) return { events: d3.events, lang: pref };
            return null;
          });
        });
      })
      .then(function (hit) {
        if (hit && hit.events) {
          cues = buildCues(hit.events);
          cueIndex = -1;
          try {
            bridge().log("Narrador: " + cues.length + " subtítulos (" + hit.lang + ")");
          } catch (e) {}
        }
      });
  }

  function syncTick() {
    if (!enabled() || !cues.length || speaking) return;
    var v = getVideo();
    if (!v || v.paused) return;
    var t = v.currentTime * 1000;
    for (var i = 0; i < cues.length; i++) {
      var c = cues[i];
      if (t >= c.startMs && t < c.endMs && i !== cueIndex) {
        cueIndex = i;
        speakText(c.text);
        break;
      }
    }
  }

  function startSyncLoop() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(syncTick, 80);
  }

  function boot() {
    observeCaptions();
    var vid = getVideoId();
    if (vid && location.pathname.indexOf("/watch") >= 0) {
      loadCaptions(vid).then(startSyncLoop);
    }
    try {
      bridge().log("Narrador Android activo");
    } catch (e) {}
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
