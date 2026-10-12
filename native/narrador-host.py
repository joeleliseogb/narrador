#!/usr/bin/env python3
"""Native messaging host: Edge online TTS + RHVoice local neural."""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


RHVOICE_SNAP_DATA = Path(
    "/var/snap/rhvoice/common/var/lib/RHVoice/data/RHVoice"
)
RHVOICE_SNAP_META = Path("/var/snap/rhvoice/common/var/lib/RHVoice")
RHVOICE_SYSTEM_DATA = Path("/usr/share/RHVoice")
EDGE_VOICE_PREFIX = "edge:"
LOCAL_VOICE_PREFIX = "local:"
_play_proc = None
_play_tmp = None

# Voces RHVoice conocidas por idioma (IDs en minúsculas)
SPANISH_RHVOICE_IDS = frozenset(
    {"mateo", "carlos", "tomas", "leticia", "spanish", "sp_es", "seba"}
)
RHVOICE_LANG_BY_ID = {
    "mateo": "es",
    "carlos": "es",
    "tomas": "es",
    "leticia": "es",
    "spanish": "es",
    "alan": "en",
    "bdl": "en",
    "bdl2": "en",
    "bdl_male": "en",
    "clb": "en",
    "slt": "en",
    "sp": "en",
    "nathan": "en",
    "lyubov": "uk",
    "aleksandr": "ru",
    "artemiy": "ru",
    "elena": "ru",
    "anna": "ka",
    "natia": "ka",
}


def edge_tts_candidates():
    home = Path.home()
    return (
        "edge-tts",
        str(home / ".local/bin/edge-tts"),
        "/usr/local/bin/edge-tts",
        "/usr/bin/edge-tts",
    )


def find_binary(candidates):
    for candidate in candidates:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return shutil.which(candidates[0]) if candidates else None


def edge_tts_bin():
    return find_binary(edge_tts_candidates())


def ffplay_bin():
    return find_binary(("ffplay", "/usr/bin/ffplay", "/usr/local/bin/ffplay"))


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) == 0:
        return None
    length = struct.unpack("=I", raw)[0]
    return json.loads(sys.stdin.buffer.read(length).decode("utf-8"))


def write_message(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("=I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def clamp(value, low, high):
    return max(low, min(high, value))


def map_rate(rate):
    """speech-dispatcher / spd-say: 0 = normal, negative = slower."""
    return clamp(int((float(rate) - 1.0) * 100), -100, 200)


def map_rhvoice_rate(rate):
    """RHVoice: 100 = ritmo natural. UI ≥0.95 se trata como normal."""
    r = safe_float(rate, 1.0)
    if r >= 0.95:
        return 100
    pct = int(round(100 + (r - 1.0) * 100))
    return clamp(pct, 75, 100)


def map_pitch(pitch):
    return clamp(int((float(pitch) - 1.0) * 100), -100, 100)


def map_volume(volume):
    return clamp(int((float(volume) - 1.0) * 100), -100, 100)


def safe_float(value, default=1.0):
    try:
        n = float(value)
        if n != n or n <= 0:  # NaN or non-positive
            return default
        return n
    except (TypeError, ValueError):
        return default


def map_edge_rate(rate):
    pct = clamp(int((safe_float(rate) - 1.0) * 100), -50, 100)
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def map_edge_volume(volume):
    pct = clamp(int((safe_float(volume) - 1.0) * 100), -50, 50)
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


def map_edge_pitch(pitch):
    hz = clamp(int((safe_float(pitch) - 1.0) * 20), -20, 20)
    return f"+{hz}Hz" if hz >= 0 else f"{hz}Hz"


def stop_playback():
    global _play_proc, _play_tmp
    if _play_proc is not None and _play_proc.poll() is None:
        _play_proc.terminate()
        try:
            _play_proc.wait(timeout=0.4)
        except subprocess.TimeoutExpired:
            _play_proc.kill()
    _play_proc = None
    if _play_tmp and os.path.isfile(_play_tmp):
        try:
            os.unlink(_play_tmp)
        except OSError:
            pass
    _play_tmp = None


def cancel_speech():
    stop_playback()
    for cmd in (
        ["spd-say", "--cancel"],
        ["killall", "spd-say"],
        ["killall", "ffplay"],
        ["killall", "mpv"],
        ["killall", "edge-playback"],
    ):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def estimate_duration_ms(text, rate=1.0):
    text = (text or "").strip()
    if not text:
        return 500
    chars = len(text)
    words = len(text.split())
    sec = max(chars / 7.0, words / 2.0) / max(0.5, float(rate))
    return int(max(800, sec * 1000 * 1.3))


def wait_playback_done(timeout_sec=180):
    global _play_proc
    if _play_proc is None:
        return 0
    t0 = time.time()
    try:
        _play_proc.wait(timeout=max(5, timeout_sec))
    except subprocess.TimeoutExpired:
        stop_playback()
    return int((time.time() - t0) * 1000)


def rhvoice_available():
    if rhvoice_test_bin() and has_spanish_rhvoice():
        return True
    if not shutil.which("spd-say"):
        return False
    if discover_rhvoice_voices():
        return True
    try:
        proc = subprocess.run(
            ["spd-say", "-L", "-o", "rhvoice"],
            capture_output=True,
            text=True,
            timeout=45,
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except (subprocess.TimeoutExpired, OSError):
        return False


def is_local_voice(name):
    voice = (name or "").strip()
    if voice.startswith(LOCAL_VOICE_PREFIX) or voice.startswith("rhvoice:"):
        return True
    if is_edge_voice(voice):
        return False
    return bool(voice) and "+" not in voice


def local_voice_id(name):
    voice = (name or "").strip()
    if voice.startswith(LOCAL_VOICE_PREFIX):
        return voice[len(LOCAL_VOICE_PREFIX) :]
    if voice.startswith("rhvoice:"):
        return voice[len("rhvoice:") :]
    return voice.lower()


def detect_engines():
    engines = []
    if edge_tts_bin():
        engines.append("edge-tts")
    if rhvoice_available():
        engines.append("rhvoice")
    return engines


def is_edge_voice(name):
    voice = (name or "").strip()
    if voice.startswith(EDGE_VOICE_PREFIX):
        return True
    return bool(re.match(r"^[a-z]{2}-[A-Z]{2}-.+Neural$", voice))


def edge_voice_id(name):
    voice = (name or "").strip()
    if voice.startswith(EDGE_VOICE_PREFIX):
        return voice[len(EDGE_VOICE_PREFIX) :]
    return voice


def classify_voice(name):
    lower = (name or "").lower()
    if is_edge_voice(name):
        return "edge-neural"
    if "rhvoice" in lower or lower.startswith("mateo"):
        return "neural"
    if lower.endswith("neural"):
        return "edge-neural"
    if "+" not in name:
        return "standard"
    variant = name.split("+")[-1].lower()
    if variant in {
        "klatt", "klatt2", "klatt3", "klatt4", "klatt5", "klatt6",
        "whisper", "whisperf", "female_whisper", "croak", "fast_test",
        "half-lifeannouncementsystem", "demonic", "robot", "universalrobot",
        "anikarobot", "anxiousandy", "mr_serious",
    }:
        return "special"
    return "variant"


def is_neural_voice_name(name):
    return classify_voice(name or "") in {"neural", "edge-neural"}


VOICE_GENDER_ES = {
    "mateo": "masculina",
    "carlos": "masculina",
    "tomas": "masculina",
    "seba": "masculina",
    "leticia": "femenina",
}


def voice_display_name(voice_id):
    key = (voice_id or "").lower()
    base = key.replace("-", " ").replace("_", " ").title()
    gender = VOICE_GENDER_ES.get(key)
    if gender:
        return f"{base} ({gender})"
    return base


def voice_lang_guess(voice_id):
    lower = (voice_id or "").lower()
    if lower in RHVOICE_LANG_BY_ID:
        return RHVOICE_LANG_BY_ID[lower]
    if re.match(r"^[a-z]{2}-", lower):
        return lower.split("-", 2)[0] + "-" + lower.split("-", 2)[1].upper()
    if lower in SPANISH_RHVOICE_IDS:
        return "es"
    return "en"


def lang_matches(voice_lang, requested_lang):
    req = (requested_lang or "es").lower().replace("_", "-")
    vlang = (voice_lang or "").lower().replace("_", "-")
    req_short = req.split("-")[0]
    vshort = vlang.split("-")[0]
    if req in vlang or vlang.startswith(req):
        return True
    if req_short == vshort:
        return True
    if req_short == "es" and vshort == "es":
        return True
    return False


def installed_rhvoice_ids():
    return {local_voice_id(v.get("voiceURI", "")) for v in discover_rhvoice_voices()}


def has_spanish_rhvoice():
    for voice_id in installed_rhvoice_ids():
        if voice_id in SPANISH_RHVOICE_IDS or voice_lang_guess(voice_id) == "es":
            return True
    return False


def pick_installed_spanish_voice():
    by_id = {
        local_voice_id(v.get("voiceURI", "")): v for v in discover_rhvoice_voices()
    }
    for prefer in ("mateo", "carlos", "tomas", "leticia", "spanish", "sp_es", "seba"):
        if prefer in by_id:
            return prefer
    for voice_id in by_id:
        if voice_id in SPANISH_RHVOICE_IDS or voice_lang_guess(voice_id) == "es":
            return voice_id
    return ""


def rhvoice_spanish_install_hint():
    return "sudo snap install rhvoice && sudo rhvoice.vm -i mateo"


def rhvoice_test_bin():
    return find_binary((
        "/var/lib/snapd/snap/bin/rhvoice.test",
        str(Path.home() / ".local/bin/rhvoice.test"),
        "rhvoice.test",
    ))


def narrador_cache_dir():
    cache = Path.home() / ".cache" / "narrador-youtube-tts"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def rhvoice_voice_in_snap(voice_id):
    voice_id = (voice_id or "").lower()
    if not voice_id:
        return False
    return (RHVOICE_SNAP_DATA / "voices" / voice_id).exists()


def rhvoice_voice_in_system(voice_id):
    voice_id = (voice_id or "").lower()
    if not voice_id:
        return False
    return (RHVOICE_SYSTEM_DATA / "voices" / voice_id).exists()


def should_use_rhvoice_snap_direct(voice_id):
    """Snap voices (Mateo) are invisible to Fedora's sd_rhvoice — synthesize directly."""
    voice_id = (voice_id or "").lower()
    if not voice_id or not rhvoice_test_bin():
        return False
    if not rhvoice_voice_in_snap(voice_id):
        return False
    if voice_id in SPANISH_RHVOICE_IDS or voice_lang_guess(voice_id) == "es":
        return True
    return not rhvoice_voice_in_system(voice_id)


def speak_rhvoice_snap_direct(text, voice_name, rate=1.0):
    global _play_tmp
    rh_bin = rhvoice_test_bin()
    if not rh_bin:
        return None

    cache = narrador_cache_dir()
    token = f"{os.getpid()}-{int(time.time() * 1000)}"
    in_path = cache / f"in-{token}.txt"
    out_path = cache / f"out-{token}.wav"

    try:
        in_path.write_text(text, encoding="utf-8")
        cmd = [rh_bin, "-p", voice_name, "-o", str(out_path), "-i", str(in_path)]
        cmd.extend(["-r", str(map_rhvoice_rate(rate))])

        gen_start = time.time()
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=120,
        )
        generate_ms = int((time.time() - gen_start) * 1000)

        if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size < 128:
            err = (proc.stderr or proc.stdout or "").strip()
            return {
                "ok": False,
                "error": err or "rhvoice snap synthesis failed",
                "engine": "rhvoice-snap",
            }

        stop_playback()
        _play_tmp = str(out_path)
        if not play_audio_file_async(str(out_path)):
            return {"ok": False, "error": "no audio player", "engine": "rhvoice-snap"}

        measured_ms = mp3_duration_ms(str(out_path))
        dur_ms = measured_ms or estimate_duration_ms(text, rate)
        play_ms = wait_playback_done(timeout_sec=max(30, dur_ms // 1000 + 20))
        actual_ms = play_ms or dur_ms
        return {
            "ok": True,
            "blocking": True,
            "durationMs": actual_ms,
            "generateMs": generate_ms,
            "engine": "rhvoice-snap",
        }
    finally:
        try:
            if in_path.is_file():
                in_path.unlink()
        except OSError:
            pass


def list_edge_voices(lang="es"):
    edge_bin = edge_tts_bin()
    if not edge_bin:
        return []

    try:
        proc = subprocess.run(
            [edge_bin, "--list-voices"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []

    if proc.returncode != 0:
        return []

    voices = []
    req = (lang or "es").replace("_", "-")
    req_short = req.split("-")[0].lower()

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Name") or line.startswith("-"):
            continue
        parts = re.split(r"\s{2,}", line)
        if not parts:
            parts = line.split()
        short_name = parts[0].strip()
        if not short_name.endswith("Neural"):
            continue
        locale = "-".join(short_name.split("-")[:2]).lower()
        if not locale.startswith(req_short + "-") and req_short not in locale:
            continue
        gender = parts[1].strip() if len(parts) > 1 else ""
        label = short_name
        if gender:
            label = f"{short_name} ({gender})"
        voices.append(
            {
                "name": f"Edge · {label}",
                "voiceURI": EDGE_VOICE_PREFIX + short_name,
                "lang": locale,
                "voiceType": "edge-neural",
                "neural": True,
            }
        )

    return voices


def discover_rhvoice_voices():
    found = {}
    voice_dirs = [
        RHVOICE_SNAP_DATA / "voices",
        RHVOICE_SYSTEM_DATA / "voices",
    ]

    installed_path = RHVOICE_SNAP_META / "installed.json"
    installed_ids = []
    if installed_path.is_file():
        try:
            installed_ids = list(json.loads(installed_path.read_text()).keys())
        except (json.JSONDecodeError, OSError):
            installed_ids = []

    candidates = set(installed_ids)
    for voice_dir in voice_dirs:
        if not voice_dir.is_dir():
            continue
        for entry in voice_dir.iterdir():
            if entry.name.startswith("."):
                continue
            candidates.add(entry.name.lower())

    for voice_id in sorted(candidates):
        if voice_id in {"english", "spanish", "russian", "ukrainian"}:
            continue
        in_snap = (RHVOICE_SNAP_DATA / "voices" / voice_id).exists()
        in_system = (RHVOICE_SYSTEM_DATA / "voices" / voice_id).exists()
        in_installed = voice_id in installed_ids
        if not (in_snap or in_system or in_installed):
            continue

        key = voice_id.lower()
        found[key] = {
            "name": f"RHVoice · {voice_display_name(voice_id)}",
            "voiceURI": LOCAL_VOICE_PREFIX + key,
            "lang": voice_lang_guess(voice_id),
            "voiceType": "local-neural",
            "neural": True,
        }

    return list(found.values())


def list_rhvoice_voices(lang="es"):
    if not shutil.which("spd-say"):
        return discover_rhvoice_voices()

    lang_short = (lang or "es").split("-")[0].lower()
    voices = []
    seen = set()

    try:
        rh_proc = subprocess.run(
            ["spd-say", "-L", "-o", "rhvoice"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        for line in rh_proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("NAME"):
                continue
            chunks = re.split(r"\s{2,}", line)
            if len(chunks) < 2:
                continue
            name = chunks[0].strip()
            if name in seen:
                continue
            seen.add(name)
            lang_col = chunks[1].strip().lower()
            name_lower = name.lower()
            is_spanish = (
                lang_short in lang_col
                or name_lower in SPANISH_RHVOICE_IDS
                or "spanish" in lang_col
                or "espa" in lang_col
            )
            if lang_short == "es" and not is_spanish:
                continue
            if lang_short != "es" and lang_short not in lang_col and name_lower not in RHVOICE_LANG_BY_ID:
                if RHVOICE_LANG_BY_ID.get(name_lower, "") != lang_short:
                    continue
            voices.append(
                {
                    "name": f"RHVoice · {name}",
                    "voiceURI": LOCAL_VOICE_PREFIX + name_lower,
                    "lang": lang_col or voice_lang_guess(name_lower),
                    "voiceType": "local-neural",
                    "neural": True,
                }
            )
    except (subprocess.TimeoutExpired, OSError):
        pass

    for voice in discover_rhvoice_voices():
        vid = local_voice_id(voice.get("voiceURI", ""))
        key = (voice.get("voiceURI") or "").lower()
        if key in seen:
            continue
        if lang_short == "es":
            if vid not in SPANISH_RHVOICE_IDS and not lang_matches(voice.get("lang", ""), lang):
                continue
        elif not lang_matches(voice.get("lang", ""), lang):
            continue
        seen.add(key)
        voices.append(voice)

    return voices


def pick_local_voice(lang="es"):
    lang_short = (lang or "es").split("-")[0].lower()
    installed = discover_rhvoice_voices()
    by_id = {local_voice_id(v.get("voiceURI", "")): v for v in installed}

    if lang_short == "es":
        for prefer in ("mateo", "carlos", "tomas", "leticia", "spanish"):
            if prefer in by_id:
                return by_id[prefer].get("voiceURI") or (LOCAL_VOICE_PREFIX + prefer)

    voices = list_rhvoice_voices(lang)
    if voices:
        return voices[0].get("voiceURI") or ""

    if lang_short == "es":
        return LOCAL_VOICE_PREFIX + "mateo"
    if by_id:
        return next(iter(by_id.values())).get("voiceURI") or (LOCAL_VOICE_PREFIX + "mateo")
    return LOCAL_VOICE_PREFIX + "mateo"


def list_voices(lang="es", engine="all"):
    eng = (engine or "all").lower()
    if eng == "edge":
        return list_edge_voices(lang)
    if eng in ("local", "rhvoice"):
        return list_rhvoice_voices(lang)
    return list_edge_voices(lang) + list_rhvoice_voices(lang)


def pick_neural_voice(lang="es"):
    voices = list_edge_voices(lang)
    if voices:
        return voices[0].get("voiceURI") or ""
    fallback = list_edge_voices("es")
    if fallback:
        return fallback[0].get("voiceURI") or ""
    return EDGE_VOICE_PREFIX + "es-ES-ElviraNeural"


def play_audio_file_async(path):
    global _play_proc
    ffplay = ffplay_bin()
    if ffplay:
        _play_proc = subprocess.Popen(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    if shutil.which("mpv"):
        _play_proc = subprocess.Popen(
            ["mpv", "--no-video", "--really-quiet", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    return False


def play_audio_file(path):
    ffplay = ffplay_bin()
    if ffplay:
        subprocess.run(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    if shutil.which("mpv"):
        subprocess.run(
            ["mpv", "--no-video", "--really-quiet", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    if shutil.which("edge-playback"):
        subprocess.run(
            ["edge-playback", "--write-media", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    return False


def mp3_duration_ms(path):
    ffprobe = find_binary(("ffprobe", "/usr/bin/ffprobe", "/usr/local/bin/ffprobe"))
    if not ffprobe:
        return 0
    try:
        proc = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return max(0, int(float(proc.stdout.strip()) * 1000))
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return 0


def speak_edge(text, voice, rate=1.0, pitch=1.0, volume=1.0):
    global _play_tmp
    voice_id = edge_voice_id(voice)
    edge_bin = edge_tts_bin()
    if not voice_id or not edge_bin:
        return {"ok": False, "error": "no edge voice"}

    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        gen_start = time.time()
        proc = subprocess.run(
            [
                edge_bin,
                "--voice",
                voice_id,
                f"--rate={map_edge_rate(rate)}",
                f"--volume={map_edge_volume(volume)}",
                f"--pitch={map_edge_pitch(pitch)}",
                "--text",
                text,
                "--write-media",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        generate_ms = int((time.time() - gen_start) * 1000)
        if proc.returncode != 0 or not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) < 128:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return {"ok": False, "error": proc.stderr.strip() or "edge-tts failed", "engine": "edge-tts"}

        stop_playback()
        _play_tmp = tmp_path
        if not play_audio_file_async(tmp_path):
            return {"ok": False, "error": "no audio player", "engine": "edge-tts"}
        measured_ms = mp3_duration_ms(tmp_path)
        dur_ms = measured_ms or estimate_duration_ms(text, rate)
        play_ms = wait_playback_done(timeout_sec=max(30, dur_ms // 1000 + 20))
        actual_ms = play_ms or dur_ms
        return {
            "ok": True,
            "blocking": True,
            "durationMs": actual_ms,
            "generateMs": generate_ms,
            "engine": "edge-tts",
        }
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def speak_rhvoice(text, lang="es", rate=1.0, pitch=1.0, volume=1.0, voice=""):
    lang_short = (lang or "es").split("-")[0]
    voice_name = local_voice_id(voice or "")
    if not voice_name:
        return {"ok": False, "error": "no rhvoice voice", "engine": "rhvoice"}

    installed = installed_rhvoice_ids()
    req_lang = (lang or "es").split("-")[0].lower()

    if voice_name not in installed:
        if req_lang == "es":
            fallback = pick_installed_spanish_voice()
            if fallback:
                voice_name = fallback
            else:
                return {
                    "ok": False,
                    "error": (
                        "Voz española RHVoice no instalada. "
                        f"Ejecuta: {rhvoice_spanish_install_hint()}"
                    ),
                    "engine": "rhvoice",
                }
        else:
            return {
                "ok": False,
                "error": f"Voz RHVoice «{voice_name}» no instalada",
                "engine": "rhvoice",
            }

    if voice_name in SPANISH_RHVOICE_IDS or voice_lang_guess(voice_name) == "es":
        lang_short = "es"

    if should_use_rhvoice_snap_direct(voice_name):
        direct = speak_rhvoice_snap_direct(text, voice_name, rate=rate)
        if direct is not None:
            return direct

    if not shutil.which("spd-say"):
        return {"ok": False, "error": "spd-say missing", "engine": "rhvoice"}

    cmd = [
        "spd-say",
        "-o",
        "rhvoice",
        "-l",
        lang_short,
        "-r",
        str(map_rate(rate)),
        "-p",
        str(map_pitch(pitch)),
        "-i",
        str(map_volume(volume)),
        "-y",
        voice_name,
        text,
    ]
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
    elapsed = int((time.time() - t0) * 1000)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        return {"ok": False, "error": err or "rhvoice failed", "engine": "rhvoice"}
    return {
        "ok": True,
        "blocking": True,
        "durationMs": max(elapsed, estimate_duration_ms(text, rate)),
        "generateMs": min(elapsed, 250),
        "engine": "rhvoice",
    }


def speak(text, lang="es", rate=1.0, pitch=1.0, volume=1.0, voice="", engine="edge"):
    if not text.strip():
        return {"ok": False}

    cancel_speech()
    rate = safe_float(rate, 1.0)
    pitch = safe_float(pitch, 1.0)
    volume = safe_float(volume, 1.0)

    engine = (engine or "edge").lower()
    voice_name = (voice or "").strip()

    if engine in ("local", "rhvoice") or is_local_voice(voice_name):
        if not rhvoice_available():
            return {"ok": False, "error": "RHVoice no instalado", "engine": "rhvoice"}
        if not is_local_voice(voice_name):
            voice_name = pick_local_voice(lang)
        return speak_rhvoice(text, lang, rate, pitch, volume, voice_name)

    if not edge_tts_bin():
        return {"ok": False, "error": "edge-tts not installed", "engine": "edge-tts"}

    if not is_edge_voice(voice_name):
        voice_name = pick_neural_voice(lang)

    return speak_edge(text, voice_name, rate, pitch, volume)


def create_silence_wav(path, duration_sec, sample_rate=22050, channels=1):
    import wave
    num_frames = int(duration_sec * sample_rate)
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b'\x00' * (num_frames * channels * 2))


def transcode_to_standard(input_path, output_path, sample_rate=22050, channels=1):
    cmd = [
        "ffmpeg", "-i", str(input_path),
        "-ar", str(sample_rate),
        "-ac", str(channels),
        "-y", str(output_path)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)


def download_translated_video_impl(video_id, voice, rate, volume, pitch, tts_engine, cues, audio_only=False, export_volume=0.0):
    out_dir = os.path.expanduser("~/Descargas")
    if not os.path.isdir(out_dir):
        out_dir = os.path.expanduser("~/Downloads")
    if not os.path.isdir(out_dir):
        out_dir = os.path.expanduser("~")

    temp_dir = os.path.join(out_dir, f"narrador_temp_{video_id}")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        # 1. Get title
        info_cmd = ["yt-dlp", "--get-title", f"https://www.youtube.com/watch?v={video_id}"]
        res = subprocess.run(info_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        title = res.stdout.strip()
        clean_title = "".join(c for c in title if c.isalnum() or c in "._- ()").strip()
        if not clean_title:
            clean_title = video_id

        # 2. Download video (only if not audio_only)
        video_temp_path = os.path.join(temp_dir, "original_video.mp4")
        if not audio_only:
            ytdl_cmd = [
                "yt-dlp",
                "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "-o", video_temp_path,
                "--no-playlist",
                f"https://www.youtube.com/watch?v={video_id}"
            ]
            subprocess.run(ytdl_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # 3. Generate audio files
        standard_cues = []
        current_time_ms = 0

        for idx, cue in enumerate(cues):
            start_ms = cue.get("startMs", 0)
            text = cue.get("text", "")
            if not text:
                continue

            gap_ms = start_ms - current_time_ms
            if gap_ms > 0:
                silence_file = os.path.join(temp_dir, f"silence_{idx}.wav")
                create_silence_wav(silence_file, gap_ms / 1000.0)
                standard_cues.append(silence_file)

            tmp_cue_raw = os.path.join(temp_dir, f"cue_{idx}_raw.wav" if "rhvoice" in tts_engine.lower() or "local" in tts_engine.lower() else f"cue_{idx}_raw.mp3")

            if "edge" in tts_engine.lower():
                voice_id = edge_voice_id(voice)
                edge_bin = edge_tts_bin()
                if not voice_id or not edge_bin:
                    raise Exception("Edge voice or binary not found")
                cmd = [
                    edge_bin,
                    "--voice", voice_id,
                    f"--rate={map_edge_rate(rate)}",
                    f"--volume={map_edge_volume(volume)}",
                    f"--pitch={map_edge_pitch(pitch)}",
                    "--text", text,
                    "--write-media", tmp_cue_raw
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
            else:
                voice_name = local_voice_id(voice or "") or "mateo"
                rh_bin = rhvoice_test_bin()
                if not rh_bin:
                    raise Exception("RHVoice binary not found")
                cache_dir = narrador_cache_dir()
                token = f"{os.getpid()}-{int(time.time() * 1000)}"
                in_path = cache_dir / f"in-{token}.txt"
                in_path.write_text(text, encoding="utf-8")
                try:
                    cmd = [rh_bin, "-p", voice_name, "-o", tmp_cue_raw, "-i", str(in_path)]
                    cmd.extend(["-r", str(map_rhvoice_rate(rate))])
                    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
                finally:
                    if in_path.is_file():
                        os.remove(in_path)

            tmp_cue_std = os.path.join(temp_dir, f"cue_{idx}_std.wav")
            transcode_to_standard(tmp_cue_raw, tmp_cue_std)

            dur_cmd = [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", tmp_cue_std
            ]
            dur_res = subprocess.run(dur_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            dur_sec = float(dur_res.stdout.strip())

            standard_cues.append(tmp_cue_std)
            current_time_ms = start_ms + int(dur_sec * 1000)

        if not standard_cues:
            raise Exception("No cues were synthesized")

        concat_list_path = os.path.join(temp_dir, "concat.txt")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for filepath in standard_cues:
                f.write(f"file '{filepath}'\n")

        narration_wav_path = os.path.join(temp_dir, "final_narration.wav")
        concat_cmd = [
            "ffmpeg", "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-ar", "22050", "-ac", "1",
            "-y", narration_wav_path
        ]
        subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if audio_only:
            final_audio_path = os.path.join(out_dir, f"{clean_title}.mp3")
            encode_cmd = [
                "ffmpeg", "-i", narration_wav_path,
                "-codec:a", "libmp3lame", "-qscale:a", "2",
                "-y", final_audio_path
            ]
            subprocess.run(encode_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return {"ok": True, "path": final_audio_path}

        audio_check_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1", video_temp_path
        ]
        audio_check_res = subprocess.run(audio_check_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        has_audio = "audio" in audio_check_res.stdout

        final_video_path = os.path.join(out_dir, f"{clean_title}.mp4")

        if has_audio:
            try:
                ev = float(export_volume)
            except (ValueError, TypeError):
                ev = 0.0

            if ev <= 0.001:
                # Omit original audio completely
                mix_cmd = [
                    "ffmpeg", "-i", video_temp_path, "-i", narration_wav_path,
                    "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac",
                    "-y", final_video_path
                ]
            else:
                mix_cmd = [
                    "ffmpeg", "-i", video_temp_path, "-i", narration_wav_path,
                    "-filter_complex", f"[0:a]volume={ev}[a0];[1:a]volume=1.0[a1];[a0][a1]amix=inputs=2:duration=first[a]",
                    "-map", "0:v", "-map", "[a]",
                    "-c:v", "copy", "-c:a", "aac",
                    "-y", final_video_path
                ]
        else:
            mix_cmd = [
                "ffmpeg", "-i", video_temp_path, "-i", narration_wav_path,
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-c:a", "aac",
                "-y", final_video_path
            ]
        subprocess.run(mix_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        return {"ok": True, "path": final_video_path}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        import shutil
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def detect_engine():
    engines = detect_engines()
    return engines[0] if engines else None


def main():
    while True:
        message = read_message()
        if message is None:
            break

        action = message.get("action")

        if action == "ping":
            engines = detect_engines()
            write_message({
                "ok": bool(engines),
                "engine": engines[0] if engines else None,
                "engines": engines,
                "rhvoiceSpanish": has_spanish_rhvoice(),
                "rhvoiceInstallHint": (
                    rhvoice_spanish_install_hint()
                    if "rhvoice" in engines and not has_spanish_rhvoice()
                    else ""
                ),
            })
        elif action == "list_voices":
            lang = message.get("lang", "es")
            engine = message.get("engine", "all")
            write_message({"ok": True, "voices": list_voices(lang, engine=engine)})
        elif action == "speak":
            result = speak(
                message.get("text", ""),
                message.get("lang", "es"),
                message.get("rate", 1.0),
                message.get("pitch", 1.0),
                message.get("volume", 1.0),
                message.get("voice", ""),
                message.get("engine", "edge"),
            )
            write_message(result if isinstance(result, dict) else {"ok": bool(result)})
        elif action == "download_translated_video":
            result = download_translated_video_impl(
                message.get("videoId", ""),
                message.get("voice", ""),
                message.get("rate", 1.0),
                message.get("volume", 1.0),
                message.get("pitch", 1.0),
                message.get("ttsEngine", "edge"),
                message.get("cues", []),
                audio_only=message.get("audioOnly", False),
                export_volume=message.get("exportVolume", 0.0)
            )
            write_message(result)
        elif action == "save_debug_html":
            html = message.get("html", "")
            try:
                debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_transcript.html")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(html)
                write_message({"ok": True, "path": debug_path})
            except Exception as e:
                write_message({"ok": False, "error": str(e)})
        else:
            write_message({"ok": False, "error": "unknown action"})


if __name__ == "__main__":
    main()
