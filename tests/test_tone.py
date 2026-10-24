#!/usr/bin/env python3
"""V1 ton karakteri — kabul ölçütleri (docs/PRD-VOICE.md). Canlı grafiğe dokunmaz: EQ eklentisi çevrimdışı, beyaz gürültüyle ölçülür.

T-V1-1 `notr` karakterde yanıt düz (prob frekanslarında ±0,3 dB)
       neden: nötr gerçekten nötr olmalı; aşama 2 kabulü (C1–C4) ton katmanı eklenince bozulmamalı
T-V1-2 her ton sürgüsü TEK BAŞINA +6 / −6 dB → kendi prob frekansında ±1,5 dB; karakter tablosu → port değerleri birebir
       neden: bant türü (enum) ya da port adı yanlışsa sürgü başka bir şey yapar; burada yakalanır
T-V1-3 `telefon`: 100 Hz ≤ −12 dB · 8 kHz ≤ −12 dB · 1 kHz ±3 dB
       neden: bant sınırlama gerçekten uygulanıyor mu
T-V1-4 `tone_on=false` + abartılı ayar → yanıt düz (±0,3 dB)
       neden: anahtar gerçekten kapatmalı
T-V1-5 tam zincir + `radyo`, referans kayıt: kırpılma 0 · boşta taban ≤ −52 dBFS
       neden: EQ yükseltmesi limitleyiciyi aşmamalı, gürültüyü öne çıkarmamalı (referans kayıt yoksa ATLANIR)
T-AUD-1 `audition.render`: nötr durumda bant seviyeleri giriş + çıkış kazancı (±0,3 dB; kazanç bir kez uygulanır), telefon karakterinde 6–9 kHz ≤ −12 dB
       neden: panelin "kulakla karşılaştır" çalması canlı zincirle aynı tanımdan üretilmeli
T-V1-10 yoğunluk: hafif ≤ orta ≤ güçlü ≤ çok (her bantta mutlak değerce), hepsi kontrol aralığında ve adımında, orta = tablo, dört yoğunluk birbirinden farklı
       neden: "daha az / daha çok" düğmeleri gerçekten kademeli olmalı ve sürgülerle çelişmemeli
T-V1-9 mod ön ayarları ton anahtarı içermez; `clamp` ton aralıklarını uygular
       neden: karakter moddan bağımsız ikinci eksendir
"""
import os, re, subprocess, sys
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_tone.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)

import numpy as np
from scipy.signal import welch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import chain
from ladspa_host import Plugin

SR = 48000
REF = os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
fails = []


ran = []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}")
    if not ok:
        fails.append(tp)


RNG = np.random.default_rng(7)
NOISE = (RNG.standard_normal(SR * 20) * 0.05).astype(np.float32)
F, P_IN = welch(NOISE[SR:], SR, nperseg=32768)


def tone_node(state):
    return [n for n in chain.nodes(state) if n[0] == "tone"][0]


def response(state, freqs):
    """Prob frekanslarında (1/6 oktav bant) kazanç, dB."""
    _n, so, label, _i, _o, ctl, _rt = tone_node(state)
    p = Plugin(so, label, SR, ctl)
    y = p.process(NOISE)
    p.close()
    _f, p_out = welch(y[SR:], SR, nperseg=32768)
    out = []
    for f0 in freqs:
        m = (F >= f0 / 2 ** (1 / 12)) & (F <= f0 * 2 ** (1 / 12))
        out.append(10 * np.log10(p_out[m].sum() / P_IN[m].sum()))
    return out


def st(**kw):
    return {**chain.DEFAULT_STATE, **chain.CHARACTERS["notr"], "tone_on": True, **kw}


PROBES = [150, 250, 500, 1400, 3500, 8000]
fmt = lambda v: " ".join(f"{x:+.2f}" for x in v)

# T-V1-1
r = response(st(), PROBES)
check("T-V1-1", max(abs(x) for x in r) <= 0.3, f"notr yanıtı {fmt(r)} dB (±0,3)")

# T-V1-2: her sürgü tek başına; prob = raflarda rafın içi, çanlarda merkez
SOLO = [("tone_low_db", 60), ("tone_mud_db", 250), ("tone_box_db", 500), ("tone_nasal_db", 1400), ("tone_pres_db", 3500), ("tone_air_db", 16000)]
bad = []
for key, f0 in SOLO:
    for g in (6.0, -6.0):
        got = response(st(**{key: g}), [f0])[0] + chain.tone_trim_db(st(**{key: g}))   # yükseklik telafisi tüm bandı kaydırır: geri ekle
        if abs(got - g) > 1.5:
            bad.append(f"{key}={g:+.0f} → {got:+.2f} @{f0}")
check("T-V1-2a", not bad, "her sürgü tek başına ±6 dB → prob ±1,5 dB" + (": " + "; ".join(bad) if bad else ""))
bad = []
for name, ch in chain.CHARACTERS.items():
    ctl = tone_node(st(**ch))[5]
    for i, (_typ, fkey, gkey, _q) in enumerate(chain.TONE_BANDS):
        if gkey and abs(ctl[f"Gain {i} (G)"] - chain.lin(ch.get(gkey, 0))) > 1e-6:
            bad.append(f"{name}.{gkey}")
        if fkey in ch and abs(ctl[f"Frequency {i} (Hz)"] - ch[fkey]) > 1e-6:
            bad.append(f"{name}.{fkey}")
    if set(ch) - set(chain.DEFAULT_STATE):
        bad.append(f"{name}: bilinmeyen anahtar")
check("T-V1-2b", not bad and "notr" in chain.CHARACTERS, f"{len(chain.CHARACTERS)} karakter → port değerleri birebir" + (": " + ", ".join(bad) if bad else ""))

# T-V1-3
lo, mid, hi = response(st(**chain.CHARACTERS["telefon"]), [100, 1000, 8000])
check("T-V1-3", lo <= -12 and hi <= -12 and abs(mid) <= 3, f"telefon: 100 Hz {lo:+.1f} · 1 kHz {mid:+.1f} · 8 kHz {hi:+.1f} dB")

# T-V1-4
r = response(st(tone_on=False, tone_low_db=9, tone_pres_db=9, tone_air_db=-9, tone_hp_hz=300), PROBES)
check("T-V1-4", max(abs(x) for x in r) <= 0.3, f"tone_on=false yanıtı {fmt(r)} dB (±0,3)")

# T-V1-10: yoğunluk ölçeği
sc = chain.scaled_character
mono = all(abs(sc(c, "hafif").get(k, 0)) <= abs(sc(c, "orta").get(k, 0)) <= abs(sc(c, "guclu").get(k, 0)) <= abs(sc(c, "cok").get(k, 0))
           for c in chain.CHARACTERS for k in chain.TONE_KEYS if k.endswith("_db") and k != "sat_db")
inrange = all(chain.clamp(dict(sc(c, a))) == sc(c, a) for c in chain.CHARACTERS for a in chain.AMOUNTS)
tel = sc("telefon", "hafif")
check("T-V1-10", mono and inrange and sc("radyo", "orta") == chain.CHARACTERS["radyo"] and sc("derin", "cok")["tone_low_db"] == 12
      and 20 < tel["tone_hp_hz"] < 300 and 3400 < tel["tone_lp_hz"] < 22000 and len(set(map(str, (sc("sicak", a) for a in chain.AMOUNTS)))) == 4,
      f"tekdüze artış {mono} · aralık içinde {inrange} · orta = tablo · telefon hafif kesimleri {tel['tone_hp_hz']:g}–{tel['tone_lp_hz']:g} Hz")

# T-V1-9
leak = [m for m, p in chain.PRESETS.items() if any(k.startswith("tone_") for k in p)]
c = chain.clamp({"tone_low_db": 99, "tone_hp_hz": 1, "tone_lp_hz": 99999, "tone_air_db": -3.26})
check("T-V1-9", not leak and c == {"tone_low_db": 12.0, "tone_hp_hz": 20.0, "tone_lp_hz": chain.TONE_LP_MAX, "tone_air_db": -3.5},
      f"modlar ton taşımaz; clamp → {c}")

# ── V1b: ıslık kısma + doygunluk ──
from scipy.signal import butter, sosfilt, correlate


def band(lo, hi, db):
    y = sosfilt(butter(4, [lo, hi], "bandpass", fs=SR, output="sos"), RNG.standard_normal(SR * 4))
    return (y / np.sqrt((y ** 2).mean()) * 10 ** (db / 20)).astype(np.float32)


def through(name, state, x):
    _n, so, label, _i, _o, ctl, _rt = [n for n in chain.nodes(state) if n[0] == name][0]
    p = Plugin(so, label, SR, ctl)
    y = p.process(x)
    p.close()
    return y


rms = lambda y: 20 * np.log10(np.sqrt((y[SR:].astype(np.float64) ** 2).mean()) + 1e-12)
voice, ess = band(200, 3000, -25), band(5000, 10000, -25)
on = st(deess_on=True)
dv, de = rms(through("dyn", on, voice)) - rms(voice), rms(through("dyn", on, ess)) - rms(ess)
check("T-V1b-1", de <= -6 and abs(dv) <= 0.5, f"ıslık kısma: ıslık bandı {de:+.1f} dB (≤ −6) · konuşma bandı {dv:+.2f} dB (±0,5)")

# A2.3: bölünmüş bantlı ıslık kısma (docs/PRD-QUALITY.md "A2.3")
def bandp(y, lo, hi):
    Y = np.abs(np.fft.rfft(y[SR:SR * 3].astype(np.float64))) ** 2   # 2 sn pencere → bin = 0,5 Hz
    return 10 * np.log10(Y[lo * 2:hi * 2].sum() + 1e-20)


ess2 = band(5500, 10000, -25)
both = (voice + ess2).astype(np.float32)
yb = through("dyn", on, both)
d_v, d_e = bandp(yb, 200, 3000) - bandp(both, 200, 3000), bandp(yb, 5500, 10000) - bandp(both, 5500, 10000)
check("A23-T1", abs(d_v) <= 0.5, f"ıslık ANINDA konuşma bandı {d_v:+.2f} dB (±0,5)")
check("A23-T2", d_e <= -6, f"aynı anda ıslık bandı {d_e:+.1f} dB (≤ −6)")
quiet = band(100, 16000, -60)
yq = through("dyn", on, quiet)
flat = [bandp(yq, lo, hi) - bandp(quiet, lo, hi) for lo, hi in ((200, 1000), (1000, 3000), (3000, 4500), (4500, 5500), (5500, 8000), (8000, 14000))]
check("A23-T3", max(abs(v) for v in flat) <= 0.3, f"eşik altında düzlük {fmt(flat)} dB (±0,3; 4,5–5,5 kHz geçiş bölgesi dahil)")
_n, so, label, _i, _o, ctl, _rt = [n for n in chain.nodes(on) if n[0] == "dyn"][0]
pl = Plugin(so, label, SR, dict(ctl)); pl.process(quiet[:SR]); lat = pl.outputs().get("latency") or 0; pl.close()
check("A23-T4", lat <= 96, f"ıslık kısma gecikmesi {lat:.0f} örnek (≤ 96)")
wh = band(1500, 9000, -28)
d_w = bandp(through("dyn", on, wh), 1500, 9000) - bandp(wh, 1500, 9000)
rule = all(chain.PRESETS[m].get("deess_on") is False for m in ("fisilti", "gece", "ham"))
check("A23-T5", abs(d_w) <= 0.5 or rule, f"fısıltı benzeri gürültüde kayıp {d_w:+.2f} dB → fısıltı kuralı {'SÜRÜYOR (kayıp > 0,5 dB)' if abs(d_w) > 0.5 else 'gereksiz'}")

# A2.4: dinamik EQ — şişme (200–450 Hz) ve sertlik (2–5 kHz), aynı çok bantlı kompresörde (docs/PRD-QUALITY.md "A2.4")
mid = band(600, 1800, -25)
mud_on, harsh_on = st(dyn_mud_on=True), st(dyn_harsh_on=True)
x1 = (band(200, 450, -18) + mid).astype(np.float32); y1 = through("dyn", mud_on, x1)
d_m, d_mid = bandp(y1, 220, 430) - bandp(x1, 220, 430), bandp(y1, 700, 1600) - bandp(x1, 700, 1600)
check("A24-T1", d_m <= -3 and abs(d_mid) <= 0.5, f"şişme bandı {d_m:+.1f} dB (≤ −3) · orta bant {d_mid:+.2f} dB (±0,5)")
x2 = band(200, 450, -35); d2 = bandp(through("dyn", mud_on, x2), 220, 430) - bandp(x2, 220, 430)
check("A24-T2", abs(d2) <= 0.5, f"eşik altı şişme bandı {d2:+.2f} dB (±0,5)")
x3 = (band(2200, 4500, -24) + mid).astype(np.float32); y3 = through("dyn", harsh_on, x3)
d_h, d_mid3 = bandp(y3, 2400, 4300) - bandp(x3, 2400, 4300), bandp(y3, 700, 1600) - bandp(x3, 700, 1600)
check("A24-T3", d_h <= -2.5 and abs(d_mid3) <= 0.5, f"sertlik bandı {d_h:+.1f} dB (≤ −2,5) · orta bant {d_mid3:+.2f} dB (±0,5)")
x4 = band(2200, 4500, -42); d4 = bandp(through("dyn", harsh_on, x4), 2400, 4300) - bandp(x4, 2400, 4300)
check("A24-T4", abs(d4) <= 0.5, f"eşik altı sertlik bandı {d4:+.2f} dB (±0,5)")
all_on = st(deess_on=True, dyn_mud_on=True, dyn_harsh_on=True)
yq5 = through("dyn", all_on, quiet)
flat5 = [bandp(yq5, lo, hi) - bandp(quiet, lo, hi) for lo, hi in ((100, 180), (180, 220), (220, 420), (420, 480), (480, 1900), (1900, 2100), (2100, 4800), (4800, 14000))]
_n, so, label, _i, _o, ctl, _rt = [n for n in chain.nodes(all_on) if n[0] == "dyn"][0]
pl = Plugin(so, label, SR, dict(ctl)); pl.process(quiet[:SR]); lat5 = pl.outputs().get("latency") or 0; pl.close()
none = st(deess_on=False, dyn_mud_on=False, dyn_harsh_on=False, dyn_body_on=False)
yn = through("dyn", none, voice)
lagn = int(np.argmax(correlate(yn[SR:SR * 2], voice[SR:SR * 2], "full"))) - (SR - 1)
resn = 20 * np.log10(np.sqrt(((yn[SR + lagn:SR * 3 + lagn] - voice[SR:SR * 3]).astype(np.float64) ** 2).mean()) / np.sqrt((voice[SR:SR * 3].astype(np.float64) ** 2).mean()) + 1e-12)
check("A24-T5", max(abs(v) for v in flat5) <= 0.3 and lat5 <= 96 and resn <= -80, f"üçü açık, eşik altı düzlük {fmt(flat5)} dB (±0,3) · gecikme {lat5:.0f} (≤ 96) · üçü kapalıyken artık {resn:.0f} dB (≤ −80)")
y6a, y6b = through("dyn", on, x1), through("dyn", on, x3)
d6 = [bandp(y6a, 220, 430) - bandp(x1, 220, 430), bandp(y6b, 2400, 4300) - bandp(x3, 2400, 4300)]
check("A24-T6", max(abs(v) for v in d6) <= 0.5, f"yalnız ıslık kısma açıkken şişme/sertlik bandı {fmt(d6)} dB (±0,5: kısılmaz)")
rule7 = [m for m in ("fisilti", "gece", "ham") if chain.PRESETS[m].get("dyn_harsh_on") is not False or chain.PRESETS[m].get("dyn_body_on") is not False]
check("A24-T7", not rule7 and all(k in chain.AXIS2 for k in ("dyn_mud_on", "dyn_mud_db", "dyn_harsh_on", "dyn_harsh_db")) and chain.DEFAULT_STATE["dyn_mud_on"] is False and chain.DEFAULT_STATE["dyn_harsh_on"] is False,
      f"sertlik fısıltı modlarında kapalı (ihlal: {rule7}) · anahtarlar ikinci eksende · varsayılan kapalı")

# A2.6b: dolgunluk — alt bant (< 200 Hz) yoğunluğu: zayıfı kaldırır, güçlüyü bırakır (docs/PRD-QUALITY.md "A2.6b")
body = st(dyn_body_on=True, dyn_body_db=6)
lo_q, lo_l = band(100, 190, -45), band(100, 190, -30)   # zayıf hece ↔ güçlü hece (referans konuşmada bu bandın p90'ı −30,7 dBFS)
xq, xl = (lo_q + mid).astype(np.float32), (lo_l + mid).astype(np.float32)
yq2, yl2 = through("dyn", body, xq), through("dyn", body, xl)
g_q, g_l = bandp(yq2, 105, 185) - bandp(xq, 105, 185), bandp(yl2, 105, 185) - bandp(xl, 105, 185)
g_mid = max(abs(bandp(yq2, 700, 1600) - bandp(xq, 700, 1600)), abs(bandp(yl2, 700, 1600) - bandp(xl, 700, 1600)))
check("A26b-T1", 5 <= g_q <= 6.5 and abs(g_l) <= 1.5 and g_mid <= 0.5, f"dolgunluk +6: zayıf alt bant {g_q:+.1f} dB (+5…+6,5) · güçlü {g_l:+.1f} dB (±1,5) · orta bant {g_mid:.2f} dB (±0,5)")
yb2 = through("dyn", body, quiet)
flat_b = [bandp(yb2, lo, hi) - bandp(quiet, lo, hi) for lo, hi in ((260, 420), (480, 1900), (2100, 4800), (5200, 14000))]
_n, so, label, _i, _o, ctl, _rt = [n for n in chain.nodes(body) if n[0] == "dyn"][0]
pl = Plugin(so, label, SR, dict(ctl)); pl.process(quiet[:SR]); lat_b = pl.outputs().get("latency") or 0; pl.close()
check("A26b-T2", max(abs(v) for v in flat_b) <= 0.3 and lat_b <= 96 and chain.DEFAULT_STATE["dyn_body_on"] is False and "dyn_body_on" in chain.AXIS2,
      f"200 Hz üstü düzlük {fmt(flat_b)} dB (±0,3) · gecikme {lat_b:.0f} (≤ 96) · varsayılan kapalı, ikinci eksen")

off = st(deess_on=False, sat_on=False)
worst = -200.0
for node in ("dyn", "sat"):
    y = through(node, off, voice)
    lag = int(np.argmax(correlate(y[SR:SR * 2], voice[SR:SR * 2], "full"))) - (SR - 1)
    a, b = y[SR + lag:SR * 3 + lag], voice[SR:SR * 3]
    worst = max(worst, 20 * np.log10(np.sqrt(((a - b).astype(np.float64) ** 2).mean()) / np.sqrt((b.astype(np.float64) ** 2).mean()) + 1e-12))
check("T-V1b-2", worst <= -80, f"kapalıyken artık {worst:.0f} dB (≤ −80)")

sine = (10 ** ((chain.SAT_BASE_DB - 8) / 20) * np.sin(2 * np.pi * 1000 * np.arange(SR * 3) / SR)).astype(np.float32)


def thd(drive):
    y = through("sat", st(sat_on=True, sat_db=drive), sine)[SR:SR * 2].astype(np.float64)
    Y = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    pk = lambda f0: Y[f0 - 30:f0 + 30].max()   # 1 sn pencere → bin = Hz
    return 100 * np.sqrt(sum(pk(1000 * k) ** 2 for k in range(2, 11))) / pk(1000)


t0, t6, t12 = thd(0), thd(8), thd(16)
check("T-V1b-3", t0 < 1 and t0 < t6 < t12, f"1 kHz THD: sürüş 0 → %{t0:.2f} · 8 → %{t6:.1f} · 16 → %{t12:.1f}")

leak = [m for m in ("fisilti", "gece", "ham") if chain.PRESETS[m].get("deess_on") is not False] + (["normal"] if "deess_on" in chain.PRESETS["normal"] else [])
miss = [n for n, c in chain.CHARACTERS.items() if "sat_on" not in c or "sat_db" not in c]
check("T-V1b-5", not leak and not miss and chain.CHARACTERS.get("megafon", {}).get("sat_on") is True and all(k in chain.AXIS2 for k in ("deess_on", "sat_db", "tone_on")),
      f"fısıltı kuralı ihlali: {leak} · doygunluk anahtarı eksik karakter: {miss}")

# T-AUD-1: kulakla karşılaştırmanın çevrimdışı işleyicisi (tools/audition.py)
import audition

x = band(100, 12000, -25)
flat = audition.render(x, SR, st())
tel = audition.render(x, SR, st(**chain.CHARACTERS["telefon"]))
bp = lambda y, lo, hi: 10 * np.log10((np.abs(np.fft.rfft(y[SR:SR * 3])) ** 2)[lo * 2:hi * 2].sum())   # 2 sn pencere → bin = 0,5 Hz
d_flat = [bp(flat, lo, hi) - bp(x, lo, hi) for lo, hi in ((200, 400), (900, 1100), (6000, 9000))]
d_tel = bp(tel, 6000, 9000) - bp(x, 6000, 9000)
# Çıkış kazancı tavanın girişindedir (A2.2) ve işleyici onu BİR KEZ uygular: kayıt, çıkış kazancı 0 iken alınır (sunucu S25).
og = chain.DEFAULT_STATE["out_db"]
check("T-AUD-1", max(abs(v - og) for v in d_flat) <= 0.3 and d_tel - og <= -12 and len(flat) >= len(x),
      f"nötr işleme {fmt(d_flat)} dB (çıkış kazancı {og:+g} ±0,3) · telefon 6–9 kHz {d_tel - og:+.1f} dB (≤ −12)")

# T-V1-5
if "--fast" in sys.argv or not os.path.exists(REF):
    print("ATLANDI  T-V1-5  referans kayıt yok")
else:
    args = [sys.executable, os.path.join(ROOT, "tools", "chain_offline.py"), REF, "--character", "radyo"]
    out = subprocess.run(args, capture_output=True, text=True).stdout
    rows = [l for l in out.splitlines() if l.strip().startswith("limit")]
    if not rows:
        check("T-V1-5", False, "chain_offline çıktısı okunamadı")
    else:
        silence = float(re.findall(r"-?\d+\.\d+", rows[-1].split(")", 1)[-1])[0])
        clip = int(re.search(r"kırpılan örnek: (\d+)", out).group(1))
        check("T-V1-5", clip == 0 and silence <= -52, f"radyo + tam zincir: kırpılan {clip} (= 0) · boşta taban {silence:.1f} dBFS (≤ −52)")
    pre = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "mic-hifi-prelimit.npy")   # limitleyici öncesi sinyal (ton nötr), bir kez üretilir
    subprocess.run(args[:3] + ["--dump-before", "dyn", pre], capture_output=True, text=True)
    y0 = np.load(pre); os.remove(pre)
    seg = lambda y: 20 * np.log10(np.sqrt((y[27 * SR:37 * SR].astype(np.float64) ** 2).mean()))
    d = [seg(through("sat", st(sat_on=True, sat_db=g), y0)) - seg(y0) for g in (12.0, 20.0)]
    out = subprocess.run(args[:3] + ["--character", "megafon"], capture_output=True, text=True).stdout
    clip = int(re.search(r"kırpılan örnek: (\d+)", out).group(1))
    check("T-V1b-4", all(abs(v) <= 1 for v in d) and clip == 0, f"doygunlukta ses yüksekliği farkı: sürüş 12 → {d[0]:+.2f} · 20 → {d[1]:+.2f} dB (±1) · megafon kırpılan {clip}")

n = len(ran)
print(f"\n{'PASS' if not fails else 'FAIL'}: {n - len(fails)}/{n}")
sys.exit(1 if fails else 0)
