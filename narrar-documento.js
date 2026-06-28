(function () {
  "use strict";

  const DEFAULTS = {
    enabled: true,
    rate: 1.0,
    pitch: 1.0,
    volume: 1.0,
    voiceURI: "",
    lang: "es-ES",
    ttsEngine: "local",
  };

  let settings = { ...DEFAULTS };
  let docElements = []; // { text: string, el: HTMLElement }
  let currentIndex = -1;
  let isSpeaking = false;
  let isPaused = true;
  let widget = null;
  let useNative = false;
  let nativeEngine = null;
  let speakEpoch = 0;
  let highlightClass = "narrador-highlight-active";

  // CSS para destacar el párrafo actual y para el widget flotante
  const style = document.createElement("style");
  style.textContent = `
    .${highlightClass} {
      background-color: rgba(240, 180, 41, 0.25) !important;
      border-left: 3px solid #c6960a !important;
      padding-left: 5px !important;
      transition: background-color 0.3s ease, border-left 0.3s ease;
    }
    #narrador-doc-widget {
      position: fixed;
      bottom: 20px;
      right: 20px;
      z-index: 100000;
      background: #0a2240;
      color: #ffffff;
      padding: 10px 15px;
      border-radius: 30px;
      box-shadow: 0 4px 15px rgba(0,0,0,0.35);
      font-family: system-ui, -apple-system, sans-serif;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 10px;
      border: 1px solid #1e4d8c;
      user-select: none;
      transition: opacity 0.3s;
    }
    #narrador-doc-widget button {
      background: transparent;
      border: none;
      color: #ffffff;
      cursor: pointer;
      font-size: 16px;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
      border-radius: 50%;
      transition: background 0.2s;
    }
    #narrador-doc-widget button:hover {
      background: rgba(255,255,255,0.15);
    }
    #narrador-doc-widget button:active {
      background: rgba(255,255,255,0.25);
    }
    #narrador-doc-widget .play-btn {
      background: #1e4d8c;
    }
    #narrador-doc-widget .play-btn:hover {
      background: #2d6bc4;
    }
    #narrador-doc-widget .widget-info {
      font-weight: 500;
      padding: 0 4px;
      min-width: 80px;
      text-align: center;
    }
  `;
  document.head.appendChild(style);

  function loadSettings() {
    return new Promise((resolve) => {
      chrome.storage.sync.get(DEFAULTS, (stored) => {
        settings = { ...DEFAULTS, ...stored };
        resolve(settings);
      });
    });
  }

  function checkNativeHost() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "CHECK_NATIVE", force: false }, (resp) => {
        useNative = Boolean(resp?.native);
        nativeEngine = resp?.engine || null;
        resolve(useNative);
      });
    });
  }

  // Analiza la página y extrae el texto legible en orden secuencial
  function parsePageContent() {
    docElements = [];
    
    // Buscar contenedor principal
    let container = document.getElementById("contenido") || document.querySelector("main") || document.querySelector("article") || document.body;
    
    // Selectores legibles en orden de importancia
    const selectors = ["p", "h2", "h3", "h4", "li", "caption", "figcaption"];
    const elements = container.querySelectorAll(selectors.join(","));
    
    elements.forEach((el) => {
      // Filtrar elementos vacíos, fórmulas en formato crudo, o elementos de navegación/herramientas
      const text = el.innerText || el.textContent || "";
      const cleaned = text.trim();
      
      // Evitar elementos ocultos, muy cortos o de herramientas
      if (!cleaned || cleaned.length < 3) return;
      if (el.closest(".toolbar") || el.closest(".aviso") || el.closest(".pie") || el.closest(".formula-raw") || el.closest(".tabla-stats")) {
        return;
      }
      
      docElements.push({
        text: cleaned,
        el: el
      });
    });
  }

  function highlightParagraph(index) {
    // Limpiar highlights previos
    document.querySelectorAll(`.${highlightClass}`).forEach((el) => {
      el.classList.remove(highlightClass);
    });

    if (index >= 0 && index < docElements.length) {
      const item = docElements[index];
      item.el.classList.add(highlightClass);
      
      // Hacer scroll suave hacia el elemento
      item.el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function speakChunk(text, index) {
    if (!text.trim() || !settings.enabled) return;

    isSpeaking = true;
    isPaused = false;
    updateWidgetUI();
    highlightParagraph(index);

    const epoch = ++speakEpoch;
    const ttsEngine = settings.ttsEngine || "local";
    const voiceURI = settings.voiceURI || (ttsEngine === "local" ? "local:mateo" : "");

    if (useNative) {
      chrome.runtime.sendMessage(
        {
          type: "NATIVE_SPEAK",
          text,
          lang: settings.lang || "es-ES",
          rate: settings.rate ?? 1.0,
          pitch: settings.pitch ?? 1.0,
          volume: settings.volume ?? 1.0,
          voice: voiceURI,
          engine: ttsEngine,
          ttsEngine,
        },
        (resp) => {
          if (epoch !== speakEpoch) return;
          
          if (resp?.ok) {
            // Avanzar al siguiente al terminar
            if (isSpeaking && !isPaused) {
              nextParagraph();
            }
          } else {
            console.error("Error al narrar página:", resp?.error || "desconocido");
            stopNarration();
          }
        }
      );
    } else {
      // Fallback a SpeechSynthesis del navegador si no hay host nativo
      window.dispatchEvent(
        new CustomEvent("narrador-speak", {
          detail: {
            text,
            rate: settings.rate ?? 1.0,
            pitch: settings.pitch ?? 1.0,
            volume: settings.volume ?? 1.0,
            lang: settings.lang || "es-ES",
            voiceURI: settings.voiceURI,
          },
        })
      );
    }
  }

  function cancelSpeech() {
    speakEpoch += 1;
    isSpeaking = false;
    if (useNative) {
      chrome.runtime.sendMessage({ type: "NATIVE_CANCEL" });
    } else {
      window.dispatchEvent(new CustomEvent("narrador-cancel"));
    }
  }

  function playNarration() {
    if (docElements.length === 0) {
      parsePageContent();
    }
    if (docElements.length === 0) return;

    if (currentIndex < 0) {
      currentIndex = 0;
    }

    isPaused = false;
    speakChunk(docElements[currentIndex].text, currentIndex);
  }

  function pauseNarration() {
    isPaused = true;
    cancelSpeech();
    updateWidgetUI();
  }

  function stopNarration() {
    isPaused = true;
    isSpeaking = false;
    currentIndex = -1;
    cancelSpeech();
    highlightParagraph(-1);
    updateWidgetUI();
  }

  function nextParagraph() {
    if (currentIndex < docElements.length - 1) {
      currentIndex++;
      speakChunk(docElements[currentIndex].text, currentIndex);
    } else {
      stopNarration();
    }
  }

  function prevParagraph() {
    if (currentIndex > 0) {
      currentIndex--;
      speakChunk(docElements[currentIndex].text, currentIndex);
    }
  }

  // Crear el widget de reproducción flotante
  function createWidget() {
    if (document.getElementById("narrador-doc-widget")) return;

    widget = document.createElement("div");
    widget.id = "narrador-doc-widget";
    widget.innerHTML = `
      <button id="narrador-prev-btn" title="Anterior (flecha izquierda)">⏮</button>
      <button id="narrador-play-btn" class="play-btn" title="Reproducir / Pausar (Espacio)">▶</button>
      <button id="narrador-stop-btn" title="Detener (Esc)">⏹</button>
      <button id="narrador-next-btn" title="Siguiente (flecha derecha)">⏭</button>
      <span class="widget-info" id="narrador-widget-info">Listo</span>
    `;

    document.body.appendChild(widget);

    document.getElementById("narrador-play-btn").addEventListener("click", () => {
      if (isSpeaking && !isPaused) {
        pauseNarration();
      } else {
        playNarration();
      }
    });

    document.getElementById("narrador-stop-btn").addEventListener("click", stopNarration);
    document.getElementById("narrador-next-btn").addEventListener("click", nextParagraph);
    document.getElementById("narrador-prev-btn").addEventListener("click", prevParagraph);

    // Soporte para atajos de teclado
    document.addEventListener("keydown", (e) => {
      // Solo actuar si el foco no está en un campo de texto/input
      if (document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA" || document.activeElement.isContentEditable) {
        return;
      }

      if (e.key === " ") {
        e.preventDefault();
        if (isSpeaking && !isPaused) pauseNarration();
        else playNarration();
      } else if (e.key === "Escape") {
        stopNarration();
      } else if (e.key === "ArrowRight") {
        nextParagraph();
      } else if (e.key === "ArrowLeft") {
        prevParagraph();
      }
    });
  }

  function updateWidgetUI() {
    if (!widget) return;
    const playBtn = document.getElementById("narrador-play-btn");
    const infoSpan = document.getElementById("narrador-widget-info");

    if (isSpeaking && !isPaused) {
      playBtn.textContent = "⏸";
      playBtn.title = "Pausar (Espacio)";
      infoSpan.textContent = `Narrando ${currentIndex + 1}/${docElements.length}`;
    } else {
      playBtn.textContent = "▶";
      playBtn.title = "Reproducir (Espacio)";
      if (currentIndex >= 0) {
        infoSpan.textContent = `Pausado ${currentIndex + 1}/${docElements.length}`;
      } else {
        infoSpan.textContent = `Documento (${docElements.length})`;
      }
    }
  }

  // Escuchar cambios de configuraciones (velocidad, volumen, voces) desde el popup
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "sync") return;
    for (const key of Object.keys(changes)) {
      settings[key] = changes[key].newValue;
    }
    // Si la narración estaba activa, re-producir el fragmento actual con los nuevos parámetros
    if (isSpeaking && !isPaused && currentIndex >= 0) {
      cancelSpeech();
      speakChunk(docElements[currentIndex].text, currentIndex);
    }
  });

  // Escuchar mensajes de prueba desde el popup
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "TEST_SPEAK") {
      if (message.rate != null) settings.rate = message.rate;
      if (message.pitch != null) settings.pitch = message.pitch;
      if (message.volume != null) settings.volume = message.volume;
      if (message.lang) settings.lang = message.lang;
      if (message.voice != null) settings.voiceURI = message.voice;
      
      cancelSpeech();
      speakChunk(message.text || "Prueba de voz del narrador.", currentIndex >= 0 ? currentIndex : 0);
      sendResponse({ ok: true });
      return true;
    }
  });

  // Inicializar
  loadSettings().then(async () => {
    // Solo activar en manuales y guías (páginas bajo la carpeta /docs/)
    const path = window.location.pathname.toLowerCase();
    if (!path.includes('/docs/')) {
      return;
    }

    await checkNativeHost();
    parsePageContent();
    createWidget();
    updateWidgetUI();
  });
})();
