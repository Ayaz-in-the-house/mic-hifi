#!/usr/bin/env python3
"""Gerçek model (MossFormer2) işçide, yalıtılmış PipeWire'da, gerçek zamanlı (docs/PRD-VOICE.md "V4 → taşıyıcı"). Canlıya dokunmaz.

V4-C1 ıslak 1,0 · kuruya düşüş ≤ 2 · xrun 0 · gecikme = D ± 1 kuantum     neden: model gerçek zamanda yetişiyor mu
V4-C2 işçi çıkışında sessiz bölüm tabanı girişe göre ≥ 5 dB düşer, normal konuşma ± 3 dB   neden: çıkan ses modelin sesi (kuru yedek değil)
V4-C3 GPU belleği ve işçinin işlemci payı yazılır
Karantina ortamı, model kaynağı, ağırlık ya da referans kayıt yoksa ATLANIR.
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_v4_carrier.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import json, os, subprocess, sys, time, wave

import numpy as np
from scipy.signal import correlate

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from iso import Iso
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import carrier

Q = os.path.expanduser("~/.cache/mic-hifi-quarantine")
PY, REF = os.path.join(Q, "v4env", "bin", "python"), os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not all(os.path.exists(p) for p in (PY, REF, os.path.join(Q, "MossFormer2_SE_48K.pt"), os.path.join(Q, "cvs"))):
    print("ATLANDI: karantina ortamı / ağırlık / referans kayıt yok (docs/research/S-v4-model-triage.md)"); sys.exit(0)
SR, D_MS, BLOCK, WIN_MS = 48000, float(carrier.QUALITY_DELAY_MS), 18000, 500.0   # canlıdaki gecikmeyle aynı; 600 ms'de zaman payı eksiydi (VW5)
D = int(D_MS * SR / 1000)
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


with Iso() as iso:
    pre = os.path.join(iso.dir, "pre.npy")   # kişisel ses: yalıtılmış örneğin geçici dizininde, çıkışta silinir
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "chain_offline.py"), REF, "--preset", "fisilti", "--dump-before", "denoise", pre], capture_output=True)
    x = np.load(pre).astype(np.float32)[:SR * 45]
    src = os.path.join(iso.dir, "in.wav")
    w = wave.open(src, "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
    status = os.path.join(iso.dir, "heavy.json")
    p = iso.spawn("pw-jack", PY, os.path.join(ROOT, "heavy", "worker.py"), "--model", "mossformer", "--delay-ms", str(D_MS), "--block", str(BLOCK), "--window-ms", str(WIN_MS),
                  "--status", status, stdout=subprocess.PIPE, stderr=open(os.path.join(iso.dir, "w.err"), "w"), text=True)
    line = p.stdout.readline().strip()
    if line != "READY" or not iso.wait_port("mic_heavy:out", 8):
        print("işçi hazır olmadı:", repr(line), open(os.path.join(iso.dir, "w.err")).read()[-600:]); sys.exit(1)
    iso.link("fake_mic:capture_FL", "mic_heavy:in_model"); iso.link("fake_mic:capture_FL", "mic_heavy:in_dry")
    time.sleep(2.0)
    rec = os.path.join(iso.dir, "out.wav")
    r = iso.record2("fake_mic:capture_FL", "mic_heavy:out", rec)
    time.sleep(0.3)
    t0 = time.time(); c0 = sum(map(int, open(f"/proc/{p.pid}/stat").read().rsplit(")", 1)[1].split()[11:13]))
    iso.play(src, "fake_mic", wait=True)
    time.sleep(1.5)
    cpu = (sum(map(int, open(f"/proc/{p.pid}/stat").read().rsplit(")", 1)[1].split()[11:13])) - c0) / os.sysconf("SC_CLK_TCK") / (time.time() - t0)
    r.terminate(); r.wait()
    st = json.load(open(status))
    gpu = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"], capture_output=True, text=True).stdout
    raw = open(rec, "rb").read(); data = raw[raw.index(b"data") + 8:]
    y = np.frombuffer(data[:len(data) // 4 * 4], dtype=np.int16).astype(np.float64).reshape(-1, 2) / 32768
a, b = y[:, 0], y[:, 1]
seg = slice(SR * 27, SR * 33)
lag = int(np.argmax(correlate(b[seg.start:seg.stop + SR], a[seg], "valid")))
db = lambda v: 20 * np.log10(np.sqrt((v ** 2).mean()) + 1e-12)
check("V4-C1", st["wet"] == 1.0 and st["fallback_count"] <= 2 and st["xruns"] == 0 and abs(lag - D) <= 1024,
      f"ıslak {st['wet']} · kuruya düşüş {st['fallback_count']} (≤ 2) · xrun {st['xruns']} · gecikme {lag} örnek (beyan {D} ± 1024) · kuru çalınan {st['dry_ms']:.0f} ms")
sil = db(b[SR * 3 + lag:SR * 9 + lag]) - db(a[SR * 3:SR * 9]); sp = db(b[SR * 27 + lag:SR * 37 + lag]) - db(a[SR * 27:SR * 37])
check("V4-C2", sil <= -5 and abs(sp) <= 3, f"sessiz bölüm tabanı {sil:+.1f} dB (≤ −5) · normal konuşma {sp:+.1f} dB (± 3)")
mem = [l.split(",")[1].strip() for l in gpu.splitlines() if l.split(",")[0].strip() == str(st.get("pid"))]
check("V4-C3", True, f"işçi işlemci payı %{cpu * 100:.0f} çekirdek · GPU belleği {mem[0] if mem else 'okunamadı'} · model payı (lead) {st.get('lead_samples')} örnek")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
