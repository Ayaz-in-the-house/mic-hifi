"""V4 kalite hattı: MossFormer2_SE_48K, işçinin blok-blok çağırdığı model. Ölçüm ve kurulum: docs/research/S-v4-model-triage.md.

Pencere W, adım = blok N. Her çağrıda son W örnek çözülür; kenarlar atılır (kenar = (W − N)/2) → geri verilen N örnek, girişin `latency` = kenar
kadar gerisine aittir (işçi bunu bilir). Kaynak ve ağırlık DEPO DIŞINDADIR (karantina dizini); ağırlık sha256 ile doğrulanır ve `weights_only=True`
ile yüklenir. Ortam değişkenleri: MIC_V4_SRC (model kaynağının kökü), MIC_V4_WEIGHTS.
"""
import hashlib, os, sys, types
from types import SimpleNamespace

import numpy as np
import torch, torchaudio

Q = os.path.expanduser("~/.cache/mic-hifi-quarantine")
SRC = os.environ.get("MIC_V4_SRC", os.path.join(Q, "cvs", "clearvoice", "clearvoice"))
WEIGHTS = os.environ.get("MIC_V4_WEIGHTS", os.path.join(Q, "MossFormer2_SE_48K.pt"))
SHA256 = "03692b9f773bbd6bb43b9c5a41f96b1e28affd66e13796b7bec66ad3d8b227c6"
EX_TEMPFAIL = 75   # gözcü bu kodu "kaynak yok, yeniden deneme" sayar
A = SimpleNamespace(sampling_rate=48000, win_len=1920, win_inc=384, fft_len=1920, num_mels=60, win_type="hamming", decode_window=4)


class MossFormer:
    def __init__(self, block, window, device="cuda"):
        if window <= block or (window - block) % 2:
            sys.exit(f"pencere {window} bloktan {block} büyük ve farkı çift olmalı")
        try:
            if hashlib.sha256(open(WEIGHTS, "rb").read()).hexdigest() != SHA256:
                raise RuntimeError("ağırlık özeti beklenenle aynı değil")
            sys.modules.setdefault("torchinfo", types.SimpleNamespace(summary=lambda *a, **k: None))
            sys.path.insert(0, SRC)
            from models.mossformer2_se.mossformer2_se_wrapper import MossFormer2_SE_48K
            self.dev = torch.device(device)
            ck = torch.load(WEIGHTS, map_location="cpu", weights_only=True)
            sd = {k.replace("module.", "", 1): v for k, v in (ck.get("model", ck) if isinstance(ck, dict) else ck).items()}
            self.net = MossFormer2_SE_48K(A).model
            self.net.load_state_dict(sd, strict=True)
            self.net.eval().to(self.dev)
        except (OSError, RuntimeError, ImportError) as e:   # model dosyası/GPU yok: kalıcı hata
            print(f"model yüklenemedi: {e}", file=sys.stderr, flush=True)
            sys.exit(EX_TEMPFAIL)
        self.N, self.W, self.latency = block, window, (window - block) // 2
        self.buf = np.zeros(window, np.float32)
        self.win = torch.hamming_window(A.win_len, periodic=False)
        self(np.zeros(block, np.float32))                   # ısınma: ilk çağrının gecikmesi canlıya düşmesin
        self.buf[:] = 0

    @torch.no_grad()
    def __call__(self, x):
        self.buf = np.concatenate((self.buf[self.N:], x))
        seg = torch.from_numpy(self.buf * 32768.0)
        fb = torchaudio.compliance.kaldi.fbank(seg.unsqueeze(0), dither=1.0, frame_length=40.0, frame_shift=8.0, num_mel_bins=A.num_mels,
                                               sample_frequency=A.sampling_rate, window_type="hamming")
        d1 = torchaudio.functional.compute_deltas(fb.T); d2 = torchaudio.functional.compute_deltas(d1)
        mask = self.net(torch.cat([fb, d1.T, d2.T], dim=1).unsqueeze(0).to(self.dev))[-1].permute(2, 1, 0).cpu()
        spec = torch.view_as_real(torch.stft(seg, A.fft_len, A.win_inc, A.win_len, center=False, window=self.win, return_complex=True))
        m = spec * mask
        y = torch.istft(torch.complex(m[..., 0], m[..., 1]), A.fft_len, A.win_inc, A.win_len, center=False, window=self.win)
        y = torch.nn.functional.pad(y, (0, self.W - len(y))).numpy() / 32768.0
        return y[self.latency:self.latency + self.N].astype(np.float32)
