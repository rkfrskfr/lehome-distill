# LeHome 옷 접기 — 우승자 정책 증류 파이프라인 (Windows Isaac Sim)

ICRA 2026 LeHome 챌린지(양팔 로봇 옷 접기) 환경을 **Windows Isaac Sim 5.1에 이식**하고,
우승자의 2.83B VLA 정책을 시연 생성기로 사용해 **51.7M ACT 소형 정책을 지식 증류로
학습**하는 파이프라인. 상세 배경·실험 결과는 [`PROJECT_REPORT.md`](PROJECT_REPORT.md) 참고.

- 현재 성적: 소형 모델 **47.5%** (긴팔 12벌 × 10회) — 동일 환경에서 측정한
  우승자 모델(46~50%)과 동급. ⚠ 2026-09-05 성공 판정기 기준점 버그를 수정해
  (`AUDIT.md` §E) 두 모델 모두 재평가 중 — 위 수치는 수정 전 판정 기준
- 핵심 실측: 행동 묶음 100스텝 전체 실행(31%) → 5스텝 실행 후 재계획(66%) —
  폐루프 주기가 성능의 지배 변수

## 시스템 구조

```
Isaac Sim (Windows, 시뮬레이션)
   ├── TCP :8767 → 15_winner_relay.py → WebSocket :8000 → 우승자 π0.5 (WSL2, JAX)
   └── TCP :8766 → 12_policy_server.py (소형 모델 ACT, PyTorch)
```

매 스텝: 시뮬레이터가 카메라 3대 RGB + 관절 상태를 모델 서버로 전송 →
서버가 관절 목표 각도 12개를 반환 → 시뮬레이터가 로봇 구동 → 반복.

## 데이터 스키마

| 키 | 형식 | 의미 |
|---|---|---|
| `observation.state` | float32 (12,) | 양팔 6관절 × 2 현재 각도 (라디안) |
| `observation.images.top_rgb` | uint8 (480, 640, 3) | 상단 카메라 (전역 시점) |
| `observation.images.left_rgb` | uint8 (480, 640, 3) | 왼손목 카메라 (국소 시점) |
| `observation.images.right_rgb` | uint8 (480, 640, 3) | 오른손목 카메라 (국소 시점) |
| `action` | float32 (12,) | 목표 관절 각도 (라디안, [왼팔 6, 오른팔 6]) |

- 통신 프로토콜(TCP): 요청 `{state, images{3키}}` → 응답 `{action: float[12]}`
- 소형 모델 출력: 100스텝 × 12관절 연속값 묶음, 앞 5스텝만 실행 후 재관측
- 카메라 배치·초점은 대회 공식 규격 그대로 (공식 데이터와 픽셀 정렬 검증)

## 파일 안내 (역할별)

**문서**
| 파일 | 내용 |
|---|---|
| `README.md` | 이 문서 |
| `PROJECT_REPORT.md` | 프로젝트 전체 보고서 (배경·방법·실험 결과) |

**시뮬레이션 환경·평가**
| 파일 | 내용 |
|---|---|
| `lehome_scene.py` | 환경 이식 본체 — 씬·물리·카메라 3대·성공 판정·도메인 랜덤화 |
| `14_benchmark.py` | 성공률 평가 루프 (모든 수치의 출처) |
| `analyze_bench.py` | 평가 CSV 집계 |

**모델 서빙 (관측 → 액션)**
| 파일 | 내용 |
|---|---|
| `12_policy_server.py` | 소형 모델(ACT) 추론 서버 — 관측을 받아 관절 각도 반환 |
| `15_winner_relay.py` | 우승자 모델(WSL WebSocket) ↔ 시뮬레이터(TCP) 중계 |

**데이터 수집·변환**
| 파일 | 내용 |
|---|---|
| `16_collect_distill.py` | 우승자 모델 시연 수집 (물리 스냅샷·실패 보관·조기 중단) |
| `17_convert_distill.py` | 수집물 → LeRobot 학습 데이터셋 변환 |
| `22_replay_snapshots.py` | 저장한 물리 상태 복원 재실행 (성공 증식·실패 지점 재시도) |

**학습·자동화**
| 파일 | 내용 |
|---|---|
| `23_train_success_head.py` | 프레임별 성공확률 예측기 학습 |
| `orchestrator.py` | 무인 실험 루프 (수집→학습→평가→판단 반복) |
| `run_collect3.ps1` / `run_full_bench.ps1` / `run_infer_sweep.ps1` | 수집·전체 평가·추론 설정 비교 드라이버 |

**평가 결과 CSV** (보고서 수치의 원자료)
| 파일 | 내용 |
|---|---|
| `bench_final_n5.csv` | 최고 기록 47.5% (12벌 × 10회) |
| `bench_noaug_n100 / aug_n100 / noaug_n5 / aug_n5.csv` | 행동 묶음 길이 × 증강 2×2 비교 (31→66% 근거) |
| `bench_teach_full.csv` | 우승자 모델 동일 환경 측정 (옷 4벌 × 8회 부분 평가; 전체 120회 수치는 45.8%) |

## 실행 개요

```powershell
# 1) 소형 모델 서버 (평가용 설정)
python 12_policy_server.py <체크포인트>\pretrained_model --n-action-steps 5

# 2) 전체 평가 (12벌 × 10회)
powershell -File run_full_bench.ps1 -Episodes 10 -Tag my_eval -Port 8766 -PhysPerAction 2

# 3) 집계
python analyze_bench.py my_eval
```

## 제3자 구성요소 (본 저장소에 미포함)

| 구성요소 | 출처 |
|---|---|
| 우승자 솔루션 (π0.5 서버·가중치) | github.com/IliaLarchenko/lehome_solution |
| ACT 구현·학습 루프 (LeRobot) | github.com/huggingface/lerobot |
| 대회 공식 환경·에셋 | github.com/lehome-official/lehome-challenge · lehome-challenge.com |
| 시뮬레이터 | NVIDIA Isaac Sim 5.1 |

※ 옷·씬 3D 에셋, 수집 데이터, 학습된 가중치는 용량 문제로 저장소에서 제외
(에셋은 공식 HuggingFace `lehome/asset_challenge` 에서 수령).
