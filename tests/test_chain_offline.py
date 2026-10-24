#!/usr/bin/env python3
"""Aşama 2 zincirinin kabul ölçütleri — referans kayıt üzerinde, canlı grafiğe dokunmadan (tools/chain.py tanımıyla).

C1 boşta taban ≤ −55 dBFS        neden: fısıltı +20 dB yükseltiliyor; bastırıcı tabanı geri indirmezse hışırtı öne çıkar
C2 fısıltı SNR ≥ 24 dB           neden: yalnız HPF 17,8 dB veriyordu; aşama 2 bunu belirgin geçmeli
C3 fısıltı − normal ≥ −7 dB      neden: ham fark −21 dB; dinleyen ses düğmesiyle oynamamalı
C4 çıkışta kırpılma = 0          neden: ham kayıtta normal ses kırpılıyordu; limitleyici tavanı tutmalı
C5 sessizlikte seviyeleyici kazancı ≤ +3 dB (HER modda)   neden: sessizlik eşiği oda gürültüsünün altına inerse kazanç tırmanır, taban pompalanır
                                 (ölçüldü 2026-10-11: Gece −60 LUFS = gürültü tabanı → +34 dB, taban −47,5 dBFS, gerçek tepe +1,3 dBTP)
C6 gerçek tepe ≤ −1 dBTP (HER modda)   neden: tavan örnek tepesini tutar; örnekler arası taşma dinleyenin çözücüsünde kırpılır
C7 çıkış hedefi: Görüşme → normal konuşma −23 ± 1 LUFS · Yayın → −16 ± 1 LUFS; ikisinde gerçek tepe ≤ −1 dBTP, kırpılma 0, fısıltı SNR ≥ 24
   neden: kullanıcı sayı değil hedef seçer; yüksek hedefte tavan daha çok çalışır, gerçek tepe taşabilir (ölçüldü: −0,84 dBTP)
C1–C4 ve C6 Normal, Fısıltı ve Gece modlarının üçünde de ölçülür (yalnız varsayılan mod ölçülürse öteki modların kusuru görünmez — yaşandı).
Referans kayıt kişisel ses olduğu için repoda değildir; yoksa test ATLANIR (çıkış 0, açıkça yazar).
"""
import os, re, subprocess, sys
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("test_chain_offline.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)

import numpy as np
from scipy.signal import butter, sosfilt

REF = os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav")
if not os.path.exists(REF):
    print("ATLANDI: referans kayıt yok:", REF); sys.exit(0)
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, "..", "tools"))
import chain, loudness
from ladspa_host import Plugin

MODES = ("normal", "fisilti", "gece")
fails, total = 0, 0


def check(tp, ok, d):
    global fails, total
    total += 1; fails += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)


# C5: yalnız süzgeç + seviyeleyici (saniyeler). Sessiz bölüm 2–10 sn.
x, sr = loudness.read_wav(REF)
hp = sosfilt(butter(4, chain.HPF_HZ, "highpass", fs=sr, output="sos"), x).astype(np.float32)
rms = lambda v: 20 * np.log10(np.sqrt((v.astype(np.float64) ** 2).mean()) + 1e-12)
for m in MODES:
    st = {**chain.DEFAULT_STATE, **chain.PRESETS[m]}
    n = [q for q in chain.nodes(st) if q[0] == "auto"][0]
    p = Plugin(n[1], n[2], sr, dict(n[5])); o = p.process(hp); lat = int(p.outputs().get("latency") or 0); p.close()
    g = rms(o[8 * sr + lat:10 * sr + lat]) - rms(hp[8 * sr:10 * sr])
    check(f"C5/{m}", g <= 3.0, f"sessizlikte seviyeleyici kazancı {g:+.1f} dB (≤ +3) · sessizlik eşiği {st['auto_silence']} LUFS")


def run(m):
    wav = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"mic-hifi-c-{m}-{os.getpid()}.wav")   # kişisel ses: tmpfs, ölçülünce silinir
    try:
        cmd = [sys.executable, os.path.join(here, "..", "tools", "chain_offline.py"), REF, "--preset", m, "--out", wav]
        for attempt in range(3):
            r = subprocess.run(cmd, capture_output=True, text=True)
            # Bastırıcı eklentisi duvar saatiyle kendini ölçer; makine meşgulken "Processing too slow" diye ÇÖKER (E38). Bu zincirin değil
            # ölçüm ortamının hatasıdır → yeniden dene; başka her hata olduğu gibi yükselir.
            if r.returncode == 0 or "Processing too slow" not in (r.stderr + r.stdout):
                break
            print(f"  ({m}: bastırıcı 'çok yavaş' diye çöktü, yeniden deneniyor {attempt + 1}/2)", flush=True)
        out = r.stdout
        if r.returncode or not os.path.exists(wav):   # sessizce "dosya yok"a düşmesin: asıl hata görünsün
            raise RuntimeError(f"chain_offline ({m}) çıkış {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
        y, _ = loudness.read_wav(wav)
        return out, loudness.measure(y, sr)
    finally:
        if os.path.exists(wav):
            os.remove(wav)


res = {m: run(m) for m in MODES}   # SIRAYLA: üç paralel bastırıcı birbirini yavaşlatıp eklentinin "çok yavaş" çöküşünü tetikliyordu (E38)
for m in MODES:
    out, meas = res[m]
    row = [l for l in out.splitlines() if l.strip().startswith("limit")][-1]
    v = [float(z) for z in re.findall(r"-?\d+\.\d+", row.split(")", 1)[-1])]
    silence, whisper_snr, gap = v[0], v[6], v[7]
    clip = int(re.search(r"kırpılan örnek: (\d+)", out).group(1))
    check(f"C1/{m}", silence <= -55, f"boşta taban {silence:.1f} dBFS (≤ −55)")
    check(f"C2/{m}", whisper_snr >= 24, f"fısıltı SNR {whisper_snr:.1f} dB (≥ 24)")
    check(f"C3/{m}", gap >= -7, f"fısıltı − normal {gap:.1f} dB (≥ −7)")
    check(f"C4/{m}", clip == 0, f"kırpılan örnek {clip} (= 0)")
    check(f"C6/{m}", meas["true_peak"] <= -1.0, f"gerçek tepe {meas['true_peak']} dBTP (≤ −1) · {meas['integrated']} LUFS · LRA {meas['lra']} LU")

# C7: çıkış yükseklik hedefi (PRD-QUALITY A2.5). Normal konuşma bölümü 27–37 sn.
def run_target(name):
    wav = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), f"mic-hifi-c7-{name}-{os.getpid()}.wav")
    try:
        r = subprocess.run([sys.executable, os.path.join(here, "..", "tools", "chain_offline.py"), REF, "--preset", "normal", "--state", f"loud_db={chain.LOUD_TARGETS[name]['loud_db']}", "--out", wav],
                           capture_output=True, text=True)
        if r.returncode or not os.path.exists(wav):
            raise RuntimeError(f"chain_offline ({name}) çıkış {r.returncode}: {(r.stderr or r.stdout)[-600:]}")
        y, _ = loudness.read_wav(wav)
        row = [l for l in r.stdout.splitlines() if l.strip().startswith("limit")][-1]
        v = [float(z) for z in re.findall(r"-?\d+\.\d+", row.split(")", 1)[-1])]
        return loudness.measure(y[27 * sr:37 * sr], sr)["integrated"], loudness.measure(y, sr)["true_peak"], int(re.search(r"kırpılan örnek: (\d+)", r.stdout).group(1)), v[6]
    finally:
        if os.path.exists(wav):
            os.remove(wav)


for name in chain.LOUD_TARGETS:
    lufs, tp, clip, snr = run_target(name)
    want = chain.LOUD_TARGETS[name]["lufs"]
    check(f"C7/{name}", abs(lufs - want) <= 1.0 and tp <= -1.0 and clip == 0 and snr >= 24,
          f"normal konuşma {lufs} LUFS (hedef {want} ± 1) · gerçek tepe {tp} dBTP (≤ −1) · kırpılan {clip} · fısıltı SNR {snr:.1f} dB (≥ 24)")
print(f"\n{'PASS' if not fails else 'FAIL'}: {total - fails}/{total}"); sys.exit(1 if fails else 0)
