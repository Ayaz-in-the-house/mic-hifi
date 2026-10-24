"""Yalıtılmış PipeWire örneği — taşıyıcı (V3) testlerinin zemini. Canlı grafiğe, WirePlumber'a ve kullanıcının sesine DOKUNMAZ.

Ayrı çalışma dizini + ayrı soket adı (`mic-iso`) ile ikinci bir `pipewire` süreci başlatır. Donanım yok: saati `support.node.driver`
sürer; `fake_mic` ve `fake_wet` (içine çalınır, `capture_FL`'den okunur) sahte mikrofon, `fake_out` sahte çıkıştır. Oturum yöneticisi: ayrı bir `wireplumber -p policy`
(yalnız politika; donanım/bluetooth izleyicisi yok, ayrı durum dizini, D-Bus kapalı).

    with Iso() as iso:
        iso.link("fake_mic:capture_FL", "fake_out:playback_MONO")
        iso.run("pw-cat", "-p", "--target", "fake_mic", "x.wav")   # araçlar PIPEWIRE_REMOTE ile bu örneğe gider
"""
import os, shutil, signal, subprocess, tempfile, time

CORE = "mic-iso"
CONF = """context.properties = {{ log.level = 2  core.daemon = true  core.name = {core}
  default.clock.rate = 48000  default.clock.quantum = {quantum}  default.clock.min-quantum = 32  default.clock.max-quantum = 2048 }}
context.spa-libs = {{ audio.convert.* = audioconvert/libspa-audioconvert  support.* = support/libspa-support }}
context.modules = [
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-client-device }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-metadata }}
  {{ name = libpipewire-module-access }}
  {{ name = libpipewire-module-link-factory }}
  {{ name = libpipewire-module-spa-node-factory }}
  {{ name = libpipewire-module-spa-device-factory }}
  {{ name = libpipewire-module-session-manager }}
]
context.objects = [
  {{ factory = spa-node-factory args = {{ factory.name = support.node.driver node.name = iso-driver node.group = iso priority.driver = 20000 }} }}
  {{ factory = adapter args = {{ factory.name = support.null-audio-sink node.name = fake_mic media.class = Audio/Source/Virtual
      audio.position = [ FL ] audio.rate = 48000 object.linger = true adapter.auto-port-config = {{ mode = dsp monitor = true position = preserve }} }} }}
  {{ factory = adapter args = {{ factory.name = support.null-audio-sink node.name = fake_wet media.class = Audio/Source/Virtual
      audio.position = [ FL ] audio.rate = 48000 object.linger = true adapter.auto-port-config = {{ mode = dsp monitor = true position = preserve }} }} }}
  {{ factory = adapter args = {{ factory.name = support.null-audio-sink node.name = fake_out media.class = Audio/Sink
      audio.position = [ MONO ] audio.rate = 48000 object.linger = true adapter.auto-port-config = {{ mode = dsp monitor = true position = preserve }} }} }}
]
"""


class Iso:
    def __init__(self, quantum=1024):
        self.dir = tempfile.mkdtemp(prefix="mic-iso-", dir=os.environ.get("XDG_RUNTIME_DIR"))
        os.chmod(self.dir, 0o700)
        # Ayrı durum/ayar dizinleri: yalıtılmış WirePlumber kullanıcının kayıtlı varsayılanlarını okumasın/yazmasın. D-Bus kapalı.
        self.env = {**os.environ, "XDG_RUNTIME_DIR": self.dir, "PIPEWIRE_RUNTIME_DIR": self.dir, "PIPEWIRE_REMOTE": CORE,
                    "XDG_STATE_HOME": os.path.join(self.dir, "state"), "XDG_CONFIG_HOME": os.path.join(self.dir, "config"),
                    "DBUS_SESSION_BUS_ADDRESS": "disabled:"}
        self.quantum, self.procs = quantum, []

    def __enter__(self):
        conf = os.path.join(self.dir, "iso.conf")
        open(conf, "w").write(CONF.format(core=CORE, quantum=self.quantum))
        self.log = open(os.path.join(self.dir, "pipewire.log"), "w")
        self.server = subprocess.Popen(["pipewire", "-c", conf], env=self.env, stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       start_new_session=True)
        for _ in range(50):
            if os.path.exists(os.path.join(self.dir, CORE)) and "fake_out:playback_MONO" in self.out("pw-link", "-i"):
                break
            time.sleep(0.1)
        else:
            self.__exit__(None, None, None)
            raise RuntimeError("yalıtılmış PipeWire ayağa kalkmadı: " + open(os.path.join(self.dir, "pipewire.log")).read()[-400:])
        # Oturum yöneticisi: yalnız politika profili (donanım, bluetooth, kamera izleyicileri YOK). Onsuz akışların portu bile oluşmaz (E20).
        self.wp_log = open(os.path.join(self.dir, "wireplumber.log"), "w")
        self.wp = subprocess.Popen(["wireplumber", "-p", "policy"], env=self.env, stdout=self.wp_log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   start_new_session=True)
        self.procs.append(self.wp)
        for _ in range(50):
            if self.wp.poll() is not None:
                break
            if "WirePlumber" in self.out("pw-cli", "ls", "Client"):
                time.sleep(0.5)
                return self
            time.sleep(0.1)
        tail = open(os.path.join(self.dir, "wireplumber.log")).read()[-400:]
        self.__exit__(None, None, None)
        raise RuntimeError("yalıtılmış WirePlumber ayağa kalkmadı: " + tail)

    def __exit__(self, *exc):
        for p in self.procs + [self.server]:   # yalnız bu sınıfın başlattığı süreçler
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        for p in self.procs + [self.server]:
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
        self.log.close()
        if hasattr(self, "wp_log"):
            self.wp_log.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cmd(self, cmd):
        return list(cmd)   # araçlar örneği PIPEWIRE_REMOTE ortam değişkeninden bulur (pw-cat'te -r "kaydet" demektir; bayrak EKLENMEZ)

    def run(self, *cmd, timeout=20, **kw):
        return subprocess.run(self._cmd(cmd), env=self.env, capture_output=True, text=True, timeout=timeout, **kw)

    def out(self, *cmd, timeout=5):
        try:
            return self.run(*cmd, timeout=timeout).stdout
        except subprocess.TimeoutExpired:
            return ""

    def spawn(self, *cmd, **kw):
        """Arka plan süreci (çıkışta kapatılır). Ek ortam: env={...}."""
        env = {**self.env, **kw.pop("env", {})}
        kw.setdefault("stdout", subprocess.DEVNULL); kw.setdefault("stderr", subprocess.DEVNULL)
        p = subprocess.Popen(self._cmd(cmd), env=env, stdin=subprocess.DEVNULL, start_new_session=True, **kw)
        self.procs.append(p)
        return p

    def link(self, a, b, passive=False):
        r = self.run("pw-link", *(["-P"] if passive else []), a, b)
        if r.returncode:
            raise RuntimeError(f"bağ kurulamadı {a} → {b}: {r.stderr.strip()}")

    def wait_port(self, name, timeout=8.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if name in self.out("pw-link", "-io").split():
                return True
            time.sleep(0.1)
        return False

    def play(self, wav, target="fake_mic", wait=True):
        """wav'ı sahte kaynağın GİRİŞİNE çalar. `--target <kaynak>` işe yaramaz: çalma akışı yalnız çıkışları hedefler, kaynak adını bulamayınca
        varsayılan çıkışa (fake_out) düşer (ölçüldü). Bu yüzden akış kendiliğinden bağlanmaz, bağ elle kurulur."""
        self._n = getattr(self, "_n", 0) + 1
        name = f"iso_play_{self._n}"
        p = self.spawn("pw-cat", "-p", "-P", "{ node.name = %s node.autoconnect = false }" % name, wav)
        port = next((c for c in (f"{name}:output_MONO", f"{name}:output_FL") if self.wait_port(c, 3)), None)
        if not port:
            raise RuntimeError("çalma akışının portu oluşmadı")
        self.link(port, f"{target}:input_FL")
        if wait:
            p.wait(timeout=120)
        return p

    def record(self, target, wav, sink_monitor=False):
        """target: kaynak düğüm adı; sink_monitor=True ise bir çıkışın izleme portundan kaydeder."""
        extra = ["-P", "{ stream.capture.sink = true }"] if sink_monitor else []
        return self.spawn("pw-cat", "-r", "--target", target, *extra, "--channels", "1", "--rate", "48000", "--format", "s16", wav)

    def record2(self, port_a, port_b, wav, name="iso_rec2"):
        """İki portu aynı anda, aynı saatle 2 kanallı kaydeder (kanallar arası gecikme ölçümü için)."""
        p = self.spawn("pw-cat", "-r", "-P", "{ node.name = %s node.autoconnect = false }" % name, "--channels", "2", "--rate", "48000", "--format", "s16", wav)
        if not (self.wait_port(f"{name}:input_FL", 3) and self.wait_port(f"{name}:input_FR", 3)):
            raise RuntimeError("2 kanallı kayıt akışının portları oluşmadı")
        self.link(port_a, f"{name}:input_FL")
        self.link(port_b, f"{name}:input_FR")
        return p

    def state(self, node):
        for line in self.out("pw-cli", "info", node).splitlines():
            if "state:" in line and '"' in line:
                return line.split('"')[1]
        return ""
