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
        self.current_chunk_idx = -1
        self.is_speaking = False
        self.is_paused = False
        self.stop_requested = False
        self.speak_thread: threading.Thread | None = None
        self.export_thread: threading.Thread | None = None

        # Configurar tema e icono
        self._setup_style()
        self._setup_icon()

        # Construir UI
        self._build_ui()

        # Cargar voces
        self._load_voices()

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
        self.rate_val_lbl.pack(side=tk.LEFT)

        # Fila 2: Controles de reproducción
        controls_row = ttk.Frame(bottom_card, style="Card.TFrame")
        controls_row.pack(fill=tk.X)

        self.btn_prev = ttk.Button(controls_row, text="⏮ Anterior", command=self.prev_section, width=10)
        self.btn_prev.pack(side=tk.LEFT, padx=3)

        self.btn_play = ttk.Button(controls_row, text="▶ Leer en voz alta", command=self.toggle_play, style="Accent.TButton", width=18)
        self.btn_play.pack(side=tk.LEFT, padx=3)

        self.btn_stop = ttk.Button(controls_row, text="⏹ Detener", command=self.stop_speech, width=10)
        self.btn_stop.pack(side=tk.LEFT, padx=3)

        self.btn_next = ttk.Button(controls_row, text="⏭ Siguiente", command=self.next_section, width=10)
        self.btn_next.pack(side=tk.LEFT, padx=3)

        self.status_lbl = ttk.Label(controls_row, text="Lectura en vivo (sin guardar archivo). Pulsa «Leer en voz alta» para escuchar.", style="Muted.TLabel")
        self.status_lbl.pack(side=tk.RIGHT, padx=8)

    def _on_rate_change(self, val):
        r = float(val)
        self.rate_val_lbl.configure(text=f"{r:.2f}x")

    def _load_voices(self):
        engine_str = self.engine_var.get()
        if "local" in engine_str:
            voices = [
                "local:mateo (RHVoice masculino - recomendado)",
                "local:carlos (RHVoice)",
                "local:leticia (RHVoice)",
            ]
        else:
            voices = [
                "edge:es-ES-ElviraNeural (Femenina España)",
                "edge:es-ES-AlvaroNeural (Masculina España)",
                "edge:es-MX-DaliaNeural (Femenina México)",
                "edge:es-MX-JorgeNeural (Masculina México)",
                "edge:es-US-PalomaNeural (Femenina EEUU)",
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
                    self.current_section_idx = 0
                    has_ocr = any("(OCR)" in title for title, _ in sections)
                    ocr_note = " · con OCR" if has_ocr else ""
                    self.file_info_lbl.configure(text=f"Archivo: {path.name} ({len(sections)} secciones{ocr_note})")

                    # Llenar árbol
                    self.tree.delete(*self.tree.get_children())
                    for i, (title, body) in enumerate(self.sections):
                        chars = len(body)
                        self.tree.insert("", tk.END, iid=str(i), text=f"{i + 1}. {title}", values=(f"{chars:,} c.",))

                    if self.sections:
                        self.tree.selection_set("0")
                        self.tree.see("0")
                        self._display_section(0)

                    self.status_lbl.configure(text=f"Cargado con éxito: {path.name}. Listo para narrar o crear MP3.")

                self.root.after(0, on_done)
            except Exception as e:
                def on_err():
                    messagebox.showerror("Error al cargar", f"Error al procesar el archivo:\n{e}")
                    self.file_info_lbl.configure(text="Error al cargar archivo")
                    self.status_lbl.configure(text="Error.")
                self.root.after(0, on_err)

        threading.Thread(target=load_worker, daemon=True).start()

    def _on_tree_select(self, event=None):
        selected = self.tree.selection()
        if not selected:
            return
        idx = int(selected[0])
        self._display_section(idx)

    def _display_section(self, idx: int):
        if idx < 0 or idx >= len(self.sections):
            return
        self.current_section_idx = idx
        title, body = self.sections[idx]
        self.reading_title_lbl.configure(text=f"{idx + 1}. {title}")
        self.text_view.delete("1.0", tk.END)
        self.text_view.insert("1.0", body)

    def toggle_play(self):
        if self.is_speaking:
            if self.is_paused:
                self.resume_speech()
            else:
                self.pause_speech()
        else:
            self.start_speech()

    def start_speech(self):
        if not self.sections:
            messagebox.showinfo("Aviso", "Primero abre un archivo PDF o libro.")
            return

        self.stop_requested = False
        self.is_speaking = True
        self.is_paused = False
        self.btn_play.configure(text="⏸ Pausar")
        self.status_lbl.configure(text="Leyendo en vivo…")

        voice, engine = self.get_selected_voice_and_engine()
        rate = float(self.rate_scale.get())

        self.speak_thread = threading.Thread(
            target=self._speech_worker,
            args=(self.current_section_idx, voice, engine, rate),
            daemon=True
        )
        self.speak_thread.start()

    def pause_speech(self):
        self.is_paused = True
        self.btn_play.configure(text="▶ Reanudar")
        self.status_lbl.configure(text="Lectura pausada.")

    def resume_speech(self):
        self.is_paused = False
        self.btn_play.configure(text="⏸ Pausar")
        self.status_lbl.configure(text="Leyendo en vivo…")

    def stop_speech(self):
        self.stop_requested = True
        self.is_speaking = False
        self.is_paused = False
        self.btn_play.configure(text="▶ Leer en voz alta")
        self.status_lbl.configure(text="Lectura detenida.")
        try:
            host.stop_playback()
        except Exception:
            pass

    def prev_section(self):
        if self.current_section_idx > 0:
            target = self.current_section_idx - 1
            self.tree.selection_set(str(target))
            self.tree.see(str(target))
            self._display_section(target)
            if self.is_speaking:
                self.stop_speech()
                self.start_speech()

    def next_section(self):
        if self.current_section_idx < len(self.sections) - 1:
            target = self.current_section_idx + 1
            self.tree.selection_set(str(target))
            self.tree.see(str(target))
            self._display_section(target)
            if self.is_speaking:
                self.stop_speech()
                self.start_speech()

    def _speech_worker(self, start_idx: int, voice: str, engine: str, rate: float):
        for s_idx in range(start_idx, len(self.sections)):
            if self.stop_requested:
                break

            self.root.after(0, lambda idx=s_idx: self._select_tree_row(idx))
            title, body = self.sections[s_idx]
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

            for para in paragraphs:
                if self.stop_requested:
                    break

                for chunk in libro_mod.chunk_paragraph(para):
                    if self.stop_requested:
                        break

                    while self.is_paused and not self.stop_requested:
                        time.sleep(0.1)

                    if self.stop_requested:
                        break

                    self.root.after(0, lambda c=chunk: self._highlight_text(c))
                    
                    res = host.speak(
                        text=chunk,
                        lang="es-ES",
                        rate=rate,
                        pitch=1.0,
                        volume=1.0,
                        voice=voice,
                        engine=engine,
                    )
                    time.sleep(0.15)

        self.root.after(0, self.stop_speech)

    def _select_tree_row(self, idx: int):
        self.tree.selection_set(str(idx))
        self.tree.see(str(idx))
        self._display_section(idx)

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

                        # Guardar texto
                        clean_text = f"{title}.\n\n{body}"
                        
                        if engine == "edge":
                            # Edge TTS
                            edge_bin = host.edge_tts_bin()
                            if edge_bin:
                                voice_id = host.edge_voice_id(voice)
                                cmd = [
                                    edge_bin,
                                    "--voice", voice_id,
                                    f"--rate={host.map_edge_rate(rate)}",
                                    "--text", clean_text,
                                    "--write-media", str(part_mp3),
                                ]
                                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                                if proc.returncode == 0 and part_mp3.is_file():
                                    temp_parts.append(part_mp3)
                                    continue
                        
                        # RHVoice fallback / default
                        in_txt = cache / f"{token}.txt"
                        in_txt.write_text(clean_text, encoding="utf-8")
                        cmd_rh = [rh_bin, "-p", host.local_voice_id(voice) or "mateo", "-o", str(part_wav), "-i", str(in_txt)]
                        proc_rh = subprocess.run(cmd_rh, capture_output=True, text=True, timeout=180)
                        
                        if part_wav.is_file() and part_wav.stat().st_size > 128:
                            # Convertir a MP3 con ffmpeg
                            subprocess.run([
                                "ffmpeg", "-y", "-i", str(part_wav),
                                "-c:a", "libmp3lame", "-b:a", "128k",
                                str(part_mp3)
                            ], capture_output=True, text=True)
                            if part_mp3.is_file():
                                temp_parts.append(part_mp3)
                            try:
                                part_wav.unlink(missing_ok=True)
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
    root.mainloop()


if __name__ == "__main__":
    main()
