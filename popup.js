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
  videoDuckVolume: 0.15,
  visibleVoices: [],
};

const enabledEl = document.getElementById("enabled");
const langEl = document.getElementById("lang");
const voiceEl = document.getElementById("voice");
const rateEl = document.getElementById("rate");
const pitchEl = document.getElementById("pitch");
const volumeEl = document.getElementById("volume");
const autoEnableCCEl = document.getElementById("autoEnableCC");
const pauseWhileLoadingSubsEl = document.getElementById("pauseWhileLoadingSubs");
const autoSyncEl = document.getElementById("autoSync");
const maxSyncRateEl = document.getElementById("maxSyncRate");
const maxSyncFieldEl = document.getElementById("max-sync-field");
const minVideoFieldEl = document.getElementById("min-video-field");
const minVideoRateEl = document.getElementById("minVideoRate");
const catchUpPlaythroughEl = document.getElementById("catchUp-playthrough");
const catchUpPauseEl = document.getElementById("catchUp-pause");
const catchUpSpeedupEl = document.getElementById("catchUp-speedup");
const catchUpSlowdownEl = document.getElementById("catchUp-slowdown");
const ttsLocalEl = document.getElementById("tts-local");
const ttsEdgeEl = document.getElementById("tts-edge");
const rateValueEl = document.getElementById("rate-value");
const maxSyncValueEl = document.getElementById("max-sync-value");
const minVideoValueEl = document.getElementById("min-video-value");
const pitchValueEl = document.getElementById("pitch-value");
const volumeValueEl = document.getElementById("volume-value");
const testBtn = document.getElementById("test-voice");
const voiceHintEl = document.getElementById("voice-hint");
const manageVoicesEl = document.getElementById("manage-voices");
const manageVoicesFooterEl = document.getElementById("manage-voices-footer");

let allVoices = [];
let visibleVoices = [];

function save(partial) {
  chrome.storage.sync.set(partial);
}

function formatRate(value) {
  return Number(value).toFixed(2).replace(/\.?0+$/, "") || "1";
}

function setRate(value) {
  const v = Math.max(0.5, Math.min(1.8, value));
  rateEl.value = String(v);
  rateValueEl.textContent = formatRate(v);
  save({ rate: v });
  document.querySelectorAll(".speed-preset").forEach((btn) => {
    btn.classList.toggle("active", Math.abs(parseFloat(btn.dataset.rate) - v) < 0.02);
  });
}

function updateCatchUpFieldsVisibility() {
  const syncOn = autoSyncEl.checked;
  const slowdown = catchUpSlowdownEl?.checked;
  const speedup = catchUpSpeedupEl?.checked;
  if (maxSyncFieldEl) {
    maxSyncFieldEl.style.display = syncOn && speedup ? "" : "none";
  }
  if (minVideoFieldEl) {
    minVideoFieldEl.style.display = syncOn && slowdown ? "" : "none";
  }
}

function setVoiceHint(text, type) {
  voiceHintEl.textContent = text;
  voiceHintEl.className = "voice-hint" + (type ? ` ${type}` : "");
}

function openVoiceOptions(e) {
  if (e) e.preventDefault();
  chrome.runtime.openOptionsPage();
}

function populateVoiceList(voices) {
  allVoices = filterNeuralVoices(voices);
  let filtered = filterVoicesByLang(allVoices, langEl.value);
  filtered = filterVisibleVoices(filtered, visibleVoices);
  const current = voiceEl.value;

  voiceEl.innerHTML = '<option value="">Automática (neuronal online)</option>';

  for (const group of VOICE_GROUPS) {
    const groupVoices = filtered.filter((v) => voiceTypeOf(v) === group.type);
    if (!groupVoices.length) continue;

    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label;

    for (const voice of groupVoices) {
      const opt = document.createElement("option");
      opt.value = voice.voiceURI;
      opt.textContent = voice.name;
      optgroup.appendChild(opt);
    }

    voiceEl.appendChild(optgroup);
  }

  if (current && [...voiceEl.options].some((o) => o.value === current)) {
    voiceEl.value = current;
  } else if (current && !visibleVoices.includes(current)) {
    voiceEl.value = "";
    save({ voiceURI: "" });
  }
  updateVoicePresetActive();
}

function loadVoicesFromPage() {
  chrome.runtime.sendMessage({ type: "CHECK_NATIVE", force: true }, (nativeResp) => {
    const engine = ttsLocalEl?.checked ? "local" : "edge";
    const engineLabel = engine === "local" ? "RHVoice local" : "Edge online";

    if (!nativeResp?.native) {
      voiceEl.innerHTML = `<option value="">Automática</option>`;
      setVoiceHint("Motor nativo no instalado. Ejecuta native/install.sh", "warn");
      return;
    }

    const engines = nativeResp.engines || [];
    if (engine === "local" && !engines.includes("rhvoice")) {
      voiceEl.innerHTML = '<option value="">Automática (local)</option>';
      setVoiceHint("RHVoice no detectado. Ejecuta: ./native/install-rhvoice.sh", "warn");
      return;
    }
    if (engine === "local" && nativeResp.rhvoiceSpanish === false) {
      const hint = nativeResp.rhvoiceInstallHint
        || "sudo snap install rhvoice && sudo rhvoice.vm -i mateo";
      setVoiceHint(`Sin voz española. Instala Mateo: ${hint}`, "warn");
    }
    if (engine === "edge" && !engines.includes("edge-tts")) {
      voiceEl.innerHTML = '<option value="">Automática (Edge)</option>';
      setVoiceHint("edge-tts no instalado. Ejecuta: pip install --user edge-tts", "warn");
      return;
    }

    chrome.runtime.sendMessage(
      { type: "LIST_NATIVE_VOICES", lang: langEl.value, engine },
      (voiceResp) => {
        const neural = filterVoicesByEngine(voiceResp?.voices || [], engine);
        if (neural.length) {
          populateVoiceList(neural);
          setVoiceHint(`${neural.length} voz(es) ${engineLabel}.`, "ok");
        } else {
          voiceEl.innerHTML = `<option value="">Automática (${engineLabel})</option>`;
          setVoiceHint(`Sin voces ${engineLabel} para este idioma.`, "warn");
        }
      }
    );
  });
}

function bindRange(input, label, key) {
  input.addEventListener("input", () => {
    const value = parseFloat(input.value);
    label.textContent = value.toFixed(1);
    save({ [key]: value });
  });
}

function populateForm(stored) {
  const engine = stored.ttsEngine || "local";
  const prefix = engine === "local" ? "local:" : "edge:";
  if (stored.voiceURI && !stored.voiceURI.startsWith(prefix)) {
    stored.voiceURI = "";
    chrome.storage.sync.set({ voiceURI: "" });
  }
  if (engine === "local" && (stored.lang || "es").startsWith("es")) {
    if (stored.voiceURI && !isSpanishLocalVoice(stored.voiceURI)) {
      stored.voiceURI = "local:mateo";
      chrome.storage.sync.set({ voiceURI: "local:mateo" });
    }
  }
  visibleVoices = (stored.visibleVoices || []).filter(
    (k) => k.startsWith("edge:") || k.startsWith("local:")
  );
  if (visibleVoices.length !== (stored.visibleVoices || []).length) {
    chrome.storage.sync.set({ visibleVoices });
  }
  enabledEl.checked = stored.enabled;
  langEl.value = stored.lang;
  rateEl.value = stored.rate;
  pitchEl.value = stored.pitch;
  volumeEl.value = stored.volume;
  autoEnableCCEl.checked = stored.autoEnableCC;
  if (pauseWhileLoadingSubsEl) {
    pauseWhileLoadingSubsEl.checked = stored.pauseWhileLoadingSubs !== false;
  }
  const catchUp = stored.catchUpMode || "playthrough";
  if (catchUpPlaythroughEl) catchUpPlaythroughEl.checked = catchUp === "playthrough";
  if (catchUpPauseEl) catchUpPauseEl.checked = catchUp === "pause";
  if (catchUpSpeedupEl) catchUpSpeedupEl.checked = catchUp === "speedup";
  if (catchUpSlowdownEl) catchUpSlowdownEl.checked = catchUp === "slowdown";
  if (ttsLocalEl) ttsLocalEl.checked = engine === "local";
  if (ttsEdgeEl) ttsEdgeEl.checked = engine === "edge";
  minVideoRateEl.value = stored.minVideoRate ?? 0.65;
  minVideoValueEl.textContent = (stored.minVideoRate ?? 0.65).toFixed(2);
  autoSyncEl.checked = stored.autoSync !== false;
  maxSyncRateEl.value = stored.maxSyncRate ?? 2.0;
  rateValueEl.textContent = formatRate(stored.rate);
  pitchValueEl.textContent = stored.pitch.toFixed(1);
  volumeValueEl.textContent = stored.volume.toFixed(1);
  maxSyncValueEl.textContent = (stored.maxSyncRate ?? 2.0).toFixed(1);
  setRate(stored.rate);
  updateCatchUpFieldsVisibility();

  if (stored.voiceURI) {
    voiceEl.value = stored.voiceURI;
  }

  loadVoicesFromPage();
  updateVoicePresetActive();
}

enabledEl.addEventListener("change", () => save({ enabled: enabledEl.checked }));
langEl.addEventListener("change", () => {
  const engine = ttsLocalEl?.checked ? "local" : "edge";
  const voiceURI =
    engine === "local" && (langEl.value || "es").startsWith("es") ? "local:mateo" : "";
  save({ lang: langEl.value, voiceURI });
  voiceEl.value = voiceURI;
  loadVoicesFromPage();
});
voiceEl.addEventListener("change", () => {
  save({ voiceURI: voiceEl.value });
  updateVoicePresetActive();
});

document.querySelectorAll(".voice-preset").forEach((btn) => {
  btn.addEventListener("click", () => {
    applyVoicePreset(btn.dataset.voice, btn.dataset.engine);
    loadVoicesFromPage();
  });
});
autoEnableCCEl.addEventListener("change", () =>
  save({ autoEnableCC: autoEnableCCEl.checked })
);
if (pauseWhileLoadingSubsEl) {
  pauseWhileLoadingSubsEl.addEventListener("change", () =>
    save({ pauseWhileLoadingSubs: pauseWhileLoadingSubsEl.checked })
  );
}
autoSyncEl.addEventListener("change", () => {
  save({ autoSync: autoSyncEl.checked });
  updateCatchUpFieldsVisibility();
});

function saveCatchUpMode(mode) {
  save({ catchUpMode: mode });
  updateCatchUpFieldsVisibility();
}

const SPANISH_LOCAL_VOICE_IDS = new Set([
  "mateo", "carlos", "tomas", "leticia", "spanish", "sp_es", "seba",
]);

function isSpanishLocalVoice(voiceURI) {
  const id = (voiceURI || "").replace(/^local:/, "").toLowerCase();
  return SPANISH_LOCAL_VOICE_IDS.has(id);
}

function saveTtsEngine(engine) {
  const voiceURI =
    engine === "local"
      ? voiceEl.value && voiceEl.value.startsWith("local:")
        ? voiceEl.value
        : "local:mateo"
      : voiceEl.value && voiceEl.value.startsWith("edge:")
        ? voiceEl.value
        : "";
  save({ ttsEngine: engine, voiceURI });
  voiceEl.value = voiceURI;
  loadVoicesFromPage();
  updateVoicePresetActive();
}

function updateVoicePresetActive() {
  const engine = ttsLocalEl?.checked ? "local" : "edge";
  document.querySelectorAll(".voice-preset").forEach((btn) => {
    const match =
      btn.dataset.engine === engine && btn.dataset.voice === voiceEl.value;
    btn.classList.toggle("active", match);
  });
}

function applyVoicePreset(voiceURI, engine) {
  if (engine === "local" && ttsLocalEl) {
    ttsLocalEl.checked = true;
  } else if (engine === "edge" && ttsEdgeEl) {
    ttsEdgeEl.checked = true;
  }
  save({ ttsEngine: engine, voiceURI });
  voiceEl.value = voiceURI;
  updateVoicePresetActive();
  setVoiceHint(
    engine === "local"
      ? `Voz ${voiceURI.replace("local:", "")} (RHVoice). Si no suena, instálala con rhvoice.vm.`
      : `Voz Edge ${voiceURI.replace("edge:", "")}.`,
    "ok"
  );
}

if (ttsLocalEl) {
  ttsLocalEl.addEventListener("change", () => {
    if (ttsLocalEl.checked) saveTtsEngine("local");
  });
}
if (ttsEdgeEl) {
  ttsEdgeEl.addEventListener("change", () => {
    if (ttsEdgeEl.checked) saveTtsEngine("edge");
  });
}

if (catchUpPlaythroughEl) {
  catchUpPlaythroughEl.addEventListener("change", () => {
    if (catchUpPlaythroughEl.checked) saveCatchUpMode("playthrough");
  });
}
if (catchUpPauseEl) {
  catchUpPauseEl.addEventListener("change", () => {
    if (catchUpPauseEl.checked) saveCatchUpMode("pause");
  });
}
if (catchUpSpeedupEl) {
  catchUpSpeedupEl.addEventListener("change", () => {
    if (catchUpSpeedupEl.checked) saveCatchUpMode("speedup");
  });
}
if (catchUpSlowdownEl) {
  catchUpSlowdownEl.addEventListener("change", () => {
    if (catchUpSlowdownEl.checked) saveCatchUpMode("slowdown");
  });
}

bindRange(maxSyncRateEl, maxSyncValueEl, "maxSyncRate");
if (minVideoRateEl && minVideoValueEl) {
  minVideoRateEl.addEventListener("input", () => {
    const v = parseFloat(minVideoRateEl.value);
    minVideoValueEl.textContent = v.toFixed(2);
    save({ minVideoRate: v });
  });
}

rateEl.addEventListener("input", () => setRate(parseFloat(rateEl.value)));

document.querySelectorAll(".speed-preset").forEach((btn) => {
  btn.addEventListener("click", () => setRate(parseFloat(btn.dataset.rate)));
});

bindRange(pitchEl, pitchValueEl, "pitch");
bindRange(volumeEl, volumeValueEl, "volume");

if (manageVoicesEl) manageVoicesEl.addEventListener("click", openVoiceOptions);
if (manageVoicesFooterEl) manageVoicesFooterEl.addEventListener("click", openVoiceOptions);

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "sync" || !changes.visibleVoices) return;
  visibleVoices = changes.visibleVoices.newValue || [];
  if (allVoices.length) populateVoiceList(allVoices);
});

testBtn.addEventListener("click", () => {
  save({
    rate: parseFloat(rateEl.value),
    pitch: parseFloat(pitchEl.value),
    volume: parseFloat(volumeEl.value),
    lang: langEl.value,
    voiceURI: voiceEl.value,
    ttsEngine: ttsLocalEl?.checked ? "local" : "edge",
  });

  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    const tab = tabs[0];
    if (!tab?.id || !tab.url?.includes("youtube.com")) {
      setVoiceHint("Abre YouTube primero, luego pulsa Probar voz.", "warn");
      return;
    }

    testBtn.disabled = true;
    testBtn.textContent = "Probando…";

    chrome.tabs.sendMessage(
      tab.id,
      {
        type: "TEST_SPEAK",
        text: "Hola, esta es una prueba del narrador de subtítulos de YouTube.",
        rate: parseFloat(rateEl.value),
        pitch: parseFloat(pitchEl.value),
        volume: parseFloat(volumeEl.value),
        lang: langEl.value,
        voice: voiceEl.value,
      },
      () => {
        testBtn.disabled = false;
        testBtn.textContent = "Probar voz";
        if (chrome.runtime.lastError) {
          setVoiceHint("Recarga YouTube (F5) y vuelve a probar.", "warn");
        } else {
          setVoiceHint("Prueba enviada. ¿Oíste la voz?", "ok");
        }
      }
    );
  });
});

chrome.storage.sync.get(DEFAULTS, populateForm);
