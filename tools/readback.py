#!/usr/bin/env python3
"""Canlı geri okuma: kayıtlı durum (state.json) → beklenen canlı parametreler ↔ çalışan grafikteki değerler. Çıkış 0 = aynı.

Dikkat: dinleyen yokken (düğüm `suspended`) yazılan değer geri okumada eski görünür, dinleyen gelince uygulanır (X34).
"""
import json, os, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain


def main():
    st = json.load(open(chain.STATE_FILE, encoding="utf-8"))
    want = chain.live_params({**chain.DEFAULT_STATE, **{k: v for k, v in st.items() if k in chain.DEFAULT_STATE}})
    got, state = {}, "YOK"
    for o in json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True).stdout):
        info = o.get("info") or {}
        if info.get("props", {}).get("node.name") == chain.CONTROL_NODE:
            state = info.get("state")
            for pr in info.get("params", {}).get("Props", []):   # iki Props girdisi döner: birleştir
                p = pr.get("params") or []
                got.update(zip(p[::2], p[1::2]))
    bad = [(k, got.get(k), v) for k, v in want.items() if k not in got or abs(float(got[k]) - float(v)) > 1e-4 * max(1.0, abs(float(v)))]
    print(f"düğüm {state} · canlı = durum: {len(want) - len(bad)}/{len(want)} parametre" + (f" · fark: {bad[:4]}" if bad else ""))
    return 1 if bad or not got else 0


if __name__ == "__main__":
    sys.exit(main())
