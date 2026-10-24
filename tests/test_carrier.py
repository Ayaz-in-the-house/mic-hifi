#!/usr/bin/env python3
"""V3 taşıyıcı — yalıtılmış PipeWire örneğinde (tests/iso.py), canlı grafiğe dokunmadan. Test noktaları: docs/research/O-*.md §11.

O01 yalıtılmış örnek ayağa kalkar; sahte mikrofona çalınan 1 kHz sahte çıkıştan aynı seviyede okunur; canlı grafiğin düğüm sayısı öncesi = içerideyken = sonrası;
    geride süreç ve dizin kalmaz
    neden: sonraki bütün taşıyıcı testlerinin zemini ve "canlı sese dokunmama" güvencesi
O03 mic-main ayağa kalkınca yakalama uçları kendiliğinden HİÇBİR ŞEYE bağlanmaz (kendi çıkışına da)
    neden: hedefsiz yakalama varsayılan kaynağa = kendi çıkışına bağlanır → geri besleme halkası
O02 yakalamanın iki kanalı ayrı kaynaklara elle bağlanır; karıştırıcı kazancı canlı değişir: (1, 0) → yalnız kuru (1 kHz), (0, 1) → yalnız ıslak (3 kHz)
    neden: taşıyıcının bütün güvenli-düşüş mantığı bu iki kazanca dayanır
O14 ıslak yol tavanı aşar (tepe +6 dBFS'e denk kazanç) → sanal mikrofonda tepe ≤ −1 dBFS + 0,2
    neden: model çıkışı taşabilir; limitleyici gerçekten en sonda mı
"""
import os, subprocess, sys, time, wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import carrier
from iso import Iso

SR = 48000
fails = []


RAN = [0]   # gerçek koşan nokta sayısı (elle yazılan toplam eskiyordu)


def check(tp, ok, d=""):
    RAN[0] += 1
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}")
    if not ok:
        fails.append(tp)


def live_nodes():
    return subprocess.run(["pw-cli", "ls", "Node"], capture_output=True, text=True).stdout.count("node.name")


def write_wav(path, x):
    w = wave.open(path, "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()


def read_wav(path):
    w = wave.open(path)
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768


db = lambda v: 20 * np.log10(v + 1e-12)

n0 = live_nodes()
with Iso() as iso:
    d = iso.dir
    iso.link("fake_mic:capture_FL", "fake_out:playback_MONO")
    src, rec = os.path.join(d, "in.wav"), os.path.join(d, "out.wav")
    write_wav(src, 0.3 * np.sin(2 * np.pi * 1000 * np.arange(SR * 2) / SR))
    r = iso.record("fake_out", rec, sink_monitor=True)
    time.sleep(0.3)
    iso.play(src, "fake_mic")
    time.sleep(0.4)
    r.terminate(); r.wait()
    y = read_wav(rec)
    act = y[np.abs(y) > 0.01]
    level = db(np.sqrt((act ** 2).mean())) if len(act) else -120.0
    n1 = live_nodes()
left = [p for p in iso.procs + [iso.server] if p.poll() is None]
n2 = live_nodes()
want = db(0.3 / np.sqrt(2))
check("O01", abs(level - want) <= 0.5 and len(act) > SR * 1.8 and n0 == n1 == n2 and not left and not os.path.exists(d),
      f"okunan {level:.1f} dBFS (beklenen {want:.1f} ±0,5) · süre {len(act) / SR:.2f} sn · canlı düğüm {n0}/{n1}/{n2} · artık süreç {len(left)} · dizin silindi {not os.path.exists(d)}")



def tone_level(y, f0):
    """f0 bileşeninin genliği (dBFS tepe), en yüksek 1 sn'lik pencerede."""
    if len(y) < SR:
        return -120.0
    best = -120.0
    for i in range(0, len(y) - SR + 1, SR // 4):
        Y = np.abs(np.fft.rfft(y[i:i + SR] * np.hanning(SR))) / (SR / 4)
        best = max(best, db(Y[f0 - 20:f0 + 20].max()))
    return best


def capture(iso, seconds, name):
    rec = os.path.join(iso.dir, name)
    r = iso.record(carrier.MAIN_OUT, rec)
    time.sleep(seconds)
    r.terminate(); r.wait()
    return read_wav(rec)


with Iso() as iso:
    conf = os.path.join(iso.dir, "mic-main.conf")
    open(conf, "w").write(carrier.render_main())
    iso.spawn("pipewire", "-c", conf)
    up = iso.wait_port(carrier.WET_PORT) and iso.wait_port(carrier.MAIN_OUT + ":capture_MONO")
    time.sleep(2.0)   # oturum yöneticisine bağlama fırsatı ver
    links = iso.out("pw-link", "-l")
    check("O03", up and "mic_main" not in links, f"mic-main portları {'var' if up else 'YOK'} · mic_main içeren bağ: {links.count('mic_main')}")

    iso.link("fake_mic:capture_FL", carrier.DRY_PORT, passive=True)
    iso.link("fake_wet:capture_FL", carrier.WET_PORT, passive=True)
    t = np.arange(SR * 30) / SR
    dry, wet = os.path.join(iso.dir, "dry.wav"), os.path.join(iso.dir, "wet.wav")
    write_wav(dry, 0.25 * np.sin(2 * np.pi * 1000 * t)); write_wav(wet, 0.25 * np.sin(2 * np.pi * 3000 * t))
    iso.play(dry, "fake_mic", wait=False); iso.play(wet, "fake_wet", wait=False)
    time.sleep(1.0)
    a = capture(iso, 2.5, "a.wav")
    r = iso.run("pw-cli", "set-param", carrier.MAIN_IN, "Props", carrier.mix_params(0.0, 1.0))
    time.sleep(0.5)
    b = capture(iso, 2.5, "b.wav")
    a1, a3, b1, b3 = tone_level(a, 1000), tone_level(a, 3000), tone_level(b, 1000), tone_level(b, 3000)
    check("O02", a1 > -14 and a3 < -60 and b3 > -14 and b1 < -60, f"(1,0): 1 kHz {a1:.1f} · 3 kHz {a3:.1f} dBFS — (0,1): 1 kHz {b1:.1f} · 3 kHz {b3:.1f} dBFS · set-param rc {r.returncode}")

    iso.run("pw-cli", "set-param", carrier.MAIN_IN, "Props", carrier.mix_params(0.0, 8.0))   # 0,25 × 8 = 2,0 → +6 dBFS
    time.sleep(0.5)
    c = capture(iso, 2.0, "c.wav")
    peak = db(np.abs(c).max()) if len(c) else 0.0
    check("O14", len(c) > SR and -4 < peak <= -0.8, f"taşan ıslak yol: sanal mikrofonda tepe {peak:.2f} dBFS (≤ −0,8)")

print(f"\n{'PASS' if not fails else 'FAIL'}: {RAN[0] - len(fails)}/{RAN[0]}")
sys.exit(1 if fails else 0)
