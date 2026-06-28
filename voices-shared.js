const VOICE_GROUPS = [
  { type: "edge-neural", label: "Neuronales online (Microsoft Edge)" },
  { type: "local-neural", label: "Neuronales locales (RHVoice)" },
  { type: "browser", label: "Navegador (Google TTS / Sistema)" },
];

const PREVIEW_TEXT =
  "Hola, esta es una muestra de voz para el narrador de subtítulos de YouTube.";

function voiceKey(voice) {
  return voice.voiceURI || voice.name || "";
}

function voiceTypeOf(voice) {
  if (voice.voiceType) return voice.voiceType;
  const uri = voice.voiceURI || voice.name || "";
  if (uri.startsWith("edge:") || /Neural$/i.test(uri)) return "edge-neural";
  if (uri.startsWith("local:") || uri.startsWith("rhvoice:")) return "local-neural";
  if (uri.startsWith("browser:") || uri.startsWith("system:") || voice.localService !== undefined) return "browser";
  return "standard";
}

function isNeuralVoice(voice) {
  const t = voiceTypeOf(voice);
  return t === "edge-neural" || t === "local-neural" || t === "browser";
}

function filterNeuralVoices(voices) {
  return voices.filter(isNeuralVoice);
}

function filterVoicesByEngine(voices, ttsEngine) {
  const type = ttsEngine === "local" ? "local-neural" : ttsEngine === "edge" ? "edge-neural" : "browser";
  return filterNeuralVoices(voices).filter((v) => voiceTypeOf(v) === type);
}

function voicePrefixForEngine(ttsEngine) {
  return ttsEngine === "local" ? "local:" : ttsEngine === "edge" ? "edge:" : "browser:";
}

function filterVoicesByLang(voices, langCode) {
  const lang = (langCode || "es").split("-")[0].toLowerCase();
  return voices.filter((v) => {
    const vl = (v.lang || "").toLowerCase();
    if (vl.startsWith(lang)) return true;
    if (lang === "es" && /spanish|mateo|elvira|alvaro/i.test(v.name || "")) return true;
    return false;
  });
}

function filterVisibleVoices(voices, visibleVoices) {
  const list = visibleVoices || [];
  if (!list.length) return voices;
  const visible = new Set(list);
  return voices.filter((v) => visible.has(voiceKey(v)));
}
