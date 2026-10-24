#!/usr/bin/env python3
"""Yayın denetim kapısı: izlenen dosyalarda kişisel veri arar. docs/PRD-PUBLISH.md Y1 (kardeş projedeki `oss-audit.sh`'in genişletilmiş hâli).

    python3 tools/oss_audit.py [--summary] [yol …]      çıkış 0 = temiz · 1 = bulgu var · 2 = TARANAMADI (liste alınamadı / dosya okunamadı)

Aranan: Bluetooth adresi (`:` ve `_` ayraçlı) · /home/<ad> · makine adı · e-posta · Tailscale (100.64/10) ve 192.168 adresleri · seri numaralı USB düğüm adı.
Yol verilmezse `git ls-files` (tüm izlenen dosyalar; kapsam dışı liste YOK — yayın ağacı tek başına temiz olmalı).
"""
import os, re, socket, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = socket.gethostname().split(".")[0] or "__makine_adi_yok__"
FIXTURES = ("tools/oss_audit.py", "tests/test_oss_audit.py", "tests/test_release.py")


def _fixture_bytes():
    out = set()
    for rel in FIXTURES:
        try:
            out.add(open(os.path.join(ROOT, rel), "rb").read())
        except OSError:
            pass
    return out


FIXTURE_BYTES = _fixture_bytes()
ALLOW = re.compile(r"noreply@anthropic\.com|[\w.+-]+@example\.(com|org)|00[:_]00[:_]00[:_]00[:_]00[:_]00")
RULES = [
    ("bluetooth adresi", re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:_]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")),
    ("ev dizini", re.compile(r"/home/[a-z_][a-z0-9_-]*")),
    ("makine adı", re.compile(r"(?<![\w-])" + re.escape(HOST) + r"(?![\w-])")),
    ("e-posta", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[a-z]{2,}")),
    ("tailscale adresi", re.compile(r"(?<![\d.])100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("özel ağ adresi", re.compile(r"(?<![\d.])192\.168\.\d{1,3}\.\d{1,3}(?![\d.])")),
    ("usb seri numaralı aygıt", re.compile(r"usb-[A-Za-z0-9_.-]*?_[0-9A-Fa-f]{8,}-\d{2}")),
]


def scan_text(text):
    """[(kural, eşleşme)] — izinli örnekler çıkarıldıktan sonra."""
    clean = ALLOW.sub("", text)
    return [(name, m.group(0)) for name, rx in RULES for m in rx.finditer(clean)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        files = args
    else:
        r = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
        files = [f for f in r.stdout.split("\n") if f]
        if r.returncode != 0 or not files:           # KAPALI-başarısız: liste alınamadıysa "temiz" denmez
            print(f"DENETİM: dosya listesi alınamadı (git çıkış {r.returncode}); TARANMADI", file=sys.stderr)
            return 2
    hits, per, unread = [], {}, []
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(ROOT, f)
        try:
            raw = open(p, "rb").read()
        except OSError as e:
            unread.append(f"{f}: {e.strerror}")
            continue
        if raw in FIXTURE_BYTES:
            continue                      # kapının kendisi ve sınamaları (UYDURMA desen örnekleri): yalnız İÇERİĞİ birebir aynıysa atlanır, ad eşleşmesi yetmez
        # İkili dosyalar ATLANMAZ: metin olarak çözülemeyen baytlar yer tutucuyla değiştirilir, gömülü dizgeler yine taranır.
        for i, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
            for name, m in scan_text(line):
                hits.append((f, i, name, m)); per[name] = per.get(name, 0) + 1
    if unread:                                       # KAPALI-başarısız: okunamayan dosya varsa sonuç "temiz" olamaz
        print(f"DENETİM: {len(unread)} dosya OKUNAMADI — sonuç geçersiz:", file=sys.stderr)
        for u in unread:
            print("  " + u, file=sys.stderr)
        return 2
    if not hits:
        print(f"DENETİM: temiz ({len(files)} dosya tarandı)")
        return 0
    if "--summary" not in sys.argv:
        for f, i, name, m in hits:
            print(f"  {f}:{i}: {name}: {m}")
    print(f"DENETİM: {len(hits)} bulgu, {len({h[0] for h in hits})} dosyada — " + " · ".join(f"{k} {v}" for k, v in sorted(per.items(), key=lambda kv: -kv[1])))
    return 1


if __name__ == "__main__":
    sys.exit(main())
