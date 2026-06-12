const langFilterEl = document.getElementById("lang-filter");
const searchEl = document.getElementById("search");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const listEl = document.getElementById("voice-list");
const showAllBtn = document.getElementById("show-all");
const hideAllBtn = document.getElementById("hide-all");

let allVoices = [];
let visibleVoices = new Set();
let previewingKey = null;

function setStatus(text, type) {
  statusEl.textContent = text;
  statusEl.className = "status" + (type ? ` ${type}` : "");
}

function setSummary(text, type) {
  summaryEl.textContent = text;
  summaryEl.className = "summary" + (type ? ` ${type}` : "");
}

function saveVisible() {
  chrome.storage.sync.set({ visibleVoices: [...visibleVoices], hiddenVoices: [] });
}

function matchesSearch(voice, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    (voice.name || "").toLowerCase().includes(q) ||
    (voice.voiceURI || "").toLowerCase().includes(q)
  );
}

function filteredVoices() {
  const neural = filterNeuralVoices(allVoices);
  const byLang = filterVoicesByLang(neural, langFilterEl.value);
  const q = searchEl.value.trim();
  return byLang.filter((v) => matchesSearch(v, q));
}

function updateSummary() {
  const list = filteredVoices();
  const active = list.filter((v) => visibleVoices.has(voiceKey(v))).length;
  setSummary(`${active} activas · ${list.length - active} desactivadas · ${list.length} en lista`);
}

function createVoiceRow(voice) {
  const key = voiceKey(voice);
  const active = visibleVoices.has(key);
  const row = document.createElement("div");
  row.className = "voice-row" + (active ? "" : " hidden-voice");

  const label = document.createElement("label");
  label.className = "show-toggle";

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = active;
  checkbox.title = "Mostrar en el selector del popup";
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) visibleVoices.add(key);
    else visibleVoices.delete(key);
    row.classList.toggle("hidden-voice", !checkbox.checked);
    saveVisible();
    updateSummary();
  });

  const nameSpan = document.createElement("span");
  nameSpan.className = "voice-name";
  nameSpan.textContent = voice.name;

  label.appendChild(checkbox);
  label.appendChild(nameSpan);

  const badge = document.createElement("span");
  badge.className = "voice-badge";
  badge.textContent = voice.lang || voiceTypeOf(voice);

  const previewBtn = document.createElement("button");
  previewBtn.type = "button";
  previewBtn.className = "btn-preview";
  previewBtn.textContent = previewingKey === key ? "…" : "Escuchar";
  previewBtn.disabled = previewingKey === key;
  previewBtn.addEventListener("click", () => previewVoice(voice, previewBtn));

  row.appendChild(label);
  row.appendChild(badge);
  row.appendChild(previewBtn);
  return row;
}

function renderList() {
  const voices = filteredVoices();
  listEl.innerHTML = "";

  if (!voices.length) {
    listEl.innerHTML =
      '<p class="empty">No hay voces neuronales. Instala RHVoice (./native/install-rhvoice.sh) o edge-tts (pip install --user edge-tts).</p>';
    updateSummary();
    return;
  }

  const grouped = new Set();

  for (const group of VOICE_GROUPS) {
    const groupVoices = voices.filter((v) => voiceTypeOf(v) === group.type);
    if (!groupVoices.length) continue;

    groupVoices.forEach((v) => grouped.add(voiceKey(v)));

    const section = document.createElement("section");
    section.className = "voice-group";
    const title = document.createElement("h2");
    title.textContent = group.label;
    section.appendChild(title);

    for (const voice of groupVoices) {
      section.appendChild(createVoiceRow(voice));
    }
    listEl.appendChild(section);
  }

  updateSummary();
}

function previewVoice(voice, btn) {
  const key = voiceKey(voice);
  previewingKey = key;
  btn.disabled = true;
  btn.textContent = "…";

  chrome.runtime.sendMessage({ type: "NATIVE_CANCEL" }, () => {
    chrome.runtime.sendMessage(
      {
        type: "NATIVE_SPEAK",
        text: PREVIEW_TEXT,
        lang: langFilterEl.value,
        rate: 0.95,
        pitch: 1.0,
        volume: 1.0,
        voice: voice.voiceURI || voice.name,
        engine: voiceTypeOf(voice) === "local-neural" ? "local" : "edge",
      },
      () => {
        previewingKey = null;
        btn.disabled = false;
        btn.textContent = "Escuchar";
      }
    );
  });
}

function loadVoices() {
  setStatus("Cargando voces del sistema…");
  chrome.runtime.sendMessage({ type: "CHECK_NATIVE", force: true }, (nativeResp) => {
    if (!nativeResp?.native) {
      setStatus("Motor nativo no disponible. Ejecuta native/install.sh y recarga la extensión.", "error");
      setSummary("");
      listEl.innerHTML = "";
      return;
    }

    chrome.runtime.sendMessage(
      { type: "LIST_NATIVE_VOICES", lang: langFilterEl.value, engine: "all" },
      (voiceResp) => {
        allVoices = filterNeuralVoices(voiceResp?.voices || []);
        if (!allVoices.length) {
          setStatus("No hay voces Edge. Instala: pip install --user edge-tts", "warn");
          renderList();
          return;
        }
        setStatus(`${allVoices.length} voz(es) neuronal(es) (${nativeResp.engine})`);
        renderList();
      }
    );
  });
}

showAllBtn.addEventListener("click", () => {
  for (const v of filteredVoices()) visibleVoices.add(voiceKey(v));
  saveVisible();
  renderList();
});

hideAllBtn.addEventListener("click", () => {
  for (const v of filteredVoices()) visibleVoices.delete(voiceKey(v));
  saveVisible();
  renderList();
});

langFilterEl.addEventListener("change", loadVoices);
searchEl.addEventListener("input", renderList);

chrome.storage.sync.get({ visibleVoices: [], lang: "es-ES" }, (stored) => {
  visibleVoices = new Set(
    (stored.visibleVoices || []).filter(
      (k) => String(k).startsWith("edge:") || String(k).startsWith("local:")
    )
  );
  if (stored.lang) langFilterEl.value = stored.lang;
  loadVoices();
});
