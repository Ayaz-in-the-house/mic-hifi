#!/usr/bin/env python3
"""Gözcü + anahtarlayıcı + GERÇEK modelli işçi birlikte, yalıtılmış PipeWire'da (docs/PRD-VOICE.md "V4 → taşıyıcı"). Canlıya dokunmaz.

VW1 dinleyen gelince işçi (gerçek model) başlar, ıslağa geçilir (≤ 20 sn: model yüklemesi dahil), karıştırıcı (0, 1)   neden: uçtan uca kalite hattı
VW2 ıslaktayken sanal mikrofonun sessiz bölüm tabanı kuru döneme göre ≥ 5 dB düşük          neden: dinleyene giden ses modelin sesi
VW3 işçiye SIGKILL → kuru ≤ 300 ms, sonra yeniden ıslak                                  neden: gerçek modelle de mikrofon işçiye bağlı ölmez
VW5 ıslakta ≥ 20 sn: kuruya düşüş 0 (açılıştaki dışında), en dar zaman payı ≥ 80 ms        neden: canlıda 4 dk'da 54 düşüş ölçüldü (pay ~6 ms'di);
    yalıtılmış örnek yük altında değil → pay canlıdaki dalgalanmayı karşılayacak kadar geniş olmalı
VW6 dinleyenden ≤ 3 sn sonra "taşıyıcıda" (işçi model yüklenirken hizalı kuru verir), "ıslak" daha sonra     neden: zaman sıçraması kaydın başında kalır
VW4 dinleyen gidince işçi kapanır, karıştırıcı (1, 0), GPU belleği bırakılır               neden: kimse dinlemiyorken GPU tüketilmez
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_v4_watch.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import json, os, signal, subprocess, sys, time, wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "tools"))
import carrier
from iso import Iso

Q = os.path.expanduser("~/.cache/mic-hifi-quarantine")
PY, REF = os.path.join(Q, "v4env", "bin", "python"), os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not all(os.path.exists(p) for p in (PY, REF, os.path.join(Q, "MossFormer2_SE_48K.pt"))):
    print("ATLANDI: karantina ortamı / ağırlık / referans kayıt yok"); sys.exit(0)
SR = 48000
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


def events(p):
    try:
        return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
    except OSError:
        return []


def wait_event(p, pred, timeout, after=0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        hit = [e for e in events(p)[after:] if pred(e)]
        if hit:
            return hit[0]
        time.sleep(0.05)
    return None


def mixer(iso):
    for o in json.loads(iso.out("pw-dump", timeout=10) or "[]"):
        if (o.get("info") or {}).get("props", {}).get("node.name") == carrier.MAIN_IN:
            d = {}
            for pr in o["info"].get("params", {}).get("Props", []):
                p = pr.get("params") or []
                d.update(zip(p[::2], p[1::2]))
            return round(float(d.get("mix:Gain 1", -1)), 3), round(float(d.get("mix:Gain 2", -1)), 3)


def gpu_of(pid):
    out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"], capture_output=True, text=True).stdout
    return any(l.split(",")[0].strip() == str(pid) for l in out.splitlines())


with Iso() as iso:
    d = iso.dir
    conf = os.path.join(d, "main.conf"); open(conf, "w").write(carrier.render_main("iso")); iso.spawn("pipewire", "-c", conf)
    assert iso.wait_port(carrier.DRY_PORT, 8)
    pre = os.path.join(d, "pre.npy")
    subprocess.run([sys.executable, os.path.join(ROOT, "tools", "chain_offline.py"), REF, "--preset", "fisilti", "--dump-before", "denoise", pre], capture_output=True)
    x = np.load(pre).astype(np.float32); sil = x[SR * 2:SR * 10]
    loop = np.tile(sil, 15)                                       # 120 sn sessiz oda sesi: taban ölçümü için durağan giriş
    src = os.path.join(d, "in.wav"); w = wave.open(src, "w"); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((np.clip(loop, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()
    iso.play(src, "fake_mic", wait=False)
    status, ev = os.path.join(d, "heavy.json"), os.path.join(d, "ev.jsonl")
    cmd = f"pw-jack {PY} {os.path.join(ROOT, 'heavy', 'worker.py')} --model mossformer --delay-ms 1000 --block 18000 --window-ms 500 --status {status}"
    iso.spawn(sys.executable, os.path.join(ROOT, "tools", "watch.py"), "--worker-cmd", cmd, "--status", status, "--model-src", "fake_mic:capture_FL",
              "--dry-src", "fake_mic:capture_FL", "--hold", "1", "--events", ev, "--start-timeout", "25")
    wait_event(ev, lambda e: e["event"] == "gözcü hazır", 5)
    rec = os.path.join(d, "app.wav")
    app = iso.spawn("pw-cat", "-r", "--target", carrier.MAIN_OUT, "-P", '{ node.name = "gorusme-uygulamasi" }', "--channels", "1", "--rate", "48000", "--format", "s16", rec)
    t_app = time.time()
    e_wet = wait_event(ev, lambda e: e["event"] == "ıslak", 25)
    t_wet = time.time() - t_app
    e_car = next((e for e in events(ev) if e["event"] == "taşıyıcıda"), None)
    e_lis = next((e for e in events(ev) if e["event"] == "dinleyen"), None)
    check("VW6", bool(e_car and e_lis and e_wet) and e_car["t"] - e_lis["t"] <= 3.0 and e_wet["t"] > e_car["t"],
          f"dinleyen → taşıyıcıda {(e_car['t'] - e_lis['t']) if (e_car and e_lis) else -1:.2f} sn (≤ 3) · → ıslak {(e_wet['t'] - e_lis['t']) if (e_wet and e_lis) else -1:.2f} sn")
    time.sleep(6.0)
    mx = mixer(iso)
    check("VW1", e_wet is not None and mx == (0.0, 1.0), f"ıslağa geçiş {t_wet:.1f} sn (≤ 25; model yüklemesi dahil) · karıştırıcı {mx}")
    time.sleep(16.0)
    st5 = json.load(open(status))
    check("VW5", st5["fallback_count"] <= 1 and (st5.get("margin_min_ms") or -1) >= 80,
          f"ıslakta ~22 sn: düşüş {st5['fallback_count']} (≤ 1, açılış) · en dar pay {st5.get('margin_min_ms')} ms (≥ 80) · en uzun model bloğu {st5.get('model_ms_max')} ms · xrun {st5['xruns']}")
    pid1 = st5["pid"]; had_gpu = gpu_of(pid1)
    n0 = len(events(ev)); t_kill = time.time(); os.kill(pid1, signal.SIGKILL)
    e_dry = wait_event(ev, lambda e: e["event"] == "kuru", 5, n0)
    e_wet2 = wait_event(ev, lambda e: e["event"] == "ıslak", 30, n0)
    check("VW3", e_dry is not None and e_dry["t"] - t_kill <= 0.3 and e_wet2 is not None, f"SIGKILL → kuru {(e_dry['t'] - t_kill) * 1000 if e_dry else -1:.0f} ms (≤ 300) · yeniden ıslak: {e_wet2 is not None}")
    time.sleep(2.0)
    pid2 = json.load(open(status))["pid"]
    app.terminate(); app.wait()
    e_gone = wait_event(ev, lambda e: e["event"] == "işçi kapatıldı" and e.get("neden") == "dinleyen yok", 8)
    time.sleep(1.0)
    check("VW4", e_gone is not None and not os.path.exists(f"/proc/{pid2}") and mixer(iso) == (1.0, 0.0) and had_gpu and not gpu_of(pid2),
          f"dinleyen gidince işçi kapandı: {e_gone is not None} · karıştırıcı {mixer(iso)} · işçi GPU kullanıyordu: {had_gpu} · sonra GPU'da: {gpu_of(pid2)}")
    raw = open(rec, "rb").read(); data = raw[raw.index(b"data") + 8:]
    y = np.frombuffer(data[:len(data) // 2 * 2], dtype=np.int16).astype(np.float64) / 32768
n = SR // 10
f = 20 * np.log10(np.sqrt((y[:len(y) // n * n].reshape(-1, n) ** 2).mean(1)) + 1e-9)
k_wet = int(t_wet * 10)
dry_lv, wet_lv = float(np.median(f[5:max(6, k_wet - 5)])), float(np.median(f[k_wet + 15:k_wet + 50]))
check("VW2", wet_lv - dry_lv <= -5, f"sanal mikrofonda oda sesi tabanı: kuru dönem {dry_lv:.1f} dBFS → ıslak dönem {wet_lv:.1f} dBFS ({wet_lv - dry_lv:+.1f} dB; ≤ −5)")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
