#!/usr/bin/env python3
"""Ses kesintisi ölçümü (PRD-QUALITY A0). Temiz kaynağı N saniye dinler ve iki BAĞIMSIZ kaynaktan kesinti arar:
  1) gürültü bastırıcının kendi uyarısı (journal: "Underrun detected"), dinlemenin başına göre zamanıyla
  2) kaydın içinde tam-sıfır koşuları (≥ 64 örnek) ve ani enerji çukurları — kullanıcının duyacağı şey

Kullanım: dropout_probe.py [--seconds 45] [--runs 3] [--load] [--settle 2.0] [--json]
  --load    ölçüm boyunca tüm çekirdeklerde sentetik işlemci yükü (normal öncelik)
Kayıt kişisel sestir: çalışma dizininde (tmpfs) 0600 tutulur ve ölçüm bitince silinir.
Çıkış kodu: 0 = kararlı durumda kesinti yok · 1 = var · 2 = ölçülemedi
"""
import json, os, subprocess, sys, tempfile, time, wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain

RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
SR = 48000


def arg(name, default, cast=float):
    return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default


def source_state(name):
    out = subprocess.run(["pactl", "-f", "json", "list", "sources"], capture_output=True, text=True).stdout
    try:
        return next((s.get("state", "?") for s in json.loads(out) if s.get("name") == name), "yok")
    except ValueError:
        return "?"


def underruns_since(t0):
    """[(dinlemenin başına göre saniye, RTF)]"""
    out = subprocess.run(["journalctl", "--user", "-u", "mic-clean.service", "--since", f"@{t0:.3f}", "-o", "short-unix", "--no-pager"],
                         capture_output=True, text=True).stdout
    res = []
    for line in out.splitlines():
        if "Underrun" not in line:
            continue
        try:
            ts = float(line.split()[0])
        except ValueError:
            continue
        rtf = line.split("RTF:")[1].split(")")[0].strip() if "RTF:" in line else "?"
        res.append((round(ts - t0, 2), rtf))
    return res


def analyse(path, settle):
    w = wave.open(path)
    y = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
    if len(y) < SR:
        return None
    z = np.concatenate(([0], (y == 0).astype(np.int8), [0]))
    d = np.diff(z)
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    runs = [(int(s), int(e - s)) for s, e in zip(starts, ends) if e - s >= 64]
    hop = SR // 100
    n = len(y) // hop
    rms = 20 * np.log10(np.sqrt((y[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    med = float(np.median(rms))
    dips = [int(i) for i in range(2, n - 2) if rms[i] < med - 25 and min(rms[i - 2], rms[i + 2]) > med - 6]   # 10 ms'lik ani çukur
    cut = int(settle * SR)
    return {"seconds": round(len(y) / SR, 2), "median_dbfs": round(med, 1),
            "zero_runs_start": [(round(s / SR, 3), k) for s, k in runs if s < cut],
            "zero_runs_steady": [(round(s / SR, 3), k) for s, k in runs if s >= cut],
            "dips_steady": [round(i * hop / SR, 2) for i in dips if i * hop >= cut]}


def cpu_ticks():
    v = [int(x) for x in open("/proc/stat").readline().split()[1:8]]
    return sum(v), v[3] + v[4]   # toplam, boşta + iowait


def one_run(seconds, settle, load):
    before = source_state(chain.CLEAN_SOURCE)
    fd, path = tempfile.mkstemp(prefix="mic-dropout-", suffix=".wav", dir=RUN)
    os.close(fd)
    os.chmod(path, 0o600)
    burners = []
    try:
        if load:
            burners = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(os.cpu_count() or 4)]
            time.sleep(1.0)
        t0, c0 = time.time(), cpu_ticks()
        rec = subprocess.Popen(["timeout", "--signal=TERM", "--kill-after=2", str(seconds + 3), "pw-record", "--target", chain.CLEAN_SOURCE,
                                "--rate", str(SR), "--channels", "1", "--format", "s16", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(seconds)
        c1 = cpu_ticks()
        rec.terminate()
        rec.wait(timeout=5)
        time.sleep(0.5)
        ur = underruns_since(t0)
        a = analyse(path, settle)
    finally:
        for b in burners:
            b.kill()
        for b in burners:
            b.wait()
        try:
            os.remove(path)
        except OSError:
            pass
    if a is None:
        return None
    a.update({"state_before": before, "load": bool(load), "loadavg": open("/proc/loadavg").read().split()[0],
              "cpu_busy": round(100 * (1 - (c1[1] - c0[1]) / max(1, c1[0] - c0[0]))),
              "underruns_start": [u for u in ur if u[0] < settle], "underruns_steady": [u for u in ur if u[0] >= settle]})
    return a


def main():
    seconds, runs, settle, load = arg("--seconds", 45.0), arg("--runs", 3, int), arg("--settle", 2.0), "--load" in sys.argv
    res, bad = [], False
    for i in range(runs):
        if i:
            time.sleep(7)   # kaynağın yeniden uykuya dönmesi için (her koşu soğuk başlasın)
        r = one_run(seconds, settle, load)
        if r is None:
            print("ölçülemedi: kayıt boş"); sys.exit(2)
        res.append(r)
        steady = len(r["underruns_steady"]) + len(r["zero_runs_steady"]) + len(r["dips_steady"])
        bad |= steady > 0
        if "--json" not in sys.argv:
            print(f"koşu {i + 1}: önce {r['state_before']:9} işlemci %{r['cpu_busy']:3d} (yük ort. {r['loadavg']}) · süre {r['seconds']:5.1f} sn · orta seviye {r['median_dbfs']:6.1f} dBFS | "
                  f"BAŞLANGIÇ (<{settle:g} sn): uyarı {len(r['underruns_start'])} {r['underruns_start']} sıfır {r['zero_runs_start']} | "
                  f"KARARLI: uyarı {len(r['underruns_steady'])} {r['underruns_steady'][:4]} sıfır {len(r['zero_runs_steady'])} {r['zero_runs_steady'][:4]} çukur {r['dips_steady'][:4]}")
    if "--json" in sys.argv:
        print(json.dumps(res))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
