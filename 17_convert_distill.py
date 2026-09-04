"""17단: 수집된 증류 에피소드 -> LeRobot 데이터셋 변환 (lerobot venv 에서 실행).

    C:/Users/H/Desktop/lerobot/.venv/Scripts/python.exe 17_convert_distill.py \
        [--src distill_data] [--dst distill_lerobot] [--subsample 2]

수집은 60Hz(행동당 16.7ms)로 저장됐고, LeHome 관행(30fps)에 맞춰 기본 2배 서브샘플.
so101-fresh 12_convert 의 검증된 API 사용법을 따른다 (create/add_frame/save_episode/finalize,
image_writer_processes=0, 윈도우).
"""

import glob
import json
import os
import shutil
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SRC = os.path.join(HERE, arg("--src", "distill_data"))
DST = os.path.join(HERE, arg("--dst", "distill_lerobot"))
SUB = int(arg("--subsample", "2"))
REPO_ID = arg("--repo-id", "hd/lehome_distill_top_long")
# 해상도 축소 (예: --resize 240x320). 우승자는 224x224 로 줄여 썼다.
# 우리는 480x640 원본을 그대로 학습해 픽셀이 6배 — 학습이 느리고 렌더 세부에
# 과적합될 위험이 있다(논문 §9.1). 종횡비 보존을 위해 240x320 권장.
RESIZE = arg("--resize", "")

ep_dirs = sorted([d for d in glob.glob(os.path.join(SRC, "*"))
                  if os.path.isdir(d) and os.path.exists(
                      os.path.join(d, "meta.json"))])
print(f"에피소드 {len(ep_dirs)}개 발견 (SRC={SRC})")
if not ep_dirs:
    raise SystemExit("없음")

if os.path.exists(DST):
    print(f"기존 {DST} 삭제")
    shutil.rmtree(DST)

from PIL import Image  # noqa: E402
from lerobot.datasets.lerobot_dataset import LeRobotDataset  # noqa: E402

CAM_KEYS = {
    "top": "observation.images.top_rgb",
    "left": "observation.images.left_rgb",
    "right": "observation.images.right_rgb",
}
features = {
    "observation.state": {"dtype": "float32", "shape": (12,),
                          "names": [f"j{i}" for i in range(12)]},
    "action": {"dtype": "float32", "shape": (12,),
               "names": [f"j{i}" for i in range(12)]},
}
IMG_H, IMG_W = (480, 640)
if RESIZE:
    IMG_H, IMG_W = (int(x) for x in RESIZE.lower().split("x"))
    print(f"이미지 축소: 480x640 -> {IMG_H}x{IMG_W}")
for k in CAM_KEYS.values():
    features[k] = {"dtype": "video", "shape": (IMG_H, IMG_W, 3),
                   "names": ["height", "width", "channels"]}

fps = 60 // SUB
ds = LeRobotDataset.create(REPO_ID, fps=fps, features=features, root=DST,
                           robot_type="bi_so101", use_videos=True,
                           image_writer_processes=0, image_writer_threads=4)

total_frames = 0
for ei, d in enumerate(ep_dirs):
    with open(os.path.join(d, "meta.json"), encoding="utf-8") as f:
        meta = json.load(f)
    states = np.load(os.path.join(d, "states.npy")).astype(np.float32)
    actions = np.load(os.path.join(d, "actions.npy")).astype(np.float32)
    n = states.shape[0]
    kept = list(range(0, n, SUB))
    for i in kept:
        frame = {
            "observation.state": states[i],
            "action": actions[i],
            "task": "fold the garment",
        }
        for sub, key in CAM_KEYS.items():
            img = Image.open(os.path.join(d, sub, f"{i:04d}.jpg")).convert("RGB")
            if RESIZE:
                img = img.resize((IMG_W, IMG_H), Image.BILINEAR)
            frame[key] = np.asarray(img, dtype=np.uint8)
        ds.add_frame(frame)
    # 윈도우: 병렬 인코딩(ProcessPool)은 spawn 으로 죽는다 -> 순차
    ds.save_episode(parallel_encoding=False)
    total_frames += len(kept)
    print(f"  [{ei+1}/{len(ep_dirs)}] {os.path.basename(d)}: "
          f"{n} -> {len(kept)}프레임 ({meta.get('garment')})")

ds.finalize()
print(f"\n완료: {len(ep_dirs)}판 {total_frames}프레임 @ {fps}fps -> {DST}")
