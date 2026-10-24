#!/usr/bin/env python3
"""Teslim ölçüleri: ses yüksekliği (ITU-R BS.1770-4 / EBU R 128), yükseklik aralığı (EBU Tech 3342) ve gerçek tepe (4× örnekleme).

  from loudness import measure;  measure(x, sr) -> {"integrated", "short_max", "lra", "sample_peak", "true_peak", "floor", "seconds"}
  loudness.py <dosya.wav>          # aynı sonuçları yazdırır
Mono sinyal TEK kanal sayılır (aynı sinüs iki kanalda olsaydı sonuç 3,01 LU yüksek çıkardı). Ölçülemeyen değer None'dır (sessizlik).
Doğrulama: tests/test_measure.py (analitik sinüs + ffmpeg `ebur128` ile karşılaştırma).
"""
import math, sys, wave

import numpy as np
from scipy.signal import lfilter, resample_poly

ABS_GATE = -70.0


def k_weight(x, sr):
    """BS.1770 K-ağırlık: üst raf (+4 dB, 1682 Hz) + yüksek geçiren (38 Hz). Katsayılar örnekleme hızına göre hesaplanır."""
    k = math.tan(math.pi * 1681.974450955533 / sr); q = 0.7071752369554196
    vh = 10 ** (3.999843853973347 / 20); vb = vh ** 0.4996667741545416
    a0 = 1 + k / q + k * k
    x = lfilter([(vh + vb * k / q + k * k) / a0, 2 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0], [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0], x)
    k = math.tan(math.pi * 38.13547087602444 / sr); q = 0.5003270373238773
    a0 = 1 + k / q + k * k
    return lfilter([1.0, -2.0, 1.0], [1, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0], x)


def _blocks(y, sr, win, hop):
    n, h = int(win * sr), int(hop * sr)
    if len(y) < n:
        return np.array([])
    c = np.concatenate(([0.0], np.cumsum(y * y)))
    idx = np.arange(0, len(y) - n + 1, h)
    return (c[idx + n] - c[idx]) / n


def _lufs(z):
    return -0.691 + 10 * np.log10(z)


def measure(x, sr):
    x = np.asarray(x, np.float64)
    out = {"seconds": round(len(x) / sr, 2), "integrated": None, "short_max": None, "lra": None, "sample_peak": None, "true_peak": None, "floor": None}
    if len(x) == 0 or not np.any(x):
        return out
    y = k_weight(x, sr)
    z = _blocks(y, sr, 0.4, 0.1)                                   # 400 ms, %75 örtüşme
    z = z[z > 0]
    keep = z[_lufs(z) > ABS_GATE] if len(z) else z
    if len(keep):
        rel = _lufs(keep.mean()) - 10.0                            # göreli kapı: mutlak kapıyı geçenlerin ortalamasının 10 LU altı
        g = keep[_lufs(keep) > rel]
        if len(g):
            out["integrated"] = round(float(_lufs(g.mean())), 2)
    s = _blocks(y, sr, 3.0, 1.0)                                   # kısa süreli: 3 sn pencere
    s = s[s > 0]
    if len(s):
        sl = _lufs(s)
        out["short_max"] = round(float(sl.max()), 2)
        a = s[sl > ABS_GATE]
        if len(a):
            b = _lufs(a[_lufs(a) > _lufs(a.mean()) - 20.0])        # yükseklik aralığı kapısı: −20 LU
            if len(b) >= 2:
                out["lra"] = round(float(np.percentile(b, 95) - np.percentile(b, 10)), 2)
    out["sample_peak"] = round(float(20 * np.log10(np.abs(x).max())), 2)
    out["true_peak"] = round(float(20 * np.log10(np.abs(resample_poly(x, 4, 1)).max())), 2)
    m = _blocks(x, sr, 0.4, 0.1)
    m = m[m > 0]
    if len(m):
        out["floor"] = round(float(10 * np.log10(np.percentile(m, 10))), 2)   # en sessiz %10'luk dilim, dBFS (ağırlıksız)
    return out


def read_wav(path):
    w = wave.open(path)
    sw, ch = w.getsampwidth(), w.getnchannels()
    raw = w.readframes(w.getnframes())
    if sw == 2:
        x = np.frombuffer(raw, dtype=np.int16).astype(np.float64) / 32768
    elif sw == 3:
        b = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        x = np.where(v >= 1 << 23, v - (1 << 24), v).astype(np.float64) / (1 << 23)
    else:
        raise ValueError("yalnız 16/24 bit")
    return x.reshape(-1, ch)[:, 0], w.getframerate()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    x, sr = read_wav(sys.argv[1])
    for k, v in measure(x, sr).items():
        print(f"{k:12} {v}")
