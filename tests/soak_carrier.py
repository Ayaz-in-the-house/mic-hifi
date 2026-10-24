#!/usr/bin/env python3
"""Taşıyıcı uzun koşu (docs/research/O §11: O06, O07) — yalıtılmış PipeWire'da işçi (sahte model) N dakika, işlemci yükü altında.

O06 yük altında N dk: işçinin xrun sayısı 0, kuruya düşüş 0                        neden: Python geri çağrısı yük altında blok kaçırıyor mu (tek süreç kararı)
O07 gecikme başta ve sonda aynı (± 1 kuantum) ve model payı (lead) eğimi ≈ 0        neden: "saat kayması yok" iddiası
Yük: çekirdeklerin yarısında boş döngü (normal öncelik). Kayıt yalnız başta ve sonda 6'şar sn (tmpfs'i doldurmamak için); arada durum dosyası örneklenir.
Ayrıca aynı sürede CANLI zincirin kesinti uyarıları sayılır (A0.8 için veri). Kullanım: soak_carrier.py [dakika=30] [yük süreci=çekirdek/2]
Bu bir kabul koşusudur, hızlı test değildir; makineyi yorar.
"""
import json, os, subprocess, sys, time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
src = open(os.path.join(HERE, "test_worker.py"), encoding="utf-8").read().split("\nt = np.arange(SR) / SR")[0]
__file__ = os.path.join(HERE, "test_worker.py")
exec(src)   # start_worker, measure, lag_between, check, Iso, SR, D …
from scipy.signal import chirp

MIN = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
NLOAD = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) // 2)
t = np.arange(SR) / SR
CHIRP = np.concatenate([np.zeros(SR // 2), 0.4 * chirp(t, 200, 1.0, 6000, method="logarithmic") * np.hanning(SR), np.zeros(SR)])
t_wall = time.strftime("%H:%M:%S")
with Iso() as iso:
    w, status = start_worker(iso)
    time.sleep(1.5)
    lag0 = lag_between(measure(iso, CHIRP, 0.3, "bas"))
    loads = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(NLOAD)]
    samples, t0 = [], time.time()
    try:
        while time.time() - t0 < MIN * 60:
            time.sleep(10)
            try:
                st = json.load(open(status))
                samples.append((time.time() - t0, st["lead_samples"], st["xruns"], st["fallback_count"], st["wet"]))
            except (OSError, ValueError):
                pass
            if w.poll() is not None:
                break
    finally:
        for l in loads:
            l.terminate()
        for l in loads:
            l.wait()
    alive = w.poll() is None
    time.sleep(1.0)
    lag1 = lag_between(measure(iso, CHIRP, 0.3, "son")) if alive else None
    st = json.load(open(status))
tt = np.array([s[0] for s in samples]); lead = np.array([s[1] for s in samples], float)
slope = float(np.polyfit(tt / 60, lead, 1)[0]) if len(tt) > 3 else float("nan")
live = subprocess.run(["journalctl", "--user", "-u", "mic-clean", "--since", t_wall, "--no-pager"], capture_output=True, text=True).stdout.count("Underrun")
dur = (samples[-1][0] / 60) if samples else 0
check("O06", alive and dur >= MIN * 0.95 and st["xruns"] == 0 and st["fallback_count"] == 0,
      f"{dur:.1f} dk, yük {NLOAD} süreç: işçi {'yaşıyor' if alive else 'ÖLDÜ'} · xrun {st['xruns']} (= 0) · kuruya düşüş {st['fallback_count']} (= 0) · ıslak {st['wet']}")
check("O07", lag1 is not None and abs(lag1 - lag0) <= 1024 and abs(slope) <= 5,
      f"gecikme başta {lag0}, sonda {lag1} örnek (fark ≤ 1024) · model payı eğimi {slope:+.2f} örnek/dk (|eğim| ≤ 5) · pay aralığı {lead.min():.0f}…{lead.max():.0f}")
print(f"      aynı sürede CANLI zincir kesinti uyarısı: {live}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {RAN[0] - len(fails)}/{RAN[0]}")
sys.exit(1 if fails else 0)
