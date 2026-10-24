#!/usr/bin/env python3
"""Tık sayacı: kısa (≲ 6 ms), geniş bantlı, çevresinden ayrışan enerji patlamalarını sayar (ağız tıkı, dudak sesi, çıtırtı adayı).

  from clicks import count;  count(x, sr) -> {"count", "per_min", "times", "pause_seconds"}
YALNIZ SÖZ ARALARINI sayar: konuşmanın içinde ünsüz patlamaları (p/t/k, s) tıkla aynı imzayı taşır ve ayrılamaz (ölçüldü: gerçek konuşmada
dakikada 540–1194 yanlış sayım). Ara = 50 ms'lik düzeyin tabana 12 dB'den yakın olduğu, iki ucundan 40 ms kırpılmış bölge.
`per_min` ara süresine göredir (dakikalık ARA başına tık).
Yöntem: 2–12 kHz bandında 2 ms'lik çerçeve enerjisi; her çerçeve ±60 ms çevresinin ORTANCASIYLA karşılaştırılır (yavaş değişen konuşma
zarfı ortancayı da kaldırır → sayılmaz); eşiği aşan ve ≤ 6 ms süren, 12 ms içinde birleşen patlamalar birer tık sayılır.
Bu bir ADAY sayacıdır: p/t/k patlamaları ve klavye de sayılabilir. Eşikler sentetik sinyalle ayarlandı (tests/test_measure.py A1-T4);
gerçek ağız tıklarıyla kalibrasyon kullanıcı kaydı gerektirir (PRD-QUALITY A1.5).
"""
import numpy as np
from scipy.signal import butter, sosfilt

# Eşik ölçümle seçildi (2026-10-11): 6 dB → 20 sentetik tıktan 19'u, 120 sn tıksız gürültüde 0 yanlış alarm; 9 dB → 12/20.
FRAME_MS, AROUND_MS, MAX_MS, MERGE_MS, THRESH_DB = 2.0, 60.0, 6.0, 12.0, 6.0
PAUSE_ABOVE_FLOOR_DB = 12.0


def count(x, sr, thresh_db=THRESH_DB):
    x = np.asarray(x, np.float64)
    n = int(sr * FRAME_MS / 1000)
    if len(x) < n * 100:
        return {"count": 0, "per_min": None, "times": [], "pause_seconds": 0.0}
    y = sosfilt(butter(4, [2000, min(12000, sr / 2 - 500)], "bandpass", fs=sr, output="sos"), x)
    h = n // 2
    c = np.concatenate(([0.0], np.cumsum(y * y)))
    idx = np.arange(0, len(y) - n + 1, h)
    e = 10 * np.log10((c[idx + n] - c[idx]) / n + 1e-14)
    k = int(AROUND_MS / (FRAME_MS / 2))
    pad = np.pad(e, k, mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * k + 1)
    med = np.median(win, axis=1)
    hot = e > med + thresh_db
    times, i, m = [], 0, len(hot)
    hop_s = h / sr
    while i < m:
        if not hot[i]:
            i += 1
            continue
        j = i
        while j + 1 < m and hot[j + 1]:
            j += 1
        if (j - i + 1) * hop_s * 1000 <= MAX_MS + FRAME_MS:        # kısa patlama → tık adayı (uzunsa konuşma/hece başlangıcı)
            t = i * hop_s
            if not times or t - times[-1] > MERGE_MS / 1000:
                times.append(round(t, 3))
        i = j + 1
    # söz araları: geniş bant 50 ms düzeyi tabana yakın olan çerçeveler; kenarlardan 40 ms kırp (hece başı/sonu ara sayılmasın)
    w = int(0.05 * sr)
    cx = np.concatenate(([0.0], np.cumsum(x * x)))
    centers = np.clip(idx + n // 2, w // 2, len(x) - w // 2 - 1)
    lev = 10 * np.log10((cx[centers + w // 2] - cx[centers - w // 2]) / w + 1e-14)
    floor = np.percentile(lev, 10)
    pause = lev < floor + PAUSE_ABOVE_FLOOR_DB
    er = int(0.04 / hop_s)
    if er:
        pause = np.convolve(pause.astype(np.int8), np.ones(2 * er + 1, dtype=np.int8), "same") == 2 * er + 1
    keep = [t for t in times if pause[min(m - 1, int(round(t / hop_s)))]]
    psec = float(pause.sum() * hop_s)
    return {"count": len(keep), "per_min": round(60 * len(keep) / psec, 1) if psec >= 1.0 else None, "times": keep, "pause_seconds": round(psec, 2)}


if __name__ == "__main__":
    import sys
    from loudness import read_wav
    x, sr = read_wav(sys.argv[1])
    r = count(x, sr)
    print(f"söz aralarında tık adayı: {r['count']} ({r['per_min']}/dk ara; ölçülen ara {r['pause_seconds']} sn)")
