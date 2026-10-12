#!/usr/bin/env bash
# Lanzador del Narrador de Libros y Audiolibros MP3
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$DIR/libro/narrador-gui.py" "$@"
