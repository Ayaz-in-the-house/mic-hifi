#!/usr/bin/env python3
"""Perde ve ses yolu (docs/PRD-VOICE.md "Aşama 5a"). Referans kayıt ve ~/.local/lib/mic-hifi/ladspa-rubberband.so ister; canlıya dokunmaz.

P1 kapalıyken düğüm yok (zincir, conf, canlı parametreler)                       neden: kapalıyken 60 ms gecikme ödenmez
P2 −3 yt, koruma açık: perde −3 ± 0,5 yt · ses yolu 0 ± 0,5 yt · yükseklik ± 1 LU   neden: "aynı kişi, daha kalın"
P3 −3 yt, koruma kapalı: perde −3 ± 0,5 · ses yolu −3 ± 0,75 yt                   neden: "daha iri kişi"
P4 +3 yt, koruma açık: perde +3 ± 0,5 · ses yolu 0 ± 1 yt (ölçüm: yukarı yönde koruma kısmi, +0,75 yt)   neden: yukarı yön
P5 gecikme ≤ 3000 örnek · işlemci ≤ %10                                          neden: canlı kullanım sınırı
P6 0 yt ve pitch_mute: çıkış = gecikmeli giriş, artık ≤ −60 dB                    neden: sıfırda/fısıltıda sese dokunmaz
P12 Kalın orta: perde −2 ± 0,5 yt · ses yolu 0 ± 0,5 · yükseklik ± 1 LU · gerçek tepe ≤ −1 dBTP    neden: "aynı kişi, daha kalın"
P13 İri orta: perde −3 ± 0,5 · ses yolu −3 ± 0,75 yt · yükseklik ± 1 LU                         neden: "daha iri biri"
P14 yoğunluk yarım tonu da ölçekler (Kalın −1/−2/−3/−4, İri −1,5/−3/−4,5/−6); perdesiz karakterler perdeyi kapatır   neden: tek "ne kadar?" ekseni
P7 Fısıltı/Gece/Ham pitch_mute açar, Normal kapatır; pitch_on/pitch_st ön ayarlarda yok   neden: mod değişince yeniden başlatma ve ayar kaybı olmaz
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_pitch.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import os, sys, time

import numpy as np

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "tools"))
import chain, gen_conf, loudness, pitch_probe as pp
from ladspa_host import Plugin

fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp)
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok:
        fails.append(tp)


off = dict(chain.DEFAULT_STATE)
names = [n[0] for n in chain.nodes(off)]
check("P1", "pitch" not in names and "rubberband" not in gen_conf.render(off) and not any(k.startswith("pitch:") for k in chain.live_params(off)) and chain.DEFAULT_STATE["pitch_on"] is False,
      f"kapalıyken düğümler: {names}")
rule = all(chain.PRESETS[m].get("pitch_mute") is True for m in ("fisilti", "gece", "ham")) and chain.PRESETS["normal"].get("pitch_mute") is False \
    and not any(k in p for p in chain.PRESETS.values() for k in ("pitch_on", "pitch_st", "pitch_formant")) and all(k in chain.AXIS2 for k in ("pitch_on", "pitch_st", "pitch_formant"))
check("P7", rule, f"fısıltı modları kuru geçirir, Normal açar; perde ayarı ön ayarlarda yok ve ikinci eksende: {rule}")
if not (os.path.exists(pp.RB) and os.path.exists(os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav"))):
    print("ATLANDI  P2–P6  eklenti ya da referans kayıt yok (kurulum: docs/RUNBOOK.md)")
else:
    SR = 48000
    x = pp.segment(); f_in = pp.f0(x); L0 = loudness.measure(x, SR)["integrated"]

    def through(patch):
        st = {**chain.DEFAULT_STATE, **chain.PRESETS["normal"], "pitch_on": True, **patch}
        n = [q for q in chain.nodes(st) if q[0] == "pitch"][0]
        p = Plugin(n[1], n[2], SR, dict(n[5])); t = time.time(); y = p.process(x); dt = time.time() - t; lat = int(p.outputs().get("latency") or 0); p.close()
        return y, lat, dt / (len(x) / SR)

    def meas(patch):
        y, lat, rtf = through(patch); y2 = y[lat:]
        return 12 * np.log2(pp.f0(y2) / f_in), pp.env_shift(x, y2[:len(x)]), loudness.measure(y2, SR)["integrated"] - L0, lat, rtf

    p2 = meas({"pitch_st": -3, "pitch_formant": True})
    check("P2", abs(p2[0] + 3) <= 0.5 and abs(p2[1]) <= 0.5 and abs(p2[2]) <= 1, f"−3 yt koruma açık: perde {p2[0]:+.2f} yt · ses yolu {p2[1]:+.2f} yt · yükseklik {p2[2]:+.1f} LU")
    p3 = meas({"pitch_st": -3, "pitch_formant": False})
    check("P3", abs(p3[0] + 3) <= 0.5 and abs(p3[1] + 3) <= 0.75, f"−3 yt koruma kapalı: perde {p3[0]:+.2f} yt · ses yolu {p3[1]:+.2f} yt")
    p4 = meas({"pitch_st": 3, "pitch_formant": True})
    check("P4", abs(p4[0] - 3) <= 0.5 and abs(p4[1]) <= 1.0, f"+3 yt koruma açık: perde {p4[0]:+.2f} yt · ses yolu {p4[1]:+.2f} yt (yukarı yönde koruma kısmi: ≤ 1 yt)")
    check("P5", p2[3] <= 3000 and max(p2[4], p3[4], p4[4]) <= 0.10, f"gecikme {p2[3]} örnek ({p2[3] / 48:.1f} ms) (≤ 3000) · işlemci en çok %{max(p2[4], p3[4], p4[4]) * 100:.1f} (≤ 10)")
    res, lags = [], []
    for patch in ({"pitch_st": 0}, {"pitch_st": -3, "pitch_mute": True}):
        y, _lat, _ = through(patch)
        seg = slice(SR, SR * 5)   # kuru yolun gecikmesi bildirilen gecikmeden farklı olabilir → hizayı ölç
        cc = np.fft.irfft(np.fft.rfft(y[seg], 2 * (SR * 4)) * np.conj(np.fft.rfft(x[seg], 2 * (SR * 4))))
        lag = int(np.argmax(cc)); lag = lag - 2 * SR * 4 if lag > SR * 4 else lag
        lags.append(lag)
        a = y[SR + lag:SR * 8 + lag]; b = x[SR:SR * 8]
        res.append(20 * np.log10(np.sqrt(((a - b) ** 2).mean()) / np.sqrt((b ** 2).mean()) + 1e-12))
    check("P6", max(res) <= -60, f"0 yt artık {res[0]:.1f} dB · pitch_mute artık {res[1]:.1f} dB (≤ −60) · kuru yolun ölçülen gecikmesi {lags} örnek")
# Aşama 5b: perdeyi kullanan karakterler
sc = chain.scaled_character
st_of = lambda c: [sc(c, a)["pitch_st"] for a in chain.AMOUNTS]
plain = [c for c in chain.CHARACTERS if c not in ("kalin", "iri")]
check("P14", st_of("kalin") == [-1.0, -2.0, -3.0, -4.0] and st_of("iri") == [-1.5, -3.0, -4.5, -6.0] and all(sc(c, a)["pitch_on"] is False for c in plain for a in chain.AMOUNTS)
      and sc("kalin", "orta")["pitch_formant"] is True and sc("iri", "orta")["pitch_formant"] is False and all(k in chain.TONE_KEYS for k in ("pitch_on", "pitch_st", "pitch_formant")),
      f"Kalın yarım ton {st_of('kalin')} · İri {st_of('iri')} · perdesiz karakterlerde perde kapalı")
if os.path.exists(pp.RB) and os.path.exists(os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")):
    import audition
    base = {**chain.DEFAULT_STATE, **chain.PRESETS["normal"]}
    ref = audition.render(x, SR, base); f_ref = pp.f0(ref); L_ref = loudness.measure(ref, SR)["integrated"]

    def char_meas(name):
        y = audition.render(x, SR, {**base, **sc(name, "orta")})[3200:]
        return 12 * np.log2(pp.f0(y) / f_ref), pp.env_shift(ref, y[:len(ref)]), loudness.measure(y, SR)["integrated"] - L_ref, loudness.measure(y, SR)["true_peak"]

    k = char_meas("kalin")
    check("P12", abs(k[0] + 2) <= 0.5 and abs(k[1]) <= 0.5 and abs(k[2]) <= 1 and k[3] <= -1, f"Kalın orta: perde {k[0]:+.2f} yt · ses yolu {k[1]:+.2f} yt · yükseklik {k[2]:+.2f} LU · gerçek tepe {k[3]} dBTP")
    i_ = char_meas("iri")
    check("P13", abs(i_[0] + 3) <= 0.5 and abs(i_[1] + 3) <= 0.75 and abs(i_[2]) <= 1, f"İri orta: perde {i_[0]:+.2f} yt · ses yolu {i_[1]:+.2f} yt · yükseklik {i_[2]:+.2f} LU")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
