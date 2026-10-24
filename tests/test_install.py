#!/usr/bin/env python3
"""Yol bağımsızlığı (chain.find_plugin, tools/install_units.py) — docs/PRD-PUBLISH.md Y2b. Canlıya dokunmaz.

Y2-7 eklenti bulma: LADSPA_PATH önce, sonra bilinen dizinler; yoksa çıplak ad; bu makinede eski sabit yolla aynı   neden: /usr/lib64 her dağıtımda yok
Y2-8 birim şablonlarında depo konumu yok (@ROOT@); kurucu gerçek konumla üretir; başka kökle üretimde o kök görünür   neden: depo başka yere klonlanabilir
"""
import os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


try:
    import chain
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "a"), os.path.join(d, "b"); os.makedirs(a); os.makedirs(b)
        open(os.path.join(b, "x.so"), "w").close()
        r1 = chain.find_plugin("x.so", env={"LADSPA_PATH": f"{a}:{b}"}, dirs=[])
        open(os.path.join(a, "x.so"), "w").close()
        r2 = chain.find_plugin("x.so", env={"LADSPA_PATH": f"{a}:{b}"}, dirs=[])
        r3 = chain.find_plugin("x.so", env={}, dirs=[b]); r4 = chain.find_plugin("yok.so", env={}, dirs=[a, b])
        ok = r1 == os.path.join(b, "x.so") and r2 == os.path.join(a, "x.so") and r3 == os.path.join(b, "x.so") and r4 == "yok.so"
    here = chain.LSP
    check("Y2-7", ok and (not os.path.exists("/usr/lib64/ladspa/lsp-plugins-ladspa.so") or here == "/usr/lib64/ladspa/lsp-plugins-ladspa.so"),
          f"arama sırası doğru: {ok} · bu makinede LSP: {here}")
except (ImportError, AttributeError) as e:
    check("Y2-7", False, f"işlev yok: {e}")
units = sorted(f for f in os.listdir(os.path.join(ROOT, "conf")) if f.endswith(".service"))
leak = [f for f in units if "projects/mic-hifi" in open(os.path.join(ROOT, "conf", f), encoding="utf-8").read()]
try:
    import install_units
    other = install_units.render("mic-console.service", "/opt/baska/mic")
    try:
        install_units.render("mic-console.service", "/opt/baska yer/mic"); spaced = False
    except ValueError:
        spaced = True          # boşluklu kök birim satırını böler → açık hata
    mine = install_units.render("mic-clean.service")
    ok8 = not leak and "/opt/baska/mic/console/server.py" in other and spaced and "@ROOT@" not in other and ROOT in mine and "@ROOT@" not in mine
    check("Y2-8", ok8, f"şablonda depo konumu olanlar: {leak or 'yok'} · başka kökle üretim doğru: {'/opt/baska/mic/console/server.py' in other} · boşluklu kök reddedildi: {spaced} · yer tutucu kalmadı: {'@ROOT@' not in mine}")
except ImportError as e:
    check("Y2-8", False, f"şablonda depo konumu olanlar: {leak or 'yok'} · kurucu yok: {e}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
