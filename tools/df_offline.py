#!/usr/bin/env python3
"""DeepFilterNet LADSPA eklentisini çevrimdışı koşar: referans kayıt → HPF → deep_filter_mono (çeşitli sınırlar).

Amaç: bastırıcının FISILTIYI ne kadar kıstığını ölçmek (literatürde ölçüm yok) ve canlı zincir için sınır seçmek.
Kullanım: df_offline.py <ref.wav> [--limits 6,12,18,24,100] [--pregain 0,20] [--out DİZİN]
Referans kayıt bölümleri (olcum.py protokolü): 2–10 sn sessizlik · 11–16 sn fısıltı · 27–37 sn normal konuşma.
"""
import ctypes as C, os, sys, time, wave

import numpy as np
from scipy.signal import butter, sosfilt

SO = os.path.expanduser("~/.local/lib/mic-hifi/libdeep_filter_ladspa.so")
SEG = {"sessiz": (2, 10), "fısıltı": (11, 16), "normal": (27, 37)}


class Hint(C.Structure):
    _fields_ = [("d", C.c_int), ("lo", C.c_float), ("hi", C.c_float)]


class Desc(C.Structure):
    pass


H = C.c_void_p
Desc._fields_ = [
    ("UniqueID", C.c_ulong), ("Label", C.c_char_p), ("Properties", C.c_int), ("Name", C.c_char_p),
    ("Maker", C.c_char_p), ("Copyright", C.c_char_p), ("PortCount", C.c_ulong),
    ("PortDescriptors", C.POINTER(C.c_int)), ("PortNames", C.POINTER(C.c_char_p)), ("PortRangeHints", C.POINTER(Hint)),
    ("ImplementationData", C.c_void_p),
    ("instantiate", C.CFUNCTYPE(H, C.POINTER(Desc), C.c_ulong)),
    ("connect_port", C.CFUNCTYPE(None, H, C.c_ulong, C.POINTER(C.c_float))),
    ("activate", C.CFUNCTYPE(None, H)),
    ("run", C.CFUNCTYPE(None, H, C.c_ulong)),
    ("run_adding", C.c_void_p), ("set_run_adding_gain", C.c_void_p),
    ("deactivate", C.CFUNCTYPE(None, H)),
    ("cleanup", C.CFUNCTYPE(None, H)),
]


def df_mono(x, sr, limit_db, block=480):
    """x: float32 mono. Dönüş: (çıkış, gerçek-zaman oranı). Eklenti iş parçacıklı; gerçek zaman temposunda beslenir."""
    lib = C.CDLL(SO)
    lib.ladspa_descriptor.restype = C.POINTER(Desc)
    lib.ladspa_descriptor.argtypes = [C.c_ulong]
    d = lib.ladspa_descriptor(0).contents
    assert d.Label == b"deep_filter_mono"
    h = d.instantiate(C.byref(d), sr)
    ctl = {2: limit_db, 3: -15.0, 4: 35.0, 5: 35.0, 6: 0.0, 7: 0.0}  # eklentinin kendi varsayılanları, sınır hariç
    keep = {p: C.c_float(v) for p, v in ctl.items()}
    for p, v in keep.items():
        d.connect_port(h, p, C.byref(v))
    ib, ob = (C.c_float * block)(), (C.c_float * block)()
    d.connect_port(h, 0, ib)
    d.connect_port(h, 1, ob)
    if d.activate:
        d.activate(h)
    y = np.zeros(len(x), dtype=np.float32)
    cpu0, t0 = time.process_time(), time.time()
    for i in range(0, len(x) - block + 1, block):
        C.memmove(ib, x[i:i + block].ctypes.data, block * 4)
        d.run(h, block)
        y[i:i + block] = np.frombuffer(ob, dtype=np.float32)
        # çalışan iş parçacığına gerçek zamanlı tempo ver (yoksa kuyruk taşar, çıktı sessiz kalır)
        ahead = (i + block) / sr - (time.time() - t0)
        if ahead > 0:
            time.sleep(ahead)
    cpu = time.process_time() - cpu0
    if d.deactivate:
        d.deactivate(h)
    d.cleanup(h)
    return y, cpu / (len(x) / sr)


def rms_db(s):
    return 20 * np.log10(np.sqrt((s.astype(np.float64) ** 2).mean()) + 1e-12)


def band_db(s, sr, lo, hi):
    n = 8192
    w = np.hanning(n)
    p = np.zeros(n // 2 + 1)
    k = 0
    for i in range(0, len(s) - n, n // 2):
        p += np.abs(np.fft.rfft(s[i:i + n] * w)) ** 2
        k += 1
    f = np.fft.rfftfreq(n, 1 / sr)
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(p[m].sum() / max(k, 1) + 1e-20)


def main():
    a = sys.argv[1:]
    ref = a[0]
    limits = [float(v) for v in (a[a.index("--limits") + 1] if "--limits" in a else "6,12,18,24,100").split(",")]
    outdir = a[a.index("--out") + 1] if "--out" in a else None
    w = wave.open(ref)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())[:, 0].astype(np.float64) / 32768
    hp = sosfilt(butter(4, 95, "highpass", fs=sr, output="sos"), x).astype(np.float32)
    seg = lambda y, k: y[int(SEG[k][0] * sr):int(SEG[k][1] * sr)]
    gains = [float(v) for v in (a[a.index("--pregain") + 1] if "--pregain" in a else "0").split(",")]
    rows = [("yalnız HPF", hp, 0.0)]
    for g in gains:  # ön kazanç: bastırıcıya girmeden yükselt, çıkışta geri al (model seviye duyarlı mı?)
        k = np.float32(10 ** (g / 20))
        for lim in limits:
            y, rtf = df_mono(hp * k, sr, lim)
            rows.append((f"DF {lim:g} dB" + (f" +{g:g}" if g else ""), y / k, rtf))
    base_w = band_db(seg(hp, "fısıltı"), sr, 500, 8000)
    base_n = band_db(seg(hp, "normal"), sr, 300, 8000)
    print(f"{'zincir':>18} {'sessiz':>8} {'fısıltı':>8} {'normal':>8} {'fıs-SNR':>8} {'fısıltı kaybı':>14} {'normal kaybı':>13} {'CPU':>6}")
    for name, y, rtf in rows:
        s, wh, n = (rms_db(seg(y, k)) for k in SEG)
        lw = band_db(seg(y, "fısıltı"), sr, 500, 8000) - base_w
        ln = band_db(seg(y, "normal"), sr, 300, 8000) - base_n
        print(f"{name:>18} {s:8.1f} {wh:8.1f} {n:8.1f} {wh - s:8.1f} {lw:11.1f} dB {ln:10.1f} dB {rtf * 100:5.1f}%")
        if outdir:
            os.makedirs(outdir, exist_ok=True)
            o = wave.open(os.path.join(outdir, name.replace(" ", "_") + ".wav"), "w")
            o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
            o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()); o.close()


if __name__ == "__main__":
    main()
