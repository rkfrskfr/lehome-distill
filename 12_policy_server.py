"""12단(서버): LeHome ACT 체크포인트를 TCP 로 서빙 (so101-fresh 13_policy_server 이식).

Isaac Sim 파이썬에는 lerobot 이 없으므로 정책은 lerobot venv 에서 돌리고,
시뮬 루프(13_rollout.py)가 로컬 TCP 로 관측을 보내 행동을 받는다.

lerobot venv 에서 실행:
    C:/Users/H/Desktop/lerobot/.venv/Scripts/python.exe 12_policy_server.py <체크포인트dir>
    옵션: --check (로드만 확인하고 종료), --n-action-steps N, --ensemble C

프로토콜: [4바이트 길이][pickle].
    {"reset": True}                              -> {"ok": True}
    {"state": (12,)f32, "images": {키: HWC u8}}  -> {"action": [12 float]}
    {"quit": True}                               -> 종료
관측 이미지 키는 체크포인트 config 의 image_features 를 그대로 따른다
(LeHome: observation.images.top_rgb / left_rgb / right_rgb).
"""

import pickle
import socket
import struct
import sys

import numpy as np
import torch

HOST, PORT = "127.0.0.1", 8766


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


def send_msg(conn, obj):
    data = pickle.dumps(obj, protocol=4)
    conn.sendall(struct.pack("<I", len(data)) + data)


# --- 합의(best-of-N 근사) -----------------------------------------------
# 논문 §7.4 의 best-of-N 은 행동-조건부 가치헤드로 후보를 고르지만, ACT 에는 그런
# 헤드가 없다. 저자 관찰("N>1 의 이득은 대부분 '아주 나쁜 청크를 피하는 것'")에
# 근거해, 관측을 살짝 흔들어 N개 청크를 뽑고 **서로 가장 가까운 것(메도이드)** 을
# 고른다. 이상치 청크가 자동으로 배제된다. 추가 모델·재학습 불필요.
CONSENSUS = 1
CONSENSUS_NOISE = 0.02
_queue = []


def consensus_action(policy, obs):
    import torch as _t
    global _queue
    if _queue:
        return _queue.pop(0)
    chunks = []
    for k in range(CONSENSUS):
        o = dict(obs)
        if k > 0:                      # 0번은 원본, 나머지는 약한 밝기/이동 흔들기
            for key, v in list(o.items()):
                # 전처리기가 None 값을 섞어 넣을 수 있다 (task 등)
                if hasattr(v, "dim") and v.dim() == 4:   # 이미지 (B,C,H,W)
                    v = v * (1.0 + (_t.rand(1, device=v.device) - 0.5)
                             * 2 * CONSENSUS_NOISE)
                    sh = int(_t.randint(-1, 2, (1,)).item())
                    if sh:
                        v = _t.roll(v, shifts=sh, dims=-1)
                    o[key] = v
        policy.reset()
        chunks.append(policy.predict_action_chunk(o)[0])   # (chunk, dim)
    st = _t.stack(chunks)                                  # (N, chunk, dim)
    d = ((st[:, None] - st[None, :]) ** 2).sum(dim=(2, 3))
    best = int(d.sum(dim=1).argmin())                      # 메도이드
    n_exec = max(1, int(policy.config.n_action_steps))
    sel = st[best][:n_exec]
    _queue = [sel[i:i + 1] for i in range(1, sel.shape[0])]
    return sel[0:1]


def main():
    global CONSENSUS, CONSENSUS_NOISE
    ckpt = sys.argv[1]
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    policy = ACTPolicy.from_pretrained(ckpt)
    if "--n-action-steps" in sys.argv:
        policy.config.n_action_steps = int(
            sys.argv[sys.argv.index("--n-action-steps") + 1])
    if "--consensus" in sys.argv:
        CONSENSUS = int(sys.argv[sys.argv.index("--consensus") + 1])
        print(f"[server] 합의 N={CONSENSUS} (메도이드 선택)", flush=True)
    if "--ensemble" in sys.argv:
        from lerobot.policies.act.modeling_act import ACTTemporalEnsembler

        coeff = float(sys.argv[sys.argv.index("--ensemble") + 1])
        policy.config.temporal_ensemble_coeff = coeff
        policy.config.n_action_steps = 1
        policy.temporal_ensembler = ACTTemporalEnsembler(
            coeff, policy.config.chunk_size)

    img_keys = sorted(policy.config.image_features.keys())
    state_dim = policy.config.input_features["observation.state"].shape[0]
    print(f"[server] image_keys={img_keys} state_dim={state_dim} "
          f"chunk={policy.config.chunk_size} "
          f"n_action_steps={policy.config.n_action_steps}", flush=True)

    if "--check" in sys.argv:
        print("[server] CHECK_OK", flush=True)
        return

    policy.to("cuda").eval()
    pre, post = make_pre_post_processors(
        policy.config, pretrained_path=ckpt,
        preprocessor_overrides={"device_processor": {"device": "cuda"}})
    print(f"[server] 체크포인트 로드 완료: {ckpt}", flush=True)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"[server] {HOST}:{PORT} 대기 중", flush=True)

    while True:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"[server] 연결: {addr}", flush=True)
        try:
            while True:
                msg = recv_msg(conn)
                if msg is None:
                    break
                if msg.get("quit"):
                    print("[server] 종료 요청", flush=True)
                    return
                if msg.get("reset"):
                    policy.reset()
                    send_msg(conn, {"ok": True, "image_keys": img_keys})
                    continue
                obs = {
                    "observation.state":
                        torch.from_numpy(np.asarray(msg["state"], dtype=np.float32))
                        .unsqueeze(0),
                }
                for k in img_keys:
                    img = np.asarray(msg["images"][k], dtype=np.uint8)
                    obs[k] = (torch.from_numpy(img).permute(2, 0, 1)
                              .float().unsqueeze(0) / 255.0)
                with torch.inference_mode():
                    obs = pre(obs)
                    if CONSENSUS > 1:
                        act = consensus_action(policy, obs)
                    else:
                        act = policy.select_action(obs)
                    act = post(act)
                # numpy 버전 차이 회피: 순수 리스트로 전송
                send_msg(conn, {"action":
                                [float(v) for v in np.asarray(act).reshape(-1)]})
        except (ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            conn.close()
            print("[server] 연결 끊김, 다음 대기", flush=True)


if __name__ == "__main__":
    main()
