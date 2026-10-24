#!/usr/bin/env python3
"""tools/chain.py → ~/.config/mic-hifi/mic-clean.conf (chain.CONF_FILE). ÜRETİLMİŞ dosyayı elle düzenleme; `--check` sapmayı yakalar.
Dosya ev dizini ve aygıt adı içerdiği için depoda izlenmez."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain

RAW = chain.RAW_SOURCE
OUT = chain.CONF_FILE


def num(v):
    return f"{v:g}" if isinstance(v, int) else f"{float(v):.6g}" if float(v) != int(v) else f"{float(v):.1f}"


def render(state=None):
    nodes = [f'{{ type = builtin name = hpf{i + 1} label = bq_highpass control = {{ "Freq" = {chain.HPF_HZ:.1f} "Q" = {q} }} }}'
             for i, q in enumerate(chain.HPF_Q)]
    links = ['{ output = "hpf1:Out" input = "hpf2:In" }']
    prev = "hpf2:Out"
    for name, so, label, pin, pout, ctl, _rt in chain.nodes(state if state is not None else chain.load_state()):
        c = " ".join(f'"{k}" = {num(v)}' for k, v in ctl.items())
        nodes.append(f'{{ type = ladspa name = {name} plugin = "{so}" label = "{label}" control = {{ {c} }} }}')
        links.append(f'{{ output = "{prev}" input = "{name}:{pin}" }}')
        prev = f"{name}:{pout}"
    ind = "\n                    "
    return f'''# mic-hifi aşama 2 — ÜRETİLMİŞ DOSYA (tools/gen_conf.py ← tools/chain.py). Elle düzenleme.
# Zincir: mikrofon FL (mono) → HPF {chain.HPF_HZ:g} Hz → seviyeleyici → DeepFilterNet → kapı → limitleyici (değerler: kayıtlı durum, ~/.config/mic-hifi/state.json)
# Ayrı süreçte çalışır (mic-clean.service); kulaklık konsolunun filter-chain.service'ine dokunmaz.

context.properties = {{
    log.level = 0
}}

context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}

context.modules = [
    {{ name = libpipewire-module-rt
        args = {{ }}
        flags = [ ifexists nofail ]
    }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}

    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "{chain.DEVICE_LABEL} (temiz)"
            media.name       = "{chain.DEVICE_LABEL} (temiz)"
            filter.graph = {{
                nodes = [
                    {ind.join(nodes)}
                ]
                links = [
                    {ind.join(links)}
                ]
                inputs  = [ "hpf1:In" ]
                outputs = [ "{prev}" ]
            }}
            audio.rate = 48000
            capture.props = {{
                node.name          = "effect_input.mic_clean"
                node.passive       = true
                audio.position     = [ FL ]
                stream.dont-remix  = true
                target.object      = "{RAW}"
                node.dont-fallback = true
            }}
            playback.props = {{
                node.name      = "effect_output.mic_clean"
                media.class    = Audio/Source
                audio.position = [ MONO ]
            }}
        }}
    }}
]
'''


if __name__ == "__main__":
    txt = render()
    if "--check" in sys.argv:
        cur = open(OUT, encoding="utf-8").read() if os.path.exists(OUT) else ""
        sys.exit(0 if cur == txt else f"SAPMA: {OUT} üretici çıktısıyla aynı değil (python3 tools/gen_conf.py)")
    if not chain.SOURCE_SET:
        sys.exit("mikrofon seçilmemiş: önce `mic device auto` (ya da `mic device set <ad>`)")
    os.makedirs(os.path.dirname(OUT), mode=0o700, exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(txt)
    print("yazıldı:", os.path.normpath(OUT))
