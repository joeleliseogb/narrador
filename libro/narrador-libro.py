#!/usr/bin/env python3
"""
Narrador de libros — TXT, EPUB, PDF, Word (.doc/.docx), ODT, RTF (RHVoice / Edge).
Uso:
  narrador-libro.py mi-libro.pdf
  narrador-libro.py mi-libro.epub --engine edge --voice edge:es-ES-ElviraNeural
  narrador-libro.py libro.pdf --from-chapter 12 --rate 0.95
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import site
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Asegurar acceso a paquetes de usuario (~/.local/lib/python3.x/site-packages)
try:
    _user_site = site.getusersitepackages()
    if _user_site and _user_site not in sys.path:
        sys.path.insert(0, _user_site)
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
HOST_PY = ROOT / "native" / "narrador-host.py"

MAX_CHUNK = 480

CONFIG_DIR = Path.home() / ".config" / "narrador-libros"
PROGRESS_FILE = CONFIG_DIR / "progreso.json"
CACHE_DIR = Path.home() / ".cache" / "narrador-libros" / "textos"


# =========================================================================
# CACHÉ DE DOCUMENTOS Y EXPORTACIÓN EN TEXTO PLANO
# =========================================================================

def get_cache_files(path: Path) -> tuple[Path, Path]:
    """Retorna las rutas para el caché estructurado JSON y el archivo de texto plano .txt."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    resolved = str(path.resolve())
    h = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    safe_name = re.sub(r"[^\w\.-]", "_", path.stem)[:32]
    json_path = CACHE_DIR / f"{safe_name}_{h}.json"
    txt_path = CACHE_DIR / f"{safe_name}_{h}.txt"
    return json_path, txt_path


def is_cached(path: Path) -> bool:
    """Comprueba si existe un caché válido y actualizado para este documento."""
    if not path.is_file():
        return False
    json_path, _ = get_cache_files(path)
    if not json_path.is_file():
        return False
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        stat = path.stat()
        return (
            data.get("file_path") == str(path.resolve())
            and data.get("mtime_ns") == stat.st_mtime_ns
            and data.get("size_bytes") == stat.st_size
            and bool(data.get("sections"))
        )
    except Exception:
        return False


def load_cached_sections(path: Path) -> list[tuple[str, str]] | None:
    """Carga las secciones extraídas directamente del caché en milisegundos."""
    if not is_cached(path):
        return None
    json_path, _ = get_cache_files(path)
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        raw_sections = data.get("sections", [])
        sections: list[tuple[str, str]] = []
        for s in raw_sections:
            if isinstance(s, dict):
                title = str(s.get("title", ""))
                body = str(s.get("body", ""))
                if body.strip():
                    sections.append((title, body))
            elif isinstance(s, (list, tuple)) and len(s) == 2:
                sections.append((str(s[0]), str(s[1])))
        return sections if sections else None
    except Exception as e:
        print(f"Aviso leyendo caché: {e}", file=sys.stderr)
        return None


def save_cached_sections(path: Path, sections: list[tuple[str, str]]) -> tuple[Path, Path] | None:
    """Guarda las secciones en caché JSON y en texto plano (.txt) para lectura instantánea."""
    if not path.is_file() or not sections:
        return None
    try:
        json_path, txt_path = get_cache_files(path)
        stat = path.stat()
        has_ocr = any("(OCR)" in title for title, _ in sections)

        payload = {
            "file_path": str(path.resolve()),
            "file_name": path.name,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
            "has_ocr": has_ocr,
            "cached_at": int(time.time()),
            "sections_count": len(sections),
            "sections": [{"title": title, "body": body} for title, body in sections],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        # Generar versión en texto plano formateado
        export_sections_to_txt(sections, txt_path, doc_name=path.name, source_path=str(path.resolve()))
        return json_path, txt_path
    except Exception as e:
        print(f"Aviso guardando caché: {e}", file=sys.stderr)
        return None


def clear_cache_for_file(path: Path) -> None:
    """Elimina el caché existente para forzar un re-análisis completo."""
    try:
        json_path, txt_path = get_cache_files(path)
        if json_path.is_file():
            json_path.unlink(missing_ok=True)
        if txt_path.is_file():
            txt_path.unlink(missing_ok=True)
        tr_json, tr_txt = get_translation_cache_files(path, "es")
        if tr_json.is_file():
            tr_json.unlink(missing_ok=True)
        if tr_txt.is_file():
            tr_txt.unlink(missing_ok=True)
    except Exception:
        pass


def get_translation_cache_files(path: Path, target_lang: str = "es") -> tuple[Path, Path]:
    """Retorna las rutas para el caché estructurado JSON y el archivo .txt traducido al español."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    resolved = str(path.resolve())
    h = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    safe_name = re.sub(r"[^\w\.-]", "_", path.stem)[:32]
    json_path = CACHE_DIR / f"{safe_name}_{h}_{target_lang}.json"
    txt_path = CACHE_DIR / f"{safe_name}_{h}_{target_lang}.txt"
    return json_path, txt_path


def is_translation_cached(path: Path, target_lang: str = "es") -> bool:
    """Comprueba si existe una traducción al español válida y actualizada en caché."""
    if not path.is_file():
        return False
    json_path, _ = get_translation_cache_files(path, target_lang)
    if not json_path.is_file():
        return False
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        stat = path.stat()
        return (
            data.get("file_path") == str(path.resolve())
            and data.get("mtime_ns") == stat.st_mtime_ns
            and data.get("size_bytes") == stat.st_size
            and bool(data.get("sections"))
        )
    except Exception:
        return False


def load_translated_cached_sections(path: Path, target_lang: str = "es") -> tuple[list[tuple[str, str]], str] | None:
    """Carga las secciones traducidas al español directamente del caché en milisegundos."""
    if not is_translation_cached(path, target_lang):
        return None
    json_path, _ = get_translation_cache_files(path, target_lang)
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        raw_sections = data.get("sections", [])
        source_lang = data.get("source_lang", "auto")
        sections: list[tuple[str, str]] = []
        for s in raw_sections:
            if isinstance(s, dict):
                title = str(s.get("title", ""))
                body = str(s.get("body", ""))
                if body.strip():
                    sections.append((title, body))
            elif isinstance(s, (list, tuple)) and len(s) == 2:
                sections.append((str(s[0]), str(s[1])))
        if sections:
            return sections, source_lang
        return None
    except Exception as e:
        print(f"Aviso leyendo caché de traducción: {e}", file=sys.stderr)
        return None


def save_translated_cached_sections(
    path: Path,
    sections: list[tuple[str, str]],
    source_lang: str = "auto",
    target_lang: str = "es"
) -> tuple[Path, Path] | None:
    """Guarda las secciones traducidas en caché JSON y en texto plano (.txt) en español."""
    if not path.is_file() or not sections:
        return None
    try:
        json_path, txt_path = get_translation_cache_files(path, target_lang)
        stat = path.stat()
        payload = {
            "file_path": str(path.resolve()),
            "file_name": path.name,
            "mtime_ns": stat.st_mtime_ns,
            "size_bytes": stat.st_size,
            "source_lang": source_lang,
            "target_lang": target_lang,
            "cached_at": int(time.time()),
            "sections_count": len(sections),
            "sections": [{"title": title, "body": body} for title, body in sections],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        export_sections_to_txt(
            sections,
            txt_path,
            doc_name=f"{path.name} (Traducido al Español)",
            source_path=str(path.resolve())
        )
        return json_path, txt_path
    except Exception as e:
        print(f"Aviso guardando caché de traducción: {e}", file=sys.stderr)
        return None


def _translate_single_block(text: str, source_lang: str = "auto", timeout: float = 12.0) -> tuple[str, str]:
    """Envía un bloque de texto a Google Translate neuronal (POST) y retorna (texto, idioma_detectado)."""
    text_clean = text.strip()
    if not text_clean:
        return text, source_lang
    req_sl = source_lang if source_lang in ("en", "fr", "de", "it", "pt") else "auto"
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl={urllib.parse.quote(req_sl)}&tl=es&dt=t"
    data = urllib.parse.urlencode({"q": text_clean}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "*/*",
        },
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                det_lang = raw[2] if len(raw) > 2 and isinstance(raw[2], str) else source_lang
                translated = "".join(part[0] for part in raw[0] if part and part[0])
                return (translated if translated.strip() else text), det_lang
        except Exception:
            if attempt == 0:
                time.sleep(0.4)
            else:
                return text, source_lang
    return text, source_lang


def translate_text_to_spanish(text: str, source_lang: str = "auto", timeout: float = 12.0) -> tuple[str, str]:
    """
    Traduce texto al español usando el endpoint neuronal de Google Translate.
    Devuelve (texto_traducido, idioma_origen_detectado).
    Soporta textos largos dividiéndolos en párrafos y bloques seguros (<2200 caracteres).
    """
    if not text or not text.strip():
        return text, source_lang

    if len(text) <= 2200:
        return _translate_single_block(text, source_lang=source_lang, timeout=timeout)

    paragraphs = text.split("\n\n")
    translated_paras: list[str] = []
    detected_lang = source_lang

    cur_block: list[str] = []
    cur_len = 0

    def flush_block():
        nonlocal cur_block, cur_len, detected_lang
        if not cur_block:
            return
        combined = "\n\n".join(cur_block)
        trans, det = _translate_single_block(combined, source_lang=source_lang, timeout=timeout)
        if det not in ("auto", "unknown", "es"):
            detected_lang = det
        translated_paras.append(trans)
        cur_block = []
        cur_len = 0

    for p in paragraphs:
        if cur_len + len(p) > 1900:
            flush_block()
        if len(p) > 1900:
            sentences = re.split(r"(?<=[.!?])\s+", p)
            s_block: list[str] = []
            s_len = 0
            for s in sentences:
                if s_len + len(s) > 1700:
                    trans, det = _translate_single_block(" ".join(s_block), source_lang=source_lang, timeout=timeout)
                    if det not in ("auto", "unknown", "es"):
                        detected_lang = det
                    translated_paras.append(trans)
                    s_block = []
                    s_len = 0
                s_block.append(s)
                s_len += len(s)
            if s_block:
                trans, det = _translate_single_block(" ".join(s_block), source_lang=source_lang, timeout=timeout)
                if det not in ("auto", "unknown", "es"):
                    detected_lang = det
                translated_paras.append(trans)
        else:
            cur_block.append(p)
            cur_len += len(p)

    flush_block()
    return "\n\n".join(translated_paras), detected_lang


def detect_document_language(sections: list[tuple[str, str]]) -> str:
    """
    Analiza una muestra de las secciones para determinar el idioma principal del documento.
    Retorna el código ISO ('es', 'en', 'fr', 'de', 'it', 'pt', etc.).
    """
    if not sections:
        return "es"
    sample_parts: list[str] = []
    total_len = 0
    for _, body in sections[:6]:
        b = body.strip()
        if b:
            sample_parts.append(b[:800])
            total_len += len(sample_parts[-1])
            if total_len > 2500:
                break
    sample_text = " ".join(sample_parts)
    return detect_language(sample_text, default_lang="es")


def translate_sections_to_spanish(
    sections: list[tuple[str, str]],
    source_path: Path | None = None,
    force: bool = False,
    progress_callback=None,
    cancel_check=None,
) -> tuple[list[tuple[str, str]], str]:
    """
    Traduce todas las secciones del documento al español y las almacena en el formato de caché optimizado.
    Retorna (secciones_en_español, idioma_detectado).
    """
    if not sections:
        return [], "es"

    # Si hay caché de traducción y no forzamos re-traducción, cargar al instante (~0.01s)
    if source_path and not force:
        cached = load_translated_cached_sections(source_path, target_lang="es")
        if cached:
            return cached

    doc_lang = detect_document_language(sections)
    if doc_lang == "es" and not force:
        return sections, "es"

    total = len(sections)
    translated_sections: list[tuple[str, str]] = []
    overall_detected = doc_lang

    for i, (title, body) in enumerate(sections):
        if cancel_check and cancel_check():
            break

        if progress_callback:
            progress_callback(i, total, f"Traduciendo sección {i + 1}/{total}: {title[:32]}…")

        tr_title = title
        if any(w in title.lower() for w in ("chapter", "section", "part", "page", "table", "figure", "index")):
            t_trans, _ = translate_text_to_spanish(title, source_lang=overall_detected)
            if t_trans and t_trans.strip():
                tr_title = t_trans.strip()

        tr_body, det = translate_text_to_spanish(body, source_lang=overall_detected)
        if det not in ("auto", "unknown", "es"):
            overall_detected = det

        translated_sections.append((tr_title, tr_body))

    if cancel_check and cancel_check():
        return sections, overall_detected

    if source_path and translated_sections:
        save_translated_cached_sections(source_path, translated_sections, source_lang=overall_detected, target_lang="es")

    if progress_callback:
        progress_callback(total, total, "Traducción al español finalizada.")

    return translated_sections, overall_detected


def export_sections_to_txt(
    sections: list[tuple[str, str]],
    target_path: Path,
    doc_name: str = "",
    source_path: str = ""
) -> None:
    """Exporta las secciones a un archivo de texto plano (.txt) estructurado y legible."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "=" * 78,
        f"LIBRO / DOCUMENTO: {doc_name or target_path.stem}",
    ]
    if source_path:
        lines.append(f"ORIGEN: {source_path}")
    lines.extend([
        f"FECHA DE EXTRACCIÓN: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"TOTAL DE PÁGINAS/SECCIONES: {len(sections)}",
        "=" * 78,
        "",
    ])

    for i, (title, body) in enumerate(sections, 1):
        lines.append(f"--- [Sección {i} | {title}] ---")
        lines.append(body.strip())
        lines.append("")

    target_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def load_bookmarks() -> dict:
    if not PROGRESS_FILE.is_file():
        return {}
    try:
        import json
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_bookmark(path: Path, section_idx: int, chunk_idx: int = 0, title: str = "", rate: float = 1.0, voice: str = "", engine: str = "") -> None:
    try:
        import json
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = load_bookmarks()
        key = str(path.resolve())
        data["last_file"] = key
        if "files" not in data:
            data["files"] = {}
        data["files"][key] = {
            "name": path.name,
            "path": key,
            "section_idx": int(section_idx),
            "chunk_idx": int(chunk_idx),
            "title": title,
            "rate": float(rate),
            "voice": voice,
            "engine": engine,
            "updated_at": int(time.time()),
        }
        PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_bookmark(path: Path) -> dict | None:
    data = load_bookmarks()
    files = data.get("files", {})
    return files.get(str(path.resolve()))


def get_last_bookmark() -> dict | None:
    data = load_bookmarks()
    last = data.get("last_file")
    if last and Path(last).is_file():
        return data.get("files", {}).get(last)
    return None


# =========================================================================
# DETECCIÓN DE IDIOMA Y RESOLUCIÓN MULTILINGÜE DE VOCES
# =========================================================================

STOPWORDS_BY_LANG = {
    "es": {
        "el", "la", "los", "las", "un", "una", "unos", "unas", "y", "o", "de", "del",
        "en", "que", "por", "para", "con", "sin", "sobre", "este", "esta", "estos", "estas",
        "ese", "esa", "su", "sus", "al", "se", "le", "les", "me", "te", "nos", "es", "son",
        "fue", "era", "como", "más", "mas", "pero", "porque", "cuando", "donde", "todo", "todos",
        "muy", "también", "tambien", "bien", "ya", "hay", "había", "habia", "hasta", "desde",
        "capítulo", "capitulo", "página", "pagina", "libro", "sección", "seccion"
    },
    "en": {
        "the", "of", "and", "to", "a", "in", "is", "you", "that", "it", "he", "was",
        "for", "on", "are", "as", "with", "his", "they", "i", "at", "be", "this", "have",
        "from", "or", "one", "had", "by", "word", "but", "not", "what", "all", "were",
        "we", "when", "your", "can", "said", "there", "use", "an", "each", "which", "she",
        "do", "how", "their", "if", "will", "up", "other", "about", "out", "many", "then",
        "them", "these", "so", "some", "her", "would", "make", "like", "him", "into",
        "time", "has", "look", "two", "more", "write", "go", "see", "number", "no", "way",
        "could", "people", "my", "than", "first", "been", "call", "who", "its", "now",
        "chapter", "section", "part", "volume", "page", "algorithms", "data", "learning",
        "between", "under", "after", "before", "should", "could", "would", "because"
    },
    "fr": {
        "le", "la", "les", "un", "une", "des", "du", "de", "et", "en", "est", "que",
        "qui", "dans", "pour", "pas", "sur", "ce", "ces", "mais", "avec", "tout", "faire",
        "son", "sa", "ses", "comme", "vous", "nous", "ils", "elle", "au", "aux", "ne", "cette"
    },
    "de": {
        "der", "die", "das", "ein", "eine", "einer", "eines", "einem", "einen", "und",
        "in", "zu", "den", "dem", "nicht", "von", "mit", "sich", "des", "auf", "für",
        "ist", "im", "als", "auch", "es", "an", "werden", "aus", "er", "hat", "dass",
        "sie", "nach", "wird", "bei", "um", "am", "sind", "noch", "wie", "über", "so"
    },
    "it": {
        "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "e", "di", "a", "da",
        "in", "con", "su", "per", "tra", "fra", "che", "non", "si", "sono", "ma", "come",
        "questo", "questa", "questi", "queste", "piu", "anche", "del", "della", "dei"
    },
    "pt": {
        "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "do", "da", "dos", "das",
        "em", "no", "na", "nos", "nas", "e", "que", "para", "com", "nao", "não", "por",
        "mais", "como", "mas", "foi", "ao", "ele", "ela", "eles", "elas", "seu", "sua"
    }
}


def detect_language(text: str, default_lang: str = "es") -> str:
    """
    Detecta el idioma de una frase o fragmento con alta precisión.
    Retorna el código ISO de 2 letras ('es', 'en', 'fr', 'de', 'it', 'pt').
    """
    text_clean = text.strip()
    if not text_clean:
        return default_lang

    lower = text_clean.lower()
    if any(c in lower for c in "ñ¿¡"):
        return "es"
    if any(c in lower for c in "äöüß"):
        return "de"
    if any(c in lower for c in "ãõ"):
        return "pt"
    if "œ" in lower or "æ" in lower:
        return "fr"

    words = [w for w in re.findall(r"\b[^\W\d_]+\b", lower)]
    if not words:
        return default_lang

    scores = {}
    for lang, sw in STOPWORDS_BY_LANG.items():
        s = sum(1 for w in words if w in sw)
        if s > 0:
            scores[lang] = s

    if not scores:
        return default_lang

    best_lang = max(scores, key=scores.get)
    if default_lang in scores and scores[default_lang] == scores[best_lang]:
        return default_lang
    return best_lang


def resolve_voice_for_chunk(
    chunk_lang: str,
    base_voice: str = "mateo",
    base_engine: str = "local"
) -> tuple[str, str, str]:
    """
    Determina la voz nativa, código de idioma BCP-47 y motor óptimo para narrar un fragmento.
    Devuelve (voice_id, lang_code, engine).
    """
    lang = (chunk_lang or "es").lower()
    engine = (base_engine or "local").lower()
    voice_lower = (base_voice or "").lower()

    # Detección de género de la voz base
    is_female = any(fem in voice_lower for fem in ("leticia", "elvira", "dalia", "paloma", "aria", "slt", "clb", "femenina", "female", "denise", "katja", "elsa", "francisca"))

    if lang == "es":
        return base_voice, "es-ES", engine

    if lang == "en":
        lang_code = "en-US"
        if "local" in engine or "rhvoice" in engine:
            en_voice = "local:slt" if is_female else "local:bdl"
            return en_voice, lang_code, "local"
        else:
            en_voice = "edge:en-US-AriaNeural" if is_female else "edge:en-US-GuyNeural"
            return en_voice, lang_code, "edge"

    if lang == "fr":
        lang_code = "fr-FR"
        fr_voice = "edge:fr-FR-DeniseNeural" if is_female else "edge:fr-FR-HenriNeural"
        return fr_voice, lang_code, "edge"

    if lang == "de":
        lang_code = "de-DE"
        de_voice = "edge:de-DE-KatjaNeural" if is_female else "edge:de-DE-ConradNeural"
        return de_voice, lang_code, "edge"

    if lang == "it":
        lang_code = "it-IT"
        it_voice = "edge:it-IT-ElsaNeural" if is_female else "edge:it-IT-DiegoNeural"
        return it_voice, lang_code, "edge"

    if lang == "pt":
        lang_code = "pt-BR"
        pt_voice = "edge:pt-BR-FranciscaNeural" if is_female else "edge:pt-BR-AntonioNeural"
        return pt_voice, lang_code, "edge"

    return base_voice, "es-ES", engine


def split_quotes_and_clauses(sentence: str) -> list[str]:
    """Separa citas textuales en comillas para permitir cambio de acento/voz en diálogos y citas."""
    sentence = sentence.strip()
    matches = list(re.finditer(r'[\"“«]([^\"”»]{3,})[\"”»]', sentence))
    if not matches:
        return [sentence]
    parts: list[str] = []
    last_idx = 0
    for m in matches:
        start, end = m.span()
        prefix = sentence[last_idx:start].strip()
        quoted = sentence[start:end].strip()
        if prefix:
            parts.append(prefix.rstrip(" ,:;-"))
        if quoted:
            parts.append(quoted)
        last_idx = end
    suffix = sentence[last_idx:].strip().lstrip(" ,:;-")
    if suffix:
        parts.append(suffix)
    return [p for p in parts if p]


def get_section_chunks(body: str, max_chunk_len: int = 240) -> list[str]:
    """
    Divide una sección de texto en oraciones naturales y fragmentos ágiles.
    Garantiza que la narración sea responsiva, que la pausa sea instantánea
    y que frases en otros idiomas se procesen con la voz adecuada.
    """
    body = normalize_text(body)
    if not body:
        return []

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    all_chunks: list[str] = []

    for para in paragraphs:
        # Dividir por oraciones (. ! ? … ; : o saltos de línea)
        raw_sentences = re.split(r"(?<=[.!?…;:])\s+|\n+", para)
        for raw_s in raw_sentences:
            raw_s = raw_s.strip()
            if not raw_s:
                continue

            # Separar citas si las hay
            sub_clauses = split_quotes_and_clauses(raw_s)
            for clause in sub_clauses:
                clause = clause.strip()
                if not clause:
                    continue

                if len(clause) <= max_chunk_len:
                    all_chunks.append(clause)
                else:
                    # Subdividir oraciones muy largas por comas o límites de palabras
                    sub_parts = re.split(r"(?<=[,])\s+", clause)
                    buf = ""
                    for sp in sub_parts:
                        sp = sp.strip()
                        if not sp:
                            continue
                        cand = f"{buf} {sp}".strip() if buf else sp
                        if len(cand) <= max_chunk_len:
                            buf = cand
                        else:
                            if buf:
                                all_chunks.append(buf)
                            if len(sp) <= max_chunk_len:
                                buf = sp
                            else:
                                for i in range(0, len(sp), max_chunk_len):
                                    all_chunks.append(sp[i : i + max_chunk_len].strip())
                                buf = ""
                    if buf:
                        all_chunks.append(buf)

    return [c for c in all_chunks if c]


def load_tts():
    if not HOST_PY.is_file():
        sys.exit(f"No se encuentra el motor de voz: {HOST_PY}")
    spec = importlib.util.spec_from_file_location("narrador_host", HOST_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_paragraph(paragraph: str, max_len: int = MAX_CHUNK) -> list[str]:
    return get_section_chunks(paragraph, max_chunk_len=max_len)


def read_txt(path: Path) -> list[tuple[str, str]]:
    text = normalize_text(path.read_text(encoding="utf-8", errors="replace"))
    return sections_from_plain_text(text, path.stem)


def sections_from_plain_text(text: str, doc_name: str) -> list[tuple[str, str]]:
    text = normalize_text(text)
    if not text:
        return []
    blocks = [b.strip() for b in re.split(r"\n\s*\n+", text) if b.strip()]
    if not blocks:
        return []
    if len(blocks) == 1:
        return [(doc_name, blocks[0])]

    sections: list[tuple[str, str]] = []
    buf: list[str] = []
    buf_title = doc_name
    part_num = 0

    heading_line = re.compile(
        r"^(?:capítulo|capitulo|chapter|parte|part|sección|seccion|section)\s+[\dIVXLCivxlcáéíóúÁÉÍÓÚ]+",
        re.IGNORECASE,
    )

    def flush_buf() -> None:
        nonlocal part_num, buf, buf_title
        if not buf:
            return
        part_num += 1
        title = buf_title if part_num == 1 and buf_title != doc_name else f"{doc_name} · {part_num}"
        sections.append((title, "\n\n".join(buf)))
        buf = []
        buf_title = doc_name

    for block in blocks:
        first_line = block.split("\n", 1)[0].strip()
        if heading_line.match(first_line) or (
            len(first_line) < 80 and first_line.isupper() and len(first_line.split()) <= 8
        ):
            flush_buf()
            buf_title = first_line
            rest = block[len(first_line) :].strip()
            if rest:
                buf.append(rest)
        else:
            buf.append(block)

    flush_buf()
    return sections if sections else [(doc_name, text)]


def is_docx_heading(style_name: str) -> bool:
    s = (style_name or "").lower().replace("_", " ")
    return (
        s.startswith("heading")
        or s.startswith("título")
        or s.startswith("titulo")
        or s.startswith("title")
        or s.startswith("encabezado")
    )


def read_docx(path: Path) -> list[tuple[str, str]] | None:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return None

    doc = Document(str(path))
    sections: list[tuple[str, str]] = []
    title = path.stem
    paras: list[str] = []

    def flush() -> None:
        nonlocal paras, title
        if paras:
            sections.append((title, "\n\n".join(paras)))
            paras = []

    def add_paragraph(p: Paragraph) -> None:
        text = (p.text or "").replace("\r", "").strip()
        if not text:
            return
        style = p.style.name if p.style else ""
        if is_docx_heading(style):
            flush()
            title = text
        else:
            paras.append(text)

    for block in doc.element.body:
        tag = block.tag.split("}")[-1] if "}" in block.tag else block.tag
        if tag == "p":
            add_paragraph(Paragraph(block, doc))
        elif tag == "tbl":
            flush()
            table = Table(block, doc)
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    paras.append(" — ".join(cells))
            flush()

    flush()
    return sections if sections else None


def find_soffice() -> str | None:
    for name in ("soffice", "libreoffice", "lowriter"):
        found = shutil.which(name)
        if found:
            return found
    return None


def convert_to_txt_with_soffice(path: Path) -> str | None:
    soffice = find_soffice()
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        outdir = Path(tmp)
        try:
            proc = subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--nologo",
                    "--nofirststartwizard",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    str(outdir),
                    str(path.resolve()),
                ],
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        candidates = sorted(outdir.glob("*.txt"))
        if not candidates:
            fallback = outdir / f"{path.stem}.txt"
            if fallback.is_file():
                candidates = [fallback]
        if not candidates:
            return None
        return candidates[0].read_text(encoding="utf-8", errors="replace")


def convert_doc_with_antiword(path: Path) -> str | None:
    antiword = shutil.which("antiword")
    if not antiword:
        return None
    try:
        proc = subprocess.run(
            [antiword, "-w", "0", str(path)],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    return proc.stdout


def read_office(path: Path) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()

    if suffix in (".docx", ".docm"):
        try:
            sections = read_docx(path)
            if sections:
                return sections
        except Exception as exc:
            print(f"Aviso: python-docx falló ({exc}), probando LibreOffice…", file=sys.stderr)

    plain: str | None = None
    if suffix == ".doc":
        plain = convert_doc_with_antiword(path)
    if not plain:
        plain = convert_to_txt_with_soffice(path)

    if not plain or not plain.strip():
        sys.exit(
            f"No se pudo extraer texto de {path.name}.\n"
            "  • DOCX: pip install --user python-docx\n"
            "  • DOC/ODT/RTF: sudo dnf install libreoffice-core (LibreOffice)\n"
            "  • DOC antiguo: sudo dnf install antiword (opcional)\n"
            "Abre el archivo en LibreOffice, guárdalo como .docx o .odt y vuelve a intentar."
        )

    return sections_from_plain_text(plain, path.stem)


def read_epub(path: Path) -> list[tuple[str, str]]:
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError as exc:
        sys.exit(
            "Para EPUB instala dependencias:\n"
            "  pip install --user ebooklib beautifulsoup4\n"
            f"({exc})"
        )

    book = epub.read_epub(str(path))
    sections: list[tuple[str, str]] = []
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        title = ""
        h = soup.find(["h1", "h2", "h3"])
        if h:
            title = h.get_text(" ", strip=True)
        blocks = []
        for el in soup.find_all(["p", "li", "blockquote", "h1", "h2", "h3", "h4"]):
            t = el.get_text(" ", strip=True)
            if t and len(t) > 2:
                blocks.append(t)
        if not blocks:
            t = soup.get_text("\n", strip=True)
            blocks = [p for p in t.split("\n") if len(p) > 2]
        label = title or f"Sección {len(sections) + 1}"
        body = "\n\n".join(blocks)
        if body.strip():
            sections.append((label, body))
    return sections


def pdf_lines_to_body(text: str) -> str:
    """Une saltos de línea típicos de PDF (corte a mitad de frase)."""
    lines = [ln.strip() for ln in text.split("\n")]
    paragraphs: list[str] = []
    buf = ""
    for line in lines:
        if not line:
            if buf:
                paragraphs.append(buf)
                buf = ""
            continue
        if not buf:
            buf = line
            continue
        ends_sentence = bool(re.search(r'[.!?…:;»"\')]$', buf))
        starts_lower = line[0].islower() if line else False
        if not ends_sentence or starts_lower:
            buf = f"{buf} {line}"
        else:
            paragraphs.append(buf)
            buf = line
    if buf:
        paragraphs.append(buf)
    if paragraphs:
        return "\n\n".join(paragraphs)
    return normalize_text(text)


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    # Unir palabras cortadas por guion al final de línea
    text = re.sub(r"(\w+)[-—]\s*\n\s*(\w+)", r"\1\2", text)
    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        # Filtrar artefactos aislados de ruido en escaneo
        if re.fullmatch(r"[\W_]+", cleaned):
            continue
        lines.append(cleaned)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def find_tesseract_bin() -> str | None:
    for candidate in ("/usr/bin/tesseract", "/usr/local/bin/tesseract"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("tesseract")


def find_tessdata_dir() -> tuple[Path | None, str]:
    """Busca el directorio tessdata y determina los idiomas disponibles (spa, eng, spa+eng)."""
    candidates = [
        ROOT / "libro" / "tessdata",
        Path.home() / ".local" / "share" / "tessdata",
        Path("/usr/share/tesseract/tessdata"),
    ]
    for d in candidates:
        if d.is_dir():
            has_spa = (d / "spa.traineddata").is_file()
            has_eng = (d / "eng.traineddata").is_file()
            if has_spa and has_eng:
                return d, "spa+eng"
            if has_spa:
                return d, "spa"
            if has_eng:
                return d, "eng"
    return None, "eng"


def run_tesseract_ocr(img_source: Path | str | bytes | object, lang: str | None = None) -> str:
    """Ejecuta OCR infalible usando tesseract directamente o pytesseract como respaldo.
    Acepta: Path, ruta str, bytes de imagen, o PyMuPDF Pixmap / PIL Image.
    """
    tess_bin = find_tesseract_bin()
    tessdata_dir, default_lang = find_tessdata_dir()
    use_lang = lang or default_lang

    tmp_path: Path | None = None
    input_file: str = ""

    if isinstance(img_source, (str, Path)) and os.path.isfile(str(img_source)):
        input_file = str(img_source)
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        input_file = str(tmp_path)

        if hasattr(img_source, "save"):
            # PyMuPDF Pixmap o PIL Image
            img_source.save(str(tmp_path))
        elif isinstance(img_source, bytes):
            tmp_path.write_bytes(img_source)
        else:
            try:
                from PIL import Image
                if hasattr(img_source, "samples") and hasattr(img_source, "width") and hasattr(img_source, "height"):
                    img = Image.frombytes("RGB", [img_source.width, img_source.height], img_source.samples)
                    img.save(str(tmp_path))
            except Exception:
                pass

    try:
        # Intento A: Invocar tesseract CLI directamente (más robusto y sin dependencias de Python)
        if tess_bin and os.path.isfile(input_file) and os.path.getsize(input_file) > 0:
            cmd = [tess_bin, input_file, "stdout", "-l", use_lang, "--psm", "3"]
            if tessdata_dir:
                cmd.extend(["--tessdata-dir", str(tessdata_dir)])
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if proc.returncode == 0 and proc.stdout.strip():
                return clean_ocr_text(proc.stdout)

        # Intento B: Si hay pytesseract y falló la orden directa
        try:
            import pytesseract
            from PIL import Image
            if tessdata_dir:
                os.environ["TESSDATA_PREFIX"] = str(tessdata_dir)
            with Image.open(input_file) as im:
                txt = pytesseract.image_to_string(im, lang=use_lang)
                if txt.strip():
                    return clean_ocr_text(txt)
        except Exception:
            pass

    except Exception as e:
        print(f"Aviso OCR: {e}", file=sys.stderr)
    finally:
        if tmp_path and tmp_path.is_file():
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return ""


def ocr_pixmap(pix, lang: str | None = None) -> str:
    """Ejecuta OCR sobre una imagen renderizada con Tesseract en español e inglés."""
    return run_tesseract_ocr(pix, lang=lang)


def extract_tables_from_page(page) -> str:
    """Detecta tablas estructuradas y estadísticas y las convierte en oraciones comprensibles al oído."""
    try:
        tabs = page.find_tables()
        if not tabs or not tabs.tables:
            return ""
        out = []
        for t_idx, tab in enumerate(tabs.tables, 1):
            rows = tab.extract()
            if not rows or len(rows) < 2:
                continue
            headers = [str(h or "").strip() for h in rows[0]]
            out.append(f"\n[Tabla {t_idx}]:")
            for r_idx, row in enumerate(rows[1:], 1):
                cells = []
                for c_idx, val in enumerate(row):
                    val_str = str(val or "").strip()
                    if val_str:
                        col_name = headers[c_idx] if c_idx < len(headers) and headers[c_idx] else f"Columna {c_idx + 1}"
                        cells.append(f"{col_name}: {val_str}")
                if cells:
                    out.append(f"Fila {r_idx}: " + "; ".join(cells) + ".")
        return "\n".join(out)
    except Exception:
        return ""


def extract_figures_and_diagrams(page, existing_text: str) -> str:
    """Detecta imágenes de gráficas o estadísticas y extrae los textos y etiquetas embebidos con OCR."""
    try:
        image_list = page.get_images(full=True)
        if not image_list:
            return ""
        doc = page.parent
        fig_texts = []

        for img_idx, img_info in enumerate(image_list, 1):
            xref = img_info[0]
            base_img = doc.extract_image(xref)
            if not base_img or not base_img.get("image"):
                continue
            width = base_img.get("width", 0)
            height = base_img.get("height", 0)
            # Descartar iconos o adornos pequeños
            if width < 120 or height < 120:
                continue

            img_bytes = base_img["image"]
            txt = run_tesseract_ocr(img_bytes)
            cleaned = clean_ocr_text(txt)
            if cleaned and len(cleaned) > 10:
                sample = cleaned[:30]
                if sample not in existing_text:
                    fig_texts.append(f"\n[Datos de Gráfica / Figura {img_idx}]:\n{cleaned}")
        return "\n".join(fig_texts)
    except Exception:
        return ""


def read_pdf_pymupdf(path: Path) -> list[tuple[str, str]] | None:
    try:
        import fitz
    except ImportError:
        return None

    sections: list[tuple[str, str]] = []
    doc = fitz.open(path)
    try:
        if doc.is_encrypted and not doc.authenticate(""):
            sys.exit(
                "Este PDF pide contraseña. Ábrelo en un lector, quita la protección "
                "y guárdalo de nuevo, o exporta a TXT/EPUB."
            )
        for i, page in enumerate(doc):
            vector_text = normalize_text(page.get_text("text"))
            tables_text = extract_tables_from_page(page)

            # Criterio para OCR:
            # 1. Menos de 100 caracteres vectoriales: suele ser escaneo/foto completo.
            # 2. O menos de 250 caracteres vectoriales pero contiene imágenes incrustadas.
            images_on_page = page.get_images()
            needs_full_ocr = len(vector_text.strip()) < 100 or (len(vector_text.strip()) < 250 and len(images_on_page) > 0)

            ocr_text = ""
            if needs_full_ocr:
                pix = page.get_pixmap(dpi=200)
                ocr_candidate = ocr_pixmap(pix)
                if len(ocr_candidate.strip()) > len(vector_text.strip()):
                    ocr_text = ocr_candidate

            fig_text = ""
            if not ocr_text:
                fig_text = extract_figures_and_diagrams(page, vector_text)

            parts = []
            if ocr_text:
                parts.append(ocr_text)
            elif vector_text:
                parts.append(pdf_lines_to_body(vector_text))

            if tables_text:
                parts.append(tables_text)
            if fig_text:
                parts.append(fig_text)

            body = "\n\n".join(p for p in parts if p.strip()).strip()
            if body:
                label_suffix = " (OCR)" if (ocr_text and not vector_text) else ""
                sections.append((f"Página {i + 1}{label_suffix}", body))
    finally:
        doc.close()
    return sections if sections else None


def read_pdf_poppler(path: Path) -> list[tuple[str, str]] | None:
    pdftotext = shutil.which("pdftotext")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftotext and not pdftoppm:
        return None

    raw_pages: list[str] = []
    if pdftotext:
        try:
            proc = subprocess.run(
                [pdftotext, "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            if proc.returncode == 0 and (proc.stdout or "").strip():
                raw_pages = proc.stdout.split("\f")
        except (OSError, subprocess.TimeoutExpired):
            pass

    sections: list[tuple[str, str]] = []

    # Si pdftotext no extrajo texto legible (típico en PDFs escaneados), renderizar con pdftoppm + OCR
    total_text = "".join(raw_pages).strip()
    if len(total_text) < 100 and pdftoppm:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [pdftoppm, "-png", "-r", "150", str(path), str(Path(tmpdir) / "page")]
            subprocess.run(cmd, capture_output=True, timeout=300)
            rendered = sorted(Path(tmpdir).glob("page-*.png"))
            for idx, p_img in enumerate(rendered, 1):
                txt = run_tesseract_ocr(p_img)
                if txt.strip():
                    sections.append((f"Página {idx} (OCR)", txt.strip()))
        return sections if sections else None

    for i, page in enumerate(raw_pages):
        body = pdf_lines_to_body(normalize_text(page))
        if body.strip():
            sections.append((f"Página {i + 1}", body))
    return sections if sections else None


def read_image_file(path: Path) -> list[tuple[str, str]]:
    """Lee archivos de imagen directa (escaneos, fotos, capturas) usando OCR."""
    text = run_tesseract_ocr(path)
    if text.strip():
        return [(f"Imagen: {path.name} (OCR)", text)]
    return []


def read_pdf(path: Path) -> list[tuple[str, str]]:
    sections = read_pdf_pymupdf(path)
    if sections:
        return sections
    sections = read_pdf_poppler(path)
    if sections:
        return sections

    sys.exit(
        "No se pudo leer el PDF ni extraer texto.\n"
        "Asegúrate de que el archivo no esté corrupto."
    )


def load_sections(path: Path, force_reload: bool = False) -> list[tuple[str, str]]:
    if not force_reload:
        cached = load_cached_sections(path)
        if cached:
            return cached

    suffix = path.suffix.lower()
    if suffix == ".txt":
        sections = read_txt(path)
    elif suffix == ".epub":
        sections = read_epub(path)
    elif suffix == ".pdf":
        sections = read_pdf(path)
    elif suffix in (".doc", ".docx", ".docm", ".odt", ".odf", ".rtf", ".wps"):
        sections = read_office(path)
    elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp"):
        sections = read_image_file(path)
    else:
        sys.exit(
            f"Formato no soportado: {suffix}. "
            "Usa .pdf, .epub, .txt, .docx, .odt o imágenes (.png, .jpg, .webp)."
        )

    if sections:
        save_cached_sections(path, sections)
    return sections


# =========================================================================
# EXPORTACIÓN DE AUDIOLIBROS EN FORMATO MP3
# =========================================================================

def synthesize_chunk_to_mp3_file(
    piece: str,
    voice: str,
    engine: str,
    rate: float,
    cache_dir: Path,
    token: str,
    host_mod,
) -> Path | None:
    piece = piece.strip()
    if not piece:
        return None

    out_mp3 = cache_dir / f"{token}.mp3"
    out_wav = cache_dir / f"{token}.wav"
    in_txt = cache_dir / f"{token}.txt"

    edge_bin = host_mod.edge_tts_bin()
    rh_bin = host_mod.rhvoice_test_bin()

    # 1. Si es motor edge y edge-tts está disponible
    if "edge" in engine.lower():
        edge_v = host_mod.edge_voice_id(voice)
        # Intentar síntesis directa en Python con el endpoint actualizado
        if hasattr(host_mod, "ensure_edge_tts_patched"):
            host_mod.ensure_edge_tts_patched()
        try:
            import asyncio
            import edge_tts
            async def _save_chunk():
                comm = edge_tts.Communicate(
                    piece,
                    edge_v,
                    rate=host_mod.map_edge_rate(rate),
                )
                await comm.save(str(out_mp3))
            asyncio.run(_save_chunk())
            if out_mp3.is_file() and out_mp3.stat().st_size > 128:
                return out_mp3
        except Exception:
            pass

        # Fallback a CLI
        if edge_bin:
            try:
                cmd = [
                    edge_bin,
                    "--voice", edge_v,
                    f"--rate={host_mod.map_edge_rate(rate)}",
                    "--text", piece,
                    "--write-media", str(out_mp3),
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0 and out_mp3.is_file() and out_mp3.stat().st_size > 128:
                    return out_mp3
            except Exception:
                pass

    # 2. RHVoice local directo a WAV y codificación a MP3
    if rh_bin:
        try:
            in_txt.write_text(piece, encoding="utf-8")
            rh_voice = host_mod.local_voice_id(voice) or "mateo"
            cmd_rh = [
                rh_bin,
                "-p", rh_voice,
                "-o", str(out_wav),
                "-i", str(in_txt),
                "-r", str(host_mod.map_rhvoice_rate(rate)),
            ]
            res = subprocess.run(cmd_rh, capture_output=True, text=True, timeout=120)
            if res.returncode == 0 and out_wav.is_file() and out_wav.stat().st_size > 128:
                cmd_ff = [
                    "ffmpeg", "-y", "-i", str(out_wav),
                    "-c:a", "libmp3lame", "-b:a", "128k",
                    str(out_mp3),
                ]
                res_ff = subprocess.run(cmd_ff, capture_output=True, text=True, timeout=60)
                if res_ff.returncode == 0 and out_mp3.is_file() and out_mp3.stat().st_size > 128:
                    return out_mp3
        except Exception:
            pass
        finally:
            out_wav.unlink(missing_ok=True)
            in_txt.unlink(missing_ok=True)

    return None


def parse_page_ranges(range_str: str, max_pages: int) -> list[int]:
    """
    Parsea una especificación de páginas/rangos como '7-99, 107-301' o '1, 3, 5-10'.
    Utiliza guiones (-) para rangos continuos y comas (,) para separar distintos rangos.
    Retorna una lista de índices 0-based ordenados ascendentemente y sin duplicados.
    Lanza ValueError con mensaje descriptivo si el formato o las páginas son inválidas.
    """
    range_str = (range_str or "").strip()
    if not range_str:
        raise ValueError("El rango de páginas no puede estar vacío.")

    normalized = range_str.replace(";", ",")
    parts = [p.strip() for p in normalized.split(",") if p.strip()]
    if not parts:
        raise ValueError("No se encontraron páginas o rangos válidos.")

    selected_pages = set()
    for part in parts:
        if "-" in part:
            sub = [s.strip() for s in part.split("-")]
            if len(sub) != 2 or not sub[0].isdigit() or not sub[1].isdigit():
                raise ValueError(f"Rango inválido: '{part}'. Usa el formato 'inicio-fin' (ej: 7-99).")
            start = int(sub[0])
            end = int(sub[1])
            if start > end:
                start, end = end, start
            if start < 1:
                start = 1
            if end > max_pages:
                end = max_pages
            if start <= max_pages:
                for p in range(start, end + 1):
                    selected_pages.add(p - 1)
        else:
            if not part.isdigit():
                raise ValueError(f"Número de página inválido: '{part}'.")
            p = int(part)
            if 1 <= p <= max_pages:
                selected_pages.add(p - 1)
            else:
                raise ValueError(f"Página fuera de límites: {p}. El documento tiene {max_pages} páginas (1 a {max_pages}).")

    if not selected_pages:
        raise ValueError(f"Ninguna de las páginas indicadas se encuentra dentro del documento (1 a {max_pages}).")

    return sorted(selected_pages)


def export_book_to_mp3(
    sections: list[tuple[str, str]],
    out_file: Path,
    voice: str = "mateo",
    engine: str = "local",
    rate: float = 1.0,
    doc_title: str = "Audiolibro",
    multilingual: bool = True,
    progress_callback=None,
    cancel_check=None,
) -> bool:
    """
    Sintetiza todas las secciones seleccionadas y las ensambla en un único archivo MP3 de alta calidad.
    """
    if not sections:
        return False

    out_file = Path(out_file).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    host_mod = load_tts()
    cache = host_mod.narrador_cache_dir()
    temp_parts: list[Path] = []
    total = len(sections)

    session_token = f"exp-{os.getpid()}-{int(time.time()*1000)}"

    try:
        for s_idx, (sec_title, sec_body) in enumerate(sections):
            if cancel_check and cancel_check():
                break

            if progress_callback:
                progress_callback(s_idx, total, f"Sintetizando sección {s_idx + 1}/{total}: {sec_title[:35]}…")

            chunks = get_section_chunks(sec_body)
            for c_idx, chunk in enumerate(chunks):
                if cancel_check and cancel_check():
                    break

                chunk_token = f"{session_token}-s{s_idx}-c{c_idx}"
                chunk_lang = detect_language(chunk) if multilingual else "es"
                spk_v, spk_l, spk_e = resolve_voice_for_chunk(chunk_lang, voice, engine)

                mp3_part = synthesize_chunk_to_mp3_file(
                    chunk, spk_v, spk_e, rate, cache, chunk_token, host_mod
                )
                if mp3_part and mp3_part.is_file():
                    temp_parts.append(mp3_part)

        if cancel_check and cancel_check():
            for p in temp_parts:
                p.unlink(missing_ok=True)
            return False

        if not temp_parts:
            return False

        if progress_callback:
            progress_callback(total, total, "Uniendo fragmentos de audio en el archivo final MP3…")

        concat_list = cache / f"{session_token}-concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in temp_parts:
                f.write(f"file '{p.resolve()}'\n")

        cmd_concat = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame", "-b:a", "128k",
            "-metadata", f"title={doc_title}",
            "-metadata", "artist=Narrador Neuronal",
            str(out_file)
        ]
        res = subprocess.run(cmd_concat, capture_output=True, text=True)
        concat_list.unlink(missing_ok=True)

        for p in temp_parts:
            p.unlink(missing_ok=True)

        return out_file.is_file() and out_file.stat().st_size > 512
    except Exception as e:
        print(f"Error en export_book_to_mp3: {e}", file=sys.stderr)
        for p in temp_parts:
            p.unlink(missing_ok=True)
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Narra documentos (TXT, EPUB, PDF, Word, ODT, RTF) con RHVoice o Edge TTS."
    )
    parser.add_argument(
        "archivo",
        type=Path,
        help="Ruta al archivo (.txt, .epub, .pdf, .doc, .docx, .odt, .rtf, …)",
    )
    parser.add_argument(
        "--engine",
        choices=("local", "edge", "auto"),
        default="auto",
        help="Motor: local=RHVoice, edge=Microsoft Edge online",
    )
    parser.add_argument(
        "--voice",
        default="",
        help="Voz, p.ej. local:mateo o edge:es-ES-ElviraNeural",
    )
    parser.add_argument("--lang", default="es-ES", help="Código de idioma")
    parser.add_argument("--rate", type=float, default=1.0, help="Velocidad (0.5–1.5)")
    parser.add_argument("--pitch", type=float, default=1.0)
    parser.add_argument("--volume", type=float, default=1.0)
    parser.add_argument(
        "--from-chapter",
        type=int,
        default=1,
        metavar="N",
        help="Empezar en la sección/capítulo/página N (1 = primero; en PDF = página)",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=0.35,
        help="Pausa en segundos entre fragmentos",
    )
    parser.add_argument(
        "--max-sections",
        type=int,
        default=0,
        help="Solo narrar las primeras N secciones (0 = todas)",
    )
    parser.add_argument(
        "--force-ocr",
        "--force-reload",
        dest="force_reload",
        action="store_true",
        help="Ignorar caché existente y forzar un nuevo análisis completo con OCR",
    )
    parser.add_argument(
        "--translate-es",
        action="store_true",
        help="Traducir el documento al español antes de narrar, exportar TXT o exportar MP3",
    )
    parser.add_argument(
        "--export-txt",
        type=Path,
        metavar="RUTA_TXT",
        help="Exportar el texto extraído (con OCR) a un archivo de texto plano .txt y salir",
    )
    parser.add_argument(
        "--export-mp3",
        type=Path,
        metavar="RUTA_MP3",
        help="Sintetizar el documento completo a un archivo de audio MP3 y salir",
    )
    parser.add_argument(
        "--pages",
        "--range",
        dest="page_range",
        type=str,
        default="",
        metavar="RANGOS",
        help="Filtrar páginas o rangos específicos para narrar o exportar (ej: '7-99, 107-301')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Solo listar secciones y fragmentos, sin hablar",
    )
    return parser.parse_args()


def pick_engine(tts, requested: str) -> str:
    if requested in ("local", "edge"):
        return requested
    engines = tts.detect_engines()
    if "rhvoice" in engines:
        return "local"
    if "edge-tts" in engines:
        return "edge"
    sys.exit("No hay motor de voz. Instala RHVoice o edge-tts (./native/install-rhvoice.sh)")


def pick_voice(tts, engine: str, voice: str, lang: str) -> str:
    if voice:
        return voice
    if engine == "local":
        vid = tts.pick_installed_spanish_voice() if hasattr(tts, "pick_installed_spanish_voice") else "mateo"
        return tts.LOCAL_VOICE_PREFIX + vid
    return tts.pick_neural_voice(lang)


def main() -> int:
    args = parse_args()
    path = args.archivo.expanduser().resolve()
    if not path.is_file():
        sys.exit(f"Archivo no encontrado: {path}")

    tts = load_tts()
    engine = pick_engine(tts, args.engine)
    voice = pick_voice(tts, engine, args.voice, args.lang)

    was_cached = is_cached(path) and not args.force_reload
    sections = load_sections(path, force_reload=args.force_reload)
    if not sections:
        sys.exit("No se extrajo texto del archivo.")

    if was_cached:
        print(f"⚡ Cargado al instante desde caché de texto (~0.01s, sin espera de OCR).")
        print(f"   (Usa --force-ocr si deseas forzar un nuevo análisis completo).")
    else:
        print(f"💾 Texto y OCR extraídos y almacenados en caché para próximas aperturas.")

    doc_lang = detect_document_language(sections)
    if args.translate_es or (doc_lang != "es" and is_translation_cached(path) and not args.force_reload):
        print(f"🌐 Cargando versión traducida al español (idioma detectado: {doc_lang.upper()})…")
        def on_cli_trans(curr, tot, msg):
            print(f"   [{curr}/{tot}] {msg}")
        sections, doc_lang = translate_sections_to_spanish(
            sections,
            source_path=path,
            force=args.force_reload,
            progress_callback=on_cli_trans,
        )
        print(f"✅ Secciones procesadas en español ({len(sections)} secciones).")

    if args.page_range:
        try:
            chosen_indices = parse_page_ranges(args.page_range, len(sections))
            sections = [sections[i] for i in chosen_indices]
            print(f"📑 Rango de páginas aplicado: {len(sections)} páginas seleccionadas según '{args.page_range}'.")
        except ValueError as err:
            sys.exit(f"❌ Error en el rango de páginas: {err}")

    if args.export_txt:
        export_sections_to_txt(sections, args.export_txt, doc_name=path.name, source_path=str(path))
        print(f"✅ Texto exportado correctamente a: {args.export_txt}")
        return 0

    if args.export_mp3:
        print(f"🎙️ Iniciando síntesis y exportación a MP3: {args.export_mp3}")
        def on_cli_progress(curr, tot, msg):
            print(f"   [{curr}/{tot}] {msg}")
        ok = export_book_to_mp3(
            sections,
            args.export_mp3,
            voice=voice,
            engine=engine,
            rate=args.rate,
            doc_title=path.stem,
            progress_callback=on_cli_progress,
        )
        if ok:
            print(f"✅ Audiolibro MP3 generado exitosamente en: {args.export_mp3}")
            return 0
        else:
            print(f"❌ Error al generar el audiolibro MP3.", file=sys.stderr)
            return 1

    start = max(1, args.from_chapter) - 1
    if args.from_chapter == 1:
        bm = get_bookmark(path)
        if bm and 0 <= bm.get("section_idx", 0) < len(sections):
            saved_idx = bm["section_idx"]
            start = saved_idx
            print(f"📍 Marcador encontrado: reanudando en {sections[start][0]} (sección {start + 1})")

    sections_to_read = sections[start:]
    if args.max_sections > 0:
        sections_to_read = sections_to_read[: args.max_sections]

    print(f"Archivo: {path.name}")
    print(f"Motor: {engine} · Voz: {voice}")
    print(f"Secciones a narrar: {len(sections_to_read)}")
    print("Pulsa Ctrl+C para pausar/detener (el progreso queda guardado automáticamente).\n")

    total_chunks = 0
    try:
        for si, (title, body) in enumerate(sections_to_read, start=start + 1):
            chunks = get_section_chunks(body)
            print(f"—— {si}. {title[:72]} ({len(chunks)} frases) ——")
            for ci, piece in enumerate(chunks):
                total_chunks += 1
                chunk_lang = detect_language(piece)
                speak_voice, speak_lang, speak_engine = resolve_voice_for_chunk(chunk_lang, voice, engine)
                save_bookmark(path, si - 1, ci, title, args.rate, voice, engine)

                preview = piece[:80] + ("…" if len(piece) > 80 else "")
                lang_tag = f"[{chunk_lang.upper()}] " if chunk_lang != "es" else ""
                print(f"  [{total_chunks}] {lang_tag}{preview}")
                if args.dry_run:
                    continue
                result = tts.speak(
                    piece,
                    speak_lang,
                    args.rate,
                    args.pitch,
                    args.volume,
                    speak_voice,
                    speak_engine,
                )
                if not result.get("ok") and not result.get("cancelled"):
                    print(f"  Error: {result.get('error', 'desconocido')}", file=sys.stderr)
                    return 1
                if args.pause > 0:
                    time.sleep(args.pause)
    except KeyboardInterrupt:
        print("\nLectura pausada por el usuario. Progreso guardado.")
        return 0

    print(f"\nFin ({total_chunks} fragmentos).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nDetenido.")
        raise SystemExit(130)
