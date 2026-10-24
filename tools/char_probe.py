#!/usr/bin/env python3
"""Karakter adayını GERÇEK konuşmada ölçer (referans kaydın normal bölümü, ton katmanı): yükseklik eşitlenmiş bant farkları + yükseklik farkı.
Kullanım: char_probe.py '{"ad": {"tone_low_db": 6, "tone_air_db": -3}}'   → her aday × 1 ve × 2 (orta / en güçlü) için bir satır
Bantlar: 95–200 · 200–400 · 400–1000 · 1000–2500 · 2500–5000 · 5000–10000 Hz. Kişisel ses tmpfs'te kalır.
"""
import os as _os, sys as _sys; _sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "tools"))
import heavy_guard; heavy_guard.guard("char_probe.py")   # ağır iş: tek sırada + nice 19 (canlı ses zincirini kesmesin; D46)
import sys, os, subprocess, json; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import numpy as np, chain, loudness, audition
from scipy.signal import butter, sosfilt
SR=48000; R=os.environ["XDG_RUNTIME_DIR"]; P=f"{R}/mic-hifi-pretone.npy"
if not os.path.exists(P): subprocess.run([sys.executable,os.path.join(os.path.dirname(os.path.abspath(__file__)),"chain_offline.py"),os.path.expanduser("~/.local/state/mic-hifi/ref/olcum-20261010.wav"),"--preset","normal","--dump-before","tone",P],capture_output=True)
seg=np.load(P).astype(np.float32)[27*SR:37*SR]
B=((95,200),(200,400),(400,1000),(1000,2500),(2500,5000),(5000,10000))
bp=lambda x,lo,hi:10*np.log10((sosfilt(butter(4,[lo,hi],"bandpass",fs=SR,output="sos"),x)**2).mean()+1e-20)
base={**chain.DEFAULT_STATE,**chain.PRESETS["normal"]}; rn=lambda p: audition.render(seg,SR,{**base,**p})
ref=rn({}); L0=loudness.measure(ref,SR)["integrated"]; R0=[bp(ref,lo,hi) for lo,hi in B]
cand=json.loads(sys.argv[1])
for ch,vals in cand.items():
    for f in (1.0,2.0):
        st=chain.clamp({k:v*f for k,v in vals.items()}); y=rn(st); dl=loudness.measure(y,SR)["integrated"]-L0; d=[bp(y,lo,hi)-r for (lo,hi),r in zip(B,R0)]
        print(f"{ch:7} ×{f:.0f} "+" ".join(f"{v-dl:+5.1f}" for v in d)+f" | en büyük {max(abs(v-dl) for v in d):.1f} · yük {dl:+.2f}")
