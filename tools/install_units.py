#!/usr/bin/env python3
"""systemd kullanıcı birimlerini depo şablonlarından (conf/*.service) üretip kurar. Şablonlarda depo konumu `@ROOT@` yer tutucusudur:
depo nereye klonlandıysa birimler oraya işaret eder. docs/PRD-PUBLISH.md Y2b.

    python3 tools/install_units.py --check             kurulu birimler = üretilen mi (çıkış 0/1)
    python3 tools/install_units.py --install [ad …]    yaz + `systemctl --user daemon-reload` (servisleri YENİDEN BAŞLATMAZ)
"""
import os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIT_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "systemd", "user")


def units():
    return sorted(f for f in os.listdir(os.path.join(ROOT, "conf")) if f.endswith(".service"))


def render(name, root=ROOT):
    if not re.fullmatch(r"[A-Za-z0-9_./+-]+", root):
        raise ValueError(f"depo yolu birim dosyasına güvenle yazılamaz (boşluk ya da özel karakter): {root!r}")
    return open(os.path.join(ROOT, "conf", name), encoding="utf-8").read().replace("@ROOT@", root)


def installed(name):
    try:
        return open(os.path.join(UNIT_DIR, name), encoding="utf-8").read()
    except OSError:
        return None


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("--")] or units()
    if "--install" in sys.argv:
        os.makedirs(UNIT_DIR, exist_ok=True)
        changed = []
        for n in names:
            txt = render(n)
            if installed(n) != txt:
                open(os.path.join(UNIT_DIR, n), "w", encoding="utf-8").write(txt); changed.append(n)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        print("kuruldu/güncellendi: " + (", ".join(changed) or "değişiklik yok") + " · servisler yeniden başlatılmadı")
        return 0
    diff = [n for n in names if installed(n) != render(n)]
    print("birimler: " + ("kurulu = üretilen" if not diff else "FARKLI ya da kurulu değil: " + ", ".join(diff)))
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
