# model_ai/LowLight

Letakkan bobot model low-light di folder ini. Nama file **harus** persis seperti
yang diharapkan kelas di `ai_engine/enhancers/`:

| File | Model | Kelas | Catatan |
|---|---|---|---|
| `mirnet.ts.pt` | MirNet | `MirNetEnhancer` | **Disarankan** — TorchScript, arsitektur tidak perlu dikenal |
| `mirnet.pth` | MirNet | `MirNetEnhancer` | state_dict; butuh arsitektur terdaftar (`register_architecture`) |
| `zerodce.pth` | Zero-DCE | `ZeroDCEnhancer` | state_dict DCE-Net, dimuat langsung |

Ekspor MirNet ke TorchScript (sekali saja, dari repo model aslinya):

```python
import torch
from model import build_mirnet   # dari repo MirNet

net = build_mirnet()
net.load_state_dict(torch.load("mirnet.pth", map_location="cpu"))
net.eval()
torch.jit.trace(net, torch.rand(1, 3, 256, 256)).save("mirnet.ts.pt")
```

Selama file di atas belum ada, engine otomatis memakai `classical` (CLAHE) dan
melaporkan alasannya ke RTDB (`lowlight_error`); pipeline tidak berhenti.
