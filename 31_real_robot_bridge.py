"""31단: 실물 SO-101 양팔 브리지 — 소형 모델 서버(12_policy_server, TCP 8766)의
관절 명령을 실물 팔로 보낸다. 월요일 실물 연동 테스트용 (lerobot venv 에서 실행).

모드:
  --selftest : 로봇·카메라 없이 모델 서버와의 프로토콜만 검증 (가짜 관측 3회) — 2026-09-05 통과
  --check : 두 팔 연결 + 현재 관절각 출력 (모터 통신 확인)
  --home  : 시뮬 홈 자세로 5초에 걸쳐 천천히 이동 (부호/오프셋 정합 확인용)
  --run   : 웹캠 3대 관측 -> 모델 서버 -> 관절 명령 폐루프 (기본은 dry-run: 출력만)
            실제 구동은 --live 를 붙여야 한다.

단위 규약 (실수 방지용, 논문 §9.11 의 '단위 버그' 교훈):
  - 시뮬/모델: 12관절 **라디안**, 순서 [왼팔 6, 오른팔 6] = MOTOR_NAMES
  - lerobot SOFollower(use_degrees=True): 팔 5관절 **도(deg)**, 그리퍼 0~100
  - 시뮬 관절 0점과 실물 캘리브 0점이 다를 수 있으므로 OFFSET_DEG/SIGN 표로 보정한다.
    --home 으로 실물이 시뮬 홈 자세와 같은 모양이 되는지 눈으로 확인 후 표를 고친다.

    python 31_real_robot_bridge.py --check --left COM5 --right COM6
    python 31_real_robot_bridge.py --home  --left COM5 --right COM6
    python 31_real_robot_bridge.py --run   --left COM5 --right COM6 --cams 0,1,2 [--live]
"""

import math
import pickle
import socket
import struct
import sys
import time

import numpy as np

MOTORS = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex",
          "wrist_roll", "gripper"]
# 시뮬 홈 자세 (lehome_scene.HOME, 라디안; 왼팔은 pan 부호 반전)
HOME_R = [1.2363, -1.7135, 1.4979, 1.0534, -0.085, -0.01176]
HOME_L = [-1.2363, -1.7135, 1.4979, 1.0534, -0.085, -0.01176]

# 시뮬(rad) -> 실물(deg) 보정표. 월요일 --home 결과를 보고 채운다.
#   real_deg = SIGN * rad2deg(sim_rad) + OFFSET_DEG
SIGN = {m: 1.0 for m in MOTORS}
OFFSET_DEG = {m: 0.0 for m in MOTORS}
# 그리퍼: 시뮬 관절각(rad) -> 실물 0~100. 수집 데이터(r4, 60판) 실측: 닫힘 -0.2~-0.1,
# 열림 최대 0.69 → 아래 범위. 실물 그리퍼 0/100 이 어느 쪽인지 --home 에서 확인 후 조정.
GRIP_RAD_OPEN, GRIP_RAD_CLOSED = 0.7, -0.2


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


def rad_to_real(prefix, q_rad):
    """6관절 라디안 -> lerobot action dict (deg / 그리퍼 0~100)."""
    out = {}
    for m, r in zip(MOTORS, q_rad):
        if m == "gripper":
            t = (r - GRIP_RAD_CLOSED) / (GRIP_RAD_OPEN - GRIP_RAD_CLOSED)
            out[f"{prefix}_{m}.pos"] = float(np.clip(t * 100.0, 0.0, 100.0))
        else:
            out[f"{prefix}_{m}.pos"] = float(SIGN[m] * math.degrees(r) + OFFSET_DEG[m])
    return out


def real_to_rad(prefix, obs):
    """lerobot observation -> 6관절 라디안 (모델 state 입력용)."""
    q = []
    for m in MOTORS:
        v = float(obs[f"{prefix}_{m}.pos"])
        if m == "gripper":
            q.append(GRIP_RAD_CLOSED + (v / 100.0) * (GRIP_RAD_OPEN - GRIP_RAD_CLOSED))
        else:
            q.append(math.radians((v - OFFSET_DEG[m]) / SIGN[m]))
    return q


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


def make_robot(left_port, right_port, max_rel):
    from lerobot.robots.bi_so_follower import BiSOFollower, BiSOFollowerConfig
    from lerobot.robots.so_follower import SOFollowerConfig
    cfg = BiSOFollowerConfig(
        id=arg("--id", "lehome_bi"),
        left_arm_config=SOFollowerConfig(port=left_port, cameras={},
                                         use_degrees=True,
                                         max_relative_target=max_rel),
        right_arm_config=SOFollowerConfig(port=right_port, cameras={},
                                          use_degrees=True,
                                          max_relative_target=max_rel),
        cameras={})
    robot = BiSOFollower(cfg)
    robot.connect()          # 캘리브 파일이 없으면 lerobot 캘리브 절차가 뜬다
    return robot


def print_joints(robot):
    obs = robot.get_observation()
    for p in ("left", "right"):
        vals = [round(float(obs[f"{p}_{m}.pos"]), 1) for m in MOTORS]
        print(f"  {p:5s} deg/grip: {vals}")
    return obs


def move_slowly(robot, target, seconds=5.0, hz=30):
    """현재 자세 -> 목표 자세로 선형 보간 이동 (급가속 방지)."""
    obs = robot.get_observation()
    cur = {k: float(obs[k]) for k in target}
    n = int(seconds * hz)
    for i in range(1, n + 1):
        a = i / n
        step = {k: cur[k] + a * (target[k] - cur[k]) for k in target}
        robot.send_action(step)
        time.sleep(1.0 / hz)


def main():
    left, right = arg("--left", "COM5"), arg("--right", "COM6")
    max_rel = float(arg("--max-rel", "20"))     # 한 번에 최대 20도만 이동 (안전)

    if "--selftest" in sys.argv:
        # 로봇·카메라 없이 프로토콜만 검증: 가짜 관측 -> 모델 서버 -> 관절 명령 변환
        conn = socket.create_connection(("127.0.0.1", int(arg("--port", "8766"))))
        send_msg(conn, {"reset": True}); print("[selftest] reset ->", recv_msg(conn))
        keys = ["observation.images.top_rgb", "observation.images.left_rgb",
                "observation.images.right_rgb"]
        rng = np.random.RandomState(0)
        state = np.array(HOME_L + HOME_R, dtype=np.float32)
        for i in range(3):
            images = {k: rng.randint(0, 255, (480, 640, 3), dtype=np.uint8) for k in keys}
            t0 = time.time()
            send_msg(conn, {"state": state, "images": images})
            act = np.asarray(recv_msg(conn)["action"], dtype=np.float32)
            target = {**rad_to_real("left", act[:6]), **rad_to_real("right", act[6:])}
            print(f"[selftest] step {i}: {1000*(time.time()-t0):.0f}ms, action(rad) "
                  f"{np.round(act, 3).tolist()}")
            print("           real(deg/grip):", {k: round(v, 1) for k, v in target.items()})
            assert act.shape == (12,) and np.isfinite(act).all()
            state = act
        conn.close(); print("[selftest] OK — 12관절 명령 생성·변환 정상")
        return

    if "--check" in sys.argv:
        robot = make_robot(left, right, max_rel)
        print("[bridge] 연결 OK — 현재 관절:")
        print_joints(robot)
        robot.disconnect()
        return

    if "--home" in sys.argv:
        robot = make_robot(left, right, max_rel)
        print("[bridge] 현재:"); print_joints(robot)
        target = {**rad_to_real("left", HOME_L), **rad_to_real("right", HOME_R)}
        print("[bridge] 목표(홈, deg):", {k: round(v, 1) for k, v in target.items()})
        input("  Enter 를 누르면 5초에 걸쳐 홈 자세로 이동합니다 (주변 확인!) ")
        move_slowly(robot, target, seconds=5.0)
        print("[bridge] 도착:"); print_joints(robot)
        print("  -> 실물이 시뮬 홈 자세(팔을 접어 몸쪽으로)와 같은 모양인지 확인. "
              "다르면 SIGN/OFFSET_DEG 표를 수정.")
        robot.disconnect()
        return

    if "--run" in sys.argv:
        import cv2
        live = "--live" in sys.argv
        cam_ids = [int(x) for x in arg("--cams", "0,1,2").split(",")]
        keys = ["observation.images.top_rgb", "observation.images.left_rgb",
                "observation.images.right_rgb"]
        caps = []
        for cid in cam_ids:
            cap = cv2.VideoCapture(cid, cv2.CAP_DSHOW)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            caps.append(cap)
        robot = make_robot(left, right, max_rel)
        conn = socket.create_connection(("127.0.0.1", int(arg("--port", "8766"))))
        send_msg(conn, {"reset": True}); recv_msg(conn)
        print(f"[bridge] 폐루프 시작 (live={live}). Ctrl+C 로 종료.")
        period = 1.0 / 30.0     # 모델은 30Hz 데이터로 학습됨
        try:
            while True:
                t0 = time.time()
                obs = robot.get_observation()
                state = np.array(real_to_rad("left", obs) + real_to_rad("right", obs),
                                 dtype=np.float32)
                images = {}
                for key, cap in zip(keys, caps):
                    ok, frame = cap.read()
                    if not ok:
                        raise RuntimeError(f"카메라 읽기 실패: {key}")
                    frame = cv2.resize(frame, (640, 480))
                    images[key] = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB).astype(np.uint8)
                send_msg(conn, {"state": state, "images": images})
                act = np.asarray(recv_msg(conn)["action"], dtype=np.float32)
                target = {**rad_to_real("left", act[:6]), **rad_to_real("right", act[6:])}
                if live:
                    robot.send_action(target)
                else:
                    print("  dry-run:", {k: round(v, 1) for k, v in target.items()})
                time.sleep(max(0.0, period - (time.time() - t0)))
        except KeyboardInterrupt:
            pass
        finally:
            conn.close(); robot.disconnect()
            for cap in caps:
                cap.release()
        return

    print(__doc__)


if __name__ == "__main__":
    main()
