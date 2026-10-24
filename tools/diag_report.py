#!/usr/bin/env python3
"""Teşhis kayıtlarından ölçü çıkarır (şimdilik: oda payı). Ayar DEĞİŞTİRMEZ. docs/PRD-QUALITY.md "Oda payı denetimi".

    python3 tools/diag_report.py [<teşhis dizini>]      → JSON: {"room_lufs", "min_margin_db", "modes": {mod: {"threshold", "margin_db", "ok"}}}

Kural (ölçüldü, C5): modun sessizlik eşiği, alt kesimden sonraki oda gürültüsünün en az MIN_MARGIN dB üstünde olmalı; yoksa seviyeleyici sessizlikte
kazancı tırmandırır. Oda gürültüsü = "sessiz" kaydının alt kesimli, K ağırlıklı 400 ms'lik bloklarının ortancası (tek bir tıkırtı ölçüyü kaydırmasın).
"""
import json, os, sys, wave

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain, loudness

MIN_MARGIN = 5.0
MODES = ("normal", "fisilti", "gece")


def room_lufs(path):
    with wave.open(path) as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, ch)[:, 0].astype(np.float64) / 32768
    if len(x) < sr * 2 or not np.any(x):
        raise ValueError("kayıt çok kısa ya da tamamen sessiz")
    y = loudness.k_weight(sosfilt(butter(4, chain.HPF_HZ, "highpass", fs=sr, output="sos"), x)[sr // 2:], sr)   # ilk yarım saniye: süzgecin oturması
    n = int(sr * 0.4)
    z = (y[:len(y) // n * n].reshape(-1, n) ** 2).mean(1)
    return float(-0.691 + 10 * np.log10(np.median(z) + 1e-20))


def main():
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "mic-hifi", "diag")
    try:
        room = room_lufs(os.path.join(d, "sessiz.wav"))
    except (OSError, EOFError, ValueError, wave.Error) as e:
        print(f"oda kaydı ölçülemedi: {e}", file=sys.stderr)
        sys.exit(1)
    modes = {}
    for m in MODES:
        thr = float({**chain.DEFAULT_STATE, **chain.PRESETS[m]}["auto_silence"])
        modes[m] = {"threshold": thr, "margin_db": round(thr - room, 1), "ok": thr - room >= MIN_MARGIN}
    print(json.dumps({"room_lufs": round(room, 1), "min_margin_db": MIN_MARGIN, "modes": modes}, ensure_ascii=False))


if __name__ == "__main__":
    main()
