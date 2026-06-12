# Narrador de libros

Lee **TXT, EPUB, PDF, Word (.doc/.docx), ODT y RTF** con el mismo motor que la extensión de YouTube (RHVoice / Edge).

## Requisitos

- Python 3
- Motor de voz: `../native/install-rhvoice.sh` y/o `../native/install-edge-tts.sh`
- Python: `pip install --user -r requirements.txt`
- Sistema (Fedora recomendado):
  ```bash
  sudo dnf install libreoffice-core poppler-utils
  sudo dnf install antiword   # opcional, mejora .doc antiguos
  ```

## Uso

```bash
cd "/home/joel/Documentos/Code APP/Narrador"

# Probar sin narrar (lista fragmentos)
python3 libro/narrador-libro.py mi-libro.epub --dry-run

# Narrar con Mateo (RHVoice)
python3 libro/narrador-libro.py mi-libro.epub --engine local --voice local:mateo

# Word / LibreOffice
python3 libro/narrador-libro.py informe.docx --engine local --voice local:mateo
python3 libro/narrador-libro.py tesis.doc --engine edge --voice edge:es-ES-ElviraNeural

# PDF (desde la página 10)
python3 libro/narrador-libro.py manual.pdf --from-chapter 10

# Narrar con voz femenina Edge
python3 libro/narrador-libro.py mi-libro.epub --engine edge --voice edge:es-ES-ElviraNeural

# Desde el capítulo 5, más lento
python3 libro/narrador-libro.py mi-libro.epub --from-chapter 5 --rate 0.9
```

Pulsa **Ctrl+C** para detener.

## Formatos

| Formato | Cómo se lee |
|---------|-------------|
| `.txt`  | Directo |
| `.epub` | ebooklib |
| `.pdf`  | PyMuPDF o `pdftotext` |
| `.docx` | python-docx (títulos y tablas) |
| `.doc`  | antiword o LibreOffice |
| `.odt` `.rtf` | LibreOffice |
| `.docm` | Como DOCX / LibreOffice |

### PDF escaneado (solo imagen)

Si el PDF es una foto o escaneo sin capa de texto, instala OCR antes, por ejemplo:

```bash
sudo dnf install ocrmypdf
ocrmypdf --language spa input.pdf output.pdf
python3 libro/narrador-libro.py output.pdf
```

## Atajo opcional

```bash
chmod +x libro/narrador-libro.py
ln -sf "$(pwd)/libro/narrador-libro.py" ~/.local/bin/narrador-libro
narrador-libro.py --help
```
