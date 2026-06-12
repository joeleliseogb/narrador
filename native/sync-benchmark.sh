#!/usr/bin/env bash
# Mide cuánto tarda realmente tu voz en narrar (ejecutar en tu PC, no en sandbox).
TEXT='está eh Rusia, eh, perdón, aquí Rusia, eh China y Estados Unidos.'
echo "Texto: ${#TEXT} caracteres"
echo

if command -v espeak-ng >/dev/null; then
  for rate in 1.0 1.5 2.0 2.5 3.0; do
  wpm=$(python3 -c "print(int(175*$rate))")
  start=$(date +%s.%N)
  espeak-ng -v es -s "$wpm" "$TEXT" >/dev/null 2>&1
  end=$(date +%s.%N)
  python3 -c "print(f'espeak-ng rate={rate}: {float('$end')-float('$start'):.2f}s')"
  done
fi

echo
if command -v spd-say >/dev/null; then
  echo "spd-say encola el audio y vuelve al instante (no bloquea)."
  echo "Por eso la extensión v2.9+ usa espeak-ng para sincronizar."
  spd-say -l es "$TEXT" &
  sleep 0.2
  echo "spd-say pid=$! (probablemente sigue hablando en segundo plano)"
fi
