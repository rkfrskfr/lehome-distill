"""자동 플라이휠 — 수집→증식→변환→학습→평가→판단→반복을 사람 없이 돈다.

우승자 논문 §2.1(비동기 학습/롤아웃 루프)을 1대 환경에 맞게 축약한 것.
GPU 가 하나라 단계를 직렬로 돌리되, 모든 상태를 state.json 에 적어 **어느 지점에서
죽어도 재실행하면 그 자리에서 이어간다**.

논문에서 이식한 자동 판단 로직:
  - 커리큘럼 (§3.2): 다음 사이클 수집량을 옷별 실패율에 비례 배분
    P ∝ e^{3(1-SR)} — 못하는 옷에 데이터를 몰아준다.
  - 성공 리플레이 증식 (§3.2): 성공률이 낮은 옷은 스냅샷 리플레이로 증식.
  - 체크포인트 롤백 (§2.5): 성적이 안 오르면 이전 최고 체크포인트로 되돌려
    그동안 모인 전체 데이터로 재학습.
  - 학습 이미지 증강 상시 ON (§2.6) — 우리는 그동안 꺼져 있었다.

실행:
    C:/Users/H/Desktop/lerobot/.venv/Scripts/python.exe orchestrator.py [--cycles 3]
상태 확인: state.json / STATUS.md / orchestrator.log
"""

import csv
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ISAAC_PY = r"C:\isaacsim\python.bat"
VENV_PY = r"C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe"
TRAIN_EXE = r"C:\Users\H\Desktop\lerobot\.venv\Scripts\lerobot-train.exe"
WIN_PY = r"C:\Users\H\AppData\Local\Microsoft\WindowsApps\python.exe"
GARMENT_ROOT = os.path.join(HERE, "Assets", "objects", "Challenge_Garment",
                            "Release", "Top_Long")

STATE_PATH = os.path.join(HERE, "state.json")
LOG_PATH = os.path.join(HERE, "orchestrator.log")
STATUS_PATH = os.path.join(HERE, "STATUS.md")

# Seen_8 은 교사도 0% (성공조건 상충) — 수집 대상에서 제외
EXCLUDE = {"Top_Long_Seen_8"}
RAW = "distill_data_r4"          # 성공 원시 수집
RAW_FAIL = "distill_data_r4_fail"
REPLAY = "distill_data_r4_replay"


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


CYCLES = int(arg("--cycles", "3"))
EVAL_EPISODES = int(arg("--eval-episodes", "15"))  # 10판은 오차 ±15%p
TRAIN_STEPS = int(arg("--train-steps", "60000"))
TRAIN_BATCH = int(arg("--train-batch", "16"))  # 48은 480x640에서 VRAM 초과(84s/step) 실측
# 학생 추론 설정 (논문 §7.1): 청크를 통째로 실행하지 말고 자주 재계획.
# 실측(2026-08-27 스윕): 청크를 통째로 실행(100)하면 31%, 5개만 실행하고
# 재계획하면 66%. 두 배 차이 — 기본값 100은 "3.3초 눈 감고 움직이기"였다.
N_ACTION_STEPS = int(arg("--n-action-steps", "5"))
# 동시에 돌릴 아이작 심 개수 (논문 §3.1 은 3~5). VRAM 32GB 기준 2가 상한.
PARALLEL_SIMS = int(arg("--parallel-sims", "1"))  # 중계기가 동시 1클라이언트만 처리 — 2면 두번째 심이 300s 타임아웃으로 전멸 (감사 확인)
# 소스별 샘플링 비중 (논문 §2.4). 오래된 주기는 낮게 — 최신 분포를 우선.
SOURCE_SHARE = {"distill_data_r4": 1.0, "distill_data_r4_replay": 1.0,
                "distill_data_recov": 1.0, "distill_data_r3": 1.0,
                "distill_data_rand": 1.0}   # 균질(랜덤화) 소스만, 전량 사용


def log(msg):
    line = f"{datetime.now():%m-%d %H:%M:%S}  {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"cycle": 0, "stage": "collect", "best": {"tag": None, "rate": 0.0},
            "history": [], "targets": {}, "no_improve": 0}


def save_state(st):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False)


def port_open(port, host="127.0.0.1", timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def run(cmd, timeout=None, env=None, cwd=HERE, log_path=None):
    """서브프로세스 실행 + 워치독. 반환: (returncode, timed_out)"""
    e = dict(os.environ)
    if env:
        e.update({k: str(v) for k, v in env.items()})
    out = open(log_path, "a", encoding="utf-8", errors="replace") \
        if log_path else subprocess.DEVNULL
    try:
        p = subprocess.Popen(cmd, cwd=cwd, env=e, stdout=out,
                             stderr=subprocess.STDOUT)
        try:
            return p.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            log(f"  !! 타임아웃 ({timeout}s) — 프로세스 트리 종료")
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"],
                           capture_output=True)
            return -1, True
    finally:
        if log_path:
            out.close()


# ---------------------------------------------------------------- 서버 관리
def ensure_teacher():
    """WSL π0.5 서버(8000) + 윈도우 중계기(8767). 죽어 있으면 되살린다."""
    if not port_open(8000):
        log("교사 서버(8000) 다운 — 재기동")
        wsl_cmd = (
            "cd /root/lehome_winner/lehome_solution && setsid nohup "
            "/root/.local/bin/uv run python scripts/serve.py --port 8000 "
            "--num_rollout_candidates 4 policy:checkpoint "
            "--policy.config pi_modified_bc_rl "
            "--policy.dir /root/lehome_winner/checkpoints/lehome_sim "
            "> /tmp/wsrv.log 2>&1 < /dev/null & sleep 110; "
            "pgrep -f serve.py | head -1")
        run(["wsl", "-d", "Ubuntu-24.04", "--", "bash", "-c", wsl_cmd],
            timeout=300)
        for _ in range(20):
            if port_open(8000):
                break
            time.sleep(5)
        log(f"  교사 8000: {port_open(8000)}")

    if not port_open(8767):
        log("중계기(8767) 다운 — 재기동")
        subprocess.Popen([WIN_PY, os.path.join(HERE, "15_winner_relay.py")],
                         cwd=HERE, stdout=open(
                             os.path.join(HERE, "relay_auto.log"), "a",
                             encoding="utf-8", errors="replace"),
                         stderr=subprocess.STDOUT,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(15):
            if port_open(8767):
                break
            time.sleep(2)
        log(f"  중계기 8767: {port_open(8767)}")
    return port_open(8000) and port_open(8767)


def stop_student():
    subprocess.run(["taskkill", "/F", "/IM", "python.exe", "/FI",
                    "WINDOWTITLE eq 12_policy_server*"], capture_output=True)
    for p in _student_pids():
        subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"],
                       capture_output=True)
    time.sleep(4)


def _student_pids():
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine "
             "-match '12_policy_server' -and $_.CommandLine -notmatch "
             "'Get-CimInstance' } | ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=60).stdout
        return [int(x) for x in re.findall(r"\d+", out)]
    except Exception:
        return []


def start_student(ckpt):
    stop_student()
    log(f"학생 서버 기동: {os.path.basename(os.path.dirname(ckpt))}")
    cmd = [VENV_PY, os.path.join(HERE, "12_policy_server.py"), ckpt]
    if N_ACTION_STEPS > 0:
        cmd += ["--n-action-steps", str(N_ACTION_STEPS)]
    subprocess.Popen(cmd,
                     cwd=HERE, stdout=open(os.path.join(HERE, "server_auto.log"),
                                           "a", encoding="utf-8",
                                           errors="replace"),
                     stderr=subprocess.STDOUT,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(30):
        if port_open(8766):
            return True
        time.sleep(3)
    return False


# ---------------------------------------------------------------- 데이터
def garments():
    return sorted(d for d in os.listdir(GARMENT_ROOT)
                  if re.match(r".*_Seen_\d+$", d) and d not in EXCLUDE)


def counts(root):
    out = {}
    base = os.path.join(HERE, root)
    if not os.path.isdir(base):
        return out
    for d in os.listdir(base):
        m = re.match(r"(Top_Long_\w+?_\d+)_", d)
        if m and os.path.exists(os.path.join(base, d, "meta.json")):
            out[m.group(1)] = out.get(m.group(1), 0) + 1
    return out


AUG_ENV = {"LEHOME_RAND_LIGHT": 1, "LEHOME_DROP_Z_RANGE": "0.545,0.63",
           "LEHOME_RAND_TABLE_TEX": 1,
           # 논문 §3.3: 카메라 포즈/초점 지터(약하게 — 교사가 공식 포즈로 학습됨)
           # + 스텝 단위 조명 흔들기(에피소드 고정 신호 제거)
           "LEHOME_RAND_CAM": 1, "LEHOME_RAND_PERSTEP": 1}


def collect(targets, seed_base):
    """옷별 목표치까지 수집. 이미 채운 옷은 건너뛴다 (재개 가능).

    논문 §3.1 은 머신당 심 3~5개를 동시에 돌린다 (씬이 프로세스당 1개뿐이라
    프로세스를 늘리는 방식). 우리는 VRAM 상 PARALLEL_SIMS(기본 2)개.
    """
    have = counts(RAW)
    jobs = []
    for i, g in enumerate(garments(), start=1):
        need = targets.get(g, 40) - have.get(g, 0)
        if need <= 0:
            log(f"  skip {g}: {have.get(g,0)}/{targets.get(g,40)}")
            continue
        for c in (1, 2):
            per = max(1, need // 2)
            z = 0.490 + 0.020 * ((i * 7 + c * 3) % 10) / 10.0
            env = dict(AUG_ENV)
            env["LEHOME_ROBOT_Z"] = f"{z:.4f}"
            env["LEHOME_RAND_GARMENT_TEX"] = 1 if c == 2 else 0
            jobs.append((g, c, per, z, env, seed_base + 10 * i + c))

    running = []   # (Popen, 설명, 파일핸들, 시작시각)

    def reap(block):
        for item in list(running):
            proc, desc, fh, t0 = item
            done = proc.poll() is not None
            if not done and block and time.time() - t0 > 3 * 3600:
                log(f"  !! 타임아웃: {desc}")
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
                done = True
            if done:
                fh.close()
                running.remove(item)
                log(f"  done {desc}")

    for (g, c, per, z, env, seed) in jobs:
        if not ensure_teacher():
            log("!! 교사/중계기 복구 실패 — 수집 중단")
            break
        while len(running) >= PARALLEL_SIMS:
            reap(True)
            if len(running) >= PARALLEL_SIMS:
                time.sleep(10)
        desc = f"{g} chunk{c} (+{per}, z={z:.4f})"
        log(f"  collect {desc}")
        e = dict(os.environ)
        e.update({k: str(v) for k, v in env.items()})
        fh = open(os.path.join(HERE, "collect_auto.log"), "a",
                  encoding="utf-8", errors="replace")
        proc = subprocess.Popen(
            [ISAAC_PY, os.path.join(HERE, "16_collect_distill.py"),
             "--garment-dir", g, "--garment-type", "Top_Long",
             "--target-keeps", str(per), "--steps", "600",
             "--port", "8767", "--seed", str(seed),
             "--out", RAW, "--keep-fail", "--snapshot", "--early-kill"],
            cwd=HERE, env=e, stdout=fh, stderr=subprocess.STDOUT)
        running.append((proc, desc, fh, time.time()))

    while running:
        reap(True)
        if running:
            time.sleep(15)
    return True


def amplify(weak, seed_base):
    """성공률이 낮은 옷: 성공 스냅샷 리플레이로 데이터 증식 (논문 §3.2)."""
    for i, g in enumerate(weak, start=1):
        if not ensure_teacher():
            return False
        log(f"  amplify {g}")
        run([ISAAC_PY, os.path.join(HERE, "22_replay_snapshots.py"),
             "--src", RAW, "--out", REPLAY, "--mode", "success",
             "--garment-dir", g, "--per-snap", "3", "--max-snaps", "15",
             "--port", "8767", "--seed", str(seed_base + i)],
            timeout=3 * 3600, env=AUG_ENV,
            log_path=os.path.join(HERE, "amplify_auto.log"))
    return True


def hard_mine(weak, seed_base):
    """실패판 스냅샷(=망친 순간)에서 교사가 회복을 시도. 성공분만 보관."""
    for i, g in enumerate(weak, start=1):
        if not ensure_teacher():
            return False
        log(f"  hard-mine {g}")
        run([ISAAC_PY, os.path.join(HERE, "22_replay_snapshots.py"),
             "--src", RAW_FAIL, "--out", REPLAY, "--mode", "recover",
             "--garment-dir", g, "--per-snap", "2", "--max-snaps", "12",
             "--port", "8767", "--seed", str(seed_base + i)],
            timeout=3 * 3600, env=AUG_ENV,
            log_path=os.path.join(HERE, "hardmine_auto.log"))
    return True


def convert(tag):
    """성공 데이터(원시 + 리플레이 + 과거 주기)를 LeRobot 데이터셋으로."""
    merged = os.path.join(HERE, f"distill_data_{tag}_merged")
    shutil.rmtree(merged, ignore_errors=True)
    os.makedirs(merged, exist_ok=True)
    n = 0
    import random as _random
    for src in (RAW, REPLAY, "distill_data_recov", "distill_data_r3",
                "distill_data_rand"):   # clean200(distill_data) 은 랜덤화 없음 — 제외
        base = os.path.join(HERE, src)
        if not os.path.isdir(base):
            continue
        eps = [d for d in sorted(os.listdir(base))
               if os.path.exists(os.path.join(base, d, "meta.json"))]
        share = SOURCE_SHARE.get(src, 1.0)
        if share < 1.0:                       # 오래된 소스는 결정적으로 솎아낸다
            keep = max(1, int(len(eps) * share))
            _random.Random(1234).shuffle(eps)
            eps = sorted(eps[:keep])
        log(f"    {src}: {len(eps)}판 (비중 {share})")
        for d in eps:
            link = os.path.join(merged, f"{src}__{d}")
            subprocess.run(["cmd", "/c", "mklink", "/J", link,
                            os.path.join(base, d)], capture_output=True)
            n += 1
    log(f"  합본 {n}판 -> 변환")
    root = f"distill_lerobot_{tag}"
    rc, _ = run([VENV_PY, os.path.join(HERE, "17_convert_distill.py"),
                 "--src", os.path.basename(merged), "--dst", root,
                 "--repo-id", f"hd/lehome_{tag}"],
                timeout=4 * 3600,
                log_path=os.path.join(HERE, "convert_auto.log"))
    return (os.path.join(HERE, root), n) if rc == 0 else (None, n)


def train(tag, root, resume_from=None):
    """학습 — 검증된 레시피(정책 프리셋: AdamW 1e-5 고정, 백본 1e-5) + 증강 ON.
    감사 교훈: 프리셋을 끄고 optimizer CLI 를 주면 백본 LR 이 1e-4 로 튀고,
    논문 LR(1e-4)은 배치 192 기준이라 배치 16 에서는 붕괴(3.3%)한다."""
    out = os.path.join(HERE, "outputs", f"act_student_{tag}")
    last = os.path.join(out, "checkpoints", "last", "pretrained_model",
                        "train_config.json")
    if os.path.exists(last):
        # 중단된 학습이 있으면 그 지점부터 재개 (lerobot 은 output_dir 존재 시 새 학습을 거부)
        log(f"  기존 체크포인트 발견 — 재개: {tag}")
        cmd = [TRAIN_EXE, f"--config_path={last}", "--resume=true"]
    else:
        shutil.rmtree(out, ignore_errors=True)
        cmd = [TRAIN_EXE,
               f"--dataset.repo_id=hd/lehome_{tag}",
               f"--dataset.root={root}",
               "--policy.type=act",
               f"--output_dir={out}",
               f"--steps={TRAIN_STEPS}",
               f"--batch_size={TRAIN_BATCH}", "--num_workers=4", "--seed=1000",
               "--save_freq=20000", "--wandb.enable=false",
               "--policy.push_to_hub=false",
               "--dataset.image_transforms.enable=true",
               "--dataset.image_transforms.max_num_transforms=3"]
        if resume_from:
            cmd += [f"--policy.pretrained_path={resume_from}"]
    log(f"  학습 시작: {tag} ({TRAIN_STEPS} steps, 증강 ON)")
    rc, _ = run(cmd, timeout=14 * 3600,
                log_path=os.path.join(HERE, f"train_{tag}.log"))
    ck = os.path.join(out, "checkpoints", f"{TRAIN_STEPS:06d}",
                      "pretrained_model")
    return ck if os.path.isdir(ck) else None


def evaluate(tag, ckpt):
    csv_path = os.path.join(HERE, f"bench_{tag}.csv")
    if os.path.exists(csv_path):
        os.remove(csv_path)
    if not start_student(ckpt):
        log("!! 학생 서버 기동 실패")
        return None
    all_g = sorted(d for d in os.listdir(GARMENT_ROOT)
                   if re.match(r".*_(Seen|Unseen)_\d+$", d))

    def bench_one(g, i):
        run([ISAAC_PY, os.path.join(HERE, "14_benchmark.py"),
             "--garment-dir", g, "--garment-type", "Top_Long",
             "--episodes", str(EVAL_EPISODES), "--steps", "600",
             "--port", "8766", "--tag", tag, "--seed", str(i),
             "--reset-mode", "initial", "--phys-per-action", "2"],
            timeout=2 * 3600,
            log_path=os.path.join(HERE, "eval_auto.log"))

    def rows_per_garment():
        got = {}
        if os.path.exists(csv_path):
            with open(csv_path, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    got[r["garment"]] = got.get(r["garment"], 0) + 1
        return got

    for i, g in enumerate(all_g, start=1):
        log(f"  eval [{i}/{len(all_g)}] {g}")
        bench_one(g, i)

    # PhysX attachShape 플레이크로 옷이 통째로 누락될 수 있다 (HANDOFF §5-2).
    # CSV 행수를 확인해 부족한 옷만 자동 재실행 — 지금까지 수동으로 하던 일.
    for attempt in (1, 2):
        got = rows_per_garment()
        missing = [g for g in all_g if got.get(g, 0) < EVAL_EPISODES]
        if not missing:
            break
        log(f"  누락 감지({attempt}차): "
            f"{[m.replace('Top_Long_','') + f'({got.get(m,0)})' for m in missing]}")
        for g in missing:
            if not start_student(ckpt):
                break
            bench_one(g, 100 + attempt * 20 + all_g.index(g))
    stop_student()
    return csv_path if os.path.exists(csv_path) else None


def train_success_head(tag):
    """성공확률 예측기 학습 (논문 §5.1). 성공+실패 에피소드를 모두 쓴다.
    AUC>=0.75 면 PASS — best-of-N / 조기종료에 투입 가능."""
    out = f"outputs/success_head_{tag}"
    log("  성공확률 예측기 학습")
    run([VENV_PY, os.path.join(HERE, "23_train_success_head.py"),
         "--ok", f"{RAW},{REPLAY}", "--fail", RAW_FAIL,
         "--epochs", "6", "--out", out, "--split-by", "chunk"],
        timeout=3 * 3600,
        log_path=os.path.join(HERE, "succhead_auto.log"))
    rep = os.path.join(HERE, out, "report.json")
    if os.path.exists(rep):
        with open(rep, encoding="utf-8") as f:
            return json.load(f)
    return {"verdict": "FAIL", "best_val_auc": None}


def pick_checkpoint(tag, final_ckpt):
    """마지막 체크포인트와 직전 후보들을 소규모(옷 3벌×5판)로 비교해 최고를 고른다."""
    root = os.path.dirname(os.path.dirname(final_ckpt))   # .../checkpoints
    steps = sorted([d for d in os.listdir(root) if d.isdigit()])[-3:]
    if len(steps) < 2:
        return final_ckpt
    probe = ["Top_Long_Seen_2", "Top_Long_Seen_6", "Top_Long_Unseen_0"]
    best, best_rate = final_ckpt, -1.0
    for stp in steps:
        ck = os.path.join(root, stp, "pretrained_model")
        if not os.path.isdir(ck) or not start_student(ck):
            continue
        t = f"{tag}_probe{stp}"
        cp = os.path.join(HERE, f"bench_{t}.csv")
        if os.path.exists(cp):
            os.remove(cp)
        for i, g in enumerate(probe, start=1):
            run([ISAAC_PY, os.path.join(HERE, "14_benchmark.py"),
                 "--garment-dir", g, "--garment-type", "Top_Long",
                 "--episodes", "5", "--steps", "600", "--port", "8766",
                 "--tag", t, "--seed", str(i), "--reset-mode", "initial",
                 "--phys-per-action", "2"],
                timeout=3600, log_path=os.path.join(HERE, "eval_auto.log"))
        r = analyze(cp) if os.path.exists(cp) else None
        rate = r["overall"] if r else -1.0
        log(f"    후보 {stp}: {rate*100:.0f}% (15판 예비)")
        if rate > best_rate:
            best, best_rate = ck, rate
    stop_student()
    return best


def analyze(csv_path):
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("success") in ("0", "1"):
                rows.append((r["garment"], int(r["success"])))
    if not rows:
        return None
    per = {}
    for g, s in rows:
        per.setdefault(g, []).append(s)
    rates = {g: sum(v) / len(v) for g, v in per.items()}
    seen = [s for g, v in per.items() if "_Seen_" in g for s in v]
    unseen = [s for g, v in per.items() if "_Unseen_" in g for s in v]
    # Seen_8 은 교사도 0% (성공조건 상충) — 전체 평균을 구조적으로 끌어내리므로
    # 함께 별도 보고한다.
    solv = [s for g, s in rows if "Seen_8" not in g]
    return {"overall": sum(s for _, s in rows) / len(rows),
            "overall_ex8": (sum(solv) / len(solv)) if solv else 0.0,
            "seen": (sum(seen) / len(seen)) if seen else 0.0,
            "unseen": (sum(unseen) / len(unseen)) if unseen else 0.0,
            "n": len(rows), "per_garment": rates}


def next_targets(rates, cur):
    """커리큘럼 (논문 §3.2): 못하는 옷에 다음 수집을 몰아준다. P ∝ e^{3(1-SR)}"""
    import math
    gs = garments()
    w = {g: math.exp(3.0 * (1.0 - rates.get(g, 0.0))) for g in gs}
    tot = sum(w.values())
    budget = 180  # 다음 사이클 총 추가 판수
    out = {}
    for g in gs:
        add = int(round(budget * w[g] / tot))
        out[g] = cur.get(g, 40) + max(5, add)
    return out


def write_status(st):
    b = st["best"]
    lines = [
        "# 자동 파이프라인 상태",
        f"\n갱신: {datetime.now():%Y-%m-%d %H:%M}",
        f"\n- 사이클: {st['cycle']} / 단계: {st['stage']}",
        f"- 최고 성적: **{b['rate']*100:.1f}%** ({b['tag']})",
        f"- 개선 없는 사이클: {st['no_improve']}",
        (f"- 성공확률 예측기: AUC {st['succ_head'].get('best_val_auc')} "
         f"({st['succ_head'].get('verdict')})" if st.get("succ_head") else
         "- 성공확률 예측기: 미학습"),
        "\n## 이력\n",
        "| 사이클 | 태그 | 전체 | Seen_8제외 | Seen | Unseen | 데이터 |",
        "|---|---|---|---|---|---|---|",
    ]
    for h in st["history"]:
        lines.append(f"| {h['cycle']} | {h['tag']} | {h['overall']*100:.1f}% | "
                     f"{h.get('overall_ex8', 0)*100:.1f}% | "
                     f"{h['seen']*100:.1f}% | {h['unseen']*100:.1f}% | "
                     f"{h.get('episodes','?')}판 |")
    if st["history"]:
        last = st["history"][-1]
        lines += ["\n## 최신 사이클 옷별 성공률\n",
                  "| 옷 | 성공률 |", "|---|---|"]
        for g, r in sorted(last.get("per_garment", {}).items()):
            lines.append(f"| {g.replace('Top_Long_','')} | {r*100:.0f}% |")
    with open(STATUS_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    st = load_state()
    log(f"=== 오케스트레이터 시작 (사이클 {st['cycle']}, 단계 {st['stage']}) ===")
    if not st["targets"]:
        st["targets"] = {g: 40 for g in garments()}
        # 약한 옷은 처음부터 더 많이
        for g in ("Top_Long_Seen_0", "Top_Long_Seen_3", "Top_Long_Seen_7"):
            st["targets"][g] = 60

    while st["cycle"] < CYCLES:
        cyc = st["cycle"] + 1
        tag = f"auto{cyc}"
        seed_base = 2000 + 200 * cyc
        log(f"\n########## 사이클 {cyc} ({tag}) ##########")

        if st["stage"] in ("collect",):
            st["stage"] = "collect"; save_state(st); write_status(st)
            if not collect(st["targets"], seed_base):
                log("수집 중단 — 종료"); return
            st["stage"] = "amplify"; save_state(st)

        if st["stage"] == "amplify":
            rates = (st["history"][-1]["per_garment"] if st["history"] else {})
            weak = sorted([g for g in garments() if rates.get(g, 0.0) < 0.3],
                          key=lambda g: rates.get(g, 0.0))[:4]
            if weak:
                log(f"증식 대상(성공률<30%): {[w.replace('Top_Long_','') for w in weak]}")
                amplify(weak, seed_base)
                # 하드마이닝 (논문 §3.2): 실패판의 '망친 순간' 상태를 복원해
                # 교사에게 다시 굴린다. 성공하면 '망친 상태에서의 회복' 데이터 —
                # 신선 롤아웃으로는 절대 안 나오는 종류다.
                log("하드마이닝 (실패 스냅샷 재시도)")
                hard_mine(weak, seed_base + 500)
            st["stage"] = "convert"; save_state(st)

        if st["stage"] == "convert":
            root, n_eps = convert(tag)
            if not root:
                log("!! 변환 실패 — 종료"); return
            st["last_root"], st["last_episodes"] = root, n_eps
            st["stage"] = "succhead"; save_state(st)

        if st["stage"] == "succhead":
            st["succ_head"] = train_success_head(tag)
            log(f"  성공확률 예측기 val AUC={st['succ_head'].get('best_val_auc')}"
                f" -> {st['succ_head'].get('verdict')}")
            st["stage"] = "train"; save_state(st)

        if st["stage"] == "train":
            # 롤백 정책 (논문 §2.5): 2사이클 연속 정체면 최고 체크포인트에서 재출발
            resume = st["best"]["ckpt"] if (st["no_improve"] >= 2 and
                                            st["best"].get("ckpt")) else None
            if resume:
                log(f"  정체 감지 — 최고 체크포인트에서 재학습: {resume}")
            ck = train(tag, st["last_root"], resume)
            if not ck:
                log("!! 학습 실패 — 종료"); return
            st["last_ckpt"] = ck
            st["stage"] = "eval"; save_state(st)

        if st["stage"] == "eval":
            # 체크포인트 선택 (지금까지 무조건 마지막 스텝을 썼다). 후보를 짧게
            # 재보고 최고를 고른다 — 과적합 구간이면 중간이 더 낫다.
            cand = pick_checkpoint(tag, st["last_ckpt"])
            if cand and cand != st["last_ckpt"]:
                log(f"  체크포인트 교체: {os.path.basename(os.path.dirname(cand))}")
                st["last_ckpt"] = cand
            csv_path = evaluate(tag, st["last_ckpt"])
            if not csv_path:
                log("!! 평가 실패 — 종료"); return
            res = analyze(csv_path)
            log(f"  결과: 전체 {res['overall']*100:.1f}% "
                f"(Seen_8 제외 {res['overall_ex8']*100:.1f}%, "
                f"Seen {res['seen']*100:.1f}% / Unseen {res['unseen']*100:.1f}%)")
            st["history"].append({"cycle": cyc, "tag": tag,
                                  "episodes": st.get("last_episodes"), **res})
            if res["overall"] > st["best"]["rate"]:
                st["best"] = {"tag": tag, "rate": res["overall"],
                              "ckpt": st["last_ckpt"]}
                st["no_improve"] = 0
                log(f"  ** 최고 기록 갱신: {res['overall']*100:.1f}% **")
            else:
                st["no_improve"] += 1
                log(f"  개선 없음 ({st['no_improve']}회 연속)")
            st["targets"] = next_targets(res["per_garment"], st["targets"])
            log(f"  다음 사이클 목표: "
                f"{ {g.replace('Top_Long_',''): v for g, v in st['targets'].items()} }")
            st["cycle"] = cyc
            st["stage"] = "collect"
            save_state(st); write_status(st)

    log("=== 전체 사이클 완료 ===")
    write_status(st)


if __name__ == "__main__":
    main()
