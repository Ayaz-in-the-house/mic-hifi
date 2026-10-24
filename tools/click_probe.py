#!/usr/bin/env python3
"""T7 — canlı parametre değişimi tık üretir mi? EQ eklentisine sinüs verir, blok sınırında tek portu değiştirir (PipeWire'ın yaptığı gibi),
geçişteki en büyük ikinci farkı kararlı durumdakiyle oranlar. Saf sinüste ikinci fark sınırlıdır; oran ≈ 1 → süreksizlik yok.
"""
import os, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain
from ladspa_host import Plugin

SR, B = 48000, 1024
K = B * 46  # blok hizalı geçiş anı (girişte faz sıçraması olmasın)
CASES = [(3500, "Gain 5 (G)", chain.lin(6), "netlik 0 → +6 dB"), (120, "Gain 1 (G)", chain.lin(6), "gövde 0 → +6 dB"),
         (1000, "Gain 4 (G)", chain.lin(-9), "geniz 0 → −9 dB"), (200, "Frequency 0 (Hz)", 300.0, "alt kesim 20 → 300 Hz"),
         (3000, "Frequency 7 (Hz)", 3400.0, "üst kesim 22k → 3,4k"), (1000, "Bypass", 1.0, "aç → kapa (netlik +6 iken)")]


def main():
    t = np.arange(K * 3) / SR
    worst = 0.0
    for f0, port, val, label in CASES:
        x = (0.25 * np.sin(2 * np.pi * f0 * t)).astype(np.float32)
        st = {**chain.DEFAULT_STATE, "tone_pres_db": 6.0 if port == "Bypass" else 0}
        ctl = [n for n in chain.nodes(st) if n[0] == "tone"][0][5]
        p = Plugin(chain.LSP, chain.LSP_PREFIX + "para_equalizer_x8_mono", SR, ctl, block=B)
        a = p.process(x[:K])
        p.ctl[port].value = val
        b = p.process(x[K:])
        p.close()
        d2 = np.abs(np.diff(np.concatenate([a, b]), 2))
        steady = max(d2[K - 8192:K - 64].max(), d2[-8192:].max())   # geçiş öncesi ve sonrası kararlı durumun büyüğü
        ratio = d2[K - 8:K + 8192].max() / steady
        worst = max(worst, ratio)
        print(f"{label:28s} geçiş/kararlı ikinci fark oranı {ratio:6.2f}")
    print(f"en kötü oran: {worst:.2f}")
    return worst


if __name__ == "__main__":
    main()
