#!/usr/bin/env python3
"""Kayıtlı sesi iyileştirir (V4 çevrimdışı): MossFormer2_SE_48K, tasarlandığı 4 sn pencereyle. docs/PRD-VOICE.md "V4 çevrimdışı".

    <karantina>/v4env/bin/python tools/enhance.py <giriş> <çıkış.wav> [--device auto|cuda|cpu]      (kısayol: mic enhance <giriş> <çıkış.wav>)

Giriş: ffmpeg'in okuduğu her ses dosyası. Çıkış: 48 kHz tek kanal 16 bit WAV, izin 0600, giriş ile aynı süre ve zamanlama.
Sıra: alt kesim 95 Hz → sabit kazançla konuşma seviyesi → model → sabit kazançla hedef ses yüksekliği (gerçek tepe ≤ −1,5 dBTP).
Var olan dosyanın üstüne YAZMAZ. Ses bu makineden çıkmaz (model ve ağırlık yerel; ağ kullanılmaz).
"""
import argparse, os, subprocess, sys, wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import heavy_guard; heavy_guard.guard("enhance")   # ağır iş: tek sırada + nice 19 (D46)
SR, WINDOW, BLOCK = 48000, 4 * 48000, 3 * 48000
FORMATS = "wav,w64,aiff,caf,flac,mp3,ogg,aac,mov,matroska,amr,ac3"   # kabul edilen kaplar (ffmpeg ayrıştırıcı adları); betik/liste türleri YOK
MAX_LIMIT_SHARE = 2.0   # sürenin bu yüzdesinden fazlası 3 dB'den çok kısılıyorsa hedefe zorlanmaz (ezilmiş ses); ulaşılan seviye bildirilir
HPF_HZ, MODEL_LUFS, CEIL_DBTP = 95.0, -23.0, -1.5   # alt kesim canlı zincirle aynı (chain.HPF_HZ) · modele giren seviye · çıkış gerçek tepe tavanı


def die(msg, code=2):
    print(msg, file=sys.stderr)
    sys.exit(code)


def limit(y, ceil, look_ms=2.0, release_ms=80.0):
    """İleri bakışlı tepe sınırlayıcı (çevrimdışı): yalnız tavanı aşan tepeler kısılır, kırpma yok. Kazanç 0,5 ms'lik adımlarda hesaplanır:
    gereken kazancın ileri-geri en küçüğü (tepe gelmeden iner) → üstel bırakma → doğrusal ara değer. Tavanı aşan yoksa ses AYNEN döner."""
    import numpy as np
    from scipy.ndimage import minimum_filter1d
    if np.abs(y).max() <= ceil:
        return y, 0.0, 0.0
    hop = SR // 2000
    n = -(-len(y) // hop)
    pk = np.abs(np.pad(y, (0, n * hop - len(y)))).reshape(n, hop).max(1)
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-12))
    k = max(1, int(look_ms * 2))
    g = minimum_filter1d(need, size=2 * k + 1, mode="nearest")
    a = np.exp(-1.0 / (release_ms * 2))
    for i in range(1, n):                                       # bırakma: kazanç 1'e üstel döner, ama gerekenden yukarı çıkmaz
        g[i] = min(g[i], 1.0 - (1.0 - g[i - 1]) * a)
    g = minimum_filter1d(g, size=3, mode="nearest")             # ara değer komşu adımın tepesini aşmasın
    # dönen ölçüler: en derin kısma (dB) ve 3 dB'den çok kısılan sürenin payı (%) — "ne kadar ezildi" sorusunun cevabı
    return y * np.interp(np.arange(len(y)), np.arange(n) * hop + hop / 2, g), float(-20 * np.log10(g.min())), float((g < 10 ** (-3 / 20)).mean() * 100)


def main():
    a = argparse.ArgumentParser(description="Kayıtlı sesi yerelde iyileştirir (gürültü giderme).")
    a.add_argument("src"); a.add_argument("dst"); a.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    a.add_argument("--target-lufs", type=float, default=-16.0, help="çıkış ses yüksekliği (varsayılan −16 LUFS: yayın/sesli mesaj; görüşme −23)")
    o = a.parse_args()
    if not os.path.isfile(o.src):
        die(f"giriş dosyası yok: {o.src}")
    if os.path.exists(o.dst):
        die(f"çıkış dosyası zaten var, üstüne yazılmaz: {o.dst}")
    # Girdi YALNIZ kendisi okunur: yalnız yerel dosya protokolü ve yalnız gerçek ses kapları. Çalma listesi/birleştirme betiği kılığındaki bir dosya
    # başka dosyaları okutamaz, ağa çıkaramaz (ölçüldü: göreli adlı ffconcat betiği komşu dosyayı okuyordu; EN5).
    r = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-i", "file:" + os.path.abspath(o.src),
                        "-vn", "-sn", "-dn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if r.returncode or not r.stdout:
        die("giriş okunamadı: " + (r.stderr.decode(errors="replace").strip().splitlines() or ["ses akışı yok"])[-1][:200])
    import numpy as np
    import torch
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "heavy"))
    from models_v4 import MossFormer
    import loudness
    from scipy.signal import butter, sosfiltfilt
    x = np.frombuffer(r.stdout, dtype=np.float32).astype(np.float64)
    # Ön hazırlık (canlı zincirle aynı sıra): alt kesim → konuşma seviyesi → model. Model seviyeye duyarlı: ham (alçak) kayıtta sessiz taban yalnız
    # 6 dB düşüyordu (ölçüldü, EN1). Süzgeç sıfır fazlı (ileri-geri) → zamanlama kaymaz. Kazanç SABİT (kayıt boyunca tek sayı) → dinamik korunur.
    x = sosfiltfilt(butter(4, HPF_HZ, "highpass", fs=SR, output="sos"), x)
    lin = loudness.measure(x, SR)
    if lin["integrated"] is None:
        die("kayıtta ölçülebilir ses yok (tamamen sessiz)")
    g_in = min(MODEL_LUFS - lin["integrated"], -3.0 - lin["sample_peak"], 40.0)
    x = (x * 10 ** (g_in / 20)).astype(np.float32)
    dev = o.device if o.device != "auto" else ("cuda" if torch.cuda.is_available() else "cpu")
    model = MossFormer(BLOCK, WINDOW, dev)                       # yüklenemezse çıkış kodu 75 + ileti
    L = model.latency
    pad = (-(len(x) + L)) % BLOCK
    xp = np.concatenate((x, np.zeros(L + pad, np.float32)))      # sondaki sıfırlar: son örneklerin de pencerenin ortasına gelmesi için
    y = np.concatenate([model(xp[i:i + BLOCK]) for i in range(0, len(xp), BLOCK)])[L:L + len(x)].astype(np.float64)   # model çıkışı girişin L gerisinde
    mo = loudness.measure(y, SR)
    clean, gain = y, (o.target_lufs - mo["integrated"]) if mo["integrated"] is not None else 0.0
    for _ in range(4):                                           # sınırlayıcı ses yüksekliğini biraz düşürür → kazancı ölçerek düzelt (en çok 4 tur)
        y, red, share = limit(clean * 10 ** (gain / 20), 10 ** ((CEIL_DBTP - 0.5) / 20))   # 0,5 dB: örnekler arası tepe payı
        res = loudness.measure(y, SR)
        if res["integrated"] is None or abs(o.target_lufs - res["integrated"]) <= 0.3:
            break
        if share > MAX_LIMIT_SHARE:                              # hedefe ulaşmak sesi ezmeyi gerektiriyor → zorlanmaz, ulaşılan seviye bildirilir
            break
        gain += o.target_lufs - res["integrated"]
    if res["true_peak"] > CEIL_DBTP:                             # nadir: örnekler arası tepe payı yetmedi → sabit kazançla indir
        y = y * 10 ** ((CEIL_DBTP - res["true_peak"]) / 20); res = loudness.measure(y, SR)
    pcm = (np.clip(y, -1.0, 1.0) * 32767.0).round().astype("<i2")
    try:
        fd = os.open(o.dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as e:
        die(f"çıkış yazılamadı: {e}")
    try:
        with os.fdopen(fd, "wb") as f, wave.open(f, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
    except Exception as e:
        os.unlink(o.dst)
        die(f"çıkış yazılamadı: {e}")
    print(f"{o.dst}: {len(x) / SR:.1f} sn · aygıt {dev} · ses yüksekliği {lin['integrated']} → {res['integrated']} LUFS (hedef {o.target_lufs:g})"
          f" · gerçek tepe {res['true_peak']} dBTP · tepe kısma en çok {red:.1f} dB, sürenin %{share:.2f}'i 3 dB'den çok · sessiz taban {lin['floor']} → {res['floor']} dBFS")


if __name__ == "__main__":
    main()
