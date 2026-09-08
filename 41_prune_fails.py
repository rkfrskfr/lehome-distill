"""41단: 실패 에피소드 이미지 정리.

실패판은 600스텝을 끝까지 돌아 1판이 약 184MB 인데, 그중 183MB 가 이미지다.
회복 실험(22_replay_snapshots)은 물리 스냅샷(snap_*.npz)과 meta.json 만 읽으므로
이미지는 필요 없다. 첫 프레임 한 장만 남긴다 — "시작 장면만으로 성패를 예측"하는
분석(23_train_success_head 의 AUC 0.82 결과)이 그 한 장만 쓰기 때문이다.

    python 41_prune_fails.py            # 전체 정리
    python 41_prune_fails.py --dry-run  # 얼마나 줄어드는지만 계산
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DRY = "--dry-run" in sys.argv
KEEP_FIRST = "0000.jpg"
CAMS = ("top", "left", "right")

freed = n_ep = 0
for fail_dir in sorted(glob.glob(os.path.join(HERE, "distill_data_*_fail"))):
    d_freed = d_eps = 0
    for ep in sorted(glob.glob(os.path.join(fail_dir, "*", ""))):
        if not os.path.exists(os.path.join(ep, "meta.json")):
            continue
        touched = False
        for cam in CAMS:
            cdir = os.path.join(ep, cam)
            if not os.path.isdir(cdir):
                continue
            for f in os.listdir(cdir):
                # top 카메라의 첫 프레임만 남긴다
                if cam == "top" and f == KEEP_FIRST:
                    continue
                p = os.path.join(cdir, f)
                try:
                    d_freed += os.path.getsize(p)
                    if not DRY:
                        os.remove(p)
                    touched = True
                except OSError:
                    pass
        if touched:
            d_eps += 1
    if d_eps:
        print(f"{os.path.basename(fail_dir):34s} {d_eps:5d}판  {d_freed/1e9:6.1f} GB")
    freed += d_freed
    n_ep += d_eps
print(f"{'합계':34s} {n_ep:5d}판  {freed/1e9:6.1f} GB" + ("  (dry-run)" if DRY else " 확보"))
