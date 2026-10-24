"""Asgari LADSPA barındırıcı (ctypes) — zincir tasarımını canlı grafiğe dokunmadan çevrimdışı sınamak için.

Plugin(so, label, sr, {"Port adı": değer}).process(x: float32 mono) -> float32 mono
Verilmeyen kontrol portları eklentinin kendi varsayılanını (LADSPA hint) alır; çıkış kontrol portları okunabilir (.outputs()).
"""
import ctypes as C, math, time

import numpy as np


class Hint(C.Structure):
    _fields_ = [("d", C.c_int), ("lo", C.c_float), ("hi", C.c_float)]


class Desc(C.Structure):
    pass


H = C.c_void_p
Desc._fields_ = [
    ("UniqueID", C.c_ulong), ("Label", C.c_char_p), ("Properties", C.c_int), ("Name", C.c_char_p),
    ("Maker", C.c_char_p), ("Copyright", C.c_char_p), ("PortCount", C.c_ulong),
    ("PortDescriptors", C.POINTER(C.c_int)), ("PortNames", C.POINTER(C.c_char_p)), ("PortRangeHints", C.POINTER(Hint)),
    ("ImplementationData", C.c_void_p),
    ("instantiate", C.CFUNCTYPE(H, C.POINTER(Desc), C.c_ulong)),
    ("connect_port", C.CFUNCTYPE(None, H, C.c_ulong, C.POINTER(C.c_float))),
    ("activate", C.CFUNCTYPE(None, H)),
    ("run", C.CFUNCTYPE(None, H, C.c_ulong)),
    ("run_adding", C.c_void_p), ("set_run_adding_gain", C.c_void_p),
    ("deactivate", C.CFUNCTYPE(None, H)),
    ("cleanup", C.CFUNCTYPE(None, H)),
]


def hint_default(h, sr):
    lo, hi, d = h.lo, h.hi, h.d
    if d & 8:  # örnekleme hızına göre
        lo, hi = lo * sr, hi * sr
    log = bool(d & 0x10)
    mix = lambda a: math.exp(math.log(max(lo, 1e-9)) * (1 - a) + math.log(max(hi, 1e-9)) * a) if log else lo * (1 - a) + hi * a
    return {0x40: lo, 0x80: mix(0.25), 0xC0: mix(0.5), 0x100: mix(0.75), 0x140: hi,
            0x200: 0.0, 0x240: 1.0, 0x280: 100.0, 0x2C0: 440.0}.get(d & 0x3C0, 0.0)


class Plugin:
    def __init__(self, so, label, sr, controls=None, block=480, realtime=False):
        self.lib = C.CDLL(so)
        self.lib.ladspa_descriptor.restype = C.POINTER(Desc)
        self.lib.ladspa_descriptor.argtypes = [C.c_ulong]
        i = 0
        while True:
            p = self.lib.ladspa_descriptor(i)
            if not p:
                raise KeyError(f"{label} bulunamadı: {so}")
            if p.contents.Label.decode() == label:
                break
            i += 1
        self.d, self.sr, self.block, self.realtime = p.contents, sr, block, realtime
        d = self.d
        self.h = d.instantiate(C.byref(d), sr)
        self.ib, self.ob = (C.c_float * block)(), (C.c_float * block)()
        self.ctl, self.out = {}, {}
        controls = dict(controls or {})
        for n in range(d.PortCount):
            pd, name = d.PortDescriptors[n], d.PortNames[n].decode()
            if pd & 8:  # ses portu
                d.connect_port(self.h, n, self.ib if pd & 1 else self.ob)
                continue
            v = C.c_float(controls.pop(name, hint_default(d.PortRangeHints[n], sr)) if pd & 1 else 0.0)
            (self.ctl if pd & 1 else self.out)[name] = v
            d.connect_port(self.h, n, C.byref(v))
        if controls:
            raise KeyError(f"bilinmeyen kontrol portu: {sorted(controls)}")
        if d.activate:
            d.activate(self.h)

    def outputs(self):
        return {k: v.value for k, v in self.out.items()}

    def process(self, x):
        x = np.ascontiguousarray(x, dtype=np.float32)
        y = np.zeros(len(x), dtype=np.float32)
        b, t0 = self.block, time.time()
        for i in range(0, len(x) - b + 1, b):
            C.memmove(self.ib, x[i:i + b].ctypes.data, b * 4)
            self.d.run(self.h, b)
            y[i:i + b] = np.frombuffer(self.ob, dtype=np.float32)
            if self.realtime:  # iş parçacıklı eklentiler (DeepFilterNet) gerçek zaman temposu ister
                ahead = (i + b) / self.sr - (time.time() - t0)
                if ahead > 0:
                    time.sleep(ahead)
        return y

    def close(self):
        if self.d.deactivate:
            self.d.deactivate(self.h)
        self.d.cleanup(self.h)
