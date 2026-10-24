#!/usr/bin/env python3
"""Teslim ölçüleri (tools/loudness.py, tools/clicks.py) — PRD-QUALITY A1. Canlı grafiğe dokunmaz.

A1-T1 1 kHz sinüs, tepe −23 dBFS, TEK kanal → −26,0 ±0,1 LUFS
      neden: ITU-R BS.1770 tanımı gereği (ortalama kare = tepe² / 2 → −26,01 dB; 1 kHz'te K-ağırlık +0,69 dB, sabit −0,691).
      EBU Tech 3341'in "−23 LUFS" durumu aynı sinüsün İKİ kanalda olmasıdır (+3,01 dB). Ölçerimiz mono kaynağı tek kanal sayar.
A1-T2 bütünleşik yükseklik, üç farklı sinyalde ffmpeg `ebur128` ile (bağımsız ikinci uygulama) ≤ 0,2 LU fark
      neden: tek uygulamaya güvenmemek; K-ağırlık ve kapılama birlikte sınanır (sessizlik aralı sinyal kapıyı çalıştırır)
A1-T3 gerçek tepe: fs/4'te 45° fazlı sinüs → ANALİTİK değere (genlik) ±0,2 dB, örnek tepesinden 3,0 dB yüksek; ffmpeg ile ≤ 0,8 dB
      (ffmpeg bu sinyalde analitik değerin 0,6 dB üstünü okuyor — ölçüldü; birincil doğruluk kaynağı analitik değerdir)
      neden: −1 dBFS örnek tavanının gerçek tepesi ölçülmüyordu
A1-T3b sessizlik → yükseklik "ölçülemez" (None), çökme yok
A1-T4 tık sayacı: gürültüye yerleştirilmiş 20 tık → 18–22; tıksız gürültüde ≤ 1; yalnız konuşma benzeri kiplenmiş gürültüde ≤ 2
      neden: "pütür" teşhisinin temeli; kaçırma ve yanlış alarm ikisi de ölçülür
A1-T4b hece benzeri patlamaların keskin başlangıçları tık sayılmaz; söz ARALARINA konan tıklar sayılır
      neden: ilk sürüm gerçek konuşmada dakikada 540–1194 "tık" saydı (ünsüz patlamaları) — konuşmanın içinde tık ile ünsüz ayrılamıyor;
      film pratiği de tıkı önce söz aralarında arar (landscape/L6). Sayaç yalnız araları sayar ve ara süresine oranlar.
ffmpeg yoksa T2 ve T3'ün karşılaştırma kısmı ATLANIR (açıkça yazar).
"""
import os, re, shutil, subprocess, sys, tempfile, wave

import numpy as np
from scipy.signal import butter, sosfilt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import clicks, loudness

SR = 48000
fails, total = [], 0


def check(tp, ok, d=""):
    global total
    total += 1
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}")
    if not ok:
        fails.append(tp)


def ffmpeg_ebur128(x):
    """(bütünleşik LUFS, gerçek tepe dBTP) — ffmpeg'in özet satırlarından."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.wav")
    w = wave.open(p, "w"); w.setnchannels(1); w.setsampwidth(3); w.setframerate(SR)
    v = (np.clip(x, -1, 1) * (2 ** 23 - 1)).astype(np.int32)
    w.writeframes(b"".join(int(s).to_bytes(3, "little", signed=True) for s in v)); w.close()
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", p, "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    shutil.rmtree(d)
    tail = out[out.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    pk = re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return (float(i.group(1)) if i else None, float(pk.group(1)) if pk else None)


rng = np.random.default_rng(11)
t = np.arange(SR * 10) / SR
sine = 10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * t)
m = loudness.measure(sine, SR)
check("A1-T1", m["integrated"] is not None and abs(m["integrated"] + 26.0) <= 0.1, f"1 kHz tepe −23 dBFS tek kanal → {m['integrated']} LUFS (−26,0 ±0,1)")

pink = sosfilt(butter(1, 400, "lowpass", fs=SR, output="sos"), rng.standard_normal(SR * 12)); pink = 0.1 * pink / np.abs(pink).max()
gated = np.concatenate([0.2 * np.sin(2 * np.pi * 300 * t[:SR * 4]), np.zeros(SR * 4), 0.02 * rng.standard_normal(SR * 4)])   # yüksek · sessiz · alçak
voiceish = sosfilt(butter(2, [200, 4000], "bandpass", fs=SR, output="sos"), rng.standard_normal(SR * 12)) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * np.arange(SR * 12) / SR)) * 0.08
if shutil.which("ffmpeg"):
    diffs = []
    for name, x in (("pembe", pink), ("kapılı", gated), ("konuşma benzeri", voiceish)):
        a, (b, _pk) = loudness.measure(x, SR)["integrated"], ffmpeg_ebur128(x)
        diffs.append((name, a, b))
    check("A1-T2", all(a is not None and b is not None and abs(a - b) <= 0.2 for _n, a, b in diffs), " · ".join(f"{n}: {a} / ffmpeg {b}" for n, a, b in diffs))
else:
    print("ATLANDI  A1-T2  ffmpeg yok")

q = 0.5 * np.sin(2 * np.pi * (SR / 4) * t + np.pi / 4)
m = loudness.measure(q, SR)
gap = m["true_peak"] - m["sample_peak"]
ff = ffmpeg_ebur128(q)[1] if shutil.which("ffmpeg") else None
exact = 20 * np.log10(0.5)   # analitik gerçek tepe: sinüsün genliği
check("A1-T3", abs(gap - 3.01) <= 0.2 and abs(m["true_peak"] - exact) <= 0.2 and (ff is None or abs(m["true_peak"] - ff) <= 0.8),
      f"örnek tepe {m['sample_peak']} · gerçek tepe {m['true_peak']} dBTP (analitik {exact:.2f} ±0,2; örnek tepeden +{gap:.2f}) · ffmpeg {ff} (≤ 0,8 fark)")

m = loudness.measure(np.zeros(SR * 3), SR)
check("A1-T3b", m["integrated"] is None and m["true_peak"] is None, f"sessizlik → {m['integrated']}, {m['true_peak']}")

noise = sosfilt(butter(2, [150, 8000], "bandpass", fs=SR, output="sos"), rng.standard_normal(SR * 10)) * 0.02
clicky = noise.copy()
pos = np.linspace(SR * 0.5, SR * 9.5, 20).astype(int)
for p in pos:
    k = int(rng.integers(48, 144))                       # 1–3 ms
    clicky[p:p + k] += 0.02 * 4 * rng.standard_normal(k) * np.hanning(k)     # +12 dB geniş bantlı patlama
n_click, n_clean, n_voice = clicks.count(clicky, SR)["count"], clicks.count(noise, SR)["count"], clicks.count(voiceish, SR)["count"]
check("A1-T4", 18 <= n_click <= 22 and n_clean <= 1 and n_voice <= 2, f"20 tık → {n_click} (18–22) · tıksız gürültü → {n_clean} (≤ 1) · kiplenmiş gürültü → {n_voice} (≤ 2)")

# A1-T4b: hece benzeri patlamalar (150 ms açık / 150 ms kapalı, keskin başlangıçlı) — başlangıçlar tık SAYILMAMALI; aralara konan 10 tık sayılmalı
syl = np.zeros(SR * 10)
env = (np.arange(SR * 10) % int(0.3 * SR)) < int(0.15 * SR)
syl[env] = (sosfilt(butter(2, [200, 6000], "bandpass", fs=SR, output="sos"), rng.standard_normal(SR * 10)) * 0.1)[env]
syl += 0.001 * rng.standard_normal(SR * 10)                                    # taban
r0 = clicks.count(syl, SR)
gaps = (np.arange(10) * 0.9 + 0.225 + 0.3) * SR                                 # kapalı bölgelerin ortası
syl2 = syl.copy()
for p in gaps.astype(int):
    k = 96
    syl2[p:p + k] += 0.02 * rng.standard_normal(k) * np.hanning(k)
r1 = clicks.count(syl2, SR)
check("A1-T4b", r0["count"] <= 1 and 9 <= r1["count"] <= 11 and r1["pause_seconds"] > 0.5,   # 150 ms aralıklar: 50 ms pencere + 40 ms kenar kırpma sonrası aralık başına ~20 ms kalır
      f"hece başlangıçları → {r0['count']} (≤ 1) · aralara 10 tık → {r1['count']} (9–11) · ölçülen ara süresi {r1['pause_seconds']} sn")

print(f"\n{'PASS' if not fails else 'FAIL'}: {total - len(fails)}/{total}")
sys.exit(1 if fails else 0)
