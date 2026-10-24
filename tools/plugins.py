#!/usr/bin/env python3
"""Eklenti kilidi: kullanıcı dizinindeki ikili eklentilerin özetini plugins.lock.json ile karşılaştırır. docs/PRD-PUBLISH.md Y3.

    python3 tools/plugins.py check     çıkış 0 = hepsi doğru (isteğe bağlı olan yoksa "yok") · 1 = uyuşmazlık ya da zorunlu eklenti yok · 2 = bakılamadı
"""
import hashlib, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.environ.get("MIC_PLUGIN_DIR") or os.path.expanduser("~/.local/lib/mic-hifi")
LOCK = os.environ.get("MIC_PLUGIN_LOCK") or os.path.join(ROOT, "plugins.lock.json")


def path(name):
    return os.path.join(PLUGIN_DIR, json.load(open(LOCK, encoding="utf-8"))["plugins"][name]["file"])


def status():
    """{ad: {"state": "ok" | "mismatch" | "missing" | "unreadable", "required": bool, "path": str}} — kilit okunamazsa OSError/ValueError yükselir."""
    out = {}
    for name, p in json.load(open(LOCK, encoding="utf-8"))["plugins"].items():
        f = os.path.join(PLUGIN_DIR, p["file"])
        if not os.path.exists(f):
            st = "missing"
        else:
            try:
                h = hashlib.sha256()
                with open(f, "rb") as fh:
                    for blk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(blk)
                st = "ok" if h.hexdigest() == p["sha256"] else "mismatch"
            except OSError:
                st = "unreadable"
        out[name] = {"state": st, "required": bool(p.get("required")), "path": f}
    return out


def verdict(st):
    """0 temiz · 1 uyuşmazlık/zorunlu yok · 2 bakılamadı (bakılamayan asla temiz sayılmaz)."""
    if any(v["state"] == "unreadable" for v in st.values()):
        return 2
    if any(v["state"] == "mismatch" or (v["state"] == "missing" and v["required"]) for v in st.values()):
        return 1
    return 0


def main():
    try:
        st = status()
    except (OSError, ValueError, KeyError) as e:
        print(f"EKLENTİ KİLİDİ: kilit dosyası okunamadı ({e}); DENETLENEMEDİ", file=sys.stderr)
        return 2
    tr = {"ok": "özet doğru", "mismatch": "ÖZET UYUŞMUYOR", "missing": "yok", "unreadable": "OKUNAMADI"}
    for n, v in st.items():
        print(f"  {n:11} {tr[v['state']]:15} {'zorunlu' if v['required'] else 'isteğe bağlı'}  {v['path']}")
    return verdict(st)


if __name__ == "__main__":
    sys.exit(main())
