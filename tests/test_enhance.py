#!/usr/bin/env python3
"""V4 çevrimdışı "kaydı iyileştir" (tools/enhance.py) — docs/PRD-VOICE.md "V4 çevrimdışı". Karantina ortamı + referans kayıt ister; yoksa atlanır.

EN1 referansın ilk 40 sn'si (ham): konuşma−sessizlik farkı ≥ 10 dB artar · çıkış ses yüksekliği hedef −16 LUFS ±1 LU · gerçek tepe ≤ −1 dBTP ·
    süre = giriş · zaman kayması ≤ 1 ms   neden: gürültü gider; ses dinlenir seviyede, kırpılmadan, zamanlaması korunarak çıkar
EN2 44,1 kHz çift kanallı giriş kabul edilir; çıkış 48 kHz tek kanal, süre ±10 ms                                       neden: gerçek kayıtlar her biçimde gelir
EN3 giriş yok · çıkış = giriş · çıkış zaten var → çıkış kodu ≠ 0, hiçbir dosya yazılmaz/ezilmez                          neden: kullanıcının kaydı ezilmemeli
EN5 ses dosyası kılığındaki çalma listesi/birleştirme betiği (başka dosyayı ya da ağ adresini gösteren) REDDEDİLİR: çıkış kodu ≠ 0, çıkış yok,
    ağ adresine bağlantı denenmez (yerel dinleyiciye istek gelmez)        neden: "ses makineden çıkmaz" sözü; girdi dosyası başka dosya okutamamalı
EN6 yaygın kaplar kabul edilir: mp3 · m4a · ogg/opus · flac · mka (süre ±50 ms)                 neden: beyaz liste gerçek kayıtları dışarıda bırakmamalı
EN4 çıkış dosyası izni 0600                                                                                               neden: ses kaydı kişisel veridir
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_enhance.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import os, shutil, subprocess, sys, tempfile, wave

import numpy as np
from scipy.signal import correlate

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = os.path.expanduser("~/.cache/mic-hifi-quarantine")
PY, REF = os.path.join(Q, "v4env", "bin", "python"), os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not all(os.path.exists(p) for p in (PY, REF, os.path.join(Q, "MossFormer2_SE_48K.pt"))):
    print("ATLANDI: karantina ortamı / ağırlık / referans kayıt yok"); sys.exit(0)
TOOL, SR = os.path.join(ROOT, "tools", "enhance.py"), 48000
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


def rd(p):
    w = wave.open(p); n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    a = np.frombuffer(w.readframes(n), dtype={2: np.int16, 4: np.int32}[sw]).astype(np.float64) / float(1 << (8 * sw - 1))
    return a.reshape(-1, ch).mean(1), sr, ch


def run(*a):
    return subprocess.run([PY, TOOL, *a], capture_output=True, text=True, timeout=600)


db = lambda v: 10 * np.log10(np.mean(v ** 2) + 1e-12)
d = tempfile.mkdtemp(prefix="enh-", dir=os.environ.get("XDG_RUNTIME_DIR")); os.chmod(d, 0o700)
try:
    src, out = os.path.join(d, "in.wav"), os.path.join(d, "out.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", REF, "-t", "40", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", src], check=True)
    r = run(src, out)
    if r.returncode or not os.path.exists(out):
        check("EN1", False, f"çıkış kodu {r.returncode}: {(r.stderr.strip().splitlines() or ['?'])[-1][:160]}"); check("EN4", False, "çıkış yok")
    else:
        x, _, _ = rd(src); y, sr, ch = rd(out)
        sys.path.insert(0, os.path.join(ROOT, "tools")); import loudness
        con = (db(y[SR * 27:SR * 37]) - db(y[SR * 2:SR * 10])) - (db(x[SR * 27:SR * 37]) - db(x[SR * 2:SR * 10]))
        m = loudness.measure(y, SR)
        a, b = x[SR * 28:SR * 34], y[SR * 28:SR * 34]
        lag = int(np.argmax(correlate(b, a, "full", "fft")) - (len(a) - 1))
        lvl_ok = abs(m["integrated"] + 16.0) <= 1.0
        check("EN1", con >= 10 and lvl_ok and m["true_peak"] <= -1.0 and len(y) == len(x) and abs(lag) <= 48 and (sr, ch) == (SR, 1),
              f"konuşma−sessizlik farkı {con:+.1f} dB (≥ +10) · ses yüksekliği {m['integrated']} LUFS (−16 ± 1) · gerçek tepe {m['true_peak']} dBTP (≤ −1) · "
              f"süre {len(y)} = {len(x)} örnek · kayma {lag} örnek (≤ 48)")
        check("EN4", (os.stat(out).st_mode & 0o777) == 0o600, f"izin {oct(os.stat(out).st_mode & 0o777)} (0600)")
    s2, o2 = os.path.join(d, "in2.wav"), os.path.join(d, "out2.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", REF, "-ss", "25", "-t", "8", "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", s2], check=True)
    r = run(s2, o2)
    if r.returncode or not os.path.exists(o2):
        check("EN2", False, f"çıkış kodu {r.returncode}: {(r.stderr.strip().splitlines() or ['?'])[-1][:160]}")
    else:
        y2, sr2, ch2 = rd(o2)
        check("EN2", (sr2, ch2) == (SR, 1) and abs(len(y2) / SR - 8.0) <= 0.01, f"çıkış {sr2} Hz · {ch2} kanal · {len(y2) / SR:.3f} sn (8,000 ± 0,010)")
    keep = os.path.join(d, "keep.wav"); shutil.copy(src, keep); h0 = open(keep, "rb").read()
    r1 = run(os.path.join(d, "yok.wav"), os.path.join(d, "o3.wav")); r2 = run(keep, keep); r3 = run(src, keep)
    check("EN3", r1.returncode != 0 and not os.path.exists(os.path.join(d, "o3.wav")) and r2.returncode != 0 and r3.returncode != 0 and open(keep, "rb").read() == h0
          and all(r_.stderr.strip() for r_ in (r1, r2, r3)),
          f"giriş yok → {r1.returncode} · çıkış = giriş → {r2.returncode} · çıkış var → {r3.returncode} · var olan dosya değişmedi: {open(keep, 'rb').read() == h0}")
    got6 = {}
    for ext, codec in (("mp3", ["-c:a", "libmp3lame"]), ("m4a", ["-c:a", "aac"]), ("ogg", ["-c:a", "libopus"]), ("flac", ["-c:a", "flac"]), ("mka", ["-c:a", "pcm_s16le"])):
        f6, o6 = os.path.join(d, "k." + ext), os.path.join(d, "k-" + ext + ".wav")
        if subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", s2, "-t", "4", *codec, f6], capture_output=True).returncode:
            got6[ext] = "kodlayıcı yok"; continue
        rr = run(f6, o6)
        got6[ext] = round(rd(o6)[0].size / SR, 2) if rr.returncode == 0 and os.path.exists(o6) else f"rc {rr.returncode}: {(rr.stderr.strip().splitlines() or ['?'])[-1][:60]}"
    check("EN6", all(v == "kodlayıcı yok" or (isinstance(v, float) and abs(v - 4.0) <= 0.05) for v in got6.values()) and sum(isinstance(v, float) for v in got6.values()) >= 3,
          f"süreler (sn): {got6} (4,00 ± 0,05; en az 3 kap)")
    # EN5: girdinin başka kaynak göstermesi
    import socket, threading
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(4); srv.settimeout(0.2); port = srv.getsockname()[1]; hits = []
    stop = threading.Event()
    def acc():
        while not stop.is_set():
            try:
                c, _ = srv.accept(); hits.append(1); c.close()
            except OSError:
                pass
    th = threading.Thread(target=acc, daemon=True); th.start()
    cases = {"liste.wav": f"#EXTM3U\n#EXT-X-TARGETDURATION:8\n#EXTINF:8,\n{src}\n#EXT-X-ENDLIST\n",
             "ag.wav": f"#EXTM3U\n#EXT-X-TARGETDURATION:8\n#EXTINF:8,\nhttp://127.0.0.1:{port}/a.ts\n#EXT-X-ENDLIST\n",
             "birlesik.wav": f"ffconcat version 1.0\nfile '{src}'\n",
             "goreli.wav": "ffconcat version 1.0\nfile in.wav\n",                                   # aynı dizindeki dosya, göreli adla ("güvenli" sayılır)
             "goreli-liste.wav": "#EXTM3U\n#EXT-X-TARGETDURATION:8\n#EXTINF:8,\nin2.wav\n#EXT-X-ENDLIST\n"}
    res5 = {}
    for name, body in cases.items():
        pth, o5 = os.path.join(d, name), os.path.join(d, "o5-" + name)
        open(pth, "w").write(body)
        rr = run(pth, o5); res5[name] = (rr.returncode, os.path.exists(o5))
    rr = run(f"http://127.0.0.1:{port}/a.wav", os.path.join(d, "o5-url.wav")); res5["url"] = (rr.returncode, os.path.exists(os.path.join(d, "o5-url.wav")))
    stop.set(); th.join(); srv.close()
    check("EN5", all(rc != 0 and not made for rc, made in res5.values()) and not hits, f"(çıkış kodu, çıkış oluştu): {res5} · yerel dinleyiciye gelen bağlantı {len(hits)} (= 0)")
finally:
    shutil.rmtree(d, ignore_errors=True)
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
