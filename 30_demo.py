"""30단: 관전 데모 — GUI 창을 띄우고 소형 모델이 옷 접는 것을 계속 보여준다.

14_benchmark 와 동일한 폐루프이지만:
  - headless=False (아이작심 창이 뜸 — 3D 장면을 실시간 관전)
  - 가상 카메라 시점 창(TopCam/WristCam)도 추가로 띄움 (모델이 보는 화면)
  - CSV 없음, 에피소드 사이 잠깐 멈춰 결과를 보여줌

    "C:/isaacsim/python.bat" 30_demo.py --garment-dir Top_Long_Seen_2 \
        --episodes 3 --port 8766
"""

import os
import pickle
import socket
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


GARMENT_DIR = arg("--garment-dir", "Top_Long_Seen_2")
GARMENT_TYPE = arg("--garment-type", "Top_Long")
EPISODES = int(arg("--episodes", "3"))
N_STEPS = int(arg("--steps", "600"))
PORT = int(arg("--port", "8766"))
SEED = int(arg("--seed", str(int(time.time()) % 100000)))
PHYS_PER_ACTION = int(arg("--phys-per-action", "2"))


def say(m):
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


say(f"=== 데모: {GARMENT_DIR} × {EPISODES}판 (창을 닫거나 Ctrl+C 로 종료) ===")

from isaacsim import SimulationApp  # noqa: E402

app = SimulationApp({"headless": False})

try:
    import numpy as np
    import torch
    from isaacsim.core.api import World
    from isaacsim.core.utils.types import ArticulationAction

    sys.path.insert(0, HERE)
    import lehome_scene as LS
    from lehome_scene import (add_cameras, build_scene, check_success_top,
                              reset_episode)

    LS.pick_garment = lambda gt, say=say: os.path.join(
        LS.ASSETS, "objects", "Challenge_Garment", "Release", GARMENT_TYPE,
        GARMENT_DIR)

    world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0")
    scene = build_scene(world, say=say, garment_type=GARMENT_TYPE)
    cams = add_cameras(scene["stage"], say=say)

    # 모델이 보는 화면(가상 카메라)을 별도 뷰포트 창으로 (실패해도 데모는 계속)
    try:
        from omni.kit.viewport.utility import create_viewport_window
        for title, prim in (("모델 시점 - 상단", "/World/Robot/Right_Robot/base/top_camera"),
                            ("모델 시점 - 왼손목", "/World/Robot/Left_Robot/gripper/left_wrist_camera")):
            w = create_viewport_window(title, width=420, height=330)
            w.viewport_api.camera_path = prim
        say("[demo] 카메라 시점 창 2개 추가")
    except Exception as e:
        say(f"[demo] 시점 창 생성 실패(계속): {e!r}")

    for _ in range(60):
        world.step(render=True)

    robots = scene["robots"]
    left, right = robots["Left_Robot"], robots["Right_Robot"]

    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect(("127.0.0.1", PORT))
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def get_obs():
        state = np.concatenate([
            left.get_joint_positions().cpu().numpy(),
            right.get_joint_positions().cpu().numpy()]).astype(np.float32)
        images = {k: np.asarray(c.get_rgba())[..., :3].astype(np.uint8)
                  for k, c in cams.items()}
        return state, images

    n_ok = 0
    for ep in range(EPISODES):
        rng = np.random.RandomState(SEED * 1000 + ep)
        say(f"--- {GARMENT_DIR} 에피소드 {ep+1}/{EPISODES} ---")
        if not reset_episode(world, scene, rng, settle_steps=180, say=say,
                             mode="initial"):
            say("  배치 실패, 다음 판")
            continue
        send_msg(conn, {"reset": True})
        recv_msg(conn)

        success = False
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
            if i % 30 == 29 and check_success_top(
                    scene["view"], scene["gcfg"], say=lambda *_: None,
                    idx=scene["check_idx"]):
                success = True
                say(f"  ★ 성공! (step {i+1}, 약 {round((i+1)/30)}초)")
                break
        if not success:
            say("  실패 (시간 초과)")
        else:
            n_ok += 1

        # 결과를 3초간 보여주고 다음 판으로
        t0 = time.time()
        while time.time() - t0 < 3.0:
            world.step(render=True)

    conn.close()
    say(f"=== {GARMENT_DIR}: {n_ok}/{EPISODES} 성공 — 다음 옷으로 전환 ===")

except KeyboardInterrupt:
    say("사용자 종료")
except Exception:
    import traceback
    say("EXCEPTION:")
    say(traceback.format_exc())

app.close()
