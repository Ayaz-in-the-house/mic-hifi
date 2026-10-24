#!/usr/bin/env python3
"""Ton yükseklik telafisi modelini üretir → tools/tone_model.json (chain.tone_trim_db kullanır). Ses içermez: yalnız eğriler ve ağırlıklar.

  bands   : her kazanç bandının ±6 ve ±12 dB'deki GERÇEK yanıtı (LSP EQ'dan darbe yanıtıyla ölçülür), 1/6 oktav ızgarada, dB
  weights : konuşmanın K ağırlıklı güç spektrumu, aynı ızgarada, toplamı 1
            kaynak: referans kaydın normal konuşma bölümü, ton katmanının girişinde (kullanıcının kendi sesi ve mikrofonu).
            Referans yoksa mevcut ağırlıklar korunur; hiç yoksa düz ağırlık yazılır (telafi kaba kalır).
Ton bantları (chain.TONE_BANDS) değişince YENİDEN ÇALIŞTIR; tests/test_characters.py K3–K4 modeli gerçek ölçümle sınar.
"""
import json, os, subprocess, sys

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import chain, loudness
from ladspa_host import Plugin

SR, N = 48000, 1 << 16
OUT = os.path.join(here, "tone_model.json")
REF = os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
GRID = [80 * 2 ** (i / 6) for i in range(46)]   # 80 Hz … 14,4 kHz
EDGES = [GRID[0] / 2 ** (1 / 12)] + [f * 2 ** (1 / 12) for f in GRID]


def response(patch):
    st = {**chain.DEFAULT_STATE, **patch}
    n = [q for q in chain.nodes(st) if q[0] == "tone"][0]
    ctl = {**n[5], "Output gain (G)": 1.0}
    x = np.zeros(N, np.float32); x[0] = 1.0
    p = Plugin(n[1], n[2], SR, ctl); h = p.process(x); p.close()
    H = 20 * np.log10(np.abs(np.fft.rfft(h.astype(np.float64))) + 1e-12)
    f = np.fft.rfftfreq(N, 1 / SR)
    return [float(np.interp(g, f, H)) for g in GRID]


def weights():
    pre = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"mic-hifi-model-{os.getpid()}.npy")
    subprocess.run([sys.executable, os.path.join(here, "chain_offline.py"), REF, "--preset", "normal", "--dump-before", "tone", pre], capture_output=True)
    y = np.load(pre); os.remove(pre)
    z = loudness.k_weight(y[27 * SR:37 * SR].astype(np.float64), SR)
    P = np.abs(np.fft.rfft(z)) ** 2
    f = np.fft.rfftfreq(len(z), 1 / SR)
    w = np.array([P[(f >= lo) & (f < hi)].sum() for lo, hi in zip(EDGES, EDGES[1:])])
    return (w / w.sum()).tolist()


def main():
    flat = response({})
    bands = {}
    for _t, _f, key, _q in chain.TONE_BANDS:
        if key:
            bands[key] = {str(g): [round(a - b, 3) for a, b in zip(response({key: g}), flat)] for g in (-12, -6, 6, 12)}
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    if os.path.exists(REF):
        w, src = [round(v, 6) for v in weights()], "referans kayıt, normal konuşma, ton girişi, K ağırlıklı"
    else:
        w, src = old.get("weights") or [round(1 / len(GRID), 6)] * len(GRID), old.get("weights_source") or "DÜZ (referans yok)"
    json.dump({"grid_hz": [round(g, 1) for g in GRID], "weights": w, "weights_source": src, "bands": bands,
               "tone_bands": [[t, f, k, q] for t, f, k, q in chain.TONE_BANDS]}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"yazıldı: {OUT} · {len(GRID)} nokta · {len(bands)} bant · ağırlık: {src}")


if __name__ == "__main__":
    main()
