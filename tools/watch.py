#!/usr/bin/env python3
"""mic-hifi gözcü (V3 taşıyıcı) — dinleyen varsa ağır işçiyi çalıştırır, anahtarlayıcıyı kuru ↔ ıslak arasında sürer. Tasarım: docs/PRD-VOICE.md "Aşama 4".

Değişmezler:
  • Güvenli durum KURUDUR: açılışta, işçi ölünce/donunca, dinleyen gidince, bütçe bitince karıştırıcı (1, 0).
  • Karıştırıcı işçiye, işçi yaşadığını (taze kalp atışı) bildirince verilir ("taşıyıcıda"): işçi model hazır olana dek hizalı kuru verir.
    "ıslak" olayı işçi wet == 1 deyince yazılır (modelin sesi dinleyene ulaşıyor).
  • Ölçer sınıfı dinleyen (seviye göstergesi) gerçek dinleyen sayılmaz.
  • Yalnız KENDİ başlattığı (ya da durum dosyasındaki, komut satırı işçi olan) süreci kapatır.

Kullanım: watch.py --worker-cmd "<komut>" --status <yol.json> [--hold 20] [--events <yol.jsonl>]
PipeWire örneği ortamdan gelir (PIPEWIRE_REMOTE / XDG_RUNTIME_DIR).
"""
import argparse, json, os, select, shlex, signal, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import carrier

from heavy_guard import METERS   # ölçer sınıfı dinleyenler (ayar pencereleri, panelin göstergesi): gerçek dinleyen sayılmaz — tek tanım
WORKER_NODE = "mic_heavy"
STALE_S, RAMP_STEPS, RAMP_STEP_S = 0.9, 5, 0.012
BUDGET_N, BUDGET_S = 3, 600.0
IDLE_POLL_S, IDLE_SCAN_S, ACTIVE_SCAN_S, NODRY_SCAN_S = 2.0, 10.0, 1.0, 1.0   # olay kaçarsa yedek yoklama aralıkları
EX_TEMPFAIL = 75   # işçinin "kaynak yok, yeniden deneme" çıkış kodu (sysexits.h)


def sh(*cmd, timeout=3):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, OSError):
        return ""


class Watch:
    def __init__(self, o):
        self.o, self.proc, self.state, self.starts, self.wet = o, None, "idle", [], 0.0
        self.last_listener, self.spawned_at, self.stop = 0.0, 0.0, False
        self.ls, self.scanned, self.dirty, self.dry_ok = set(), 0.0, True, False
        self.latency = None

    def trim_events(self, limit=1 << 20):
        """Olay günlüğü sınırsız büyümesin (gözcü 7/24 koşar): açılışta sınırı aşmışsa sıfırlanır."""
        try:
            if self.o.events and os.path.getsize(self.o.events) > limit:
                os.truncate(self.o.events, 0)
        except OSError:
            pass

    def event(self, kind, **kw):
        rec = {"t": round(time.time(), 3), "event": kind, **kw}
        if self.o.events:
            with open(self.o.events, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False), flush=True)

    # ── grafik ──
    def scan(self, now):
        """Grafiği TEK `pw-link -l` çağrısıyla okur: mic-main çıkışına bağlı GERÇEK dinleyenler (ölçerler ve işçi hariç) + kuru bağ var mı.
        Yalnız bağ olayı geldiğinde ya da yedek aralık dolduğunda çağrılır (boşta 20 çatal/sn → %11 çekirdek ölçüldü; W12)."""
        out, cur, res, dry = sh("pw-link", "-l"), None, set(), False
        for line in out.splitlines():
            if not line.startswith(" "):
                cur = line.strip()
            elif cur and cur.startswith(carrier.MAIN_OUT + ":") and "|->" in line:
                node = line.split("|->", 1)[1].strip().rsplit(":", 1)[0]
                if node != WORKER_NODE and not node.startswith(METERS):
                    res.add(node)
            elif cur == carrier.DRY_PORT and "|<-" in line and line.split("|<-", 1)[1].strip() == self.o.dry_src:
                dry = True
        self.ls, self.scanned, self.dirty, self.dry_ok = res, now, False, dry
        if not dry:
            # Kuru yol (temiz kaynak → anahtarlayıcının kuru girişi). Yakalama bilerek kendiliğinden bağlanmaz; bağ yoksa mikrofon sessizdir.
            r = subprocess.run(["pw-link", self.o.dry_src, carrier.DRY_PORT], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                self.dry_ok = True
                self.event("kuru bağ kuruldu")

    def report_latency(self, samples):
        """Kalite mikrofonunun bildirdiği gecikme (O09): işçi taşırken D, kuruda 0. Görüntüyle kaydeden uygulama sesi buna göre eşler."""
        if samples != self.latency:
            sh("pw-cli", "set-param", carrier.MAIN_OUT, "ProcessLatency", "{ rate = %d }" % samples)
            self.latency = samples

    def mix(self, dry, wet):
        sh("pw-cli", "set-param", carrier.MAIN_IN, "Props", carrier.mix_params(dry, wet))
        self.wet = wet

    def ramp(self, to_wet):
        a = self.wet
        for i in range(1, RAMP_STEPS + 1):
            w = a + ((1.0 if to_wet else 0.0) - a) * i / RAMP_STEPS
            self.mix(1.0 - w, w)
            time.sleep(RAMP_STEP_S)

    # ── işçi ──
    def status(self):
        try:
            return json.load(open(self.o.status, encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def is_worker_pid(self, pid):
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().decode(errors="replace").replace("\0", " ")
        except OSError:
            return False
        return "worker.py" in cmd

    def proc_dead(self):
        """İşçi öldü mü. `poll()` yetmez: GPU kullanan süreç SIGKILL'den sonra ~240 ms daha "yaşıyor" görünür (sürücü belleği bırakırken
        iş parçacıkları bekler; ölçüldü), o sırada ses üretmez. Lider iş parçacığı ise hemen zombi (Z) olur → ölüm oradan okunur."""
        if self.proc is None or self.proc.poll() is not None:
            return True
        try:
            return open(f"/proc/{self.proc.pid}/stat").read().rsplit(")", 1)[1].split()[0] in "ZX"
        except (OSError, IndexError):
            return True

    def adopt_orphan(self):
        """Önceki gözcüden kalan işçi: kapatılır (durumu bilinmiyor). Yalnız komut satırı işçi olan süreç."""
        pid = self.status().get("pid")
        if pid and self.is_worker_pid(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                for _ in range(20):
                    if not os.path.exists(f"/proc/{pid}"):
                        break
                    time.sleep(0.05)
                else:
                    os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            self.event("sahipsiz işçi kapatıldı", pid=pid)

    def budget_ok(self):
        now = time.time()
        self.starts = [t for t in self.starts if now - t < BUDGET_S]
        return len(self.starts) < BUDGET_N

    def start_worker(self):
        try:
            os.remove(self.o.status)
        except OSError:
            pass
        self.starts.append(time.time())
        self.spawned_at = time.time()
        self.proc = subprocess.Popen(shlex.split(self.o.worker_cmd), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.state = "starting"
        self.event("işçi başlatıldı", pid=self.proc.pid, deneme=len(self.starts))

    def link_worker(self):
        ports = sh("pw-link", "-io").split()
        if not all(f"{WORKER_NODE}:{p}" in ports for p in ("in_model", "in_dry", "out")):
            return False
        for a, b in ((self.o.model_src, f"{WORKER_NODE}:in_model"), (self.o.dry_src, f"{WORKER_NODE}:in_dry"), (f"{WORKER_NODE}:out", carrier.WET_PORT)):
            subprocess.run(["pw-link", a, b], capture_output=True, timeout=3)
        return True

    def kill_worker(self, why):
        p, self.proc = self.proc, None
        if p and p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL if why == "dondu" else signal.SIGTERM)   # donmuş süreç SIGTERM'i işlemez
            except OSError:
                pass
            try:
                p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(p.pid, signal.SIGKILL)
                    p.wait(timeout=2)   # topla: zombi bırakma
                except (OSError, subprocess.TimeoutExpired):
                    pass
        self.event("işçi kapatıldı", neden=why)

    def to_dry(self, why):
        self.mix(1.0, 0.0)   # tek adım: ıslak yol zaten yok/bozuk, beklemek sessizliği uzatır
        self.report_latency(0)
        self.event("kuru", neden=why)

    # ── döngü ──
    def tick(self):
        now = time.time()
        # Kuru bağ yokken (temiz kaynak yeniden başlıyor) sık dene: bağ yoksa kalite mikrofonu sessizdir (W13).
        if self.dirty or now - self.scanned > (NODRY_SCAN_S if not self.dry_ok else IDLE_SCAN_S if self.state in ("idle", "locked") else ACTIVE_SCAN_S):
            self.scan(now)
        ls = self.ls
        if ls:
            self.last_listener = now
        if self.state == "idle":
            if ls:
                if self.budget_ok():
                    self.event("dinleyen", kim=sorted(ls))
                    self.start_worker()
                elif self.state != "locked":
                    self.state = "locked"
                    self.event("kilitli", neden=f"{BUDGET_S:.0f} sn içinde {BUDGET_N} başarısız başlatma")
            return
        if self.state == "locked":
            if not ls and now - self.last_listener > self.o.hold:
                self.state = "idle"
                self.event("kilit kalktı", neden="dinleyen gitti")   # panel "çalışmıyor"da asılı kalmasın; sonraki dinleyende yeniden denenir
            return
        dead = self.proc_dead()
        st = self.status()
        stale = self.state in ("carried", "wet") and st and now - st.get("t", now) > STALE_S
        if dead or stale:
            self.to_dry("işçi öldü" if dead else "işçi dondu")
            p = self.proc
            self.kill_worker("öldü" if dead else "dondu")   # zombi lideri de burada toplanır (wait) → çıkış kodu ancak bundan sonra bilinir
            code = p.returncode if (dead and p is not None) else None
            if code == EX_TEMPFAIL:   # "kaynak yok" (GPU belleği, model dosyası): yeniden deneme düzeltmez, her deneme kaynak harcar
                self.state = "locked"
                self.event("kilitli", neden=f"işçi çıkış kodu {EX_TEMPFAIL} (kaynak yok)")
            else:
                self.state = "idle"
            return
        if not ls and now - self.last_listener > self.o.hold:
            self.ramp(False)
            self.report_latency(0)
            self.event("kuru", neden="dinleyen yok")
            self.kill_worker("dinleyen yok")
            self.state, self.starts = "idle", []   # düzgün kapanış bütçeyi sıfırlar
            return
        if self.state == "starting":
            if now - self.spawned_at > self.o.start_timeout:
                self.to_dry("işçi hazır olmadı")
                self.kill_worker("zaman aşımı")
                self.state = "idle"
            elif self.link_worker():
                self.state = "linked"
                self.event("işçi bağlandı")
        elif self.state == "linked":
            # İşçi yaşıyorsa (kalp atışı taze) karıştırıcı HEMEN ona verilir: işçi, model hazır olana dek girişin D gecikmişini KURU verir
            # (sözleşmesi). Böylece zaman sıçraması açılışın ilk saniyesinde olur; model hazır olunca geçiş işçinin içinde, hizalıdır.
            if st and now - st.get("t", 0) <= STALE_S:
                self.ramp(True)
                self.report_latency(int(st.get("D_samples", 0)))
                self.state = "carried"
                self.event("taşıyıcıda")
            elif now - self.spawned_at > self.o.start_timeout:
                self.to_dry("işçi hazır olmadı")
                self.kill_worker("zaman aşımı")
                self.state = "idle"
        elif self.state == "carried":
            if st.get("wet") == 1.0:
                self.state = "wet"
                self.event("ıslak")

    def run(self):
        for s in (signal.SIGTERM, signal.SIGINT):
            signal.signal(s, lambda *_: setattr(self, "stop", True))
        self.trim_events()
        self.mix(1.0, 0.0)
        self.report_latency(0)
        self.scan(time.time())
        self.adopt_orphan()
        self.event("gözcü hazır", durum="kuru")
        mon = subprocess.Popen(["pw-link", "-m", "-o", "-l"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        try:
            while not self.stop:
                # Bağ olayı gelince hemen uyanır. Boştayken yoklama yok denecek kadar seyrek; işçi varken kalp atışı/ölüm için sık.
                r, _, _ = select.select([mon.stdout], [], [], self.o.poll if self.state not in ("idle", "locked") else IDLE_POLL_S if self.dry_ok else NODRY_SCAN_S)
                if r:
                    os.read(mon.stdout.fileno(), 65536)
                    self.dirty = True
                self.tick()
        finally:
            mon.terminate()
            self.mix(1.0, 0.0)
            self.report_latency(0)
            if self.proc:
                self.kill_worker("gözcü kapanıyor")
            self.event("gözcü kapandı", durum="kuru")


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--worker-cmd", required=True)
    a.add_argument("--status", required=True)
    a.add_argument("--model-src", required=True, help="modele giden ses portu")
    a.add_argument("--dry-src", required=True, help="hizalı yedek için kuru ses portu")
    a.add_argument("--hold", type=float, default=20.0)
    a.add_argument("--poll", type=float, default=0.05)
    a.add_argument("--start-timeout", type=float, default=15.0)
    a.add_argument("--events")
    Watch(a.parse_args()).run()


if __name__ == "__main__":
    main()
