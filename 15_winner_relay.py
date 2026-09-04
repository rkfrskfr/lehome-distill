"""15단(중계기): 우승팀 WebSocket 서버 <-> 우리 TCP 브리지.

Isaac Sim 파이썬에는 pip 이 막혀 있어(site-packages ACL) websockets 를 못 넣는다.
그래서 윈도우 일반 파이썬에서 중계기를 돌린다:

    Isaac Sim  --TCP(pickle)-->  이 중계기  --WebSocket(JSON)-->  WSL2 우승팀 서버

중계기가 청크 관리·옷종류 부트스트랩·inference_config 를 전부 처리하므로
시뮬 쪽은 기존과 똑같이 "관측 보내고 행동 하나 받기"만 하면 된다
(12_policy_server.py 와 동일한 TCP 프로토콜, 포트만 다름).

실행 (윈도우 일반 파이썬):
    python 15_winner_relay.py [--ws ws://localhost:8000] [--garment top_long]
"""

import asyncio
import base64
import json
import os
import pickle
import struct
import sys
import threading

import numpy as np
import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
TCP_HOST, TCP_PORT = "127.0.0.1", 8767
WS_URL = "ws://localhost:8000"
if "--ws" in sys.argv:
    WS_URL = sys.argv[sys.argv.index("--ws") + 1]
GARMENT = "top_long"
if "--garment" in sys.argv:
    GARMENT = sys.argv[sys.argv.index("--garment") + 1]
# 옷 종류를 고정하면 부트스트랩(모델의 자체 분류)을 건너뛴다.
# 대회 규정상 평가 때는 라벨을 못 쓰지만, 무대 검증 단계에서는
# '분류 실패'라는 교란 변수를 없애기 위해 쓴다.
FIXED_ID = None
if "--garment-id" in sys.argv:
    FIXED_ID = int(sys.argv[sys.argv.index("--garment-id") + 1])

GARMENT_TYPES = ("top_long", "top_short", "pant_long", "pant_short")

with open(os.path.join(HERE, "checkpoints", "winner_sim", "assets",
                       "inference_config.json"), encoding="utf-8") as f:
    INFER_CFG = json.load(f)["per_garment_type"]

# 청크 실행 상한 (--exec-limit N). 0 = 받은 만큼 전부 실행(기존 동작).
EXEC_LIMIT = int(sys.argv[sys.argv.index("--exec-limit") + 1])     if "--exec-limit" in sys.argv else 0
FULL_CFG = "--full-cfg" in sys.argv

IMG_KEYS = ("observation.images.top_rgb",
            "observation.images.left_rgb",
            "observation.images.right_rgb")


def log(msg):
    print(f"[relay] {msg}", flush=True)


def enc_img(arr):
    arr = np.ascontiguousarray(np.asarray(arr, dtype=np.uint8))
    return {"base64": base64.b64encode(arr.tobytes()).decode("ascii"),
            "shape": list(arr.shape), "dtype": "uint8"}


class WinnerPolicy:
    """청크 큐 + 옷종류 부트스트랩 + 인페인팅 앵커 관리."""

    def __init__(self, ws):
        self.ws = ws
        self.reset()

    def reset(self):
        self.queue = []
        self.garment_id = FIXED_ID   # None 이면 첫 청크로 부트스트랩
        self.initial_actions = None
        self.step = 0
        self.last_pred = {}
        if FIXED_ID is not None:
            log(f"옷 종류 고정: {GARMENT_TYPES[FIXED_ID]} (id={FIXED_ID})")

    def cfg(self):
        name = (GARMENT_TYPES[self.garment_id]
                if self.garment_id is not None else GARMENT)
        c = INFER_CFG[name]
        if FULL_CFG:
            # 체크포인트의 옷별 추론 설정을 **전부** 전달한다.
            # 지금까지 3개만 보내서 actions_to_execute(=5) 가 누락됐고, 우리는
            # 받은 청크를 끝까지 소비했다 — 학생에서 확인된 "눈 감고 실행" 문제와
            # 같은 계열. (실측: 학생은 청크 100→5 로 31%→66%)
            return dict(c)
        return {"noise_temperature": c["noise_temperature"],
                "cfg_scale": c["cfg_scale"],
                "time_threshold_inpaint": c["time_threshold_inpaint"]}

    async def act(self, state, images):
        if self.queue:
            return self.queue.pop(0)

        req = {
            "type": "infer_chunk",
            "session_id": "isaac",
            "observation.state": [float(v) for v in np.asarray(state).reshape(-1)],
            "inference_config": self.cfg(),
        }
        for k in IMG_KEYS:
            req[k] = enc_img(images[k])
        if self.garment_id is not None:
            req["garment_type_id"] = int(self.garment_id)
        if self.initial_actions is not None:
            req["initial_actions"] = self.initial_actions

        await self.ws.send(json.dumps(req))
        rsp = json.loads(await self.ws.recv())
        if "error" in rsp:
            raise RuntimeError(f"서버 오류: {rsp['error']}")

        self.last_pred = {k: rsp.get(k) for k in
                          ("success_pred", "completion_pred", "garment_type_pred",
                           "ttc_pred", "checkpoint_pred")}

        # 부트스트랩: 첫 청크는 옷 종류를 알아내는 용도로만 쓰고 제자리 유지
        if self.garment_id is None:
            self.garment_id = int(rsp.get("garment_type_pred", 0))
            log(f"옷 종류 확정: {GARMENT_TYPES[self.garment_id]} "
                f"(id={self.garment_id})")
            self.initial_actions = None
            return [float(v) for v in np.asarray(state).reshape(-1)]

        acts = rsp.get("actions") or []
        if not acts:
            raise RuntimeError("서버가 행동을 안 줌")
        if not hasattr(self, "_logged_len"):
            self._logged_len = True
            log(f"서버가 준 행동 개수: {len(acts)} (실행 상한 {EXEC_LIMIT or 'none'})")
        self.queue = [list(map(float, a)) for a in acts]
        if EXEC_LIMIT:
            self.queue = self.queue[:EXEC_LIMIT]   # 나머지는 버리고 재계획
        nxt = rsp.get("next_initial_actions")
        self.initial_actions = nxt if nxt else None
        return self.queue.pop(0)


def recv_msg(conn):
    hdr = conn.recv(4, __import__("socket").MSG_WAITALL)
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


def send_msg(conn, obj):
    data = pickle.dumps(obj, protocol=4)
    conn.sendall(struct.pack("<I", len(data)) + data)


async def main():
    import socket

    log(f"우승팀 서버 접속: {WS_URL}")
    async with websockets.connect(WS_URL, max_size=200 * 1024 * 1024,
                                  ping_interval=None) as ws:
        await ws.send(json.dumps({"type": "ping"}))
        log(f"ping 응답: {await ws.recv()}")
        policy = WinnerPolicy(ws)

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((TCP_HOST, TCP_PORT))
        srv.listen(1)
        srv.setblocking(True)
        log(f"{TCP_HOST}:{TCP_PORT} 대기 중 (Isaac 접속을 기다림)")

        loop = asyncio.get_event_loop()
        while True:
            conn, addr = await loop.run_in_executor(None, srv.accept)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            log(f"Isaac 연결: {addr}")
            try:
                while True:
                    msg = await loop.run_in_executor(None, recv_msg, conn)
                    if msg is None:
                        break
                    if msg.get("quit"):
                        log("종료 요청")
                        return
                    if msg.get("reset"):
                        policy.reset()
                        send_msg(conn, {"ok": True, "image_keys": list(IMG_KEYS)})
                        continue
                    act = await policy.act(msg["state"], msg["images"])
                    policy.step += 1
                    if policy.step % 50 == 0:
                        p = policy.last_pred
                        log(f"step {policy.step}: success={p.get('success_pred')} "
                            f"completion={p.get('completion_pred')} "
                            f"ttc={p.get('ttc_pred')}")
                    send_msg(conn, {"action": act, "pred": policy.last_pred})
            except (ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                conn.close()
                log("Isaac 연결 끊김, 다음 대기")


if __name__ == "__main__":
    asyncio.run(main())
