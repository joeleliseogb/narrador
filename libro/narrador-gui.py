#!/usr/bin/env python3
"""
Narrador de Libros — Interfaz Gráfica (GUI)
Permite abrir PDF, EPUB, TXT, Word (.docx) y ODT, leerlos en voz alta
con voces neuronales (RHVoice / Edge) y exportarlos como audiolibros MP3.
"""

from __future__ import annotations

import os
import re
import sys
import time
import queue
import shutil
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Añadir directorios de librerías
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "libro"))
sys.path.insert(0, str(ROOT / "native"))

import site
try:
    _user_site = site.getusersitepackages()
    if _user_site and _user_site not in sys.path:
        sys.path.insert(0, _user_site)
except Exception:
    pass

import importlib.util

# Cargar módulo narrador-host
HOST_PY = ROOT / "native" / "narrador-host.py"
spec = importlib.util.spec_from_file_location("narrador_host", HOST_PY)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)

# Cargar funciones de extracción de narrador-libro
LIBRO_PY = ROOT / "libro" / "narrador-libro.py"
spec_libro = importlib.util.spec_from_file_location("narrador_libro", LIBRO_PY)
libro_mod = importlib.util.module_from_spec(spec_libro)
spec_libro.loader.exec_module(libro_mod)


class BookNarratorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Narrador de Libros & Creador de Audiolibros MP3")
        self.root.geometry("1020x720")
        self.root.minsize(800, 560)

        # Estado
        self.current_file: Path | None = None
        self.sections: list[tuple[str, str]] = []  # [(title, body)]
        self.current_section_idx = -1
        self.current_chunk_idx = 0
        self.is_speaking = False
        self.is_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.speech_session_id = 0
        self._programmatic_tree_select = False
        self.multilingual_var = tk.BooleanVar(value=True)
        self.speak_thread: threading.Thread | None = None
        self.export_thread: threading.Thread | None = None

        # Configurar tema e icono
        self._setup_style()
        self._setup_icon()

        # Construir UI
        self._build_ui()

        # Cargar voces
        self._load_voices()

        # Atajos de teclado para control total
        self.root.bind("<space>", self._on_key_space)
        self.root.bind("<Left>", self._on_key_left)
        self.root.bind("<Right>", self._on_key_right)
        self.root.bind("<Escape>", self._on_key_escape)

        # Guardar progreso al cerrar ventana
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Comprobar si hay lectura anterior
        self._update_resume_button()

    def _setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Paleta de colores moderna
        self.bg_color = "#0f172a"      # Slate 900
        self.card_bg = "#1e293b"       # Slate 800
        self.text_color = "#f8fafc"    # Slate 50
        self.accent_color = "#2563eb"  # Blue 600
        self.accent_hover = "#1d4ed8"
        self.green_color = "#059669"   # Emerald 600
        self.green_hover = "#047857"
        self.amber_color = "#d97706"   # Amber 600
        self.amber_hover = "#b45309"

        self.root.configure(bg=self.bg_color)

        style.configure("TFrame", background=self.bg_color)
        style.configure("Card.TFrame", background=self.card_bg)
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color, font=("Sans", 10))
        style.configure("Card.TLabel", background=self.card_bg, foreground=self.text_color, font=("Sans", 10))
        style.configure("Header.TLabel", background=self.card_bg, foreground=self.text_color, font=("Sans", 14, "bold"))
        style.configure("Muted.TLabel", background=self.card_bg, foreground="#94a3b8", font=("Sans", 9))
        
        style.configure("TButton", font=("Sans", 10), padding=6)
        style.configure("Accent.TButton", background=self.accent_color, foreground="#ffffff", font=("Sans", 10, "bold"), padding=6)
        style.map("Accent.TButton", background=[("active", self.accent_hover)])

        style.configure("Green.TButton", background=self.green_color, foreground="#ffffff", font=("Sans", 10, "bold"), padding=6)
        style.map("Green.TButton", background=[("active", self.green_hover)])

        style.configure("Amber.TButton", background=self.amber_color, foreground="#ffffff", font=("Sans", 10, "bold"), padding=6)
        style.map("Amber.TButton", background=[("active", self.amber_hover)])

        style.configure("Treeview", 
                        background="#1e293b", 
                        foreground="#f8fafc", 
                        fieldbackground="#1e293b",
                        rowheight=28,
                        font=("Sans", 10))
        style.map("Treeview", background=[("selected", "#3b82f6")], foreground=[("selected", "#ffffff")])

    def _setup_icon(self):
        icon_path = ROOT / "icons" / "icon128.png"
        if icon_path.is_file():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

    def _build_ui(self):
        # 1. Barra superior de acciones
        top_bar = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        top_bar.pack(fill=tk.X, padx=12, pady=(12, 6))

        title_lbl = ttk.Label(top_bar, text="📖 Narrador de Libros", style="Header.TLabel")
        title_lbl.pack(side=tk.LEFT, padx=(0, 16))

        btn_open = ttk.Button(top_bar, text="📂 Abrir Libro / PDF", command=self.open_file_dialog, style="Accent.TButton")
        btn_open.pack(side=tk.LEFT, padx=4)

        self.btn_resume = ttk.Button(top_bar, text="📍 Reanudar", command=self.resume_last_book, style="Amber.TButton")
        self.btn_resume.pack(side=tk.LEFT, padx=4)

        btn_export = ttk.Button(top_bar, text="💾 Guardar como MP3 (Opcional)", command=self.open_export_dialog, style="Green.TButton")
        btn_export.pack(side=tk.LEFT, padx=6)

        self.file_info_lbl = ttk.Label(top_bar, text="Ningún archivo cargado", style="Muted.TLabel")
        self.file_info_lbl.pack(side=tk.RIGHT, padx=8)

        # 2. Panel central (Secciones a la izquierda + Visor de texto a la derecha)
        center_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        center_paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Panel izquierdo: Lista de secciones / páginas
        left_frame = ttk.Frame(center_paned, style="Card.TFrame", padding=8)
        center_paned.add(left_frame, weight=1)

        sec_title = ttk.Label(left_frame, text="Índice / Capítulos / Páginas", style="Card.TLabel", font=("Sans", 10, "bold"))
        sec_title.pack(anchor=tk.W, pady=(0, 6))

        tree_frame = ttk.Frame(left_frame, style="Card.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=("chars",), show="tree headings")
        self.tree.heading("#0", text="Sección / Página", anchor=tk.W)
        self.tree.heading("chars", text="Caracteres", anchor=tk.E)
        self.tree.column("#0", stretch=True, width=180)
        self.tree.column("chars", stretch=False, width=80, anchor=tk.E)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Panel derecho: Visor de texto
        right_frame = ttk.Frame(center_paned, style="Card.TFrame", padding=8)
        center_paned.add(right_frame, weight=3)

        right_top = ttk.Frame(right_frame, style="Card.TFrame")
        right_top.pack(fill=tk.X, pady=(0, 6))

        self.reading_title_lbl = ttk.Label(right_top, text="Vista previa del texto", style="Card.TLabel", font=("Sans", 10, "bold"))
        self.reading_title_lbl.pack(side=tk.LEFT)

        text_container = ttk.Frame(right_frame, style="Card.TFrame")
        text_container.pack(fill=tk.BOTH, expand=True)

        self.text_view = tk.Text(
            text_container,
            wrap=tk.WORD,
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#ffffff",
            selectbackground="#2563eb",
            selectforeground="#ffffff",
            font=("DejaVu Serif", 11),
            padx=16,
            pady=16,
            relief=tk.FLAT,
        )
        text_scroll = ttk.Scrollbar(text_container, orient=tk.VERTICAL, command=self.text_view.yview)
        self.text_view.configure(yscrollcommand=text_scroll.set)
        self.text_view.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Etiqueta de resaltado de párrafo
        self.text_view.tag_configure("highlight", background="#c6960a", foreground="#ffffff")

        # 3. Panel inferior de reproducción y configuración
        bottom_card = ttk.Frame(self.root, style="Card.TFrame", padding=10)
        bottom_card.pack(fill=tk.X, padx=12, pady=(6, 12))

        # Fila 1: Opciones de voz
        voice_row = ttk.Frame(bottom_card, style="Card.TFrame")
        voice_row.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(voice_row, text="Motor de voz:", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.engine_var = tk.StringVar(value="local")
        self.engine_combo = ttk.Combobox(voice_row, textvariable=self.engine_var, values=["local (RHVoice)", "edge (Microsoft Edge)"], state="readonly", width=18)
        self.engine_combo.pack(side=tk.LEFT, padx=(0, 14))
        self.engine_combo.bind("<<ComboboxSelected>>", self._on_engine_change)

        ttk.Label(voice_row, text="Voz:", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.voice_var = tk.StringVar(value="Mateo (masculina local)")
        self.voice_combo = ttk.Combobox(voice_row, textvariable=self.voice_var, state="readonly", width=26)
        self.voice_combo.pack(side=tk.LEFT, padx=(0, 14))

        ttk.Label(voice_row, text="Velocidad:", style="Card.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        self.rate_scale = ttk.Scale(voice_row, from_=0.6, to=1.5, value=1.0, command=self._on_rate_change)
        self.rate_scale.pack(side=tk.LEFT, padx=(0, 4), fill=tk.X, expand=True)
        self.rate_val_lbl = ttk.Label(voice_row, text="1.0x", style="Card.TLabel", width=4)
        self.rate_val_lbl.pack(side=tk.LEFT, padx=(0, 10))

        self.chk_multilingual = ttk.Checkbutton(
            voice_row,
            text="🌐 Multilingüe (Inglés/Español auto)",
            variable=self.multilingual_var,
        )
        self.chk_multilingual.pack(side=tk.RIGHT, padx=4)

        # Fila 2: Controles de reproducción
        controls_row = ttk.Frame(bottom_card, style="Card.TFrame")
        controls_row.pack(fill=tk.X)

        self.btn_prev = ttk.Button(controls_row, text="⏮ Anterior (←)", command=self.prev_section, width=13)
        self.btn_prev.pack(side=tk.LEFT, padx=3)

        self.btn_play = ttk.Button(controls_row, text="▶ Leer en voz alta (Espacio)", command=self.toggle_play, style="Accent.TButton", width=25)
        self.btn_play.pack(side=tk.LEFT, padx=3)

        self.btn_stop = ttk.Button(controls_row, text="⏹ Detener (Esc)", command=self.stop_speech, width=13)
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        self.btn_next = ttk.Button(controls_row, text="⏭ Siguiente (→)", command=self.next_section, width=13)
        self.btn_next.pack(side=tk.LEFT, padx=3)

        self.page_indicator_lbl = ttk.Label(controls_row, text="", style="Card.TLabel", font=("Sans", 10, "bold"))
        self.page_indicator_lbl.pack(side=tk.LEFT, padx=(10, 6))

        self.status_lbl = ttk.Label(controls_row, text="Lectura en vivo. Barra espaciadora: pausar/reanudar. Flechas: cambiar página.", style="Muted.TLabel")
        self.status_lbl.pack(side=tk.RIGHT, padx=8)

    def _on_rate_change(self, val):
        r = float(val)
        self.rate_val_lbl.configure(text=f"{r:.2f}x")

    def _load_voices(self):
        engine_str = self.engine_var.get()
        if "local" in engine_str:
            voices = [
                "local:mateo (Español - Masculino recomendado)",
                "local:carlos (Español - Masculino)",
                "local:leticia (Español - Femenina)",
                "local:slt (Inglés nativo - Femenina)",
                "local:bdl (Inglés nativo - Masculino)",
                "local:clb (Inglés nativo - Femenina)",
            ]
        else:
            voices = [
                "edge:es-ES-AlvaroNeural (Español España - Masculina)",
                "edge:es-ES-ElviraNeural (Español España - Femenina)",
                "edge:es-MX-JorgeNeural (Español México - Masculina)",
                "edge:es-MX-DaliaNeural (Español México - Femenina)",
                "edge:en-US-AndrewMultilingualNeural (Multilingüe Neural)",
                "edge:en-US-AriaNeural (Inglés - Femenina)",
                "edge:en-US-GuyNeural (Inglés - Masculina)",
            ]
        self.voice_combo.configure(values=voices)
        if voices:
            self.voice_combo.current(0)

    def _on_engine_change(self, event=None):
        self._load_voices()

    def get_selected_voice_and_engine(self) -> tuple[str, str]:
        engine_str = self.engine_var.get()
        engine = "local" if "local" in engine_str else "edge"
        raw_voice = self.voice_var.get().split()[0]
        return raw_voice, engine

    def open_file_dialog(self):
        filetypes = [
            ("Documentos e Imágenes (con OCR)", "*.pdf *.epub *.txt *.docx *.doc *.odt *.rtf *.png *.jpg *.jpeg *.webp *.tiff *.bmp"),
            ("Archivos PDF (con OCR y Tablas)", "*.pdf"),
            ("Imágenes y Escaneos (OCR)", "*.png *.jpg *.jpeg *.webp *.tiff *.bmp"),
            ("Libros EPUB", "*.epub"),
            ("Archivos de Texto", "*.txt"),
            ("Documentos Word", "*.docx *.doc"),
            ("Documentos LibreOffice", "*.odt"),
            ("Todos los archivos", "*.*"),
        ]
        chosen = filedialog.askopenfilename(title="Seleccionar libro, documento o imagen escaneada", filetypes=filetypes)
        if not chosen:
            return

        self.load_file(Path(chosen))

    def load_file(self, path: Path):
        self.stop_speech()
        self.current_file = path
        self.file_info_lbl.configure(text=f"Analizando {path.name} (OCR automático si hay imágenes/tablas)…")
        self.status_lbl.configure(text="Extrayendo texto y aplicando OCR si es necesario…")
        self.root.update_idletasks()

        # Consultar marcador previo de este archivo
        saved_bm = libro_mod.get_bookmark(path)

        def load_worker():
            try:
                sections = libro_mod.load_sections(path)
                def on_done():
                    if not sections:
                        messagebox.showwarning("Sin contenido", "No se pudo extraer texto del documento o imagen.")
                        self.file_info_lbl.configure(text="Sin texto legible.")
                        self.status_lbl.configure(text="Listo.")
                        return

                    self.sections = sections
                    has_ocr = any("(OCR)" in title for title, _ in sections)
                    ocr_note = " · con OCR" if has_ocr else ""
                    self.file_info_lbl.configure(text=f"Archivo: {path.name} ({len(sections)} secciones{ocr_note})")

                    # Llenar árbol
                    self.tree.delete(*self.tree.get_children())
                    for i, (title, body) in enumerate(self.sections):
                        chars = len(body)
                        self.tree.insert("", tk.END, iid=str(i), text=f"{i + 1}. {title}", values=(f"{chars:,} c.",))

                    # Determinar si reanudamos en el punto guardado
                    start_target = 0
                    start_chunk = 0
                    is_resumed = False
                    if saved_bm:
                        s_idx = saved_bm.get("section_idx", 0)
                        c_idx = saved_bm.get("chunk_idx", 0)
                        if 0 <= s_idx < len(self.sections):
                            start_target = s_idx
                            start_chunk = max(0, c_idx)
                            is_resumed = (start_target > 0 or start_chunk > 0)

                    self.current_section_idx = start_target
                    self.current_chunk_idx = start_chunk
                    self._select_tree_row(start_target)

                    if is_resumed:
                        self.status_lbl.configure(text=f"📍 Reanudando en {self.sections[start_target][0]} (último punto guardado)…")
                    else:
                        self.status_lbl.configure(text=f"Cargado: {path.name}. Narrando automáticamente…")

                    self._update_resume_button()
                    # Iniciar narración inmediatamente después de analizar
                    self.root.after(120, lambda: self.start_speech(from_section=start_target, from_chunk=start_chunk))

                self.root.after(0, on_done)
            except Exception as e:
                def on_err():
                    messagebox.showerror("Error al cargar", f"Error al procesar el archivo:\n{e}")
                    self.file_info_lbl.configure(text="Error al cargar archivo")
                    self.status_lbl.configure(text="Error.")
                self.root.after(0, on_err)

        threading.Thread(target=load_worker, daemon=True).start()

    def _on_tree_select(self, event=None):
        if self._programmatic_tree_select:
            return
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        if idx == self.current_section_idx:
            return
        was_speaking = self.is_speaking
        self.stop_speech()
        self._display_section(idx)
        if was_speaking:
            self.start_speech(from_section=idx, from_chunk=0)

    def _display_section(self, idx: int):
        if idx < 0 or idx >= len(self.sections):
            return
        self.current_section_idx = idx
        title, body = self.sections[idx]
        self.reading_title_lbl.configure(text=f"{idx + 1}. {title}")
        self.text_view.delete("1.0", tk.END)
        self.text_view.insert("1.0", body)

        pct = int((idx + 1) / len(self.sections) * 100) if self.sections else 0
        self.page_indicator_lbl.configure(text=f"📍 Pág. {idx + 1}/{len(self.sections)} ({pct}%)")

    def toggle_play(self):
        if self.is_speaking:
            if self.is_paused:
                self.resume_speech()
            else:
                self.pause_speech()
        else:
            self.start_speech()

    def start_speech(self, from_section: int | None = None, from_chunk: int | None = None):
        if not self.sections:
            messagebox.showinfo("Aviso", "Primero abre un archivo PDF o libro.")
            return

        target_sec = from_section if from_section is not None else self.current_section_idx
        if target_sec < 0 or target_sec >= len(self.sections):
            target_sec = 0

        target_chunk = from_chunk if from_chunk is not None else max(0, self.current_chunk_idx)

        # Cancelar inmediatamente cualquier reproducción previa
        self.speech_session_id += 1
        self.is_paused = False
        self.pause_event.set()
        try:
            host.cancel_speech()
        except Exception:
            pass

        self.current_section_idx = target_sec
        self.current_chunk_idx = target_chunk
        self.is_speaking = True
        self.btn_play.configure(text="⏸ Pausar (Espacio)")
        self.status_lbl.configure(text=f"Leyendo pág. {target_sec + 1}…")

        voice, engine = self.get_selected_voice_and_engine()
        rate = float(self.rate_scale.get())

        current_session = self.speech_session_id
        self.speak_thread = threading.Thread(
            target=self._speech_worker,
            args=(current_session, target_sec, target_chunk, voice, engine, rate),
            daemon=True,
        )
        self.speak_thread.start()

    def pause_speech(self):
        if not self.is_speaking or self.is_paused:
            return
        self.is_paused = True
        self.pause_event.clear()
        self.btn_play.configure(text="▶ Reanudar (Espacio)")
        self.status_lbl.configure(text=f"⏸ Lectura pausada en pág. {self.current_section_idx + 1}, frase {self.current_chunk_idx + 1}.")
        try:
            host.cancel_speech()
        except Exception:
            pass
        self.save_progress(self.current_section_idx, self.current_chunk_idx)

    def resume_speech(self):
        if not self.is_speaking or not self.is_paused:
            return
        self.is_paused = False
        self.btn_play.configure(text="⏸ Pausar (Espacio)")
        self.status_lbl.configure(text=f"▶ Reanudando en pág. {self.current_section_idx + 1}, frase {self.current_chunk_idx + 1}…")
        self.pause_event.set()

    def stop_speech(self):
        self.speech_session_id += 1
        self.is_speaking = False
        self.is_paused = False
        self.pause_event.set()
        self.btn_play.configure(text="▶ Leer en voz alta (Espacio)")
        self.status_lbl.configure(text="Lectura detenida.")
        try:
            host.cancel_speech()
        except Exception:
            pass
        try:
            self.text_view.tag_remove("highlight", "1.0", tk.END)
        except Exception:
            pass
        self.save_progress(self.current_section_idx, self.current_chunk_idx)

    def prev_section(self):
        if self.current_section_idx > 0:
            target = self.current_section_idx - 1
            was_speaking = self.is_speaking
            self.stop_speech()
            self._select_tree_row_programmatic(target)
            if was_speaking:
                self.start_speech(from_section=target, from_chunk=0)

    def next_section(self):
        if self.current_section_idx < len(self.sections) - 1:
            target = self.current_section_idx + 1
            was_speaking = self.is_speaking
            self.stop_speech()
            self._select_tree_row_programmatic(target)
            if was_speaking:
                self.start_speech(from_section=target, from_chunk=0)

    def _speech_worker(self, session_id: int, start_idx: int, start_chunk_idx: int, voice: str, engine: str, rate: float):
        for s_idx in range(start_idx, len(self.sections)):
            if session_id != self.speech_session_id:
                return

            self.current_section_idx = s_idx
            self.root.after(0, lambda idx=s_idx: self._select_tree_row_programmatic(idx))
            self.save_progress(s_idx, 0)
            title, body = self.sections[s_idx]
            chunks = libro_mod.get_section_chunks(body)
            if not chunks:
                continue

            chunk_start = start_chunk_idx if s_idx == start_idx else 0
            for c_idx in range(chunk_start, len(chunks)):
                if session_id != self.speech_session_id:
                    return

                self.current_chunk_idx = c_idx
                chunk = chunks[c_idx]

                while self.is_paused:
                    if session_id != self.speech_session_id:
                        return
                    self.pause_event.wait(timeout=0.1)

                if session_id != self.speech_session_id:
                    return

                self.root.after(0, lambda c=chunk: self._highlight_text(c))

                if self.multilingual_var.get():
                    detected_lang = libro_mod.detect_language(chunk)
                else:
                    detected_lang = "es"

                speak_voice, speak_lang, speak_engine = libro_mod.resolve_voice_for_chunk(
                    detected_lang, voice, engine
                )

                lang_tag = f"[{detected_lang.upper()}] " if detected_lang != "es" else ""
                self.root.after(
                    0,
                    lambda lbl=f"Leyendo pág. {s_idx + 1}/{len(self.sections)} {lang_tag}(frase {c_idx + 1}/{len(chunks)})…": self.status_lbl.configure(text=lbl)
                )

                res = host.speak(
                    text=chunk,
                    lang=speak_lang,
                    rate=rate,
                    pitch=1.0,
                    volume=1.0,
                    voice=speak_voice,
                    engine=speak_engine,
                )

                if self.is_paused and session_id == self.speech_session_id:
                    while self.is_paused:
                        if session_id != self.speech_session_id:
                            return
                        self.pause_event.wait(timeout=0.1)

                    if session_id != self.speech_session_id:
                        return

                    res = host.speak(
                        text=chunk,
                        lang=speak_lang,
                        rate=rate,
                        pitch=1.0,
                        volume=1.0,
                        voice=speak_voice,
                        engine=speak_engine,
                    )

                if session_id != self.speech_session_id:
                    return

                if c_idx % 3 == 0:
                    self.save_progress(s_idx, c_idx)

                time.sleep(0.08)

        if session_id == self.speech_session_id:
            self.root.after(0, self.stop_speech)

    def _select_tree_row(self, idx: int):
        self._select_tree_row_programmatic(idx)

    def _select_tree_row_programmatic(self, idx: int):
        self._programmatic_tree_select = True
        try:
            if self.tree.exists(str(idx)):
                self.tree.selection_set(str(idx))
                self.tree.see(str(idx))
            self._display_section(idx)
        finally:
            self._programmatic_tree_select = False

    def _highlight_text(self, chunk: str):
        self.text_view.tag_remove("highlight", "1.0", tk.END)
        snippet = chunk[:40].strip()
        if not snippet:
            return
        idx = self.text_view.search(snippet, "1.0", tk.END)
        if idx:
            end_idx = f"{idx}+{len(chunk)}c"
            self.text_view.tag_add("highlight", idx, end_idx)
            self.text_view.see(idx)

    def save_progress(self, section_idx: int | None = None, chunk_idx: int | None = None):
        if not self.current_file or not self.sections:
            return
        idx = section_idx if section_idx is not None else self.current_section_idx
        c_idx = chunk_idx if chunk_idx is not None else max(0, self.current_chunk_idx)
        if 0 <= idx < len(self.sections):
            title = self.sections[idx][0]
            voice, engine = self.get_selected_voice_and_engine()
            rate = float(self.rate_scale.get())
            libro_mod.save_bookmark(self.current_file, idx, c_idx, title, rate, voice, engine)

    def resume_last_book(self):
        bm = libro_mod.get_last_bookmark()
        if bm and Path(bm.get("path", "")).is_file():
            self.load_file(Path(bm["path"]))
        else:
            messagebox.showinfo("Sin lecturas previas", "No hay ningún libro guardado previamente.")

    def _update_resume_button(self):
        bm = libro_mod.get_last_bookmark()
        if bm and Path(bm.get("path", "")).is_file():
            name = bm.get("name", "Libro")
            idx = bm.get("section_idx", 0) + 1
            short_name = name if len(name) <= 18 else name[:16] + "…"
            self.btn_resume.configure(text=f"📍 Reanudar: {short_name} (pág. {idx})", state=tk.NORMAL)
        else:
            self.btn_resume.configure(text="📍 Reanudar (ninguno)", state=tk.DISABLED)

    def check_last_file_auto_resume(self):
        bm = libro_mod.get_last_bookmark()
        if bm and Path(bm.get("path", "")).is_file():
            self.load_file(Path(bm["path"]))

    def _on_key_space(self, event):
        if isinstance(event.widget, (ttk.Entry, tk.Entry)):
            return
        self.toggle_play()
        return "break"

    def _on_key_left(self, event):
        if isinstance(event.widget, (ttk.Entry, tk.Entry)):
            return
        self.prev_section()
        return "break"

    def _on_key_right(self, event):
        if isinstance(event.widget, (ttk.Entry, tk.Entry)):
            return
        self.next_section()
        return "break"

    def _on_key_escape(self, event):
        self.stop_speech()
        return "break"

    def _on_close(self):
        self.save_progress()
        self.stop_speech()
        self.root.destroy()

    # ==========================================
    # CREADOR Y EXPORTADOR DE AUDIOLIBROS EN MP3
    # ==========================================
    def open_export_dialog(self):
        if not self.sections:
            messagebox.showinfo("Aviso", "Primero abre un archivo PDF o libro para exportar a MP3.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Guardar como Audiolibro MP3 (Opcional)")
        dialog.geometry("540x440")
        dialog.resizable(False, False)
        dialog.configure(bg=self.card_bg)
        dialog.transient(self.root)
        dialog.grab_set()

        # Opciones
        pad = {"padx": 16, "pady": 8}

        ttk.Label(dialog, text="💾 Guardar como MP3", style="Header.TLabel").pack(anchor=tk.W, **pad)
        ttk.Label(dialog, text="Crea un archivo de audio permanente en tu disco solo si deseas conservarlo.", style="Muted.TLabel").pack(anchor=tk.W, padx=16, pady=(0, 6))

        range_frame = ttk.LabelFrame(dialog, text="Rango a guardar", padding=10)
        range_frame.pack(fill=tk.X, **pad)

        range_var = tk.StringVar(value="all")
        ttk.Radiobutton(range_frame, text=f"Todo el libro ({len(self.sections)} páginas/secciones)", variable=range_var, value="all").pack(anchor=tk.W, pady=2)
        ttk.Radiobutton(range_frame, text=f"Solo la página/sección actual ({self.current_section_idx + 1})", variable=range_var, value="current").pack(anchor=tk.W, pady=2)

        # Destino
        dest_frame = ttk.LabelFrame(dialog, text="Archivo MP3 de salida", padding=10)
        dest_frame.pack(fill=tk.X, **pad)

        default_name = f"{self.current_file.stem if self.current_file else 'audiolibro'}.mp3"
        dest_var = tk.StringVar(value=str(Path.home() / "Música" / default_name))
        
        entry_dest = ttk.Entry(dest_frame, textvariable=dest_var)
        entry_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        def browse_dest():
            f = filedialog.asksaveasfilename(
                title="Guardar audiolibro MP3 como...",
                initialfile=default_name,
                defaultextension=".mp3",
                filetypes=[("Archivos MP3", "*.mp3")],
            )
            if f:
                dest_var.set(f)

        ttk.Button(dest_frame, text="Examinar…", command=browse_dest).pack(side=tk.RIGHT)

        # Barra de progreso y estado
        prog_bar = ttk.Progressbar(dialog, mode="determinate")
        prog_bar.pack(fill=tk.X, padx=16, pady=(12, 4))

        status_export_lbl = ttk.Label(dialog, text="Listo para iniciar.", style="Muted.TLabel")
        status_export_lbl.pack(anchor=tk.W, padx=16)

        btn_box = ttk.Frame(dialog, style="Card.TFrame")
        btn_box.pack(fill=tk.X, padx=16, pady=16)

        cancel_flag = [False]

        def do_export():
            out_file = Path(dest_var.get())
            if not out_file.parent.exists():
                messagebox.showerror("Error", f"La carpeta de destino no existe:\n{out_file.parent}")
                return

            btn_start.configure(state=tk.DISABLED)
            btn_cancel.configure(text="Cancelar")

            # Determinar secciones
            if range_var.get() == "current":
                target_sections = [self.sections[self.current_section_idx]]
            else:
                target_sections = self.sections

            voice, engine = self.get_selected_voice_and_engine()
            rate = float(self.rate_scale.get())

            def worker():
                cache = host.narrador_cache_dir()
                rh_bin = host.rhvoice_test_bin()
                temp_parts = []
                total_sections = len(target_sections)

                prog_bar["maximum"] = total_sections

                try:
                    for i, (title, body) in enumerate(target_sections):
                        if cancel_flag[0]:
                            break

                        status_export_lbl.configure(text=f"Sintetizando {i + 1}/{total_sections}: {title[:40]}…")
                        prog_bar["value"] = i

                        # Sintetizar párrafos de esta sección
                        token = f"export-{os.getpid()}-{i}-{int(time.time()*1000)}"
                        part_wav = cache / f"{token}.wav"
                        part_mp3 = cache / f"{token}.mp3"

                        # Sintetizar fragmentos de esta sección con soporte multilingüe
                        chunks = libro_mod.get_section_chunks(clean_text)
                        for c_idx, piece in enumerate(chunks):
                            if cancel_flag[0]:
                                break
                            c_token = f"{token}-{c_idx}"
                            c_wav = cache / f"{c_token}.wav"
                            c_mp3 = cache / f"{c_token}.mp3"

                            c_lang = libro_mod.detect_language(piece) if self.multilingual_var.get() else "es"
                            spk_v, spk_l, spk_e = libro_mod.resolve_voice_for_chunk(c_lang, voice, engine)

                            if spk_e == "edge":
                                edge_bin = host.edge_tts_bin()
                                if edge_bin:
                                    cmd = [
                                        edge_bin,
                                        "--voice", host.edge_voice_id(spk_v),
                                        f"--rate={host.map_edge_rate(rate)}",
                                        "--text", piece,
                                        "--write-media", str(c_mp3),
                                    ]
                                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                                    if proc.returncode == 0 and c_mp3.is_file() and c_mp3.stat().st_size > 128:
                                        temp_parts.append(c_mp3)
                                        continue

                            # RHVoice local
                            in_txt = cache / f"{c_token}.txt"
                            in_txt.write_text(piece, encoding="utf-8")
                            cmd_rh = [rh_bin, "-p", host.local_voice_id(spk_v) or "mateo", "-o", str(c_wav), "-i", str(in_txt)]
                            proc_rh = subprocess.run(cmd_rh, capture_output=True, text=True, timeout=120)

                            if c_wav.is_file() and c_wav.stat().st_size > 128:
                                subprocess.run([
                                    "ffmpeg", "-y", "-i", str(c_wav),
                                    "-c:a", "libmp3lame", "-b:a", "128k",
                                    str(c_mp3)
                                ], capture_output=True, text=True)
                                if c_mp3.is_file():
                                    temp_parts.append(c_mp3)
                            try:
                                c_wav.unlink(missing_ok=True)
                                in_txt.unlink(missing_ok=True)
                            except Exception:
                                pass

                    if cancel_flag[0]:
                        status_export_lbl.configure(text="Exportación cancelada.")
                        btn_start.configure(state=tk.NORMAL)
                        return

                    status_export_lbl.configure(text="Uniendo fragmentos de audio…")

                    if not temp_parts:
                        messagebox.showerror("Error", "No se generó ningún fragmento de audio.")
                        return

                    # Concatenar todos los fragmentos
                    concat_list = cache / f"concat-{int(time.time())}.txt"
                    with open(concat_list, "w", encoding="utf-8") as f:
                        for p in temp_parts:
                            f.write(f"file '{p.resolve()}'\n")

                    title_meta = self.current_file.stem if self.current_file else "Audiolibro"
                    cmd_concat = [
                        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_list),
                        "-c", "copy",
                        "-metadata", f"title={title_meta}",
                        "-metadata", "artist=Narrador Neuronal",
                        str(out_file)
                    ]
                    subprocess.run(cmd_concat, capture_output=True, text=True)

                    # Limpieza
                    concat_list.unlink(missing_ok=True)
                    for p in temp_parts:
                        p.unlink(missing_ok=True)

                    prog_bar["value"] = total_sections
                    status_export_lbl.configure(text=f"✓ Completado: {out_file.name}")
                    messagebox.showinfo("¡Audiolibro Creado!", f"Audiolibro guardado con éxito en:\n\n{out_file}")
                    dialog.destroy()

                except Exception as ex:
                    messagebox.showerror("Error de exportación", f"Ocurrió un error al generar el MP3:\n{ex}")
                finally:
                    btn_start.configure(state=tk.NORMAL)

            threading.Thread(target=worker, daemon=True).start()

        def on_cancel():
            cancel_flag[0] = True
            dialog.destroy()

        btn_start = ttk.Button(btn_box, text="Iniciar Exportación MP3", command=do_export, style="Green.TButton")
        btn_start.pack(side=tk.LEFT, padx=4)

        btn_cancel = ttk.Button(btn_box, text="Cerrar", command=on_cancel)
        btn_cancel.pack(side=tk.RIGHT, padx=4)


def main():
    root = tk.Tk()
    app = BookNarratorGUI(root)
    if len(sys.argv) > 1 and Path(sys.argv[1]).is_file():
        app.load_file(Path(sys.argv[1]))
    else:
        # Si se abre sin argumentos, verificar y cargar automáticamente el último libro
        app.check_last_file_auto_resume()
    root.mainloop()


if __name__ == "__main__":
    main()
