"""16단: 증류 데이터 수집 — 우승팀 정책(교사)의 성공 에피소드를 기록한다.

매 정책 스텝마다 카메라 3대 JPG + 상태(12) + 행동(12)을 저장하고,
성공한 에피소드만 남긴다 (실패는 디렉터리째 삭제).
결과물은 so101-fresh 12_convert 패턴으로 LeRobot 데이터셋으로 변환 예정.

    "C:/isaacsim/python.bat" 16_collect_distill.py --garment-dir Top_Long_Seen_5 \
        --episodes 8 --steps 600 --port 8767 --out distill_data
"""

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


GARMENT_DIR = arg("--garment-dir", "Top_Long_Seen_5")
GARMENT_TYPE = arg("--garment-type", "Top_Long")
EPISODES = int(arg("--episodes", "8"))
# 성공 N판 채울 때까지 시도 (상한 3N). 0 이면 기존 방식(--episodes 고정 시도).
TARGET_KEEPS = int(arg("--target-keeps", "0"))
# 실패판도 <OUT>_fail\ 에 보관 (성공 예측기·AWR 학습용. 변환기는 OUT 만 읽으므로
# 증류 데이터는 오염되지 않는다). 프레임은 어차피 찍고 지우던 것이라 추가 비용 없음.
KEEP_FAIL = "--keep-fail" in sys.argv
# 물리 상태 스냅샷 (우승자 논문 §3.2): step 5 = 리플레이 증식용 시작 상태,
# 실패판은 100스텝마다 = 교사 회복 시도(자동 DAgger)용 중간 상태.
SNAPSHOT = "--snapshot" in sys.argv
# 조기 종료 (논문 §3.1 stuck detector): 가망 없는 판을 끝까지 돌리지 않는다.
# 실패판이 전체의 ~72% 이고 각각 600스텝을 완주하므로 수집 시간의 큰 몫을 낭비한다.
EARLY_KILL = "--early-kill" in sys.argv
EARLY_MIN_STEP = int(arg("--early-min-step", "300"))
EARLY_PATIENCE = int(arg("--early-patience", "180"))
# 스텝 단위 시각 흔들기 (논문 §3.3 per-step). 에피소드 단위만 하면 판마다
# 겉모습이 고정돼 '이 판은 이런 색' 이라는 지름길 신호가 남는다.
PERSTEP_AUG = os.environ.get("LEHOME_RAND_PERSTEP") == "1"
N_STEPS = int(arg("--steps", "600"))
PORT = int(arg("--port", "8767"))
OUT = os.path.join(HERE, arg("--out", "distill_data"))
SEED = int(arg("--seed", "100"))
os.makedirs(OUT, exist_ok=True)
RESULT = os.path.join(HERE, f"16_result_{GARMENT_DIR}_s{SEED}.txt")

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
    # MSG_WAITALL 은 윈도우에서 타임아웃 소켓과 함께 못 쓴다 (WinError 10045)
    # — settimeout 을 쓰므로 루프로 4바이트를 채운다.
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


if TARGET_KEEPS > 0:
    say(f"=== 16단 증류 수집: {GARMENT_DIR} 성공 {TARGET_KEEPS}판 목표 "
        f"(최대 {TARGET_KEEPS * 3}시도) -> {OUT} ===")
else:
    say(f"=== 16단 증류 수집: {GARMENT_DIR} × {EPISODES}판 -> {OUT} ===")

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
                              jitter_cameras, perstep_light, reset_episode)

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

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect(("127.0.0.1", PORT))
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    # 야간 무인 실행 보호: 교사 서버가 죽으면 무한 대기 대신 예외로 종료
    conn.settimeout(300.0)

    def get_obs():
        state = np.concatenate([
            left.get_joint_positions().cpu().numpy(),
            right.get_joint_positions().cpu().numpy()]).astype(np.float32)
        images = {k: np.asarray(c.get_rgba())[..., :3].astype(np.uint8)
                  for k, c in cams.items()}
        return state, images

    def n_pass_now():
        """현재 통과 조건 수 (0~5). 진전 여부 판정용."""
        idx = list(scene["check_idx"])
        thr = [t * float(scene["gcfg"]["scale"][0])
               for t in scene["gcfg"]["success_distance"]]
        p = scene["view"].get_world_positions().cpu().numpy().reshape(
            -1, 3)[idx] * 100.0

        def d(a, b):
            return float(np.linalg.norm(p[a] - p[b]))

        return sum([d(0, 4) <= thr[0], d(2, 3) <= thr[1], d(1, 5) <= thr[2],
                    d(0, 1) >= thr[3], d(4, 5) >= thr[4]])

    def save_snap(ep_dir, i):
        """물리 상태 스냅샷: 천 입자 pos/vel + 관절각. 복원 = set_world_positions
        + set_velocities + set_joint_positions (reinject_garment 과 동일 API)."""
        v = scene["view"]
        try:
            vel = v.get_velocities().cpu().numpy()
        except Exception:
            vel = np.zeros((1, scene["baked"].shape[0], 3), dtype=np.float32)
        np.savez_compressed(
            os.path.join(ep_dir, f"snap_{i:04d}.npz"), step=i,
            cloth_pos=v.get_world_positions().cpu().numpy(),
            cloth_vel=vel,
            qL=left.get_joint_positions().cpu().numpy(),
            qR=right.get_joint_positions().cpu().numpy(),
            robot_z=LS.ROBOT_Z)

    n_kept = 0
    max_eps = TARGET_KEEPS * 3 if TARGET_KEEPS > 0 else EPISODES
    for ep in range(max_eps):
        if TARGET_KEEPS > 0 and n_kept >= TARGET_KEEPS:
            break
        rng = np.random.RandomState(SEED * 1000 + ep)
        say(f"--- 에피소드 {ep+1}/{max_eps} (보관 {n_kept}) ---")
        if not reset_episode(world, scene, rng, settle_steps=180, say=say,
                             mode="initial"):
            say("  배치 실패, 건너뜀")
            continue
        # 카메라 지터는 리셋 직후 1회 (교사가 공식 포즈로 학습됐으므로 약하게)
        if os.environ.get("LEHOME_RAND_CAM") == "1":
            jitter_cameras(cams, scene["stage"], rng, say=say)
            for _ in range(6):
                world.step(render=True)

        send_msg(conn, {"reset": True})
        recv_msg(conn)

        ep_dir = os.path.join(OUT, f"{GARMENT_DIR}_s{SEED}_e{ep:03d}")
        # 재실행 시 이전 실행의 잔재 프레임이 섞이지 않게 통째로 비운다
        # (GPU 천 물리는 비트 결정적이지 않아 성공 스텝 수가 달라질 수 있음)
        shutil.rmtree(ep_dir, ignore_errors=True)
        for sub in ("top", "left", "right"):
            os.makedirs(os.path.join(ep_dir, sub), exist_ok=True)
        states, actions, preds = [], [], []
        success, succ_step = False, -1
        best_pass, last_gain = 0, 0
        # 교사(π0.5)가 매 스텝 돌려주는 성공확률로 '망친 순간'을 잡는다.
        # 논문 §3.2: EMA(α=0.2) 가 자기 최고치(>0.25) 대비 0.12 이상 떨어지는
        # 지점 = 유망하던 판을 정책이 눈에 띄게 망친 순간 -> 하드마이닝 상태로 저장.
        # 절대값은 시작조건에 좌우되지만 '하락폭'은 그 편향이 상쇄된다.
        ema, run_max, ruin_saved = None, 0.0, 0

        t0 = time.time()
        for i in range(N_STEPS):
            state, images = get_obs()
            send_msg(conn, {"state": state, "images": images})
            rsp = recv_msg(conn)
            act = np.asarray(rsp["action"], dtype=np.float32)
            pr = rsp.get("pred") or {}
            sp = pr.get("success_pred")
            try:
                sp = float(np.asarray(sp).reshape(-1)[0]) if sp is not None else None
            except Exception:
                sp = None
            preds.append([sp if sp is not None else np.nan,
                          float(np.asarray(pr.get("completion_pred", np.nan))
                                .reshape(-1)[0])
                          if pr.get("completion_pred") is not None else np.nan])

            # 기록 (관측은 행동 결정 시점의 것)
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

            if PERSTEP_AUG and i % 10 == 0:
                perstep_light(scene["stage"], rng)

            if SNAPSHOT:
                if i == 5:
                    save_snap(ep_dir, i)
                elif sp is not None:
                    ema = sp if ema is None else 0.8 * ema + 0.2 * sp
                    if ema > run_max:
                        run_max = ema
                    elif (run_max > 0.25 and run_max - ema > 0.12
                          and ruin_saved < 3 and i > 30):
                        save_snap(ep_dir, i)
                        ruin_saved += 1
                        say(f"  [망친순간] step {i+1}: 성공확률 {run_max:.2f}"
                            f"->{ema:.2f} 스냅샷")
                        run_max = ema   # 다음 하락을 새로 재기 위해 기준 리셋
                elif i % 100 == 99:
                    save_snap(ep_dir, i)   # 예측값이 없을 때의 대비책

            if i % 30 == 29:  # 포크 방식: 30스텝마다 판정
                if check_success_top(scene["view"], scene["gcfg"], say=say,
                                     idx=scene["check_idx"]):
                    success, succ_step = True, i + 1
                    break
                if EARLY_KILL:
                    npass = n_pass_now()
                    if npass > best_pass:
                        best_pass, last_gain = npass, i
                    elif (i >= EARLY_MIN_STEP
                          and i - last_gain >= EARLY_PATIENCE):
                        say(f"  조기종료(step {i+1}): {EARLY_PATIENCE}스텝 진전 "
                            f"없음, 통과 {best_pass}/5")
                        break

        dt_wall = time.time() - t0
        if success:
            np.save(os.path.join(ep_dir, "states.npy"), np.stack(states))
            np.save(os.path.join(ep_dir, "actions.npy"), np.stack(actions))
            np.save(os.path.join(ep_dir, "preds.npy"),
                    np.asarray(preds, dtype=np.float32))
            meta = {"garment": GARMENT_DIR, "seed": SEED, "ep": ep,
                    "steps": len(states), "success_step": succ_step,
                    "fps_nominal": 60, "robot_z": LS.ROBOT_Z}
            with open(os.path.join(ep_dir, "meta.json"), "w",
                      encoding="utf-8") as f:
                json.dump(meta, f, indent=1)
            n_kept += 1
            say(f"  성공(step {succ_step}) -> 보관 ({dt_wall:.0f}초, "
                f"{len(states)}프레임)")
        elif KEEP_FAIL:
            np.save(os.path.join(ep_dir, "states.npy"), np.stack(states))
            np.save(os.path.join(ep_dir, "actions.npy"), np.stack(actions))
            np.save(os.path.join(ep_dir, "preds.npy"),
                    np.asarray(preds, dtype=np.float32))
            meta = {"garment": GARMENT_DIR, "seed": SEED, "ep": ep,
                    "steps": len(states), "success": False,
                    "fps_nominal": 60, "robot_z": LS.ROBOT_Z}
            with open(os.path.join(ep_dir, "meta.json"), "w",
                      encoding="utf-8") as f:
                json.dump(meta, f, indent=1)
            fail_root = OUT + "_fail"
            os.makedirs(fail_root, exist_ok=True)
            dst = os.path.join(fail_root, os.path.basename(ep_dir))
            shutil.rmtree(dst, ignore_errors=True)
            os.rename(ep_dir, dst)
            say(f"  실패 -> 보관(fail) ({dt_wall:.0f}초)")
        else:
            shutil.rmtree(ep_dir, ignore_errors=True)
            say(f"  실패 -> 폐기 ({dt_wall:.0f}초)")

    conn.close()
    say("")
    say(f"수집 완료: {n_kept} 에피소드 보관 (목표 "
        f"{TARGET_KEEPS if TARGET_KEEPS > 0 else EPISODES})")

except Exception:
    import traceback
    say("EXCEPTION:")
    say(traceback.format_exc())
    # 진행 중이던 에피소드가 meta.json 없이 남았으면 고아 폴더이므로 폐기
    _ed = globals().get("ep_dir")
    if _ed and not os.path.exists(os.path.join(_ed, "meta.json")):
        shutil.rmtree(_ed, ignore_errors=True)
        say(f"중단 에피소드 폐기: {os.path.basename(_ed)}")

app.close()
