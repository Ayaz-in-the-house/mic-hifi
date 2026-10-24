#!/usr/bin/env python3
"""Karakterlerin GERÇEK konuşmadaki duyulur etkisi (docs/PRD-QUALITY.md "A2.6a"). Referans kayıt ister; canlıya dokunmaz.

K1 Gövde +6 dB → 95–200 Hz orta banda (400–1000 Hz) göre ≥ +4 dB; 1–2,5 kHz orta banda göre ±0,7 dB   neden: sürgü, sesin enerjisinin olduğu yere etki etmeli
K2 beş ton karakteri: yükseklik eşitlenmiş en büyük bant farkı orta ≥ 3 dB, en güçlü ≥ 6 dB, yoğunlukla artar   neden: duyulur fark
K3 5 karakter × 4 yoğunluk: ses yüksekliği − nötr ±0,5 LU             neden: karakter tonu değiştirsin, yüksekliği değil
K4 her kazanç sürgüsü tek başına ±6 dB: ses yüksekliği ±0,7 LU         neden: telafi elle ayarda da çalışmalı
K5 Derin ve Radyo en güçlü + tavan, tüm kayıt: kırpılma 0, gerçek tepe ≤ −1 dBTP   neden: büyük alt artış tavanı zorlamamalı
K8 dolgunluk açık: 95–200 Hz zarf yayılması (p90 − p10) ≥ 3 dB daralır, güçlü heceler (p90) ±1 dB   neden: "tok" = alt bant daha sürekli, daha yüksek değil
K6 Derin: (95–400 Hz ort.) − (1–5 kHz ort.) orta ≥ 4 dB, en güçlü ≥ 8 dB   neden: "kalın, koyu"nun ölçüsü
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_characters.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import os, subprocess, sys

import numpy as np
from scipy.signal import butter, sosfilt

REF = os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not os.path.exists(REF):
    print("ATLANDI: referans kayıt yok:", REF); sys.exit(0)
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "tools"))
import audition, chain, loudness

SR = 48000
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


pre = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"mic-hifi-pretone-{os.getpid()}.npy")   # kişisel ses: tmpfs, okununca silinir
r = subprocess.run([sys.executable, os.path.join(here, "..", "tools", "chain_offline.py"), REF, "--preset", "normal", "--dump-before", "tone", pre], capture_output=True, text=True)
if not os.path.exists(pre):
    sys.exit(f"ton öncesi sinyal üretilemedi: {(r.stderr or r.stdout)[-400:]}")
full = np.load(pre).astype(np.float32); os.remove(pre)
seg = full[27 * SR:37 * SR]   # normal konuşma bölümü
BANDS = ((95, 200), (200, 400), (400, 1000), (1000, 2500), (2500, 5000), (5000, 10000))
bp = lambda x, lo, hi: 10 * np.log10((sosfilt(butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x) ** 2).mean() + 1e-20)
base = {**chain.DEFAULT_STATE, **chain.PRESETS["normal"]}
render = lambda patch, x=seg: audition.render(x, SR, {**base, **patch})
lufs = lambda y: loudness.measure(y, SR)["integrated"]
ref = render({}); L0 = lufs(ref); R = [bp(ref, lo, hi) for lo, hi in BANDS]
delta = lambda y: [bp(y, lo, hi) - r0 for (lo, hi), r0 in zip(BANDS, R)]

d1 = delta(render({"tone_low_db": 6}))
# Yükseklik telafisi tüm bandı birlikte kaydırır → etki ORTA banda göre ölçülür (telafiden bağımsız).
check("K1", d1[0] - d1[2] >= 4 and abs(d1[3] - d1[2]) <= 0.7, f"Gövde +6 dB → 95–200 Hz, orta banda göre {d1[0] - d1[2]:+.1f} dB (≥ +4) · 1–2,5 kHz orta banda göre {d1[3] - d1[2]:+.1f} dB (±0,7)")

TONAL = ("sicak", "parlak", "radyo", "derin", "yakin")
contrast, loud, k6 = {}, {}, {}
for ch in TONAL:
    for amt in chain.AMOUNTS:
        y = render(chain.scaled_character(ch, amt)); dl = lufs(y) - L0; d = delta(y)
        contrast[ch, amt], loud[ch, amt] = max(abs(v - dl) for v in d), dl
        if ch == "derin":
            k6[amt] = (d[0] + d[1]) / 2 - (d[3] + d[4]) / 2
weak = [f"{c} orta {contrast[c, 'orta']:.1f}" for c in TONAL if contrast[c, "orta"] < 3] + [f"{c} en güçlü {contrast[c, 'cok']:.1f}" for c in TONAL if contrast[c, "cok"] < 6]
order = [c for c in TONAL if not contrast[c, "hafif"] < contrast[c, "orta"] < contrast[c, "guclu"] < contrast[c, "cok"]]
check("K2", not weak and not order, "yükseklik eşitlenmiş en büyük bant farkı (orta / en güçlü): " + " · ".join(f"{c} {contrast[c, 'orta']:.1f}/{contrast[c, 'cok']:.1f}" for c in TONAL)
      + (f" · ZAYIF: {weak}" if weak else "") + (f" · sıra bozuk: {order}" if order else ""))
worst = max(loud.items(), key=lambda kv: abs(kv[1]))
check("K3", abs(worst[1]) <= 0.5, f"20 kombinasyonda ses yüksekliği farkı en çok {worst[1]:+.2f} LU ({worst[0][0]} {worst[0][1]}) (±0,5)")
gains = [k for _t, _f, k, _q in chain.TONE_BANDS if k]
single = {(k, g): lufs(render({k: g})) - L0 for k in gains for g in (6, -6)}
w4 = max(single.items(), key=lambda kv: abs(kv[1]))
check("K4", abs(w4[1]) <= 0.7, f"tek sürgü ±6 dB'de ses yüksekliği farkı en çok {w4[1]:+.2f} LU ({w4[0][0]} {w4[0][1]:+d}) (±0,7)")
k5 = []
for ch in ("derin", "radyo"):
    y = render(chain.scaled_character(ch, "cok"), full)
    k5.append((ch, int((np.abs(y) >= 0.999).sum()), loudness.measure(y, SR)["true_peak"]))
check("K5", all(c == 0 and tp <= -1.0 for _n, c, tp in k5), " · ".join(f"{n} en güçlü: kırpılan {c}, gerçek tepe {tp} dBTP" for n, c, tp in k5) + " (0 · ≤ −1)")
check("K6", k6["orta"] >= 4 and k6["cok"] >= 8, f"Derin alt − üst karşıtlığı: orta {k6['orta']:.1f} dB (≥ 4) · en güçlü {k6['cok']:.1f} dB (≥ 8)")

# K8: dolgunluk gerçek konuşmada alt bandı SÜREKLİ yapar (PRD-QUALITY A2.6b)
def env(x, lo, hi, n=2400, hop=480):
    """50 ms pencere, 10 ms adım. Ayrık (örtüşmesiz) 50 ms kareler 163 örnek veriyordu: yüzdelikler kare hizasına göre ±1 dB oynuyordu (ölçüldü)."""
    b = sosfilt(butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), x)
    return np.array([10 * np.log10((b[i:i + n] ** 2).mean() + 1e-18) for i in range(0, len(b) - n, hop)])


e0 = env(ref, 95, 200); voiced = e0 > -50 + (bp(ref, 95, 200) - bp(seg, 95, 200))
eb = env(render({"dyn_body_on": True, "dyn_body_db": 6}), 95, 200)
m = min(len(e0), len(eb)); e0v, ebv = e0[:m][voiced[:m]], eb[:m][voiced[:m]]
sp0, sp1 = np.percentile(e0v, 90) - np.percentile(e0v, 10), np.percentile(ebv, 90) - np.percentile(ebv, 10)
dp90 = np.percentile(ebv, 90) - np.percentile(e0v, 90)
check("K8", sp0 - sp1 >= 3 and abs(dp90) <= 1, f"dolgunluk: 95–200 Hz zarf yayılması {sp0:.1f} → {sp1:.1f} dB (≥ 3 dB daralır) · güçlü heceler (p90) {dp90:+.1f} dB (±1)")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
