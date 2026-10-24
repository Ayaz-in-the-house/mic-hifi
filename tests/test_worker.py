#!/usr/bin/env python3
"""V3 ağır işçi (heavy/worker.py) — sahte modelle, yalıtılmış PipeWire örneğinde. Test noktaları: docs/research/O-*.md §11.

O04 sahte model (kimlik), D = 300 ms: çıtırtının (chirp) işçi çıkışı ile doğrudan yol arasındaki gecikmesi
    beklenen: D ± 1 kuantum (1024 örnek), 3 ölçümde aynı örnek · ıslak ağırlığı 1 · düşüş 0
    neden: gecikme sabit ve beyan edilen değerle aynı olmalı (görüntü senkronu, ölçüm, hizalı yedek buna dayanır)
O05 sahte model blokların %15'inde blok süresinin 3 katı geç kalır
    beklenen: düşüş sayısı > 0 VE çıkış = girişin D gecikmişi (artık ≤ −50 dB), sıfır-örnek koşusu yok
    neden: "model geç kalınca ses kesilmez, tekrar etmez, kaymaz" iddiasının kendisi (bugünkü ses kesintisinin karşılığı)
O04b sahte model + latency 3000 örnek (ileri bakışlı model): gecikme latency'siz ölçümle aynı, artık ≤ −50 dB
    neden: pencere kenarını atan gerçek model çıktıyı geride verir; işçi bunu bilmezse ıslak/kuru hizası kayar
O17 model yüklenirken (sahte model, --load-delay 5): işçi ≤ 1 sn'de hazır; çıkış = girişin D gecikmişi, KURU (kazanç 1,0); yükleme bitince ıslak (kazanç 0,5), gecikme aynı
    neden: gözcü işçiye hemen geçebilsin → açılıştaki zaman sıçraması başa çekilsin; yükleme sırasında da sözleşme geçerli
O18 model yüklenemezse (iş parçacığında çıkış 75) süreç ≤ 3 sn'de çıkış kodu 75 ile biter      neden: gözcünün "kaynak yok" kilidi buna bağlı
O08a işçiye SIGKILL: yalıtılmış grafikte sahte mikrofon ve sahte çıkış düğümleri yaşamaya devam eder, işçinin portları kaybolur
    neden: işçi ölümü grafiği bozmamalı (kuruya geçiş gözcünün işi — O08b, gözcüyle birlikte)
Ortam yoksa (heavy/.venv) testler ATLANIR ve nasıl kurulacağını söyler.
"""
import json, os, signal, subprocess, sys, time, wave

import numpy as np
from scipy.signal import chirp, correlate

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from iso import Iso

ROOT = os.path.dirname(HERE)
PY = os.path.join(ROOT, "heavy", ".venv", "bin", "python")
WORKER = os.path.join(ROOT, "heavy", "worker.py")
SR, D_MS = 48000, 300.0
D = int(D_MS * SR / 1000)
if not os.path.exists(PY):
    print("ATLANDI: heavy/.venv yok → cd heavy && uv sync --frozen"); sys.exit(0)
fails = []


RAN = [0]   # gerçek koşan nokta sayısı (elle yazılan toplam eskiyordu)


def check(tp, ok, d=""):
    RAN[0] += 1
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}")
    if not ok:
        fails.append(tp)


def write_wav(path, x):
    w = wave.open(path, "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()


def read2(path):
    w = wave.open(path)
    y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
    return y.reshape(-1, 2)


def start_worker(iso, *extra):
    status = os.path.join(iso.dir, "heavy.json")
    p = iso.spawn("pw-jack", PY, WORKER, "--delay-ms", str(D_MS), "--block", "4800", "--status", status, *extra, stdout=subprocess.PIPE, text=True)
    line = p.stdout.readline().strip()
    if line != "READY" or not iso.wait_port("mic_heavy:out", 5):
        raise RuntimeError(f"işçi hazır olmadı: {line!r}")
    iso.link("fake_mic:capture_FL", "mic_heavy:in_model")
    iso.link("fake_mic:capture_FL", "mic_heavy:in_dry")
    return p, status


def lag_between(y):
    """Kanal 1'in kanal 0'a göre gecikmesi (örnek)."""
    a, b = y[:, 0], y[:, 1]
    return int(np.argmax(correlate(b, a, "full"))) - (len(a) - 1)


def measure(iso, sig, seconds, name):
    src, rec = os.path.join(iso.dir, name + "-in.wav"), os.path.join(iso.dir, name + "-out.wav")
    write_wav(src, sig)
    r = iso.record2("fake_mic:capture_FL", "mic_heavy:out", rec, name="rec_" + name)
    time.sleep(0.3)
    iso.play(src, "fake_mic", wait=True)
    time.sleep(seconds)
    r.terminate(); r.wait()
    return read2(rec)


t = np.arange(SR) / SR
CHIRP = np.concatenate([np.zeros(SR // 2), 0.4 * chirp(t, 200, 1.0, 6000, method="logarithmic") * np.hanning(SR), np.zeros(SR)])

with Iso() as iso:
    w, status = start_worker(iso)
    time.sleep(1.5)   # ıslağa oturma (histerezis)
    lags = [lag_between(measure(iso, CHIRP, 0.3, f"c{i}")) for i in range(3)]
    st = json.load(open(status))
    check("O04", all(abs(l - D) <= 1024 for l in lags) and len(set(lags)) == 1 and st["wet"] == 1.0 and st["fallback_count"] == 0,
          f"ölçülen gecikme {lags} örnek (beyan {D} ± 1024) · ıslak {st['wet']} · düşüş {st['fallback_count']} · xrun {st['xruns']}")
    base = lags[0]

    w.send_signal(signal.SIGKILL); w.wait()
    time.sleep(1.0)
    ports = iso.out("pw-link", "-io")
    check("O08a", "mic_heavy" not in ports and iso.state("fake_mic") != "" and iso.state("fake_out") != "" and iso.server.poll() is None,
          f"işçi portu kaldı mı: {'mic_heavy' in ports} · fake_mic {iso.state('fake_mic')} · fake_out {iso.state('fake_out')}")

with Iso() as iso:   # O04b: ileri bakışlı model (çıktısı latency kadar geride) hizayı bozmaz
    w, status = start_worker(iso, "--latency-samples", "3000", "--gain", "0.5")   # kazanç 0,5: ölçülen ses ISLAK yoldan mı geliyor, ayırt edilsin
    time.sleep(1.5)
    yb = measure(iso, CHIRP, 0.3, "la")
    lag_b = lag_between(yb)
    a_, b_ = yb[:, 0], yb[:, 1]
    seg_ = slice(SR // 2, SR // 2 + SR)
    res_b = 20 * np.log10(np.sqrt(((b_[seg_.start + lag_b:seg_.stop + lag_b] - 0.5 * a_[seg_]) ** 2).mean()) / np.sqrt(((0.5 * a_[seg_]) ** 2).mean()) + 1e-12)
    stb = json.load(open(status))
    check("O04b", lag_b == base and res_b <= -50 and stb["wet"] == 1.0 and stb["fallback_count"] == 0,
          f"latency 3000 örnekli model: gecikme {lag_b} (= {base}) · artık {res_b:.1f} dB (≤ −50) · ıslak {stb['wet']} · düşüş {stb['fallback_count']}")

with Iso() as iso:
    w, status = start_worker(iso, "--late-prob", "0.15", "--late-factor", "3")
    time.sleep(1.5)
    n = SR * 12
    from scipy.signal import butter, sosfilt
    noise = sosfilt(butter(4, [150, 6000], "bandpass", fs=SR, output="sos"), np.random.default_rng(5).standard_normal(n))
    sig = 0.2 * noise / np.abs(noise).max() * 3   # dönemsiz sinyal: kayma/tekrar/atlama çapraz korelasyonda ve artıkta görünür (sinüs yanıltır)
    sig = np.clip(sig, -0.9, 0.9)
    y = measure(iso, sig, 0.6, "late")
    st = json.load(open(status))
    a, b = y[:, 0], y[:, 1]
    lag = lag_between(y[SR:SR * 4])
    seg = slice(SR * 2, SR * 10)
    ref, out = a[seg], b[seg.start + lag:seg.stop + lag]
    resid = 20 * np.log10(np.sqrt(((out - ref) ** 2).mean()) / np.sqrt((ref ** 2).mean()) + 1e-12)
    z = (np.abs(out) < 1e-4).astype(int)
    run = max((len(r) for r in "".join(map(str, z)).split("0")), default=0)   # en uzun sıfır koşusu
    check("O05", st["fallback_count"] > 0 and resid <= -50 and run < 48 and lag == base,
          f"düşüş {st['fallback_count']} · kuru çalınan {st['dry_ms']:.0f} ms · artık {resid:.1f} dB (≤ −50) · en uzun sıfır koşusu {run} örnek · gecikme {lag} (= {base})")

with Iso() as iso:   # O17: model arkada yüklenirken işçi hizalı kuru verir
    def ratio(y, lag):
        a_, b_ = y[:, 0], y[:, 1]; sg = slice(SR // 2, SR // 2 + SR)
        return float(np.sqrt((b_[sg.start + lag:sg.stop + lag] ** 2).mean()) / np.sqrt((a_[sg] ** 2).mean()))
    t0 = time.time()
    try:
        w, status = start_worker(iso, "--load-delay", "5", "--gain", "0.5")
        t_ready = time.time() - t0
        y1 = measure(iso, CHIRP, 0.3, "ld1"); l1 = lag_between(y1); r1 = ratio(y1, l1); st1 = json.load(open(status))
        t1 = time.time()
        while time.time() - t1 < 8 and json.load(open(status)).get("wet") != 1.0:
            time.sleep(0.1)
        y2 = measure(iso, CHIRP, 0.3, "ld2"); l2 = lag_between(y2); r2 = ratio(y2, l2); st2 = json.load(open(status))
        check("O17", t_ready <= 1.0 and l1 == base and abs(r1 - 1.0) <= 0.03 and st1["wet"] == 0.0 and l2 == base and abs(r2 - 0.5) <= 0.03 and st2["wet"] == 1.0,
              f"hazır {t_ready:.2f} sn (≤ 1) · yüklenirken gecikme {l1} (= {base}), kazanç {r1:.3f} (1,0), ıslak {st1['wet']} · sonra gecikme {l2}, kazanç {r2:.3f} (0,5), ıslak {st2['wet']}")
    except RuntimeError as e:
        check("O17", False, f"{e} (hazır olma {time.time() - t0:.1f} sn)")
    p18 = iso.spawn("pw-jack", PY, WORKER, "--delay-ms", str(D_MS), "--block", "4800", "--load-fail", "--name", "mic_heavy_fail")
    try:
        rc18 = p18.wait(timeout=3)
    except subprocess.TimeoutExpired:
        rc18 = None
    check("O18", rc18 == 75, f"çıkış kodu {rc18} (= 75)")

print(f"\n{'PASS' if not fails else 'FAIL'}: {RAN[0] - len(fails)}/{RAN[0]}")
sys.exit(1 if fails else 0)
