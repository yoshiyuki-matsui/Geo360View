# TenkakuNinja Python Environment Notes

更新日: 2026-06-18

このメモは、`~/TenkakuNinjaProject` 配下に増えたvenvの役割を忘れないための棚卸しです。

## 基本方針

```text
semantic_work.sqlite
  プログラム内部の処理・監査・再生成用DB

tmp.gpkg
  ユーザがQGISで見る/操作する成果物

venv310_yolo_gpu
  今後の本命YOLO GPU推論環境

venv_yolo
  既存処理・CubeMap処理で使っている環境
  実行中の処理がある間はpip install/uninstallしない
```

`ultralytics` や周辺パッケージを入れた後にCPU版Torchへ戻ることがあるため、
YOLO推論前は必ずCUDA確認を行います。

## 確認コマンド

```bash
python - <<'PY'
import torch
import torchvision
from torchvision.ops import nms

print("torch", torch.__version__)
print("torchvision", torchvision.__version__)
print("cuda", torch.cuda.is_available())
print("arch", torch.cuda.get_arch_list())
print("device", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no cuda")

if torch.cuda.is_available():
    boxes = torch.tensor([[0, 0, 10, 10], [1, 1, 11, 11]], dtype=torch.float32).cuda()
    scores = torch.tensor([0.9, 0.8], dtype=torch.float32).cuda()
    print("nms", nms(boxes, scores, 0.5))
PY
```

RTX 5080で期待する状態:

```text
cuda True
arch に sm_120
device NVIDIA GeForce RTX 5080
nms tensor(..., device='cuda:0')
```

Codex実行環境では `nvidia-smi` がOS側でブロックされることがあります。
その場合、Codexからの `torch.cuda.is_available() == False` はGPU環境破損の根拠にしません。
ユーザーシェル上の確認結果を優先します。

## venv一覧

### `~/TenkakuNinjaProject/venv310`

用途:

- TenkakuNinjaProjectの汎用Python 3.10環境
- `requirements.txt` 系のベース環境

棚卸し時点:

```text
Python 3.10.20
torch 2.5.1+cu121
torchvision 0.20.1+cu121
torchaudio 2.5.1+cu121
ultralytics 8.4.24
opencv-python 4.13.0
numpy 1.26.4
py360convert 未導入
```

メモ:

- Codex実行環境からはCUDA不可に見えた。
- 汎用・互換確認用として残す。

### `~/TenkakuNinjaProject/venv313`

用途:

- Python 3.13検証用

棚卸し時点:

```text
Python 3.13.9
torch 未導入
ultralytics 未導入
opencv-python 4.13.0
numpy 2.4.3
```

メモ:

- YOLO本番処理には使わない。
- Python 3.13は一部周辺パッケージで詰まる可能性があるため実験用。

### `~/TenkakuNinjaProject/venv_yolo`

用途:

- 既存CubeMap/YOLO処理環境
- 長時間CubeMap処理中は触らない

棚卸し時点:

```text
Python 3.10.20
torch 2.9.1+cu128
torchvision 0.24.1+cu128
torchaudio 2.9.1+cu128
ultralytics 8.4.41
opencv-python 4.13.0
py360convert 1.0.4
numpy 1.26.4
PyQt5 導入あり
```

メモ:

- CubeMap処理で使用中の可能性があるため、実行中はpipで書き換えない。
- labelImg/Qt系の都合でPython 3.10に寄せた可能性あり。

### `~/TenkakuNinjaProject/venv_yolo_gpu`

用途:

- Python 3.13のGPU動作確認用
- 短時間のYOLO GPU検証用

ユーザーシェルで確認済み:

```text
Python 3.13.9
torch 2.12.1+cu130
torchvision 0.27.1+cu130
cuda True
arch ['sm_75', 'sm_80', 'sm_86', 'sm_90', 'sm_100', 'sm_120']
device NVIDIA GeForce RTX 5080
torchvision.ops.nms CUDA OK
```

棚卸し時点:

```text
ultralytics 8.4.70
opencv-python 4.13.0
py360convert 1.0.4
numpy 2.4.6
```

注意:

- Codex実行環境ではtorchaudio importが失敗した。
- YOLOには通常torchaudio不要。気になる場合は、後でTorch/TorchVision/Torchaudioを同じindexから入れ直す。
- 長期運用はPython 3.10側を推奨。

### `~/TenkakuNinjaProject/venv310_yolo_gpu`

用途:

- 今後の本命YOLO GPU推論環境
- 既存 `venv_yolo` と同じPython 3.10系に揃える

棚卸し時点:

```text
Python 3.10.20
torch 2.12.1+cu130
torchvision 0.27.1+cu130
ultralytics 8.4.70
opencv-python 4.13.0
py360convert 1.0.4
numpy 2.2.6
```

注意:

- Codex実行環境ではGPUアクセスがOSにブロックされた。
- ユーザーシェルで `cuda True`, `sm_120`, `RTX 5080`, `nms cuda` を確認してから本番使用する。
- Codex実行環境ではtorchaudio importが失敗した。YOLO推論には通常不要。

## 推奨運用

### CubeMap処理

実行中の既存処理を壊さないため、現在動かしているvenvをそのまま使う。

```bash
source ~/TenkakuNinjaProject/venv_yolo/bin/activate
```

### YOLO GPU推論

本命は `venv310_yolo_gpu`。

```bash
source ~/TenkakuNinjaProject/venv310_yolo_gpu/bin/activate

python TenkakuNinja/yolo_detect.py \
  --work-db /path/to/semantic_work.sqlite \
  --model /path/to/model.pt \
  --model-name pothole_detector \
  --faces down \
  --device 0 \
  --chunk-size 100
```

GPU確認が通らない場合だけ、検証済みの `venv_yolo_gpu` を短期利用する。

### パッケージ更新ルール

```text
1. CubeMap処理中のvenvは触らない
2. labelImg / Qt系とYOLO GPU推論環境は混ぜない
3. ultralytics等を入れた後は、最後にCUDA版Torchを確認する
4. YOLO実行前に torch.cuda.is_available(), sm_120, nms CUDA を確認する
```

### CUDA版Torchを入れ直す例

```bash
python -m pip install --pre torch torchvision torchaudio \
  --index-url https://download.pytorch.org/whl/nightly/cu128
```

または、現在GPU確認できているcu130系を維持する場合は、その時点のPyTorch公式/インストール元に合わせて
`torch`, `torchvision`, `torchaudio` の世代を揃える。

