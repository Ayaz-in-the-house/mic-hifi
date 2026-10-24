#!/usr/bin/env python3
"""Oda payı denetimi (tools/diag_report.py) — docs/PRD-QUALITY.md "Oda payı denetimi". Referans kayıt ister; yoksa atlanır.

DR1 referansın sessiz bölümü: oda −60 ± 1,5 LUFS; pay Normal ≈ 10, Fısıltı/Gece ≈ 6 dB; hepsi yeterli    neden: bilinen ölçümle tutarlılık
DR2 aynı bölüm +8 dB: Fısıltı ve Gece yetersiz (pay < 5)                                                 neden: kural gerçekten ayırıyor
DR3 kayıt yok / bozuk dosya: çıkış kodu ≠ 0                                                              neden: sunucu boş sonuç göstermesin
"""
import json, os, subprocess, sys, tempfile, wave

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not os.path.exists(REF):
    print("ATLANDI: referans kayıt yok"); sys.exit(0)
TOOL = os.path.join(ROOT, "tools", "diag_report.py")
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


def run(d):
    r = subprocess.run([sys.executable, TOOL, d], capture_output=True, text=True, timeout=60)
    try:
        return r.returncode, json.loads(r.stdout)
    except ValueError:
        return r.returncode, None


w = wave.open(REF); sr = w.getframerate()
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())[:, 0][sr * 2:sr * 10]
with tempfile.TemporaryDirectory(dir=os.environ.get("XDG_RUNTIME_DIR")) as d:
    def put(sig):
        o = wave.open(os.path.join(d, "sessiz.wav"), "w"); o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes(np.clip(sig, -32768, 32767).astype(np.int16).tobytes()); o.close()
    rc0, j0 = run(d)
    open(os.path.join(d, "sessiz.wav"), "wb").write(b"bozuk"); rc0b, j0b = run(d)
    check("DR3", rc0 != 0 and j0 is None and rc0b != 0 and j0b is None, f"kayıt yok → {rc0} · bozuk → {rc0b}")
    put(x); rc1, j1 = run(d)
    m1 = (j1 or {}).get("modes", {})
    check("DR1", rc1 == 0 and abs(j1["room_lufs"] + 60) <= 1.5 and all(m1[k]["ok"] for k in ("normal", "fisilti", "gece")) and abs(m1["normal"]["margin_db"] - 10) <= 1.5 and abs(m1["fisilti"]["margin_db"] - 6) <= 1.5,
          f"oda {j1 and j1['room_lufs']} LUFS (−60 ± 1,5) · pay " + " · ".join(f"{k} {v['margin_db']} dB {'✓' if v['ok'] else '✗'}" for k, v in m1.items()))
    put(x.astype(np.float64) * 10 ** (8 / 20)); rc2, j2 = run(d)
    m2 = (j2 or {}).get("modes", {})
    check("DR2", rc2 == 0 and not m2["fisilti"]["ok"] and not m2["gece"]["ok"] and abs(j2["room_lufs"] - j1["room_lufs"] - 8) <= 0.5,
          f"+8 dB: oda {j2 and j2['room_lufs']} LUFS · " + " · ".join(f"{k} {v['margin_db']} dB {'✓' if v['ok'] else '✗'}" for k, v in m2.items()))
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
