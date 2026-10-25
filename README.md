<p align="center"><img src="assets/icon.svg" width="96" alt="mic-hifi"></p>

# mic-hifi

**English** · [Türkçe](README.tr.md)

A local system that processes a USB microphone layer by layer on PipeWire and exposes the result as a **virtual microphone**, plus a small web panel to control it.
Audio never leaves your computer: no cloud, no account.

Chain: high-pass (95 Hz) → leveller (lifts whispering, freezes in silence) → compressor → noise suppression (DeepFilterNet3) → silence gate →
tone (8-band equaliser, ready-made characters) → multiband dynamics (fullness, boominess, harshness, sibilance) → saturation → ceiling limiter.
Optional: pitch / vocal-tract shift and a second, delayed "quality" microphone (a stronger noise remover running on the graphics card).

## Roadmap — what doing it unlocks

The cleaning chain and the panel were built by measurement and run live. The microphone itself (capsule, placement, in-device processing) and listener-side verification have not been broken down yet. Gains in the table are **expectations, not measured results**.

| layer | known today (done) | not done · untested · unknown | when done, it unlocks | method / source |
|---|---|---|---|---|
| **L1** acoustics: capsule, distance, room | Almost all noise is below 80 Hz; self-noise ~27 dB(A); 16 bit / ~17 kHz | Frequency response not measured (no reference mic) → no tone correction. Effect of mouth distance only calculated (~+15 dB, not measured). Room reverb not addressed | **Cheapest gain:** move the mic to 4–5 cm from the mouth (free). Once measured, tone can be flattened to sound like your own voice | 5-minute distance test; response measurement with a reference mic or known source |
| **L2** device: inside the USB mic | The device adjusts the ring-mic gain internally; its mute button shows in the panel | In-device automatic gain / processing not fully characterised. The vendor control channel is **intentionally not written to** | Device and chain stop "fighting" each other | Read-only measurement; no commands sent to the device |
| **L3** Linux / PipeWire / capture | Virtual microphone; a watchdog repairs profile drift; restart ~2.5 s | Under heavy multi-core load the noise suppressor can miss blocks (short dropouts) — **open**; root cause of profile drift not named | Dropout-free live use under load | Move the suppressor into a separate worker process (carrier design tested in isolation) + long soak run |
| **L4** cleaning chain | **Strong:** whisper SNR 8.6 → 27.1 dB; leveller, compressor, DeepFilterNet3, gate, split-band de-esser, dynamic EQ; output targets −23 / −16 LUFS, true peak ≤ −1 dBTP | Only Whisper mode passed its acceptance test; Normal and Night values not settled by measurement. No live mouth-click / crackle removal, no dereverb; echo cancellation tried but not wired in. Most settings not verified by ear | Near-studio delivery; echo cancellation for speaker calls | Test-set recording with your own voice (~20 min) + the panel's diagnostic recording |
| **L5** quality path (GPU) | Second, ~1 s delayed "quality" microphone live (MossFormer2); file enhancement (`mic enhance`); offline it beats DeepFilterNet (SNR 37.1 vs 30.7 dB) | Not verified by ear; setup not documented in this repo; not the main microphone | Cleaner sound for recording and streaming where latency does not matter | Setup documentation + listening test |
| **L6** voice character, pitch, conversion | 10 characters, intensity, your own characters; pitch (Rubber Band) | Formant not adjustable separately; AI voice conversion not done | Change your own voice colour; convert to another voice with AI | Open-source voice-conversion models (licence and latency measured) |
| **L7** panel, install, distribution | Panel, diagnostic recording, profiles; mic chosen with `mic device`; Apache-2.0; clean release tree | Install not walked end to end on a clean machine; setup wizard postponed; no English UI; no CI; DeepFilterNet mandatory | Others can install and use it on their own machine | Clean-machine/VM install walk + CI with synthetic signals |

**The ceiling you cannot pass.** The biggest quality gap is hardware: ~27 dB(A) self-noise and 16 bit / ~17 kHz. Software suppresses noise afterwards; a good microphone never produces it — software cannot close that gap. Realistic target: clean sound for calls and streaming; studio vocals are out of reach with this microphone.

**Open-source angle.** A whisper mode was found in none of the commercial products reviewed; the chain is fully local on PipeWire. Because the microphone is chosen with `mic device`, the method applies to other USB microphones too — even though only one has been measured.

**Plan:** the two biggest gains are still free: move the mic closer and record the test set. Then dropout-free live use (L3), then listening verification and documenting the quality path.

- [ ] **L1** distance measurement + frequency response
- [ ] **L2** characterise in-device gain (read-only)
- [ ] **L3** dropout-free under load (suppressor in a separate worker)
- [ ] **L4** settle Normal/Night by measurement; mouth clicks, echo cancellation
- [ ] **L5** quality-path setup docs + listening test
- [ ] **L6** formant + AI voice conversion
- [ ] **L7** clean-machine install walk, English UI, CI

## Who can do what — manufacturer ↔ user

Part of what it takes to get the best sound from a microphone exists **only at the manufacturer** (capsule measurements, processing inside the device); another part the **user can measure themselves**. As long as the manufacturer does not publish, software corrects by guesswork; every user measurement closes the gap.

### Data the manufacturer should publish

| data | why it matters | standard / how |
|---|---|---|
| Frequency response (on-axis, at a stated distance) and polar pattern | The only solid basis for tone correction; with no reference measurement, tone is not corrected today | Anechoic measurement, as CSV (e.g. IEC 60268-4 methods) |
| Self-noise (dB(A)), sensitivity (dBFS at 94 dB SPL), maximum SPL | The ceiling of how clean quiet speech such as whispering can get | Datasheet values |
| Real ADC resolution and sample rate (the converter itself, not just what the USB descriptor says) | Tells whether the 16 bit / ~17 kHz limit comes from the hardware or from configuration | Datasheet + USB Audio Class descriptor |
| In-device processing: automatic gain, limiter, noise gate, high-pass — and whether each can be switched off | The device's own automatic gain "fights" the software chain; on this device gain is adjusted internally | Processing list + USB Audio Class controls |
| Control channel (HID) protocol documentation | Gain, mute, LEDs can be managed safely from any platform; writing to an undocumented channel is risky, so this project does not | Open protocol document |
| Firmware version and update path | You know which version a measurement belongs to | Release notes |

### Tests users can run themselves (with this repo)

| test | what it tells you | how | data you can share |
|---|---|---|---|
| Status check | Which microphone is processed, is the chain running, is the default input right | `bin/mic status` · `python3 tests/verify.py` | Acceptance output |
| Room tone | The room's noise floor — whether Whisper/Night mode has enough headroom | Panel → diagnostic recording → "room tone" | Measured level (dBFS / LUFS) |
| Distance test | The gain from moving the mic closer (calculated ~+15 dB, not measured) | Record the same sentence at 15 cm and 5 cm, then measure | Difference between the two |
| Test-set recording | Whisper / quiet / normal voice × keyboard / breath; settling mode values by measurement | The panel's diagnostic recording steps | Measurement results (not the audio itself) |
| Delivery measurement | Loudness (LUFS) and true peak — does it meet the call / streaming target | Panel → "measure recording" | LUFS / dBTP values |
| Before/after listening | Record raw and clean at the same time, then play them back in turn | `bin/mic ab 8` | Preference note |
| Verification by ear | How characters and pitch sound on your own voice | Panel → "compare by ear" | Feedback |

**Privacy:** recordings never leave your computer and never enter this repository; what you share are measurement results, not the audio.

### Recommendations to manufacturers — biggest quality gain for the smallest cost

Cost and gain are estimates; not measured on this microphone.

| recommendation | added cost | expected gain |
|---|---|---|
| Publish factory measurements (frequency response, self-noise, sensitivity) | **Zero** — already measured in production | Software corrects tone accurately; users know the mic's real limits |
| Expose 24 bit / 48 kHz over USB where the ADC supports it | Firmware only | More headroom for quiet speech, wider bandwidth |
| Make in-device automatic gain switchable (via a USB Audio Class control) | Firmware only | The software chain behaves predictably; gain "pumping" stops |
| Enable a default high-pass (~80 Hz) in the device | Firmware only | On this mic almost all noise is below 80 Hz: hum and desk rumble are cut at the source |
| Ship a foam windscreen / pop filter and a simple shock mount | A few cents to a few euros | Fewer plosive pops and less desk-borne vibration |
| Document the control channel (HID) | Writing a document | Settings managed safely from any platform |
| Low-noise supply for the preamp (a clean regulator) | Very low parts cost | Lower self-noise — less noise for software to suppress afterwards |

## Screenshots

![Microphone console: mode, voice character and tone settings](assets/screenshots/panel.png)

![Diagnostic recording: fine-tuning with room tone and short sample recordings](assets/screenshots/teshis-kaydi.png)

## Requirements

- Linux, **PipeWire** (measured with 1.6.8) and WirePlumber; the `pactl`, `pw-link`, `pw-cli`, `pw-record` commands
- Python 3 (the panel and the chain use only the standard library); `requirements.txt` (numpy, scipy) for the measurement tools and tests
- LSP Plugins LADSPA package (from your distribution, e.g. `lsp-plugins-ladspa` on Fedora)
- DeepFilterNet LADSPA plugin v0.5.6: downloaded from upstream and placed at `~/.local/lib/mic-hifi/libdeep_filter_ladspa.so`; its digest is pinned in `plugins.lock.json`
- Optional: Rubber Band LADSPA plugin (for pitch; on Fedora `bash tools/install_rubberband.sh` installs it without root)

This repository contains none of the third-party components above (see `NOTICE`).

## Installation

```bash
bin/mic device list                      # USB microphone candidates
bin/mic device set <source name> --label "My mic"   # with a single candidate: bin/mic device auto
python3 tools/plugins.py check           # do the plugin digests match the lock?
python3 tools/gen_conf.py                # generate the PipeWire configuration (~/.config/mic-hifi/mic-clean.conf)
python3 tools/install_units.py --install # install the systemd user units pointing at this checkout
systemctl --user enable --now mic-clean mic-prio mic-console
bin/mic console                          # panel address (with a personal key for the first visit)
python3 tests/verify.py                  # verification on the live chain
```

Panel: `http://127.0.0.1:8767/` (reachable only from this computer). In your apps, pick "<label> (temiz)" as the microphone ("temiz" = clean).
Uninstall: `systemctl --user disable --now mic-clean mic-prio mic-console mic-main mic-watch`.

Tests that need no personal recording: `python3 tests/test_console_server.py`, `python3 tests/test_device.py`, `python3 tests/test_install.py`,
`python3 tests/test_plugins.py`, `python3 tests/test_measure.py`, `python3 tests/test_conf_load.py`, `python3 tests/test_tone.py --fast`.

## Limitations

- PipeWire only; PulseAudio or JACK on their own are not supported.
- **Measured on a single machine (Fedora 44) and a single microphone.** The installation steps have not been walked end to end on a clean machine; plugin paths may differ on other distributions (`LADSPA_PATH` is honoured).
- The noise suppressor continuously uses about a third of a CPU core. If a heavy memory-bound job (e.g. a compile) runs at the same time, short dropouts can occur; the panel shows the count for the last 10 minutes.
- Settings were chosen by measurement; **verifying them by ear is up to you** — you decide how the characters and pitch sound on your own voice.
- The user interface is in Turkish.
- The "quality" microphone (`mic-main`, `mic-watch`) and `bin/mic enhance` need a separate Python environment, an NVIDIA graphics card and a model you download yourself (MossFormer2_SE_48K, Apache-2.0); this repository contains neither the model nor the environment, and their setup is not documented here. If you will not use them, do not enable those two units.
- Design notes and measurement logs are not published in this repository; `docs/...` references in the code point to those notes.

## License

Apache-2.0 (`LICENSE`). Third-party components used at runtime and their licences: `NOTICE`. Security reports: `SECURITY.md`. Contributing: `CONTRIBUTING.md`.
