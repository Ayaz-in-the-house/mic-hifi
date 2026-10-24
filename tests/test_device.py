#!/usr/bin/env python3
"""Aygıt ayarı ve keşfi (tools/chain.py, bin/mic device) — docs/PRD-PUBLISH.md Y2a. Canlıya dokunmaz.

Y2-1 kaynak çözümü: ortam > dosya > "ayarlanmadı"; bozuk dosyada çökme yok          neden: deterministik, içe aktarmada yan etkisiz
Y2-2 keşif: tek USB girişi → o; 0 / ≥2 → seçim yok + adaylar; monitor ve USB olmayan aday değil   neden: yanlış mikrofonu sessizce seçme
Y2-3 etiket: sanal mikrofon adları etiketten; varsayılan "Mikrofon"                  neden: marka adı koda gömülü olmasın
Y2-4 kod dizinlerinde seri numaralı aygıt adı ve ev dizini yok                       neden: Y1 tabanındaki kod bulguları kapanır
Y2-5 üretilmiş conf izlenmiyor; üretici ayar dizinine yazar; birim %E yolunu kullanır   neden: üretilmiş, kişisel dosya depoda durmaz
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
fails, ran = [], []


def check(tp, ok, d=""):
    ran.append(tp); print(f"{'PASS' if ok else 'FAIL'}  {tp}  {d}", flush=True)
    if not ok: fails.append(tp)


def chain_val(expr, cfg=None, env_src=None):
    """Temiz bir yorumlayıcıda chain'i verilen ayar dizini/ortamla içe aktarıp ifadeyi döndürür."""
    d = tempfile.mkdtemp()
    if cfg is not None:
        os.makedirs(os.path.join(d, "mic-hifi")); open(os.path.join(d, "mic-hifi", "device.json"), "w").write(cfg)
    env = {k: v for k, v in os.environ.items() if k != "MIC_SOURCE"}
    env.update(XDG_CONFIG_HOME=d, PYTHONPATH=os.path.join(ROOT, "tools"))
    if env_src: env["MIC_SOURCE"] = env_src
    r = subprocess.run([sys.executable, "-c", f"import chain, carrier, gen_conf, json; print(json.dumps({expr}))"], env=env, capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else f"HATA: {r.stderr.strip()[-120:]}"


A, B = "alsa_input.usb-Acme_Mic_1-00.mono-fallback", "alsa_input.usb-Other_2-00.analog-stereo"
v = [chain_val("chain.RAW_SOURCE", json.dumps({"source": A}), B), chain_val("chain.RAW_SOURCE", json.dumps({"source": A})), chain_val("chain.RAW_SOURCE"),
     chain_val("chain.RAW_SOURCE", "{bozuk"), chain_val("chain.SOURCE_SET", json.dumps({"source": A})), chain_val("chain.SOURCE_SET")]
check("Y2-1", v[0] == B and v[1] == A and isinstance(v[2], str) and "AYARLANMADI" in v[2] and v[3] == v[2] and v[4] is True and v[5] is False, f"ortam+dosya → {v[0]} · dosya → {v[1]} · hiçbiri → {v[2]} · bozuk → {v[3]} · ayarlı mı: {v[4]}/{v[5]}")
try:
    import chain
    mk = lambda *names: json.dumps([{"name": n} for n in names])
    one = chain.discover_sources(mk("alsa_output.pci.monitor", "alsa_input.pci-0000.analog-stereo", A, "alsa_output.usb-Acme_Mic_1-00.analog-stereo.monitor", "effect_output.mic_clean"))
    two = chain.discover_sources(mk(A, B)); none = chain.discover_sources(mk("alsa_input.pci-0000.analog-stereo")); bad = chain.discover_sources("{bozuk")
    check("Y2-2", one == (A, [A]) and two == (None, [A, B]) and none == (None, []) and bad == (None, []), f"tek → {one[0]} · iki → {two} · yok → {none} · bozuk → {bad}")
except (ImportError, AttributeError) as e:
    check("Y2-2", False, f"işlev yok: {e}")
lab = [chain_val("[chain.DEVICE_LABEL, carrier.DESCRIPTION, 'node.description = \"Acme (temiz)\"' in gen_conf.render(dict(chain.DEFAULT_STATE))]", json.dumps({"source": A, "label": "Acme"})),
       chain_val("[chain.DEVICE_LABEL, 'node.description = \"Mikrofon (temiz)\"' in gen_conf.render(dict(chain.DEFAULT_STATE))]")]
check("Y2-3", isinstance(lab[0], list) and lab[0][0] == "Acme" and lab[0][1].startswith("Acme (kalite") and lab[0][2] is True and isinstance(lab[1], list) and lab[1] == ["Mikrofon", True], f"etiketli → {lab[0]} · varsayılan → {lab[1]}")
import oss_audit
code = [f for f in subprocess.run(["git", "ls-files", "tools", "bin", "tests", "console", "heavy", "conf"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
        if f and f not in oss_audit.FIXTURES and f != "tests/test_device.py"]   # uydurma desen örneği taşıyan sınama dosyaları: kapının kendi listesi
hits = []
for f in code:
    try:
        for i, line in enumerate(open(os.path.join(ROOT, f), encoding="utf-8"), 1):
            hits += [f"{f}:{i} {n}" for n, _m in oss_audit.scan_text(line) if n in ("usb seri numaralı aygıt", "ev dizini")]
    except (OSError, UnicodeDecodeError):
        pass
check("Y2-4", not hits, f"kod dizinlerinde bulgu: {hits or 'yok'}")
tracked = subprocess.run(["git", "ls-files", "conf/mic-clean.conf"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
out = chain_val("gen_conf.OUT")
unit = open(os.path.join(ROOT, "conf", "mic-clean.service"), encoding="utf-8").read()
check("Y2-5", not tracked and isinstance(out, str) and out.endswith("/mic-hifi/mic-clean.conf") and "/conf/" not in out and "pipewire -c %E/mic-hifi/mic-clean.conf" in unit,
      f"izleniyor mu: {bool(tracked)} · üretici hedefi: {out} · birim %E kullanıyor: {'pipewire -c %E/mic-hifi/mic-clean.conf' in unit}")
print(f"\n{'PASS' if not fails else 'FAIL'}: {len(ran) - len(fails)}/{len(ran)}")
sys.exit(1 if fails else 0)
