#!/usr/bin/env python3
"""tools/chain.py'deki zinciri referans kayıt üzerinde çevrimdışı koşar ve bölüm bölüm ölçer.

Kullanım: chain_offline.py <ref.wav> [--preset normal|fisilti|gece|ham] [--character ad] [--out çıkış.wav] [--state anahtar=değer ...] [--set düğüm.Port=değer ...]
Bölümler (olcum.py protokolü): 2–10 sn sessizlik · 11–16 sn fısıltı · 27–37 sn normal konuşma.
"""
import os, sys, wave
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("chain_offline.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)

import numpy as np
from scipy.signal import butter, sosfilt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain
from ladspa_host import Plugin

SEG = {"sessiz": (2, 10), "fısıltı": (11, 16), "normal": (27, 37)}


def db(v):
    return 20 * np.log10(v + 1e-12)


def stats(y, sr):
    out = {}
    for k, (a, b) in SEG.items():
        s = y[int(a * sr):int(b * sr)].astype(np.float64)
        out[k] = (db(np.sqrt((s ** 2).mean())), db(np.abs(s).max()))
    return out


def main():
    a = sys.argv[1:]
    w = wave.open(a[0])
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())[:, 0].astype(np.float64) / 32768
    over = {}
    state = dict(chain.DEFAULT_STATE)
    if "--preset" in a:
        state.update(chain.PRESETS[a[a.index("--preset") + 1]])
    if "--character" in a:
        state.update(chain.CHARACTERS[a[a.index("--character") + 1]])
    for i, t in enumerate(a):
        if t == "--state":   # durum anahtarı: --state dyn_mud_on=true --state sat_db=12 (aralığa oturtulur)
            k, v = a[i + 1].split("=")
            state.update(chain.clamp({k: {"true": True, "false": False}.get(v.lower(), v) if v.lower() in ("true", "false") else float(v)}))
        if t == "--set":
            k, v = a[i + 1].split("=")
            n, p = k.split(".", 1)
            over.setdefault(n, {})[p] = float(v)
    y = sosfilt(butter(4, chain.HPF_HZ, "highpass", fs=sr, output="sos"), x).astype(np.float32)
    rows = [("ham", stats(x, sr)), ("hpf", stats(y, sr))]
    for name, so, label, _i, _o, ctl, rt in chain.nodes(state):
        if "--dump-before" in a and a[a.index("--dump-before") + 1] == name:
            np.save(a[a.index("--dump-before") + 2], y)
            return
        p = Plugin(so, label, sr, {**ctl, **over.get(name, {})}, realtime=rt)
        y = p.process(y)
        lat = p.outputs().get("latency")
        p.close()
        rows.append((name + (f" (+{lat / sr * 1000:.0f} ms)" if lat else ""), stats(y, sr)))
    print(f"{'aşama':>18} " + " ".join(f"{k + ' RMS/tepe':>18}" for k in SEG) + f" {'fıs-SNR':>8} {'fıs−normal':>10}")
    for n, s in rows:
        print(f"{n:>18} " + " ".join(f"{s[k][0]:9.1f} /{s[k][1]:6.1f}" for k in SEG)
              + f" {s['fısıltı'][0] - s['sessiz'][0]:8.1f} {s['fısıltı'][0] - s['normal'][0]:10.1f}")
    clip = int((np.abs(y) >= 0.999).sum())
    print(f"çıkışta kırpılan örnek: {clip}")
    if "--out" in a:
        o = wave.open(a[a.index("--out") + 1], "w")
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
        o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()); o.close()


if __name__ == "__main__":
    main()
