"""V3 taşıyıcı — mikrofonun sahibi olan anahtarlayıcının (mic-main) TEK tanımı. Tasarım: docs/research/O-*.md §5.2, docs/PRD-VOICE.md "V3".

mic-main küçük bir `pipewire -c` sürecidir: 2 kanallı yakalama (AUX0 = kuru/temiz, AUX1 = ıslak/ağır işçi) → karıştırıcı → limitleyici →
sanal mikrofon. Ağır işçi ölse de bu düğüm yaşar; gözcü karıştırıcıyı kuruya çeker. Yakalama kendiliğinden HİÇBİR ŞEYE bağlanmaz
(`node.autoconnect = false`): hedefsiz yakalama varsayılan kaynağa, yani kendi çıkışına bağlanıp geri besleme halkası kurardı.
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chain

MAIN_IN = "effect_input.mic_main"      # parametre düğümü: "mix:Gain 1" (kuru), "mix:Gain 2" (ıslak)
MAIN_OUT = "effect_output.mic_main"
DRY_PORT, WET_PORT = MAIN_IN + ":input_AUX0", MAIN_IN + ":input_AUX1"
CEILING = 0.891                        # −1 dBFS: model çıkışı tavanı aşabilir; tek gerçek tavan koruması burada


QUALITY_DELAY_MS = 1000                # işçinin sabit gecikmesi; conf/mic-watch.service aynı değeri taşır (S31 denetler). Ölçü: 600 → pay −22 ms; 750 → 72 ms; 850 → 3 dk 176 ms ama 9 dk 39 ms (nadir yavaş blok)
DESCRIPTION = chain.DEVICE_LABEL + " (kalite · %s sn gecikmeli)" % ("%g" % (QUALITY_DELAY_MS / 1000)).replace(".", ",")


def render_main(description=DESCRIPTION):
    return f'''# mic-hifi taşıyıcı — ÜRETİLMİŞ DOSYA (tools/carrier.py). Elle düzenleme.
context.properties = {{ log.level = 0 }}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = "{description}"
            media.name       = "{description}"
            filter.graph = {{
                nodes = [
                    {{ type = builtin name = mix label = mixer control = {{ "Gain 1" = 1.0 "Gain 2" = 0.0 }} }}
                    {{ type = ladspa name = limit plugin = "{chain.LSP}" label = "{chain.LSP_PREFIX}limiter_mono" control = {{ "Bypass" = 0 "Threshold (G)" = {CEILING} "Gain boost" = 0 "Automatic level regulation" = 0 "Lookahead (ms)" = 5.0 }} }}
                ]
                links = [ {{ output = "mix:Out" input = "limit:Input" }} ]
                inputs  = [ "mix:In 1" "mix:In 2" ]
                outputs = [ "limit:Output" ]
            }}
            audio.rate = 48000
            capture.props = {{
                node.name         = "{MAIN_IN}"
                node.passive      = true
                node.autoconnect  = false
                audio.position    = [ AUX0 AUX1 ]
                stream.dont-remix = true
            }}
            playback.props = {{
                node.name      = "{MAIN_OUT}"
                media.class    = Audio/Source
                priority.session = 1
                priority.driver  = 1
                audio.position = [ MONO ]
            }}
        }}
    }}
]
'''


def mix_params(dry, wet):
    """Karıştırıcı kazançları için pw-cli set-param gövdesi."""
    return '{ params = [ "mix:Gain 1" %.6g "mix:Gain 2" %.6g ] }' % (dry, wet)


if __name__ == "__main__":
    sys.stdout.write(render_main())
