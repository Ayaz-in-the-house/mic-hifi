#!/usr/bin/env python3
"""mic-hifi ağır işçi — PipeWire-JACK istemcisi içinde blok-blok model çalıştırır. Tasarım: docs/research/O-*.md §4, docs/PRD-VOICE.md "V3".

Portlar: in_model (modele giden ses) · in_dry (yedek, hizalı kuru ses) · out.
Sözleşme: çıkış HER ZAMAN girişin tam D örnek gecikmişidir. Model bloğu zamanında yetiştirdiyse o örnekler modelden, yetiştiremediyse
aynı zaman dilimindeki kuru sesten gelir (kısa çapraz geçişle). Yani model geç kalınca ses ne kesilir, ne tekrar eder, ne kayar.

Zaman çizgisi tek bir mutlak örnek sayacıdır (n): giriş, kuru ve ıslak tamponlar aynı mutlak indeksle adreslenir (dairesel).
Gerçek zaman geri çağrısı yalnız kopyalar ve kazanç rampası uygular; model ayrı, normal öncelikli iş parçacığında koşar.

Çalıştırma: pw-jack python worker.py --model identity --delay-ms 300 --block 4800 --status <yol.json>
"""
import argparse, json, os, random, signal, sys, threading, time

import jack
import numpy as np

SR_EXPECT = 48000


class Identity:
    """Sahte model: gecikmeli kimlik. Taşıyıcı testleri bununla yapılır (gerçek model darbeyi/çıtırtıyı "temizleyip" ölçümü bozar)."""

    def __init__(self, gain=1.0, late_prob=0.0, late_factor=2.0, block_s=0.1, seed=1, latency=0):
        self.gain, self.late_prob, self.late_factor, self.block_s = gain, late_prob, late_factor, block_s
        self.rng = random.Random(seed)
        self.latency = int(latency)                       # ileri bakışlı modelin taklidi: çıktı girişe göre bu kadar örnek geride
        self.tail = np.zeros(self.latency, np.float32)

    def __call__(self, x):
        if self.late_prob and self.rng.random() < self.late_prob:
            time.sleep(self.block_s * self.late_factor)   # bloğun süresinin katı kadar geç kal
        if self.latency:
            z = np.concatenate((self.tail, x)); x, self.tail = z[:len(x)], z[len(x):].copy()
        return x * self.gain if self.gain != 1.0 else x


class Worker:
    def __init__(self, make_model, latency, delay, block, fade, name="mic_heavy", status=None, hold=8):
        # Model ARKADA yüklenir (make_model iş parçacığında çağrılır): ses istemcisi hemen açılır ve yükleme sürerken hizalı kuru verir →
        # gözcü işçiye hemen geçebilir, açılıştaki zaman sıçraması başa çekilir (docs/PRD-VOICE.md O17).
        self.make_model, self.model, self.D, self.N, self.F, self.status_path, self.hold = make_model, None, delay, block, fade, status, hold
        self.exit_code = 0
        # Model ileri bakışlıysa (pencere kenarını atıyorsa) çıktısı girişe göre L örnek geridedir: ıslak tampona k·N − L konumuna yazılır.
        # Sözleşme değişmez: çıkış her zaman girişin tam D gecikmişi. D, blok + L + hesap payını karşılamalıdır.
        self.L = int(latency)
        if delay < block + self.L + 1024:
            sys.exit(f"gecikme {delay} örnek yetersiz: blok {block} + model gecikmesi {self.L} + pay 1024 gerekir")
        self.R = 1 << int(np.ceil(np.log2(delay + block * 4 + 16384)))   # dairesel tampon boyu (2'nin kuvveti)
        self.mask = self.R - 1
        self.inb = np.zeros(self.R, np.float32)    # modele giden giriş
        self.dryb = np.zeros(self.R, np.float32)   # hizalı yedek
        self.wetb = np.zeros(self.R, np.float32)   # model çıkışı
        self.n = 0              # yazılmış giriş örneği (mutlak) — yalnız RT iş parçacığı yazar
        self.wet_ready = 0      # modelin bitirdiği mutlak örnek — yalnız model iş parçacığı yazar
        self.w = 0.0            # ıslak ağırlığı (0 = kuru, 1 = ıslak)
        self.good = 0           # art arda zamanında gelen kuantum sayısı (ıslağa dönüş histerezisi)
        self.fallbacks = 0      # ıslaktan kuruya düşüş sayısı
        self.dry_samples = 0    # kuru çalınan örnek
        self.xruns = 0
        self.margin_min = None  # ıslaktayken görülen en dar zaman payı (örnek): ıslak hazır − (çalınacak son örnek + geçiş payı)
        self.model_s_max = 0.0  # en uzun model bloğu hesabı (sn)
        self.stop = threading.Event()
        self.client = jack.Client(name, no_start_server=True)
        self.p_model = self.client.inports.register("in_model")
        self.p_dry = self.client.inports.register("in_dry")
        self.p_out = self.client.outports.register("out")
        self.client.set_process_callback(self.process)
        self.client.set_xrun_callback(self._xrun)
        self.client.set_shutdown_callback(lambda status, reason: self.stop.set())

    def _xrun(self, delay):
        self.xruns += 1

    def _put(self, buf, start, data):
        i, k = start & self.mask, len(data)
        if i + k <= self.R:
            buf[i:i + k] = data
        else:
            h = self.R - i
            buf[i:] = data[:h]
            buf[:k - h] = data[h:]

    def _get(self, buf, start, k):
        i = start & self.mask
        if i + k <= self.R:
            return buf[i:i + k]
        return np.concatenate((buf[i:], buf[:k - (self.R - i)]))

    def process(self, frames):
        n = self.n
        self._put(self.inb, n, self.p_model.get_array())
        self._put(self.dryb, n, self.p_dry.get_array())
        self.n = n + frames
        pos = self.n - frames - self.D     # bu kuantumda çalınacak ilk mutlak örnek
        out = self.p_out.get_array()
        if pos < 0:
            out[:] = 0.0
            return
        dry = self._get(self.dryb, pos, frames)
        # Islak ancak bu kuantum + çapraz geçiş payı kadar hazırsa "var" sayılır: kuruya kayarken kullanılacak ıslak örnekler gerçek olsun.
        slack = self.wet_ready - (pos + frames + self.F)
        have = slack >= 0
        if self.w == 1.0 and (self.margin_min is None or slack < self.margin_min):
            self.margin_min = slack
        if have:
            self.good += 1
        else:
            if self.good >= self.hold and self.w > 0.0:
                self.fallbacks += 1
            self.good = 0
        target = 1.0 if self.good >= self.hold else 0.0
        if self.w == target:
            if target == 1.0:
                out[:] = self._get(self.wetb, pos, frames)
            else:
                out[:] = dry
                self.dry_samples += frames
            return
        # çapraz geçiş: w, F örnekte hedefe doğrusal gider (kuantumlar arası sürer)
        step = (1.0 / self.F) if target > self.w else (-1.0 / self.F)
        ramp = np.clip(self.w + step * np.arange(1, frames + 1, dtype=np.float32), 0.0, 1.0)
        wet = self._get(self.wetb, pos, frames) if self.wet_ready >= pos + frames else dry
        out[:] = wet * ramp + dry * (1.0 - ramp)
        self.w = float(ramp[-1])

    def model_loop(self):
        try:
            self.model = self.make_model()
        except SystemExit as e:                              # model "kaynak yok" diye çıktı (75): süreç aynı kodla bitsin → gözcü kilitler
            self.exit_code = e.code if isinstance(e.code, int) else 1
            self.stop.set()
            return
        except Exception as e:                               # ortam/dosya eksik de kalıcıdır: yeniden deneme düzeltmez
            print(f"model yüklenemedi: {e}", file=sys.stderr, flush=True)
            self.exit_code = 75
            self.stop.set()
            return
        if int(getattr(self.model, "latency", 0)) != self.L:
            print(f"model gecikmesi {getattr(self.model, 'latency', 0)} ≠ beyan {self.L}", file=sys.stderr, flush=True)
            self.exit_code = 1
            self.stop.set()
            return
        k = max(0, self.n // self.N - 1)   # yükleme sırasında geçen bloklar atlanır; bir önceki blok modelin geçmişini doldurur
        while not self.stop.is_set():
            end = (k + 1) * self.N
            if self.n < end:
                time.sleep(0.002)
                continue
            if self.n - k * self.N > self.R - self.N:        # model çok geride kaldı: tampon üzerine yazıldı → güncel bloğa atla
                k = (self.n - self.D) // self.N
                continue
            t0 = time.monotonic()
            y = np.asarray(self.model(self._get(self.inb, k * self.N, self.N).copy()), np.float32)
            if k > 1:                                       # ilk bloklar ısınma (çekirdek derleme, bellek ayırma)
                self.model_s_max = max(self.model_s_max, time.monotonic() - t0)
            start = k * self.N - self.L
            if start < 0:                                  # ilk blok: zaman çizgisinin başından önceki kısım atılır
                y, start = y[-start:], 0
            self._put(self.wetb, start, y)
            self.wet_ready = end - self.L
            k += 1

    def write_status(self):
        s = {"pid": os.getpid(), "model_ready": self.model is not None, "D_samples": self.D, "D_ms": round(self.D / SR_EXPECT * 1000, 2), "block": self.N, "wet": round(self.w, 3),
             "fallback_count": self.fallbacks, "dry_ms": round(self.dry_samples / SR_EXPECT * 1000, 1), "xruns": self.xruns,
             "lead_samples": self.wet_ready - (self.n - self.D),
             "margin_min_ms": None if self.margin_min is None else round(self.margin_min / SR_EXPECT * 1000, 1), "model_ms_max": round(self.model_s_max * 1000, 1), "t": round(time.time(), 2)}
        tmp = self.status_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(s, f)
        os.replace(tmp, self.status_path)

    def run(self):
        with self.client:
            if self.client.samplerate != SR_EXPECT:
                sys.exit(f"örnekleme hızı {self.client.samplerate}, {SR_EXPECT} bekleniyordu")
            print("READY", flush=True)
            t = threading.Thread(target=self.model_loop, daemon=True)
            t.start()
            while not self.stop.wait(0.25):                  # kalp atışı ana iş parçacığından: model yüklenirken de, model takılsa da atar
                if self.status_path:                         # (süreç donarsa atmaz → gözcü kuruya çeker)
                    self.write_status()
            t.join(timeout=2)
        if self.status_path:
            self.write_status()


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--model", default="identity", choices=["identity", "mossformer"])
    a.add_argument("--latency-samples", type=int, default=0, help="yalnız sahte model: ileri bakış taklidi")
    a.add_argument("--window-ms", type=float, default=500.0, help="yalnız mossformer: çözme penceresi (blok = adım)")
    a.add_argument("--device", default="cuda")
    a.add_argument("--delay-ms", type=float, default=300.0)
    a.add_argument("--block", type=int, default=4800)
    a.add_argument("--fade-ms", type=float, default=20.0)
    a.add_argument("--gain", type=float, default=1.0)
    a.add_argument("--late-prob", type=float, default=0.0)
    a.add_argument("--late-factor", type=float, default=2.0)
    a.add_argument("--load-delay", type=float, default=0.0, help="yalnız sahte model: yükleme süresi taklidi (sn)")
    a.add_argument("--load-fail", action="store_true", help="yalnız sahte model: yükleme 'kaynak yok' (75) ile başarısız")
    a.add_argument("--name", default="mic_heavy")
    a.add_argument("--status")
    o = a.parse_args()
    if o.model == "mossformer":
        window = int(round(o.window_ms * SR_EXPECT / 1000))
        latency = (window - o.block) // 2

        def make():
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from models_v4 import MossFormer              # torch yalnız bu hat seçilince yüklenir (hafif ortamda torch yok)
            return MossFormer(o.block, window, o.device)
    else:
        latency = o.latency_samples

        def make():
            if o.load_fail:
                sys.exit(75)                              # sınama: "kaynak yok"
            time.sleep(o.load_delay)                      # sınama: yavaş model yüklemesi
            return Identity(o.gain, o.late_prob, o.late_factor, o.block / SR_EXPECT, latency=o.latency_samples)
    w = Worker(make, latency, int(round(o.delay_ms * SR_EXPECT / 1000)), o.block, int(round(o.fade_ms * SR_EXPECT / 1000)), o.name, o.status)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: w.stop.set())
    w.run()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(w.exit_code)   # yorumlayıcının olağan kapanışı (torch/CUDA yıkımı) 2 sn'yi aşıyor → gözcü SIGKILL'e düşüyordu (ölçüldü); ses istemcisi zaten kapandı


if __name__ == "__main__":
    main()
