#!/usr/bin/env python3
"""mic-hifi canlı test noktaları — ürün katmanından (canlı PipeWire grafı) ölçer.
Zincirin ses kalitesi kabulü ayrı: tests/test_chain_offline.py (referans kayıt, C1–C4).

TP1  sanal kaynak var         : "effect_output.mic_clean" Audio/Source olarak listelenir
     neden: uygulamalar onu seçebilmeli; yoksa hiçbir şey teslim edilmemiştir.
TP2  uğultu kesiliyor         : zincir 7 sn "işlemsiz" duruma alınır (yalnız HPF kalır), ham + temiz aynı anda kaydedilir;
                                20–80 Hz ≥ 12 dB düşer VE 500 Hz–8 kHz ±1 dB aynı kalır; sonra önceki ayarlar geri yazılır
     neden: bastırıcı ve yükseltme açıkken bant farkı ortam sesine bağlıdır (9–34 dB ölçüldü) → HPF tek başına ölçülmeli.
TP3  yapılandırma sapmasız    : conf/mic-clean.conf = tools/gen_conf.py çıktısı; canlı çıkışta kırpılma yok
     neden: elle düzenlenmiş conf, çevrimdışı kabul testinin (C1–C4) ölçtüğü zincir olmaktan çıkar.
TP4  tek kanal                : temiz kaynak mono
     neden: kapsül tek; L ve R birebir aynı ölçüldü.
TP5  kulaklık konsolu sağlam  : effect_input.bta_console hâlâ grafta
     neden: ayrı süreç şartı — mikrofon zinciri BT konsolunu düşürmemeli.
TP8  eklenti kilidi          : kullanıcı dizinindeki ikili eklentilerin sha256'sı plugins.lock.json ile aynı
TP6  boşta bedel yok          : dinleyen yokken ham mikrofon kaynağı SUSPENDED/IDLE (RUNNING değil)
     neden: kimse bakmıyorken kaynak tüketme kuralı (node.passive).
"""
import json, os, subprocess, sys, tempfile, time, wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
import chain
RAW = chain.RAW_SOURCE
CLEAN = "effect_output.mic_clean"
env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
fails = []


def check(tp, ok, detail):
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {detail}")
    if not ok:
        fails.append(tp)


def sources():
    out = subprocess.run(["pactl", "-f", "json", "list", "sources"], env=env, capture_output=True, text=True).stdout
    return {s["name"]: s for s in json.loads(out)}


def band_db(x, sr, lo, hi):
    n = 8192
    win = np.hanning(n)
    p = np.zeros(n // 2 + 1)
    k = 0
    for i in range(0, len(x) - n, n // 2):
        p += np.abs(np.fft.rfft(x[i:i + n] * win)) ** 2
        k += 1
    f = np.fft.rfftfreq(n, 1 / sr)
    m = (f >= lo) & (f < hi)
    return 10 * np.log10(p[m].sum() / max(k, 1) + 1e-20)


def load(path):
    w = wave.open(path)
    ch, sr = w.getnchannels(), w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
    return a.reshape(-1, ch), sr


src = sources()
check("TP1", CLEAN in src, f"{CLEAN} {'var' if CLEAN in src else 'YOK'}")
if CLEAN not in src:
    sys.exit(1)
ch = src[CLEAN]["sample_specification"]
check("TP4", " 1ch " in f" {ch} ", f"biçim: {ch}")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "console"))
import chain
from server import push_live

saved = chain.load_state()
push_live({**chain.DEFAULT_STATE, **chain.PRESETS["ham"], "limit_on": False})  # yalnız HPF kalsın (state.json'a dokunmaz)
time.sleep(0.5)
try:
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "raw.wav"), os.path.join(d, "clean.wav")
        recs = [subprocess.Popen(["pw-record", "--target", RAW, "--rate", "48000", "--channels", "2", "--format", "s16", a], env=env),
                subprocess.Popen(["pw-record", "--target", CLEAN, "--rate", "48000", "--channels", "1", "--format", "s16", b], env=env)]
        time.sleep(6)
        for r in recs:
            r.terminate(); r.wait()
        xr, sr = load(a)
        xc, _ = load(b)
        xr, xc = xr[sr:, 0], xc[sr:, 0]  # ilk saniye: akış kurulumu
        # İki kayıtçı farklı anda başlar; ortam sesi durağan değil → aynı örnekleri karşılaştırmak için hizala.
        n = min(len(xr), len(xc))
        xr, xc = xr[:n], xc[:n]
        cc = np.fft.irfft(np.fft.rfft(xc, 2 * n) * np.conj(np.fft.rfft(xr, 2 * n)))
        lag = int(np.argmax(cc))
        lag = lag - 2 * n if lag > n else lag  # >0: temiz kayıt geride
        if lag > 0:
            xc, xr = xc[lag:], xr[:n - lag]
        elif lag < 0:
            xr, xc = xr[-lag:], xc[:n + lag]
        print(f"      hizalama: {lag} örnek ({lag / sr * 1000:.1f} ms), ortak süre {len(xr) / sr:.2f} sn")
        lo = band_db(xr, sr, 20, 80) - band_db(xc, sr, 20, 80)
        mid = band_db(xc, sr, 500, 8000) - band_db(xr, sr, 500, 8000)
        tot = lambda x: 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-12)
finally:
    ok_restore, why = push_live(saved)  # ne olursa olsun önceki ayarlar geri (limitleyici kapalı kalmasın)
muted = tot(xr) <= -110   # tam dijital sessizlik: mikrofon kendi tuşundan sessizde → ölçülecek sinyal yok (zincirin kusuru değil)
if muted and ok_restore:
    print(f"ATLA  TP2  ham mikrofon tam sessizlik veriyor ({tot(xr):.0f} dBFS) — cihazın sessize alma tuşu açık olabilir; ayarlar geri yazıldı")
else:
    check("TP2", lo >= 12 and abs(mid) <= 1.0 and ok_restore, f"20–80 Hz {lo:.1f} dB düştü (≥ 12) · 500 Hz–8 kHz {mid:+.2f} dB (±1) · ayarlar geri yazıldı: {ok_restore} {why}")
gen = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "gen_conf.py"), "--check"])
clip = int((np.abs(xc) >= 0.999).sum())
check("TP3", gen.returncode == 0 and clip == 0, f"conf sapması {'yok' if gen.returncode == 0 else 'VAR'} · canlı kırpılan örnek {clip}")
print(f"      toplam seviye: ham {tot(xr):.1f} → temiz {tot(xc):.1f} dBFS")

sinks = subprocess.run(["pactl", "list", "sinks", "short"], env=env, capture_output=True, text=True).stdout
if "effect_input.bta_console" in sinks or os.path.isdir(os.path.expanduser("~/projects/bt-audio-hifi")):
    check("TP5", "effect_input.bta_console" in sinks, "effect_input.bta_console grafta")
else:
    print("ATLA  TP5  kardeş proje (kulaklık konsolu) bu makinede kurulu değil")

# TP7 bellek koruması: zincir süreci takasa atılmamalı, sayfaları geri alınmaya karşı korunmalı
#     neden: 2026-10-11 ölçümü — sürecin yarısı takastaydı, bastırıcının 51 MB kodunun 1,3 MB'ı bellekteydi; ses iş parçacıkları
#     diskten sayfa beklerken blok kaçırıyordu ("Underrun", RTF 4–12). Öncelik yükseltmek bunu çözmez.
here = os.path.dirname(os.path.abspath(__file__))
import install_units
unit_repo = install_units.render("mic-clean.service")   # şablon + bu deponun konumu
try:
    unit_live = open(os.path.expanduser("~/.config/systemd/user/mic-clean.service"), encoding="utf-8").read()
except OSError:
    unit_live = ""
cg = subprocess.run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", "mic-clean.service"], capture_output=True, text=True).stdout.strip()
rd = lambda f: open(f"/sys/fs/cgroup{cg}/{f}").read().strip() if cg and os.path.exists(f"/sys/fs/cgroup{cg}/{f}") else "?"
swap_max, swap_cur, low = rd("memory.swap.max"), rd("memory.swap.current"), rd("memory.low")
check("TP7", unit_live == unit_repo and swap_max == "0" and swap_cur == "0" and low.isdigit() and int(low) >= 128 * 2 ** 20,
      f"kurulu birim = depo: {unit_live == unit_repo} · takas sınırı {swap_max} (0) · takasta {swap_cur} bayt (0) · geri alma koruması {low} (≥ 134217728)")

import plugins
try:
    pst = plugins.status(); prc = plugins.verdict(pst)
except (OSError, ValueError, KeyError) as e:
    pst, prc = {}, 2
check("TP8", prc == 0, "eklenti özetleri kilitle aynı: " + (", ".join(f"{n} {v['state']}" for n, v in pst.items()) or "kilit okunamadı"))

listeners = subprocess.run(["pgrep", "-f", "pw-loopback --name mic_monitor"], capture_output=True, text=True).stdout.split()
if not listeners:   # başka bir uygulama (ör. GNOME Ayarlar'ın seviye ölçeri) temiz kaynağı dinliyorsa RUNNING doğrudur
    time.sleep(2)
    links = subprocess.run(["pw-link", "-l"], capture_output=True, text=True).stdout
    listeners = [l.split("|->")[1].strip().split(":")[0] for blk in links.split("\n" + CLEAN + ":")[1:] for l in blk.split("\n")[1:] if "|->" in l]
    listeners = [n for n in listeners if n != "effect_input.mic_main"]   # kalite mikrofonunun kuru bağı edilgendir: mikrofonu uyanık tutmaz
if listeners:
    print(f"ATLA  TP6  kaynağı dinleyen var ({listeners[0]}) — dinleyen kapanınca ölçülür")
else:
    time.sleep(8)  # kayıtçılar kapandı; düğümün boşa düşmesini bekle
    state = sources()[RAW]["state"]
    check("TP6", state != "RUNNING", f"dinleyen yokken ham mikrofon durumu: {state}")

skipped = bool(listeners) + bool(muted and ok_restore)
print(f"\n{'PASS' if not fails else 'FAIL'}: {7 - len(fails) - skipped}/{7 - skipped}" + (f" ({skipped} nokta atlandı)" if skipped else ""))
sys.exit(1 if fails else 0)
