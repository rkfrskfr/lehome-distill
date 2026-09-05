r"""22단: 성공 스냅샷 리플레이 증식 (우승자 논문 §3.2 이식).

수집된 에피소드의 물리 상태 스냅샷(snap_XXXX.npz)을 복원하고, **시각 랜덤화만
다시 뽑아** 교사에게 재실행시킨다. 성공하면 새 에피소드로 보관 →
희귀한 성공(약한 옷)을 여러 판으로 증식한다.

  --mode success : snap_0005 복원 (에피소드 초반 상태) -> 시각만 바꿔 재수집.
                   원료 = distill_data_r4\  (성공판)
  --mode recover : 실패판의 중간 스냅샷 복원 -> 교사가 회복 시도 (자동 DAgger).
                   원료 = distill_data_r4_fail\  (실패판)
                   성공하면 "망친 상태에서 복구하는" 데이터가 생긴다.

    "C:/isaacsim/python.bat" 22_replay_snapshots.py --src distill_data_r4 \
        --out distill_data_r4_replay --mode success --garment-dir Top_Long_Seen_0 \
        --per-snap 3 --port 8767
"""

import glob
import json
import os
import pickle
import shutil
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


SRC = os.path.join(HERE, arg("--src", "distill_data_r4"))
OUT = os.path.join(HERE, arg("--out", "distill_data_r4_replay"))
MODE = arg("--mode", "success")
GARMENT_DIR = arg("--garment-dir", "Top_Long_Seen_0")
GARMENT_TYPE = arg("--garment-type", "Top_Long")
PER_SNAP = int(arg("--per-snap", "3"))      # 스냅샷 하나당 재실행 횟수
MAX_SNAPS = int(arg("--max-snaps", "20"))   # 처리할 스냅샷 상한
N_STEPS = int(arg("--steps", "600"))
PORT = int(arg("--port", "8767"))
SEED = int(arg("--seed", "1000"))
os.makedirs(OUT, exist_ok=True)
RESULT = os.path.join(HERE, f"22_result_{MODE}_{GARMENT_DIR}.txt")

_lines = []


def say(m):
    _lines.append(str(m))
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")
    print(m, flush=True)


def send_msg(c, o):
    d = pickle.dumps(o, protocol=4)
    c.sendall(struct.pack("<I", len(d)) + d)


def recv_msg(c):
    h = b""
    while len(h) < 4:
        k = c.recv(4 - len(h))
        if not k:
            return None
        h += k
    (ln,) = struct.unpack("<I", h)
    b = b""
    while len(b) < ln:
        k = c.recv(min(1 << 20, ln - len(b)))
        if not k:
            return None
        b += k
    return pickle.loads(b)


# 스냅샷 수집
#   success : 성공판의 초반(step 5) 상태 -> 시각만 바꿔 재실행 (희귀 성공 증식)
#   recover : 실패판의 '망친 순간' 상태 -> 교사가 회복 시도 (자동 DAgger)
#   semi    : **거의 성공했던 실패판**(조건 3개 이상 통과)의 상태만 골라 재시도.
#             논문 §3.2 의 semi-success replay — 완전 실패보다 훨씬 값진 원료다.
def _npass_of(ep_dir):
    """실패판이 최종적으로 몇 개 조건을 통과했는지 (preds/meta 로는 알 수 없어
    수집 로그의 조기종료 기록 대신 여기서는 스냅샷 개수로 근사하지 않고,
    meta.json 의 n_pass 가 있으면 사용)."""
    try:
        m = json.load(open(os.path.join(ep_dir, "meta.json"), encoding="utf-8"))
        return int(m.get("n_pass", -1))
    except Exception:
        return -1


def _peak_pred(ep_dir):
    """그 에피소드에서 교사가 예측한 최고 성공확률 (preds.npy). 없으면 -1."""
    f = os.path.join(ep_dir, "preds.npy")
    if not os.path.exists(f):
        return -1.0
    try:
        import numpy as _np
        a = _np.load(f)
        v = a[:, 0]
        v = v[~_np.isnan(v)]
        return float(v.max()) if v.size else -1.0
    except Exception:
        return -1.0


# 에피소드별 후보 스냅샷 수집. recover 모드는 에피소드당 1개(마지막 직전 = 아직
# 회복 여지가 있는 중간 상태; 맨 마지막은 타임아웃 종료 상태라 제외)를 골라
# **여러 에피소드에 고르게** 분산시킨다 (감사: 정렬 앞 2판에서만 뽑히던 문제).
import numpy as _np0
cands = []   # (ep_dir, snap_path, robot_z)
for ep in sorted(glob.glob(os.path.join(SRC, f"{GARMENT_DIR}_*"))):
    if not os.path.isdir(ep):
        continue
    snaps = sorted(glob.glob(os.path.join(ep, "snap_*.npz")))
    if MODE == "semi":
        if _peak_pred(ep) < 0.35 and _npass_of(ep) < 3:
            continue
    if MODE == "success":
        pick = [s for s in snaps if int(os.path.basename(s)[5:9]) <= 5]
    else:
        mid = [s for s in snaps if int(os.path.basename(s)[5:9]) > 5]
        pick = [mid[-2]] if len(mid) >= 2 else mid[-1:]
    for s in pick:
        try:
            rz = float(_np0.load(s)["robot_z"])
        except Exception:
            rz = 0.5
        cands.append((ep, s, round(rz, 4)))

# 로봇 높이: 스냅샷마다 수집 청크의 z 가 다르다(±10mm). 무대는 프로세스당 1개
# 높이로만 지을 수 있으므로 **다수 높이를 골라 그 스냅샷만** 복원한다 (감사 지적:
# 이걸 무시하면 팔 높이가 1cm 어긋난 상태에서 회복을 시도하게 된다).
if cands:
    from collections import Counter as _Ctr
    z_major = _Ctr(rz for _, _, rz in cands).most_common(1)[0][0]
    os.environ["LEHOME_ROBOT_Z"] = f"{z_major:.4f}"
    cands = [c for c in cands if c[2] == z_major]
    say_z = f"로봇 z={z_major:.4f} (스냅샷 {len(cands)}개 일치)"
else:
    say_z = "스냅샷 없음"
cands_all = [s for _, s, _ in cands]
snap_files = cands_all[:MAX_SNAPS]
say(f"=== 22단 리플레이({MODE}): {GARMENT_DIR} 스냅샷 {len(snap_files)}개 "
    f"× {PER_SNAP}회 -> {OUT} === [{say_z}]")
if not snap_files:
    say("스냅샷 없음 — 종료")
    raise SystemExit(0)

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True})

try:
    import numpy as np
    import torch
    from PIL import Image
    from isaacsim.core.api import World
    from isaacsim.core.utils.types import ArticulationAction

    sys.path.insert(0, HERE)
    import lehome_scene as LS
    from lehome_scene import (add_cameras, build_scene, check_success_top,
                              randomize_garment_texture, randomize_table_texture)

    LS.pick_garment = lambda gt, say=say: os.path.join(
        LS.ASSETS, "objects", "Challenge_Garment", "Release", GARMENT_TYPE,
        GARMENT_DIR)

    world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0")
    scene = build_scene(world, say=say, garment_type=GARMENT_TYPE)
    cams = add_cameras(scene["stage"], say=say)
    for _ in range(60):
        world.step(render=True)

    robots = scene["robots"]
    left, right = robots["Left_Robot"], robots["Right_Robot"]
    view = scene["view"]

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect(("127.0.0.1", PORT))
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    conn.settimeout(300.0)

    def get_obs():
        state = np.concatenate([
            left.get_joint_positions().cpu().numpy(),
            right.get_joint_positions().cpu().numpy()]).astype(np.float32)
        images = {k: np.asarray(c.get_rgba())[..., :3].astype(np.uint8)
                  for k, c in cams.items()}
        return state, images

    def restore(snap, rng):
        """물리 상태 복원 + 시각 랜덤화 재추첨 (논문의 핵심: 물리는 같고 겉모습만 다름)."""
        d = np.load(snap)
        pos = torch.tensor(d["cloth_pos"], device="cuda:0", dtype=torch.float32)
        vel = torch.tensor(d["cloth_vel"], device="cuda:0", dtype=torch.float32)
        if pos.dim() == 2:
            pos = pos[None]
            vel = vel[None]
        view.set_world_positions(pos)
        view.set_velocities(vel)
        left.set_joint_positions(torch.tensor(d["qL"], device="cuda:0"))
        right.set_joint_positions(torch.tensor(d["qR"], device="cuda:0"))
        left.set_joint_velocities(torch.zeros(6, device="cuda:0"))
        right.set_joint_velocities(torch.zeros(6, device="cuda:0"))

        # 시각만 새로 뽑는다 (조명 + 테이블/옷 텍스처)
        from pxr import UsdLux as _UL, Gf as _Gf
        from isaacsim.core.utils.stage import get_current_stage as _gcs
        stage = _gcs()
        dome = _UL.DomeLight(stage.GetPrimAtPath("/World/Light"))
        dome.GetIntensityAttr().Set(float(rng.uniform(800.0, 2000.0)))
        col = 0.6 + 0.4 * rng.uniform(size=3)
        dome.GetColorAttr().Set(_Gf.Vec3f(*[float(c) for c in col]))
        randomize_table_texture(stage, rng, say)
        # 옷 텍스처 스왑은 수집기와 같은 환경변수로 켠다 (교사 성공률 보호).
        # 성공 리플레이(성공만 보관)에서는 논문대로 p=0.8 까지 세게 걸어도 된다.
        if os.environ.get("LEHOME_RAND_GARMENT_TEX") == "1" and rng.rand() < 0.8:
            randomize_garment_texture(stage, rng, say)

        # 카메라 annotator 갱신 (리셋 뒤 렌더 필수 — 검증된 함정)
        for _ in range(12):
            world.step(render=True)

    # --- 오프라인 점수 선별 (감사 제안): 후보 스냅샷의 천 좌표로 판정 조건을 계산해
    # "거의 성공(통과 조건 많고 여유가 작은)" 상태부터 재시도한다. 시각 정보 없이
    # 물리 상태만으로 계산 가능. 성공 모드(step5)는 점수 무의미하므로 recover/semi 만.
    if MODE in ("recover", "semi") and snap_files:
        idx_ck = list(scene["check_idx"])
        thr_ck = [t * float(scene["gcfg"]["scale"][0])
                  for t in scene["gcfg"]["success_distance"]]
        pairs = [(0, 4), (2, 3), (1, 5), (0, 1), (4, 5)]
        scored = []
        for s_path in cands_all if 'cands_all' in dir() else snap_files:
            try:
                cp = np.load(s_path)["cloth_pos"].reshape(-1, 3)[idx_ck] * 100.0
            except Exception:
                continue
            dd = [float(np.linalg.norm(cp[a] - cp[b])) for a, b in pairs]
            passed = [dd[0] <= thr_ck[0], dd[1] <= thr_ck[1], dd[2] <= thr_ck[2],
                      dd[3] >= thr_ck[3], dd[4] >= thr_ck[4]]
            # 근접 조건 여유(작을수록 좋음) — 미통과 조건만 합산
            deficit = sum(max(0.0, dd[k] - thr_ck[k]) for k in range(3)) +                       sum(max(0.0, thr_ck[k] - dd[k]) for k in (3, 4))
            scored.append((sum(passed), -deficit, s_path))
        scored.sort(reverse=True)
        snap_files = [s_path for _, _, s_path in scored][:MAX_SNAPS]
        say("[select] 상위 스냅샷 (통과수, -여유cm): " +
            ", ".join(f"{a}/{-b:.1f}" for a, b, _ in scored[:MAX_SNAPS]))

    n_kept = 0
    for si, snap in enumerate(snap_files):
        for rep in range(PER_SNAP):
            rng = np.random.RandomState(SEED * 10000 + si * 100 + rep)
            tag = f"{os.path.basename(os.path.dirname(snap))}_" \
                  f"{os.path.basename(snap)[:-4]}_s{SEED}_r{rep}"
            say(f"--- [{si+1}/{len(snap_files)}] {tag} ---")
            restore(snap, rng)
            send_msg(conn, {"reset": True})
            recv_msg(conn)

            ep_dir = os.path.join(OUT, tag)
            shutil.rmtree(ep_dir, ignore_errors=True)
            for sub in ("top", "left", "right"):
                os.makedirs(os.path.join(ep_dir, sub), exist_ok=True)
            states, actions = [], []
            success, succ_step = False, -1
            t0 = time.time()
            for i in range(N_STEPS):
                state, images = get_obs()
                send_msg(conn, {"state": state, "images": images})
                rsp = recv_msg(conn)
                act = np.asarray(rsp["action"], dtype=np.float32)
                states.append(state)
                actions.append(act)
                for key, sub in (("observation.images.top_rgb", "top"),
                                 ("observation.images.left_rgb", "left"),
                                 ("observation.images.right_rgb", "right")):
                    Image.fromarray(images[key]).save(
                        os.path.join(ep_dir, sub, f"{i:04d}.jpg"), quality=92)
                left.apply_action(ArticulationAction(
                    joint_positions=torch.tensor(act[:6], device="cuda:0")))
                right.apply_action(ArticulationAction(
                    joint_positions=torch.tensor(act[6:], device="cuda:0")))
                world.step(render=True)
                if i % 30 == 29:
                    if check_success_top(scene["view"], scene["gcfg"], say=say,
                                         idx=scene["check_idx"]):
                        success, succ_step = True, i + 1
                        break

            if success:
                np.save(os.path.join(ep_dir, "states.npy"), np.stack(states))
                np.save(os.path.join(ep_dir, "actions.npy"), np.stack(actions))
                with open(os.path.join(ep_dir, "meta.json"), "w",
                          encoding="utf-8") as f:
                    json.dump({"garment": GARMENT_DIR, "steps": len(states),
                               "success_step": succ_step, "fps_nominal": 60,
                               "robot_z": LS.ROBOT_Z, "replay_of": snap,
                               "mode": MODE}, f, indent=1)
                n_kept += 1
                say(f"  성공(step {succ_step}) -> 보관 ({time.time()-t0:.0f}초)")
            else:
                shutil.rmtree(ep_dir, ignore_errors=True)
                say(f"  실패 -> 폐기 ({time.time()-t0:.0f}초)")

    conn.close()
    say("")
    say(f"리플레이 완료: {n_kept}판 증식 ({len(snap_files)}스냅샷 × {PER_SNAP})")

except Exception:
    import traceback
    say("EXCEPTION:")
    say(traceback.format_exc())

app.close()
