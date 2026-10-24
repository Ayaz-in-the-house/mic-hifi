#!/usr/bin/env python3
"""Kulakla karşılaştırma: AYNI kaydı farklı ses karakterleriyle çevrimdışı işler (canlı ayara dokunmadan).

  audition.py render <giriş.wav> <durum.json> <çıkış.wav>     ton → ıslık kısma → doygunluk → limitleyici (tools/chain.py tanımıyla)
  audition.py measure <giriş.wav> <durum.json>                aynı işlemden sonra teslim ölçülerini JSON yazar (ses yüksekliği, gerçek tepe, taban, tık)
Giriş, zincirin ton katmanından ÖNCEKİ sesi olmalıdır (panel kaydı ton/ıslık/doygunluk geçici olarak kapalıyken alır).
Canlı zincirle aynı eklentiler ve aynı parametreler kullanılır; tek fark limitleyicinin ikinci kez uygulanmasıdır.
"""
import json, os, sys, wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain
from ladspa_host import Plugin

POST = ("pitch", "tone", "dyn", "sat", "limit")


def render(x, sr, state):
    y = np.asarray(x, np.float32)
    pad = np.zeros(sr // 10, np.float32)          # eklenti gecikmeleri kadar kuyruk (sonu kesilmesin)
    y = np.concatenate([y, pad])
    for name, so, label, _i, _o, ctl, rt in chain.nodes(state):
        if name in POST:
            p = Plugin(so, label, sr, ctl, realtime=rt)
            y = p.process(y)
            p.close()
    return y


def load(src, st):
    w = wave.open(src)
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())[:, 0].astype(np.float32) / 32768
    state = {**chain.DEFAULT_STATE, **chain.clamp({k: v for k, v in json.load(open(st, encoding="utf-8")).items() if k in chain.DEFAULT_STATE})}
    return x, sr, state


def measure(src, st):
    import clicks, loudness
    x, sr, state = load(src, st)
    y = render(x, sr, state)[:len(x) + sr // 20]
    m = loudness.measure(y, sr)
    c, c_in = clicks.count(y, sr), clicks.count(x, sr)
    m.update({"clicks_per_min": c["per_min"], "clicks": c["count"], "clicks_in_per_min": c_in["per_min"]})
    return m


def main():
    src, st, dst = sys.argv[2:5]
    x, sr, state = load(src, st)
    y = render(x, sr, state)
    os.umask(0o077)
    o = wave.open(dst, "w"); o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr)
    o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes()); o.close()


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "measure":
        print(json.dumps(measure(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 5 and sys.argv[1] == "render":
        main()
    else:
        sys.exit(__doc__)
