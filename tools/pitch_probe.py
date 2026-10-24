#!/usr/bin/env python3
"""Perde kaydırıcı adaylarını GERÇEK konuşmada ölçer: gecikme, işlemci payı, perde (F0) kayması, ses yolu (spektral zarf) kayması, yükseklik.
Kullanım: pitch_probe.py [yarım ton ...]   (varsayılan −3)   · referans kaydın normal bölümü, ton katmanının girişi. Kişisel ses tmpfs'te kalır.
F0: 40 ms çerçevede özilinti tepesi (70–300 Hz), sesli çerçevelerin ortancası. Zarf kayması: 1/3 oktav yumuşatılmış uzun süreli spektrumun
log-frekansta çapraz ilintisi (yarım ton). Formant korunuyorsa zarf kayması ≈ 0, korunmuyorsa ≈ perde kayması."""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("pitch_probe.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import os, subprocess, sys, time

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
import chain, loudness
from ladspa_host import Plugin

SR = 48000
RB = os.path.expanduser("~/.local/lib/mic-hifi/ladspa-rubberband.so")
ENGINES = {"klasik (R2)": "rubberband-pitchshifter-mono", "ince (R3)": "rubberband-r3-pitchshifter-mono", "canlı": "rubberband-live-pitchshifter-mono"}


def segment():
    pre = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"mic-hifi-pp-{os.getpid()}.npy")
    subprocess.run([sys.executable, os.path.join(here, "chain_offline.py"), os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav"), "--preset", "normal", "--dump-before", "tone", pre], capture_output=True)
    y = np.load(pre).astype(np.float32); os.remove(pre)
    return y[27 * SR:37 * SR]


def f0(x):
    n, hop, out = 2880, 480, []
    for i in range(0, len(x) - n, hop):
        fr = x[i:i + n].astype(np.float64)
        if np.sqrt((fr ** 2).mean()) < 10 ** (-40 / 20):
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[n - 1:]
        lo, hi = SR // 300, SR // 50   # 50 Hz tabanı: −6 yarım tonda F0 (112 → 79 Hz) alt sınıra dayanıp ortancayı yukarı çekiyordu
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.45 * ac[0]:
            out.append(SR / k)
    return float(np.median(out)) if out else float("nan")


def envelope(x):
    P = np.abs(np.fft.rfft(x.astype(np.float64) * np.hanning(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / SR)
    grid = 200 * 2 ** (np.arange(0, 12 * 4.5 * 4) / 48)            # 200 Hz … ~4,5 kHz, 1/4 yarım ton adım
    return grid, np.array([10 * np.log10(P[(f >= g / 2 ** (1 / 6)) & (f < g * 2 ** (1 / 6))].mean() + 1e-30) for g in grid])


def env_shift(a, b):
    _g, ea = envelope(a); _g, eb = envelope(b)
    ea, eb = ea - ea.mean(), eb - eb.mean()
    best = max(range(-32, 33), key=lambda s: float(np.dot(ea[max(0, -s):len(ea) - max(0, s)], eb[max(0, s):len(eb) - max(0, -s)])) / (len(ea) - abs(s)))
    return best / 4.0


def run(label, semis, formant, x):
    ctl = {"Cents": 0.0, "Semitones": float(semis), "Octaves": 0.0, "Formant Preserving": float(formant), "Wet-Dry Mix": 0.0}
    if "r3" not in label and "live" not in label:
        ctl["Crispness"] = 3.0
    p = Plugin(RB, label, SR, ctl); t = time.time(); y = p.process(x); dt = time.time() - t; lat = int(p.outputs().get("latency") or 0); p.close()
    return y, lat, dt / (len(x) / SR)


if __name__ == "__main__":
    x = segment(); f_in = f0(x); L0 = loudness.measure(x, SR)["integrated"]
    print(f"giriş: F0 ortanca {f_in:.1f} Hz · {L0} LUFS")
    for semis in [float(a) for a in sys.argv[1:]] or [-3.0]:
        for name, label in ENGINES.items():
            for fp in (1, 0):
                y, lat, rtf = run(label, semis, fp, x)
                y2 = y[lat:] if lat < len(y) else y
                fo = f0(y2)
                print(f"{semis:+.0f} yt · {name:12} · formant koruma {'açık ' if fp else 'kapalı'}: gecikme {lat:5d} örnek ({lat / 48:5.1f} ms) · işlemci %{rtf * 100:4.1f} · "
                      f"perde {12 * np.log2(fo / f_in):+5.2f} yt · ses yolu {env_shift(x, y2[:len(x)]):+5.2f} yt · yükseklik {loudness.measure(y2, SR)['integrated'] - L0:+.1f} LU")
