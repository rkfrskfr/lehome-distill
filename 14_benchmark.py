"""14단: 성공률 측정 — 한 옷으로 여러 판(공식 soft reset 랜덤 적용).

Isaac 부팅이 비싸므로 한 프로세스에서 N판을 돈다.
    "C:/isaacsim/python.bat" 14_benchmark.py --garment-dir Top_Long_Seen_1 \
        --episodes 3 --steps 400 --port 8767 --tag winner

결과: bench_<tag>.csv (판별 성공여부/스텝/최종거리), 요약은 bench_<tag>.txt
"""

import csv
import os
import pickle
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


GARMENT_DIR = arg("--garment-dir", "Top_Long_Seen_1")
GARMENT_TYPE = arg("--garment-type", "Top_Long")
EPISODES = int(arg("--episodes", "3"))
N_STEPS = int(arg("--steps", "400"))
PORT = int(arg("--port", "8767"))
TAG = arg("--tag", "winner")
SEED = int(arg("--seed", "0"))
# 공식 evaluation.py 는 정책 행동 1개당 env.step 1회 = 물리 1스텝(dt=1/90).
# 3으로 두면 정책이 학습 때보다 3배 느린 시간에서 돌아 폐루프가 어긋난다.
PHYS_PER_ACTION = int(arg("--phys-per-action", "1"))
RESET_MODE = arg("--reset-mode", "initial")

# 평가는 항상 명목 조건: 드라이버 셸에 남은 수집용 랜덤화 환경변수가 새어 들어와
# 평가 조건을 바꾸는 사고를 막는다 (--keep-env 로 명시할 때만 허용).
if "--keep-env" not in sys.argv:
    for _k in list(os.environ):
        if _k.startswith("LEHOME_RAND_") or _k in ("LEHOME_DROP_Z_RANGE",):
            os.environ.pop(_k, None)

CSV_PATH = os.path.join(HERE, f"bench_{TAG}.csv")
CSV_FIELDS = ["garment", "ep", "success", "step", "n_pass",
              "d0", "d1", "d2", "d3", "d4", "sec"]
TXT_PATH = os.path.join(HERE, f"bench_{TAG}_{GARMENT_DIR}.txt")

_lines = []


def say(msg):
    _lines.append(str(msg))
    with open(TXT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(_lines) + "\n")
    print(msg, flush=True)


def send_msg(conn, obj):
    data = pickle.dumps(obj, protocol=4)
    conn.sendall(struct.pack("<I", len(data)) + data)


def recv_msg(conn):
    hdr = conn.recv(4, socket.MSG_WAITALL)
    if len(hdr) < 4:
        return None
    (ln,) = struct.unpack("<I", hdr)
    buf = b""
    while len(buf) < ln:
        chunk = conn.recv(min(1 << 20, ln - len(buf)))
        if not chunk:
            return None
        buf += chunk
    return pickle.loads(buf)


say(f"=== 14단 성능측정: {GARMENT_DIR} × {EPISODES}판 (최대 {N_STEPS}스텝, 포트 {PORT}) ===")

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": True})

rows = []
try:
    import numpy as np
    import torch
    from isaacsim.core.api import World
    from isaacsim.core.utils.types import ArticulationAction

    sys.path.insert(0, HERE)
    import lehome_scene as LS
    from lehome_scene import (add_cameras, build_scene, check_success_top,
                              reset_episode)

    # 지정한 옷 하나만 쓰도록 선택기를 고정
    LS.pick_garment = lambda gt, say=say: os.path.join(
        LS.ASSETS, "objects", "Challenge_Garment", "Release", GARMENT_TYPE,
        GARMENT_DIR)

    # 물리 dt: 공식은 1/90 이지만 우리 복제에서는 1/60 이 압도적으로 낫다
    # (실측 120판: 1/60 -> 45.8%, 1/90 -> 3.3%). 원인 미확명 — 우리 팔이 공식보다
    # 느려서 행동당 시간이 더 필요한 것으로 보인다. 남은 최대 미스터리.
    PHYS_DT = float(arg("--phys-dt", str(1.0 / 60.0)))
    world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0",
                  physics_dt=PHYS_DT, rendering_dt=PHYS_DT)
    say(f"물리 dt={PHYS_DT:.5f} ({1/PHYS_DT:.0f}Hz), 행동당 {PHYS_PER_ACTION}스텝 "
        f"= 행동당 {1000*PHYS_DT*PHYS_PER_ACTION:.1f}ms")
    scene = build_scene(world, say=say, garment_type=GARMENT_TYPE)
    cams = add_cameras(scene["stage"], say=say)
    for _ in range(60):
        world.step(render=True)

    robots = scene["robots"]
    left, right = robots["Left_Robot"], robots["Right_Robot"]

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect(("127.0.0.1", PORT))
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    say(f"서버 연결 OK (포트 {PORT})")

    def get_obs():
        state = np.concatenate([
            left.get_joint_positions().cpu().numpy(),
            right.get_joint_positions().cpu().numpy()]).astype(np.float32)
        images = {k: np.asarray(c.get_rgba())[..., :3].astype(np.uint8)
                  for k, c in cams.items()}
        return state, images

    for ep in range(EPISODES):
        rng = np.random.RandomState(SEED * 1000 + ep)
        say("")
        say(f"--- 에피소드 {ep+1}/{EPISODES} ---")
        placed = reset_episode(world, scene, rng, settle_steps=180, say=say,
                               mode=RESET_MODE)
        if not placed:
            say("  배치 실패 — 이 판 건너뜀")
            rows.append({"garment": GARMENT_DIR, "ep": ep, "success": "PLACE_FAIL",
                         "step": -1})
            continue

        send_msg(conn, {"reset": True})
        recv_msg(conn)

        t0 = time.time()
        success, succ_step = False, -1
        for i in range(N_STEPS):
            state, images = get_obs()
            send_msg(conn, {"state": state, "images": images})
            rsp = recv_msg(conn)
            act = np.asarray(rsp["action"], dtype=np.float32)
            left.apply_action(ArticulationAction(
                joint_positions=torch.tensor(act[:6], device="cuda:0")))
            right.apply_action(ArticulationAction(
                joint_positions=torch.tensor(act[6:], device="cuda:0")))
            for k in range(PHYS_PER_ACTION):
                world.step(render=(k == 0))

            if i % 50 == 49:
                if check_success_top(scene["view"], scene["gcfg"], say=say,
                                     idx=scene["check_idx"]):
                    success, succ_step = True, i + 1
                    say(f"  *** 성공 (step {i+1}) ***")
                    break

        dt = time.time() - t0
        idx = list(scene["check_idx"])
        thr = [t * float(scene["gcfg"]["scale"][0])
               for t in scene["gcfg"]["success_distance"]]
        p = scene["view"].get_world_positions().cpu().numpy().reshape(-1, 3)[idx] * 100
        d = [float(np.linalg.norm(p[a] - p[b]))
             for a, b in ((0, 4), (2, 3), (1, 5), (0, 1), (4, 5))]
        n_pass = sum([d[0] <= thr[0], d[1] <= thr[1], d[2] <= thr[2],
                      d[3] >= thr[3], d[4] >= thr[4]])
        say(f"  결과: 성공={success} 조건통과={n_pass}/5 "
            f"거리={[round(x,1) for x in d]} ({dt:.0f}초)")
        rows.append({"garment": GARMENT_DIR, "ep": ep,
                     "success": int(success), "step": succ_step,
                     "n_pass": n_pass,
                     **{f"d{j}": round(v, 2) for j, v in enumerate(d)},
                     "sec": round(dt)})

    conn.close()
    n_ok = sum(1 for r in rows if r.get("success") == 1)
    say("")
    say(f"=== {GARMENT_DIR}: {n_ok}/{len(rows)} 성공 ===")

except Exception:
    import traceback
    say("EXCEPTION:")
    say(traceback.format_exc())

# CSV 누적 (여러 옷 실행분을 한 파일에)
if rows:
    exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        # 고정 필드: 첫 행이 PLACE_FAIL 이어도 열이 깨지지 않게
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerows(rows)

app.close()
