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


class ToolTip:
    """Muestra un mensaje flotante elegante al posar el cursor sobre un widget."""

    def __init__(self, widget: tk.Widget, text: str, delay_ms: int = 250):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tip_window = None
        self._after_id = None

        self.widget.bind("<Enter>", self._on_enter, add="+")
        self.widget.bind("<Leave>", self._on_leave, add="+")
        self.widget.bind("<ButtonPress>", self._on_leave, add="+")

    def update_text(self, new_text: str):
        self.text = new_text
        if self.tip_window:
            self._hide()
            self._show()

    def _on_enter(self, event=None):
        self._schedule()

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _schedule(self):
        self._cancel()
        if self.text:
            self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if not self.text or self.tip_window:
            return
        try:
            x = self.widget.winfo_rootx() + 4
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except Exception:
            return

        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        try:
            tw.attributes("-topmost", True)
        except Exception:
            pass

        frame = tk.Frame(tw, bg="#0f172a", bd=1, relief=tk.SOLID, highlightbackground="#38bdf8", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)

        lbl = tk.Label(
            frame,
            text=self.text,
            bg="#0f172a",
            fg="#f8fafc",
            font=("Sans", 9),
            padx=8,
            pady=4,
            justify=tk.LEFT,
        )
        lbl.pack()

    def _hide(self):
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


class BookNarratorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Narrador de Libros & Creador de Audiolibros MP3")
        self.root.geometry("1020x720")
        self.root.minsize(800, 560)

        # Estado
        self.current_file: Path | None = None
        self.sections: list[tuple[str, str]] = []  # Secciones activas (original o español)
        self.original_sections: list[tuple[str, str]] = []
        self.translated_sections: list[tuple[str, str]] = []
        self.doc_language = "es"
        self.translate_to_spanish_var = tk.BooleanVar(value=False)
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

        # Estilos de botones de iconos compactos (con tooltip al posar el mouse)
        style.configure("Icon.TButton", font=("Sans", 11), padding=4, width=3)

        style.configure("IconAccent.TButton", background=self.accent_color, foreground="#ffffff", font=("Sans", 11, "bold"), padding=4, width=3)
        style.map("IconAccent.TButton", background=[("active", self.accent_hover)])

        style.configure("IconGreen.TButton", background=self.green_color, foreground="#ffffff", font=("Sans", 11, "bold"), padding=4, width=3)
        style.map("IconGreen.TButton", background=[("active", self.green_hover)])

        style.configure("IconAmber.TButton", background=self.amber_color, foreground="#ffffff", font=("Sans", 11, "bold"), padding=4, width=3)
        style.map("IconAmber.TButton", background=[("active", self.amber_hover)])

        style.configure("IconActive.TButton", background="#2563eb", foreground="#ffffff", font=("Sans", 11, "bold"), padding=4, width=3)
        style.map("IconActive.TButton", background=[("active", "#1d4ed8")])

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
        # 1. Barra superior de acciones (iconos compactos con tooltip)
        top_bar = ttk.Frame(self.root, style="Card.TFrame", padding=(12, 8))
        top_bar.pack(fill=tk.X, padx=12, pady=(12, 6))

        title_lbl = ttk.Label(top_bar, text="📖 Narrador", style="Header.TLabel")
        title_lbl.pack(side=tk.LEFT, padx=(0, 14))

        btn_open = ttk.Button(top_bar, text="📂", command=self.open_file_dialog, style="IconAccent.TButton")
        btn_open.pack(side=tk.LEFT, padx=3)
        self.tip_open = ToolTip(btn_open, "Abrir libro, PDF, Word o imagen con OCR (📂)")

        self.btn_resume = ttk.Button(top_bar, text="📍", command=self.resume_last_book, style="IconAmber.TButton")
        self.btn_resume.pack(side=tk.LEFT, padx=3)
        self.tip_resume = ToolTip(self.btn_resume, "Reanudar última lectura (📍)")

        self.btn_translate = ttk.Button(
            top_bar,
            text="🌐",
            command=self._on_toggle_translate,
            style="Icon.TButton",
            state=tk.DISABLED,
        )
        self.btn_translate.pack(side=tk.LEFT, padx=3)
        self.tip_translate = ToolTip(self.btn_translate, "Traducir al Español (🌐 Alternar original / traducido)")

        self.btn_export_txt = ttk.Button(top_bar, text="📄", command=self.export_txt_dialog, style="Icon.TButton", state=tk.DISABLED)
        self.btn_export_txt.pack(side=tk.LEFT, padx=3)
        self.tip_export_txt = ToolTip(self.btn_export_txt, "Exportar texto extraído a archivo plano .txt (📄)")

        self.btn_force_ocr = ttk.Button(top_bar, text="🔄", command=self.reload_force_ocr, style="Icon.TButton", state=tk.DISABLED)
        self.btn_force_ocr.pack(side=tk.LEFT, padx=3)
        self.tip_force_ocr = ToolTip(self.btn_force_ocr, "Re-analizar documento y forzar nuevo escaneo OCR (🔄)")

        btn_export = ttk.Button(top_bar, text="💾", command=self.open_export_dialog, style="IconGreen.TButton")
        btn_export.pack(side=tk.LEFT, padx=3)
        self.tip_export_mp3 = ToolTip(btn_export, "Guardar como audiolibro permanente en MP3 (💾)")

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

        # Eventos del visor de texto: sincronizar cursor con la frase para lectura interactiva
        self.text_view.bind("<ButtonRelease-1>", lambda e: self.root.after(25, self._sync_cursor_to_chunk))
        self.text_view.bind("<Double-Button-1>", lambda e: self.root.after(25, self._sync_cursor_to_chunk))
        self.text_view.bind("<Key>", self._on_text_key)

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
        ToolTip(self.engine_combo, "Seleccionar motor de voz (RHVoice local o Edge online)")
        ToolTip(self.voice_combo, "Seleccionar voz para la narración")
        ToolTip(self.rate_scale, "Ajustar velocidad de narración (0.6x a 1.5x)")

        self.chk_multilingual = ttk.Checkbutton(
            voice_row,
            text="🌐 Multilingüe auto",
            variable=self.multilingual_var,
        )
        self.chk_multilingual.pack(side=tk.RIGHT, padx=4)
        ToolTip(self.chk_multilingual, "Detectar citas y frases en inglés u otros idiomas automáticamente")

        # Fila 2: Controles de reproducción con iconos y tooltips
        controls_row = ttk.Frame(bottom_card, style="Card.TFrame")
        controls_row.pack(fill=tk.X)

        self.btn_prev = ttk.Button(controls_row, text="⏮", command=self.prev_section, style="Icon.TButton")
        self.btn_prev.pack(side=tk.LEFT, padx=3)
        self.tip_prev = ToolTip(self.btn_prev, "Página anterior (← Flecha izquierda)")

        self.btn_play = ttk.Button(controls_row, text="▶", command=self.toggle_play, style="IconAccent.TButton")
        self.btn_play.pack(side=tk.LEFT, padx=3)
        self.tip_play = ToolTip(self.btn_play, "Leer en voz alta / Pausar (Barra espaciadora)")

        self.btn_stop = ttk.Button(controls_row, text="⏹", command=self.stop_speech, style="Icon.TButton")
        self.btn_stop.pack(side=tk.LEFT, padx=3)
        self.tip_stop = ToolTip(self.btn_stop, "Detener narración (Escape)")

        self.btn_next = ttk.Button(controls_row, text="⏭", command=self.next_section, style="Icon.TButton")
        self.btn_next.pack(side=tk.LEFT, padx=3)
        self.tip_next = ToolTip(self.btn_next, "Página siguiente (→ Flecha derecha)")

        self.page_indicator_lbl = ttk.Label(controls_row, text="", style="Card.TLabel", font=("Sans", 10, "bold"))
        self.page_indicator_lbl.pack(side=tk.LEFT, padx=(10, 6))

        self.status_lbl = ttk.Label(controls_row, text="Barra espaciadora: pausar/reanudar. Flechas: cambiar página.", style="Muted.TLabel")
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

    def load_file(self, path: Path, force_reload: bool = False):
        self.stop_speech()
        self.current_file = path
        is_from_cache = (not force_reload) and libro_mod.is_cached(path)

        if is_from_cache:
            self.file_info_lbl.configure(text=f"Cargando {path.name} desde caché instantáneo…")
            self.status_lbl.configure(text="⚡ Cargando texto extraído previamente (sin demora de OCR)…")
        elif force_reload:
            self.file_info_lbl.configure(text=f"Re-analizando {path.name} (Forzando nuevo OCR)…")
            self.status_lbl.configure(text="Re-escaneando documento con OCR y actualizando caché…")
        else:
            self.file_info_lbl.configure(text=f"Analizando {path.name} (OCR automático si hay imágenes/tablas)…")
            self.status_lbl.configure(text="Extrayendo texto y aplicando OCR si es necesario…")
        self.root.update_idletasks()

        # Consultar marcador previo de este archivo
        saved_bm = libro_mod.get_bookmark(path)

        def load_worker():
            try:
                sections = libro_mod.load_sections(path, force_reload=force_reload)
                def on_done():
                    if not sections:
                        messagebox.showwarning("Sin contenido", "No se pudo extraer texto del documento o imagen.")
                        self.file_info_lbl.configure(text="Sin texto legible.")
                        self.status_lbl.configure(text="Listo.")
                        return

                    self.original_sections = sections
                    self.doc_language = libro_mod.detect_document_language(sections)

                    cached_tr = libro_mod.load_translated_cached_sections(path, target_lang="es")
                    if cached_tr:
                        self.translated_sections = cached_tr[0]
                    else:
                        self.translated_sections = []

                    self.btn_translate.configure(state=tk.NORMAL)
                    self.btn_export_txt.configure(state=tk.NORMAL)
                    self.btn_force_ocr.configure(state=tk.NORMAL)

                    # Si el documento no está en español y tenemos caché de traducción, activar traducción automáticamente
                    if self.doc_language != "es" and self.translated_sections:
                        self.translate_to_spanish_var.set(True)
                        self.sections = self.translated_sections
                    else:
                        self.translate_to_spanish_var.set(False)
                        self.sections = self.original_sections

                    if self.translate_to_spanish_var.get():
                        self.btn_translate.configure(style="IconActive.TButton")
                        if hasattr(self, "tip_translate"):
                            self.tip_translate.update_text("🌐 Mostrando versión en Español (Clic para ver original)")
                    else:
                        self.btn_translate.configure(style="Icon.TButton")
                        if hasattr(self, "tip_translate"):
                            self.tip_translate.update_text("🌐 Traducir al Español (Clic para traducir/activar)")

                    self._update_file_info_header()

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
                    self._refresh_tree_and_view(target_section=start_target, target_chunk=start_chunk)

                    origin_str = " (⚡ Caché instantáneo)" if is_from_cache else ""
                    trans_str = " (🌐 En Español)" if self.translate_to_spanish_var.get() else ""
                    if is_resumed:
                        self.status_lbl.configure(text=f"📍 Reanudando en {self.sections[start_target][0]}{origin_str}{trans_str}…")
                    else:
                        self.status_lbl.configure(text=f"Cargado: {path.name}{origin_str}{trans_str}. Narrando automáticamente…")

                    self._update_resume_button()

                    # Si el documento no está en español y no tiene traducción en caché todavía:
                    if self.doc_language != "es" and not self.translated_sections:
                        def prompt_trans():
                            ans = messagebox.askyesno(
                                "🌐 Documento en otro idioma detectado",
                                f"El documento '{path.name}' parece estar en {self.doc_language.upper()}.\n\n"
                                "¿Deseas traducirlo al español automáticamente para:\n"
                                " • Narrarlo con pronunciación fluida en español\n"
                                " • Ver y leer el texto en español\n"
                                " • Guardar el audiolibro MP3 en español?\n\n"
                                "(El texto traducido se guardará en caché para que nunca tengas que esperar de nuevo)."
                            )
                            if ans:
                                self.translate_book(force=False, auto_start_speech=True)
                            else:
                                self.root.after(100, lambda: self.start_speech(from_section=start_target, from_chunk=start_chunk))
                        self.root.after(200, prompt_trans)
                    else:
                        self.root.after(120, lambda: self.start_speech(from_section=start_target, from_chunk=start_chunk))

                self.root.after(0, on_done)
            except Exception as e:
                def on_err():
                    messagebox.showerror("Error al cargar", f"Error al procesar el archivo:\n{e}")
                    self.file_info_lbl.configure(text="Error al cargar archivo")
                    self.status_lbl.configure(text="Error.")
                self.root.after(0, on_err)

        threading.Thread(target=load_worker, daemon=True).start()

    def _update_file_info_header(self):
        if not self.current_file:
            self.file_info_lbl.configure(text="Ningún archivo cargado")
            return
        has_ocr = any("(OCR)" in title for title, _ in self.sections)
        badge_ocr = " · con OCR" if has_ocr else ""
        if self.translate_to_spanish_var.get():
            badge_lang = " · 🌐 Español (Traducido)"
        elif self.doc_language != "es":
            badge_lang = f" · [{self.doc_language.upper()}]"
        else:
            badge_lang = " · [ES]"
        self.file_info_lbl.configure(
            text=f"Archivo: {self.current_file.name} ({len(self.sections)} secciones{badge_ocr}{badge_lang})"
        )

    def _refresh_tree_and_view(self, target_section: int = 0, target_chunk: int = 0):
        cur_sec = max(0, min(target_section, len(self.sections) - 1)) if self.sections else 0
        self._programmatic_tree_select = True
        try:
            self.tree.delete(*self.tree.get_children())
            for i, (title, body) in enumerate(self.sections):
                chars = len(body)
                self.tree.insert("", tk.END, iid=str(i), text=f"{i + 1}. {title}", values=(f"{chars:,} c.",))
        finally:
            self._programmatic_tree_select = False

        self.current_section_idx = cur_sec
        self.current_chunk_idx = target_chunk
        self._select_tree_row(cur_sec)

    def _on_toggle_translate(self):
        if not self.original_sections:
            return

        new_val = not self.translate_to_spanish_var.get()
        self.translate_to_spanish_var.set(new_val)

        was_speaking = self.is_speaking
        saved_sec = max(0, self.current_section_idx)

        if new_val:
            self.btn_translate.configure(style="IconActive.TButton")
            if hasattr(self, "tip_translate"):
                self.tip_translate.update_text("🌐 Mostrando versión en Español (Clic para ver original)")
            if self.translated_sections:
                self.stop_speech()
                self.sections = self.translated_sections
                self._refresh_tree_and_view(target_section=saved_sec, target_chunk=0)
                self._update_file_info_header()
                self.status_lbl.configure(text="🌐 Modo Español activado. Narración y texto en español.")
                if was_speaking:
                    self.start_speech(from_section=saved_sec, from_chunk=0)
            else:
                self.translate_book(force=False, auto_start_speech=was_speaking)
        else:
            self.btn_translate.configure(style="Icon.TButton")
            if hasattr(self, "tip_translate"):
                self.tip_translate.update_text("🌐 Traducir al Español (Clic para traducir y ver en español)")
            self.stop_speech()
            self.sections = self.original_sections
            self._refresh_tree_and_view(target_section=saved_sec, target_chunk=0)
            self._update_file_info_header()
            self.status_lbl.configure(text="Mostrando texto original.")
            if was_speaking:
                self.start_speech(from_section=saved_sec, from_chunk=0)

    def translate_book(self, force: bool = False, auto_start_speech: bool = True):
        if not self.original_sections or not self.current_file:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("🌐 Traduciendo al Español")
        dialog.geometry("520x220")
        dialog.resizable(False, False)
        dialog.configure(bg=self.card_bg)
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="🌐 Traduciendo documento al español", style="Header.TLabel").pack(anchor=tk.W, padx=16, pady=(12, 4))
        ttk.Label(dialog, text="Traduciendo con IA neuronal y guardando en formato de lectura rápida…", style="Muted.TLabel").pack(anchor=tk.W, padx=16, pady=(0, 8))

        prog_bar = ttk.Progressbar(dialog, mode="determinate", maximum=len(self.original_sections))
        prog_bar.pack(fill=tk.X, padx=16, pady=8)

        lbl_status = ttk.Label(dialog, text="Iniciando traducción…", style="Muted.TLabel")
        lbl_status.pack(anchor=tk.W, padx=16, pady=4)

        cancel_flag = [False]

        def on_cancel():
            cancel_flag[0] = True
            dialog.destroy()

        btn_cancel = ttk.Button(dialog, text="Cancelar", command=on_cancel)
        btn_cancel.pack(anchor=tk.E, padx=16, pady=12)

        def worker():
            def on_progress(curr, tot, msg):
                self.root.after(0, lambda c=curr, m=msg: (
                    prog_bar.configure(value=c),
                    lbl_status.configure(text=m)
                ))

            try:
                tr_sections, det_lang = libro_mod.translate_sections_to_spanish(
                    self.original_sections,
                    source_path=self.current_file,
                    force=force,
                    progress_callback=on_progress,
                    cancel_check=lambda: cancel_flag[0]
                )

                def on_finish():
                    if cancel_flag[0]:
                        self.translate_to_spanish_var.set(False)
                        self.btn_translate.configure(style="Icon.TButton")
                        if hasattr(self, "tip_translate"):
                            self.tip_translate.update_text("🌐 Traducir al Español (Clic para traducir y ver en español)")
                        return
                    dialog.destroy()
                    if tr_sections:
                        self.translated_sections = tr_sections
                        self.translate_to_spanish_var.set(True)
                        self.btn_translate.configure(style="IconActive.TButton")
                        if hasattr(self, "tip_translate"):
                            self.tip_translate.update_text("🌐 Mostrando versión en Español (Clic para ver original)")
                        self.sections = tr_sections
                        saved_sec = max(0, min(self.current_section_idx, len(tr_sections) - 1))
                        self._refresh_tree_and_view(target_section=saved_sec, target_chunk=0)
                        self._update_file_info_header()
                        self.status_lbl.configure(text=f"✅ Traducido al español ({det_lang.upper()} ➔ ES). Narrando en español…")
                        if auto_start_speech:
                            self.root.after(100, lambda: self.start_speech(from_section=saved_sec, from_chunk=0))
                    else:
                        messagebox.showerror("Error", "No se pudo completar la traducción.")
                        self.translate_to_spanish_var.set(False)
                        self.btn_translate.configure(style="Icon.TButton")
                        if hasattr(self, "tip_translate"):
                            self.tip_translate.update_text("🌐 Traducir al Español (Clic para traducir y ver en español)")

                self.root.after(0, on_finish)
            except Exception as e:
                self.root.after(0, lambda err=e: (
                    dialog.destroy(),
                    messagebox.showerror("Error", f"Error durante la traducción:\n{err}"),
                    self.translate_to_spanish_var.set(False),
                    self.btn_translate.configure(style="Icon.TButton")
                ))

        threading.Thread(target=worker, daemon=True).start()

    def export_txt_dialog(self):
        if not self.sections or not self.current_file:
            messagebox.showinfo("Aviso", "Primero abre un libro o documento.")
            return

        is_translated = self.translate_to_spanish_var.get()
        suffix = "_espanol.txt" if is_translated else "_texto_extraido.txt"
        default_name = f"{self.current_file.stem}{suffix}"
        target = filedialog.asksaveasfilename(
            title="Exportar texto plano extraído" + (" (en Español)" if is_translated else ""),
            initialfile=default_name,
            defaultextension=".txt",
            filetypes=[("Archivo de texto plano (.txt)", "*.txt"), ("Todos los archivos", "*.*")],
        )
        if not target:
            return

        try:
            target_path = Path(target)
            doc_label = f"{self.current_file.name} (Traducido al Español)" if is_translated else self.current_file.name
            libro_mod.export_sections_to_txt(
                self.sections, target_path, doc_name=doc_label, source_path=str(self.current_file.resolve())
            )
            messagebox.showinfo(
                "Exportación exitosa",
                f"El texto extraído de '{self.current_file.name}' se guardó en:\n\n{target_path}\n\n"
                f"Contiene {len(self.sections)} páginas/secciones en texto plano listas para leer o editar."
            )
            self.status_lbl.configure(text=f"✅ Texto guardado en: {target_path.name}")
        except Exception as e:
            messagebox.showerror("Error al exportar", f"No se pudo guardar el archivo de texto:\n{e}")

    def reload_force_ocr(self):
        if not self.current_file:
            messagebox.showinfo("Aviso", "No hay ningún documento abierto para re-analizar.")
            return

        confirm = messagebox.askyesno(
            "Re-analizar documento",
            f"¿Deseas descartar el caché de texto y volver a ejecutar el análisis OCR completo sobre '{self.current_file.name}'?\n\n"
            "Útil si el archivo en disco cambió o deseas volver a escanear tablas, diagramas e imágenes."
        )
        if not confirm:
            return

        libro_mod.clear_cache_for_file(self.current_file)
        self.load_file(self.current_file, force_reload=True)

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

    def _display_section(self, idx: int, reset_chunk: bool = True):
        if idx < 0 or idx >= len(self.sections):
            return
        self.current_section_idx = idx
        if reset_chunk:
            self.current_chunk_idx = 0
        title, body = self.sections[idx]
        self.reading_title_lbl.configure(text=f"{idx + 1}. {title}")
        self.text_view.delete("1.0", tk.END)
        self.text_view.insert("1.0", body)

        pct = int((idx + 1) / len(self.sections) * 100) if self.sections else 0
        self.page_indicator_lbl.configure(text=f"📍 Pág. {idx + 1}/{len(self.sections)} ({pct}%)")

        chunks = libro_mod.get_section_chunks(body)
        if chunks and 0 <= self.current_chunk_idx < len(chunks):
            self._highlight_text(chunks[self.current_chunk_idx])

    def _get_chunk_idx_at_cursor(self) -> int | None:
        """Determina con exactitud qué frase u oración corresponde a la selección o cursor actual."""
        if not self.sections or self.current_section_idx < 0:
            return None
        if self.current_section_idx >= len(self.sections):
            return None

        try:
            sel_ranges = self.text_view.tag_ranges("sel")
            if sel_ranges:
                pos_index = sel_ranges[0]
            else:
                pos_index = self.text_view.index(tk.INSERT)
            char_offset = len(self.text_view.get("1.0", pos_index))
        except Exception:
            return None

        body = self.sections[self.current_section_idx][1]
        chunks = libro_mod.get_section_chunks(body)
        if not chunks:
            return 0

        cur_pos = 0
        matched_idx = 0
        for i, c in enumerate(chunks):
            snippet = c[:30].strip()
            found = body.find(snippet, cur_pos)
            if found == -1:
                snippet = c[:15].strip()
                found = body.find(snippet, cur_pos)
            if found != -1:
                end = found + len(c)
                cur_pos = found + max(1, len(snippet))
                if char_offset <= end:
                    return i
                matched_idx = i
            else:
                end = cur_pos + len(c)
                if char_offset <= end:
                    return i
                cur_pos = end
                matched_idx = i

        return matched_idx

    def _sync_cursor_to_chunk(self):
        """Sincroniza la frase activa con el párrafo donde el usuario hizo clic o marcó texto."""
        chunk_idx = self._get_chunk_idx_at_cursor()
        if chunk_idx is not None and 0 <= self.current_section_idx < len(self.sections):
            self.current_chunk_idx = chunk_idx
            body = self.sections[self.current_section_idx][1]
            chunks = libro_mod.get_section_chunks(body)
            if 0 <= chunk_idx < len(chunks):
                chunk = chunks[chunk_idx]
                self._highlight_text(chunk)
                snippet = chunk[:55].strip()
                if self.is_speaking and not self.is_paused:
                    # Si ya está narrando, saltar la narración en vivo directamente a esta frase
                    self.start_speech(from_section=self.current_section_idx, from_chunk=chunk_idx)
                else:
                    self.status_lbl.configure(
                        text=f"📍 Cursor en frase {chunk_idx + 1}/{len(chunks)}: '{snippet}' (Espacio para leer)"
                    )

    def _on_text_key(self, event):
        """Control de teclado dentro del visor de texto: lectura interactiva sin dañar el texto."""
        if event.keysym in ("Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End"):
            self.root.after(25, self._sync_cursor_to_chunk)
            return None
        if event.state & 0x4:  # Atajos Ctrl+C, Ctrl+A
            return None
        if event.keysym == "space":
            self.toggle_play()
            return "break"
        if event.keysym == "Escape":
            self.stop_speech()
            return "break"
        return "break"

    def toggle_play(self):
        if not self.is_speaking:
            cursor_chunk = self._get_chunk_idx_at_cursor()
            target_chunk = cursor_chunk if cursor_chunk is not None else max(0, self.current_chunk_idx)
            self.start_speech(from_section=self.current_section_idx, from_chunk=target_chunk)
            return

        if self.is_paused:
            cursor_chunk = self._get_chunk_idx_at_cursor()
            if cursor_chunk is not None and cursor_chunk != self.current_chunk_idx:
                self.start_speech(from_section=self.current_section_idx, from_chunk=cursor_chunk)
            else:
                self.resume_speech()
        else:
            self.pause_speech()

    def start_speech(self, from_section: int | None = None, from_chunk: int | None = None):
        if not self.sections:
            messagebox.showinfo("Aviso", "Primero abre un archivo PDF o libro.")
            return

        target_sec = from_section if from_section is not None else self.current_section_idx
        if target_sec < 0 or target_sec >= len(self.sections):
            target_sec = 0

        if from_chunk is None:
            cursor_chunk = self._get_chunk_idx_at_cursor()
            target_chunk = cursor_chunk if cursor_chunk is not None else max(0, self.current_chunk_idx)
        else:
            target_chunk = from_chunk

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
        self.btn_play.configure(text="⏸")
        if hasattr(self, "tip_play"):
            self.tip_play.update_text("Pausar lectura (Barra espaciadora)")
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
        self.btn_play.configure(text="▶")
        if hasattr(self, "tip_play"):
            self.tip_play.update_text("Reanudar lectura (Barra espaciadora)")
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
        self.btn_play.configure(text="⏸")
        if hasattr(self, "tip_play"):
            self.tip_play.update_text("Pausar lectura (Barra espaciadora)")
        self.status_lbl.configure(text=f"▶ Reanudando en pág. {self.current_section_idx + 1}, frase {self.current_chunk_idx + 1}…")
        self.pause_event.set()

    def stop_speech(self):
        self.speech_session_id += 1
        self.is_speaking = False
        self.is_paused = False
        self.pause_event.set()
        self.btn_play.configure(text="▶")
        if hasattr(self, "tip_play"):
            self.tip_play.update_text("Leer en voz alta (Barra espaciadora)")
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
            self.btn_resume.configure(state=tk.NORMAL)
            if hasattr(self, "tip_resume"):
                self.tip_resume.update_text(f"Reanudar última lectura: {name} (pág. {idx})")
        else:
            self.btn_resume.configure(state=tk.DISABLED)
            if hasattr(self, "tip_resume"):
                self.tip_resume.update_text("Reanudar (sin lecturas previas)")

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

        # Opciones de idioma
        lang_frame = ttk.LabelFrame(dialog, text="Opciones de idioma", padding=10)
        lang_frame.pack(fill=tk.X, **pad)

        export_es_var = tk.BooleanVar(value=bool(self.translate_to_spanish_var.get() or self.doc_language != "es"))
        chk_export_es = ttk.Checkbutton(
            lang_frame,
            text="🌐 Narrar y guardar audiolibro en Español (Traducido)",
            variable=export_es_var,
        )
        chk_export_es.pack(anchor=tk.W, pady=2)

        # Destino
        dest_frame = ttk.LabelFrame(dialog, text="Archivo MP3 de salida", padding=10)
        dest_frame.pack(fill=tk.X, **pad)

        default_dir = Path.home()
        if self.current_file and self.current_file.parent.exists():
            default_dir = self.current_file.parent
        elif (Path.home() / "Documentos").exists():
            default_dir = Path.home() / "Documentos"
        elif (Path.home() / "Música").exists():
            default_dir = Path.home() / "Música"

        base_stem = self.current_file.stem if self.current_file else "audiolibro"
        if export_es_var.get() and self.doc_language != "es":
            default_name = f"{base_stem}_espanol.mp3"
        else:
            default_name = f"{base_stem}.mp3"
        dest_var = tk.StringVar(value=str(default_dir / default_name))

        def on_export_es_toggled():
            curr = dest_var.get()
            if export_es_var.get() and not curr.endswith("_espanol.mp3"):
                new_n = re.sub(r"(\.mp3)$", r"_espanol\1", curr)
                dest_var.set(new_n)
            elif not export_es_var.get() and curr.endswith("_espanol.mp3"):
                new_n = curr.replace("_espanol.mp3", ".mp3")
                dest_var.set(new_n)

        chk_export_es.configure(command=on_export_es_toggled)

        entry_dest = ttk.Entry(dest_frame, textvariable=dest_var)
        entry_dest.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        def browse_dest():
            f = filedialog.asksaveasfilename(
                title="Guardar audiolibro MP3 como...",
                initialdir=str(default_dir),
                initialfile=Path(dest_var.get()).name,
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
            raw_dest = dest_var.get().strip()
            if not raw_dest:
                messagebox.showerror("Error", "Por favor especifica una ruta para guardar el archivo MP3.")
                return

            out_file = Path(raw_dest)
            try:
                out_file.parent.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo crear la carpeta de destino:\n{e}")
                return

            btn_start.configure(state=tk.DISABLED)
            btn_cancel.configure(text="Cancelar")

            voice, engine = self.get_selected_voice_and_engine()
            rate = float(self.rate_scale.get())

            def worker():
                def on_progress(current_idx, total_count, text):
                    self.root.after(0, lambda c=current_idx, t=text: (
                        status_export_lbl.configure(text=t),
                        prog_bar.configure(value=c)
                    ))

                try:
                    # Determinar qué secciones usar (originales o traducidas)
                    use_spanish = export_es_var.get()
                    if use_spanish:
                        if not self.translated_sections and self.current_file:
                            cached_tr = libro_mod.load_translated_cached_sections(self.current_file, "es")
                            if cached_tr:
                                self.translated_sections = cached_tr[0]
                        if not self.translated_sections:
                            on_progress(0, len(self.original_sections), "Traduciendo secciones al español antes de sintetizar…")
                            tr_secs, _ = libro_mod.translate_sections_to_spanish(
                                self.original_sections,
                                source_path=self.current_file,
                                progress_callback=on_progress,
                                cancel_check=lambda: cancel_flag[0],
                            )
                            if cancel_flag[0]:
                                return
                            self.translated_sections = tr_secs
                        active_source = self.translated_sections if self.translated_sections else self.sections
                    else:
                        active_source = self.sections

                    if range_var.get() == "current" and 0 <= self.current_section_idx < len(active_source):
                        target_sections = [active_source[self.current_section_idx]]
                    else:
                        target_sections = active_source

                    self.root.after(0, lambda: prog_bar.configure(maximum=len(target_sections), value=0))

                    # Si se narra en español, asegurar voz española nativa
                    export_voice = voice
                    if use_spanish:
                        v_lower = voice.lower()
                        if not any(sp_v in v_lower for sp_v in ("mateo", "carlos", "leticia", "es-")):
                            export_voice = "local:mateo" if "local" in engine else "edge:es-ES-ElviraNeural"

                    success = libro_mod.export_book_to_mp3(
                        sections=target_sections,
                        out_file=out_file,
                        voice=export_voice,
                        engine=engine,
                        rate=rate,
                        doc_title=(self.current_file.stem if self.current_file else "Audiolibro") + (" (Español)" if use_spanish else ""),
                        multilingual=not use_spanish,
                        progress_callback=on_progress,
                        cancel_check=lambda: cancel_flag[0],
                    )

                    def on_finish():
                        btn_start.configure(state=tk.NORMAL)
                        btn_cancel.configure(text="Cerrar")
                        if cancel_flag[0]:
                            status_export_lbl.configure(text="Exportación cancelada.")
                            return

                        if success and out_file.is_file() and out_file.stat().st_size > 512:
                            prog_bar.configure(value=len(target_sections))
                            status_export_lbl.configure(text=f"✓ Completado: {out_file.name}")
                            messagebox.showinfo("¡Audiolibro Creado!", f"Audiolibro guardado con éxito en:\n\n{out_file}")
                            dialog.destroy()
                        else:
                            status_export_lbl.configure(text="Error al generar el archivo MP3.")
                            messagebox.showerror(
                                "Error de exportación",
                                "No se pudo generar el archivo MP3.\n"
                                "Verifica que el motor de voz (RHVoice) y ffmpeg estén funcionando."
                            )

                    self.root.after(0, on_finish)
                except Exception as ex:
                    self.root.after(0, lambda: (
                        messagebox.showerror("Error de exportación", f"Ocurrió un error inesperado al exportar:\n{ex}"),
                        btn_start.configure(state=tk.NORMAL),
                        btn_cancel.configure(text="Cerrar")
                    ))

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
