# LeHome 윈도우 포트 — 인수인계 (2026-08-22)

새 세션 시작 시 이 문서 + 메모리 `lehome-windows-port.md`(함정 전체 목록)를 먼저 읽을 것.

## 1. 지금까지의 결과 (요약)

### 무대 (검증 완료)
- LeHome(ICRA 2026 옷접기 챌린지) 씬을 윈도우 아이작심 5.1에 복제. 버그 16개 해체
  (좌표 미적용, 도/라디안 게인, 고정베이스, 로봇 높이 2.2cm, 판정 인덱스, 렌더 누락 등).
- 카메라 3대 공식 데이터셋과 픽셀 정렬 확인. 성공 판정기는 공식 이식 + 메시순서 인덱스 매핑.
- **작동 조건: dt 1/60** (공식 1/90은 우리 스택에서 붕괴 — 가설 5개 기각, 미해결 1개 남음, §5).

### 교사 (우승팀 π0.5, 2.83B)
- WSL2에서 JAX 서버로 가동, 윈도우 아이작심과 중계기로 연결.
- 성적: 전체 45.8%(120판)~50%(100판), 잘하는 옷 기준 93%(3벌×5판=14/15) (우승팀 보고 80%+ 와 부합).
- 취약성: 베이스 높이 +10mm에 -38%p, +20mm에 사실상 전멸.

### 학생 3명 (ACT 51.7M, 30k스텝, 같은 레시피, 고유속도 33.3ms 평가)
| 학생 | 교과서 | 전체 | Seen | Unseen | +10mm 하락 |
|---|---|---|---|---|---|
| v1 소량 | 59판 | 28% | 30% | 20% | — |
| clean200 대량 | 195판 | 30.8% | 37% | **0%** | -20pp |
| rand137 랜덤화 | 137판(±5mm+조명) | 25% | 27% | 15% | **-12.5pp** |

핵심 관찰:
- 데이터 스케일링 뚜렷 (교과서 15판 옷 60%, 1판 옷 0%).
- 동질 데이터 증량 → Seen↑ Unseen↓ (암기 패턴).
- 랜덤화 → 하락폭 최소 (방향 맞음, n=20이라 미확정) + 학생들은 교사보다 원래 둔감.
- **행동 소모 속도 민감성**: 30fps 학습 → 60Hz 평가 시 2.6배 손실. 반드시 `--phys-per-action 2`.

## 2. 인프라 지도

### 서버/포트 (재부팅 시 전부 재시작 필요)
| 포트 | 무엇 | 시작 명령 |
|---|---|---|
| 8000 | 우승팀 π0.5 (WSL) | `wsl -d Ubuntu-24.04 -- bash -c "cd /root/lehome_winner/lehome_solution && setsid nohup /root/.local/bin/uv run python scripts/serve.py --port 8000 --num_rollout_candidates 4 policy:checkpoint --policy.config pi_modified_bc_rl --policy.dir /root/lehome_winner/checkpoints/lehome_sim > /tmp/wsrv.log 2>&1 < /dev/null &"` (기동 ~90초) |
| 8767 | 교사 중계기 (윈도우 py) | `Start-Process python -ArgumentList '15_winner_relay.py'` (옵션 `--garment-id 0` = 옷종류 고정) |
| 8766 | 학생 서버 (lerobot venv) | `Start-Process C:\Users\H\Desktop\lerobot\.venv\Scripts\python.exe -ArgumentList '12_policy_server.py','<체크포인트\pretrained_model>'` |

### 데이터/모델
- 원시 수집: `distill_data\`(깨끗 200판), `distill_data_rand\`(랜덤화 137판)
- LeRobot: `distill_lerobot_v2\`(195판), `distill_lerobot_rand\`(137판)
- 학생 체크포인트: `outputs\act_student_{v1,clean200,rand137}\checkpoints\030000\pretrained_model`
- 결과 CSV: `bench_*.csv` (분석: `analyze_bench.py <tag>`, 취약성: `analyze_brittle.py`)

### 핵심 스크립트
- `lehome_scene.py` — 공용 무대 (환경변수: `LEHOME_ROBOT_Z`, `LEHOME_DROP_Z`,
  `LEHOME_DROP_Z_RANGE`(판별 균등샘플, 고정값보다 우선), `LEHOME_RAND_LIGHT`,
  `LEHOME_RAND_TABLE_TEX`(테이블 100종), `LEHOME_RAND_GARMENT_TEX`(옷 BaseColor 44종))
- `14_benchmark.py` — 평가 (`--phys-per-action 2` 학생 필수 / 1 교사)
- `16_collect_distill.py` → `17_convert_distill.py` — 수집→변환
- 드라이버: `run_full_bench.ps1`, `run_collect2.ps1`, `run_eval_students.ps1`, `run_brittle_students.ps1`

## ★★ 2026-09-05 환경 버그 2건 수정 — 이 문서의 이전 수치는 전부 "수정 전" 기준

1. 판정기 기준점 매핑(17:00) 2. 초기 자세 = 테이블에 밀린 쿠킹 좌표 → 옷을 상판 위 34cm 에서
낙하(20:35). 자세한 내용 `AUDIT.md` §E. 수정 후 원본 모델 첫 60판 81.7%(공식 74.5%) 로 정합 확인.
새 파이프라인: `teacher_eval.ps1`(원본 재평가) → `fix_chain.ps1`(재수집 `distill_data_fix` →
`act_student_fix` 학습 → `fix_n5` 평가) / `post_eval.ps1`(구 모델 재평가). 결과 표: `python compile_results.py`.

**고친 환경 성적 (09-07, 120판)**: 원본 85.8% · **`act_student_combo` 76.7% (최고 학생, 674판 학습, Unseen 70%)** ·
`act_student_cur` 75.8%/70.8%(2회, n=240 73.3%) · seed2 62.5% · 구 챔피언 58.3% · 증강OFF 55.0% ·
`act_student_fix`(고친 환경 169판만) 40.0%. **데이터 양이 성능을 좌우** (267→505→674판: 58→73→77%).
데모·실물 기본 모델 = `act_student_combo` (`run_demo.ps1` 자동 선택).

## 0. 현재 최고 성적 (2026-08-27, 수정 전 환경)

**학생 `act_student_r3plus_aug` (267판, 60k, 증강 ON) + `--n-action-steps 5`
= 전체 47.5% (Seen 50%, Unseen 35%, Seen_8 제외 51.8%), 120판.**
교사(π0.5 2.83B) 46~50% 와 동급. `bench_final_n5.csv`.
⚠ **위 수치는 구판정·높은 낙하 기준** (2026-09-05 17:00 판정기 기준점 매핑 버그, 20:35 초기 자세
버그(옷을 상판 위 34cm 에서 낙하) 수정, AUDIT.md §E).
신판정 기준선은 `bench_final_n5_rep.csv`(챔피언 재평가) / `bench_teacher_v3.csv`(교사).

⚠ **평가·수집 시 반드시 `--n-action-steps 5`** 로 학생 서버를 띄울 것.
기본값(100)은 카메라를 한 번 보고 3.3초를 눈 감고 실행하는 설정이며 31% 로 반토막.
시간앙상블(`--ensemble`)은 효과 없음(37.5%).

## 3-A. 자동 파이프라인 (2026-08-26 구축) — **이제 이걸 돌린다**

`orchestrator.py` 하나가 수집→증식→변환→성공예측기→학습→평가→판단을 무한 반복.
상태는 `state.json`, 사람이 볼 요약은 `STATUS.md` (사이클별 성적·옷별 성공률·AUC).
어느 단계에서 죽어도 **재실행하면 그 자리에서 이어감** (단계·목표치 전부 state 에).

    C:/Users/H/Desktop/lerobot/.venv/Scripts/python.exe orchestrator.py --cycles 3

논문(arXiv:2606.27163)에서 이식한 자동 판단:
- **커리큘럼** §3.2: 다음 수집량 = P ∝ e^{3(1-옷별성공률)} (못하는 옷에 몰아줌)
- **성공 리플레이 증식** §3.2: 성공률<30% 옷은 `22_replay_snapshots.py` 로 스냅샷
  복원 후 시각만 바꿔 재실행 (물리는 동일, 텍스처 스왑 p=0.8)
- **성공확률 예측기** §5.1: `23_train_success_head.py` — 성공+실패 에피소드로
  P(성공|프레임) 학습. ⚠ **누수 확인**: 첫 프레임만으로 AUC 0.82 → 접기 진행이 아니라
  시작 조건을 읽음. 조기종료·best-of-N 에 사용 금지 (진단 도구로만).
  success tail boost(마지막 20프레임 20배), label smoothing, 에피소드 단위 홀드아웃.
- **조기 종료** §3.1: `--early-kill` — 180스텝 진전 없으면 판 종료(실패판 72%가
  600스텝을 완주하던 낭비 제거). 스냅샷·실패데이터는 그대로 보관.
- **체크포인트 롤백** §2.5: 2사이클 연속 정체 시 최고 체크포인트에서 재학습.
- **이미지 증강 상시 ON** §2.6: `--dataset.image_transforms.enable=true`
  (**그동안 꺼져 있었음** — Unseen 붕괴의 유력 원인).

서버 자동 복구 내장(교사 8000 / 중계 8767), 단계별 타임아웃 워치독.
⚠ 미해결: 8/26 13:20 에 교사·중계·수집이 **동시 전멸**한 사고 (원인 불명, 이벤트
로그 무기록). 오케스트레이터는 이런 사고에서 자동 복구하도록 만들었지만,
자기 자신이 죽으면 재실행이 필요하다 (스케줄러 등록은 권한 정책에 막힘).

## 3-0. 방향 전환 (2026-08-25): 절대 성능 올인 + 우승자 논문 이식

- 3주기(r3) 결과: 학생 B(267판 합본, 60k) **28.3%** — 31% 벽 못 깸, 병목 = 약한 옷
  데이터 기근 (Seen_0/3/7 각 8~9판 → 0~10%). 비교 연구(§4)는 사용자 지시로 보류.
- **우승자 논문 정독 완료** → 이식 계획은 `LEHOME_paper_notes.md` (필독).
- **완료 (r4 수집 241판 + 실패 608판)**: 옷별 40판(SeedBase 700) + 약한 옷 팜
  (Seen_0/3/7 +20판, 낮은 낙하 0.545~0.58, SeedBase 900) → `distill_data_r4\`.
  신기능: `--snapshot`(물리 상태 npz — step5=리플레이 증식용, 실패판 100스텝마다
  =교사 회복 DAgger용), `--keep-fail`(실패판을 `distill_data_r4_fail\` 에 보관 —
  성공 예측기·AWR 학습용; 변환기는 성공 폴더만 읽으므로 오염 없음).
- 다음(내일): ①성공 스냅샷 리플레이 증식 엔진 ②교사 회복 DAgger(실패 스냅샷 복원
  → 교사 재시도) ③변형 3개 학습: 증강 ON(lerobot image_transforms — **지금까지
  꺼져 있었음!**) / 증강 약 / 큰 ACT ④성공 예측기 → 오프라인 검증 통과 시 best-of-N.
- 학생 서버 8766 은 현재 act_student_r3plus 60k 체크포인트로 떠 있음.

## 3. 다음 작업 ① 데이터 다양성 재설계 (3주기 수집) — **완료 (r3, 130판)**

구현 완료 + 스모크 통과 + 본실행 가동:
1. `16_collect_distill.py`에 `--target-keeps N` 구현 (성공 N판까지, 상한 3N 시도).
   재실행 잔재 제거·고아 폴더 정리·소켓 타임아웃 300s 포함.
2. 흔들림 전부 구현: 높이 ±10mm(청크별), `LEHOME_DROP_Z_RANGE=0.545,0.63`(판별),
   조명, 테이블 텍스처 100종, 옷 BaseColor 44종 (공식 포크 로직 이식, 셰이더 자동 탐색).
3. **드라이버 `run_collect3.ps1`**: Seen 9벌(Seen_8 제외) × 20판, 옷별 2청크(각자 로봇 z),
   옷 텍스처는 half 모드(짝수 청크만) — 교사 성공률 헤지 + 효과 비교축.
   중계기 사망 감지·환경변수 정리 내장. 로그 `collect3.log`, 출력 `distill_data_r3\`.
4. 완료 후: CSV/폴더 수 확인 → `17_convert_distill.py` 변환 → 동일 레시피 학습(30k, 배치16)
   → §4 프로토콜 평가. 스모크 산출물은 `smoke_r3\` (본 데이터에 미포함).

## 4. 다음 작업 ② 랜덤화 효과 통계 확정

현재 신호(하락폭 -20pp vs -12.5pp)는 n=20이라 오차(±11pp) 안. 확정 프로토콜:
- 높이 {0.505, 0.510, 0.515} × 옷 4벌(Seen_1/2/4/9) × **15판** × 학생 2명(clean200, rand137)
  = 360판 ≈ 6시간. `run_brittle_students.ps1`의 `-Episodes 15` + heights에 0.515 추가.
- 판정: 명목 대비 하락폭의 95% CI가 겹치지 않으면 확정. 3주기 학생(§3)도 완성되면 같이.

## 5. 미해결 (알고 있어야 할 것)

1. **dt 1/90 미스터리**: 기각된 가설 5개(게인 단위, 행동시간, 씬버퍼, 포크 타이밍, 마찰).
   남은 용의자: `suppressReadback` 파이프라인 차이 — 실험하려면 `World(device="cpu")` +
   `omni.physx.get_physx_interface().overwrite_gpu_setting(1)` + lehome_scene의 cuda 텐서를
   cpu로 (반나절 개조). 그 전까지 우리 수치는 "복제 무대 기준"으로 명시할 것.
2. **PhysX attachShape 플레이크**: 벤치마크에서 옷이 통째로 스킵됨. CSV 행수 확인 →
   빠진 옷 개별 재실행. (드라이버에 자동 재시도 미구현.)
3. **rand137 실패판 천 폭발**(좌표 1e10cm): 원인 미조사. 랜덤화 높이+학생 행동 조합 의심.
4. ~~Seen_8은 교사도 0% (성공조건 상충 의심)~~ → 2026-09-05 해결: 판정기 기준점 매핑 버그
   (쿠킹 좌표 z +23cm 미보정). `lehome_scene.map_check_points` v3 로 수정. Seen_8 은 학습
   데이터가 아직 0판이므로 수집 대상에 다시 넣을 것 (`seen8_chain.ps1` 이 교사 재평가 후 자동 수집).

## 8. 실물 SO-101 연동 순서 (월요일)

1. 모델 서버: `python 12_policy_server.py <ckpt> --n-action-steps 5` (GPU 없으면 `--device cpu` 도 됨, 15ms/스텝)
2. 프로토콜 확인(로봇 불필요): `python 31_real_robot_bridge.py --selftest` — 2026-09-05 통과
3. `--check --left COMx --right COMy` → 모터 통신·현재 각도
4. `--home` → 시뮬 홈 자세로 천천히 이동. 모양이 다르면 `SIGN/OFFSET_DEG` 표 수정
5. `--run --cams 0,1,2` (dry-run, 명령만 출력) → 이상 없으면 `--live`
   그리퍼 범위 상수는 수집 데이터 실측(닫힘 -0.2 / 열림 0.7 rad)으로 맞춰 둠.
