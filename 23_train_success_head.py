"""23단: 성공확률 예측기 학습 (우승자 논문 §5.1 success head 이식).

수집된 성공/실패 에피소드로 P(이 에피소드가 성공한다 | 현재 프레임) 을 학습한다.
논문에서는 정책 본체의 보조 헤드였지만, 우리 ACT 는 그런 헤드가 없으므로
**독립 예측기**로 만든다. 쓰임새 3가지:
  1) 라이브 실패 감지 -> 가망 없는 에피소드 조기 종료 (수집 속도 ↑, 논문 §3.1)
  2) best-of-N 행동 선택 (논문 §7.4)
  3) 진행 상황 출력 (성공확률 곡선)

논문 트릭 이식:
  - success tail boost: 성공 에피소드 마지막 20프레임에 20배 가중 (§5.3)
  - label smoothing α=0.05, 옷별 평균 성공률로 스무딩 (§5.3)
  - completion 헤드 (t/T, 성공 판만) — 성공확률보다 안정적인 진행 신호 (§6.3)
  - 에피소드 단위 홀드아웃 (프레임 누수 방지)

실행 (lerobot venv):
    C:/Users/H/Desktop/lerobot/.venv/Scripts/python.exe 23_train_success_head.py \
        --ok distill_data_r4 --fail distill_data_r4_fail --epochs 6
"""

import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


OK_DIRS = arg("--ok", "distill_data_r4").split(",")
FAIL_DIRS = arg("--fail", "distill_data_r4_fail").split(",")
EPOCHS = int(arg("--epochs", "6"))
BATCH = int(arg("--batch", "64"))
STRIDE = int(arg("--stride", "5"))        # 프레임 서브샘플
OUT = os.path.join(HERE, arg("--out", "outputs/success_head"))
VAL_FRAC = float(arg("--val-frac", "0.15"))
SEED = int(arg("--seed", "0"))
os.makedirs(OUT, exist_ok=True)

import torch  # noqa: E402
import torch.nn as nn  # noqa: E402
from PIL import Image  # noqa: E402
from torch.utils.data import DataLoader, Dataset  # noqa: E402
from torchvision import transforms  # noqa: E402
from torchvision.models import ResNet18_Weights, resnet18  # noqa: E402

DEV = "cuda" if torch.cuda.is_available() else "cpu"
rng = np.random.RandomState(SEED)


def scan(dirs, label):
    eps = []
    for d in dirs:
        root = os.path.join(HERE, d.strip())
        for ep in sorted(glob.glob(os.path.join(root, "*"))):
            meta = os.path.join(ep, "meta.json")
            if not os.path.isdir(ep) or not os.path.exists(meta):
                continue
            frames = sorted(glob.glob(os.path.join(ep, "top", "*.jpg")))
            if len(frames) < 30:
                continue
            g = json.load(open(meta, encoding="utf-8")).get("garment", "?")
            eps.append({"dir": ep, "frames": frames, "y": label, "garment": g})
    return eps


episodes = scan(OK_DIRS, 1) + scan(FAIL_DIRS, 0)
if not episodes:
    raise SystemExit("에피소드 없음")
n_ok = sum(e["y"] for e in episodes)
print(f"에피소드 {len(episodes)}개 (성공 {n_ok}, 실패 {len(episodes)-n_ok})")

# 옷별 평균 성공률 (label smoothing 용, 논문 §5.3)
garments = sorted({e["garment"] for e in episodes})
sr = {g: float(np.mean([e["y"] for e in episodes if e["garment"] == g]))
      for g in garments}
print("옷별 성공률:", {g: round(v, 2) for g, v in sr.items()})

# 홀드아웃. episode = 에피소드 단위, chunk = 수집 청크(=옷+시드) 단위.
# 청크는 로봇 높이·텍스처 계열이 공유되므로 에피소드 단위로 나누면 모델이
# "이 청크는 잘 되는 청크"를 외워버린다 (group leakage). chunk 분할이 엄격.
SPLIT_BY = arg("--split-by", "episode")
if SPLIT_BY == "chunk":
    import re as _re
    for e in episodes:
        m = _re.match(r"(.+_s\d+)_e\d+", os.path.basename(e["dir"]))
        e["chunk"] = m.group(1) if m else os.path.basename(e["dir"])
    chunks = sorted({e["chunk"] for e in episodes})
    perm = rng.permutation(len(chunks))
    val_chunks = {chunks[i] for i in perm[:max(1, int(len(chunks) * VAL_FRAC))]}
    train_eps = [e for e in episodes if e["chunk"] not in val_chunks]
    val_eps = [e for e in episodes if e["chunk"] in val_chunks]
    print(f"청크 분할: 전체 {len(chunks)} -> 검증 {len(val_chunks)}")
else:
    idx = rng.permutation(len(episodes))
    n_val = max(1, int(len(episodes) * VAL_FRAC))
    val_ids = set(idx[:n_val].tolist())
    train_eps = [e for i, e in enumerate(episodes) if i not in val_ids]
    val_eps = [e for i, e in enumerate(episodes) if i in val_ids]
print(f"학습 {len(train_eps)} / 검증 {len(val_eps)} 에피소드")

TF_TRAIN = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ColorJitter(0.3, 0.3, 0.3, 0.05),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])
TF_EVAL = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])

ALPHA = 0.05          # label smoothing
TAIL_N, TAIL_W = 20, 20.0   # success tail boost (논문 §5.3)


class FrameSet(Dataset):
    def __init__(self, eps, train):
        self.train = train
        self.items = []
        for e in eps:
            T = len(e["frames"])
            for t in range(0, T, STRIDE):
                # 가중치: 성공판의 마지막 20프레임에 20배 (거의 성공한 상태와
                # 진짜 성공을 구분하는 신호를 강화)
                w = 1.0
                if e["y"] == 1 and t >= T - TAIL_N:
                    w = TAIL_W
                y = e["y"] * (1 - ALPHA) + sr.get(e["garment"], 0.3) * ALPHA
                self.items.append((e["frames"][t], y, t / max(1, T - 1), w,
                                   e["y"]))

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        path, y, comp, w, y_hard = self.items[i]
        img = Image.open(path).convert("RGB")
        x = (TF_TRAIN if self.train else TF_EVAL)(img)
        return x, torch.tensor([y, comp, w, y_hard], dtype=torch.float32)


class Head(nn.Module):
    """공유 백본 + 2헤드 (success, completion)."""

    def __init__(self):
        super().__init__()
        self.backbone = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
        feat = self.backbone.fc.in_features
        self.backbone.fc = nn.Identity()
        self.succ = nn.Linear(feat, 1)
        self.comp = nn.Linear(feat, 1)

    def forward(self, x):
        f = self.backbone(x)
        return self.succ(f).squeeze(-1), self.comp(f).squeeze(-1)


def auc(y, p):
    y = np.asarray(y)
    p = np.asarray(p)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Mann-Whitney U
    order = np.argsort(np.concatenate([pos, neg]))
    ranks = np.empty(len(order), dtype=float)
    ranks[order] = np.arange(1, len(order) + 1)
    r_pos = ranks[:len(pos)].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main():
    tr = DataLoader(FrameSet(train_eps, True), batch_size=BATCH, shuffle=True,
                    num_workers=4, drop_last=True, persistent_workers=True)
    va = DataLoader(FrameSet(val_eps, False), batch_size=BATCH, shuffle=False,
                    num_workers=2, persistent_workers=True)
    print(f"학습 프레임 {len(tr.dataset)} / 검증 {len(va.dataset)}")

    model = Head().to(DEV)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-4, weight_decay=1e-3)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, EPOCHS * len(tr))
    bce = nn.BCEWithLogitsLoss(reduction="none")
    mse = nn.MSELoss(reduction="none")
    best = -1.0

    for ep in range(EPOCHS):
        model.train()
        tot = 0.0
        for x, meta in tr:
            x = x.to(DEV, non_blocking=True)
            y, comp, w, _ = meta.to(DEV).unbind(1)
            ls, lc = model(x)
            loss_s = (bce(ls, y) * w).mean()
            # completion 은 성공 판만 (논문 §6.3)
            m = (w > 0) & (y > 0.5)
            loss_c = (mse(torch.sigmoid(lc), comp) * m.float()).mean()
            loss = loss_s + 0.2 * loss_c
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            tot += float(loss)

        model.eval()
        ys, ps = [], []
        with torch.no_grad():
            for x, meta in va:
                x = x.to(DEV, non_blocking=True)
                ls, _ = model(x)
                ps += torch.sigmoid(ls).cpu().numpy().tolist()
                ys += meta[:, 3].numpy().tolist()
        a = auc(ys, ps)
        acc = float(np.mean((np.asarray(ps) > 0.5) == (np.asarray(ys) > 0.5)))
        print(f"[epoch {ep+1}/{EPOCHS}] loss={tot/max(1,len(tr)):.4f} "
              f"val_AUC={a:.3f} val_acc={acc:.3f}", flush=True)
        if a > best:
            best = a
            torch.save({"model": model.state_dict(), "auc": a, "acc": acc,
                        "garment_sr": sr}, os.path.join(OUT, "best.pt"))

    # 오프라인 검증 판정 (논문 계획대로: 통과해야 best-of-N 에 투입)
    verdict = "PASS" if best >= 0.75 else "FAIL"
    with open(os.path.join(OUT, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"best_val_auc": best, "verdict": verdict,
                   "n_episodes": len(episodes), "n_success": int(n_ok),
                   "garment_sr": sr}, f, indent=1)
    print(f"\n=== 최종 val AUC {best:.3f} -> {verdict} "
          f"(0.75 이상이면 best-of-N 투입 가능) ===")


if __name__ == "__main__":
    main()
