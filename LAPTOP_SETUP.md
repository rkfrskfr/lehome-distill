# 다른 컴퓨터(노트북)에서 실물 로봇 돌리기 — 설치 안내

이 데스크톱이 아니라 **로봇을 연결한 다른 컴퓨터**에서 모델을 돌리는 방법.
Isaac Sim 은 필요 없다. 그래픽카드도 없어도 되지만, 있으면 제어 주기가 훨씬 안정적이다.
노트북 한 대에 모델과 로봇을 함께 올리는 것이 권장 구성이다.

절차 자체는 `REAL_ROBOT_RUNBOOK.md` 를 따르고, 이 문서는 **그 전에 노트북에 무엇을 깔아야 하는지**만 다룬다.

---

## 1. 권장 구성: 노트북 한 대에 전부

| | 모델 계산 | 로봇·카메라 |
|---|---|---|
| **권장** | 노트북 | 노트북 |
| 비권장 | 데스크톱(원격) | 노트북 |

노트북 한 대로 충분한 이유
- 모델은 5스텝에 한 번만 신경망을 돌린다. 실측(데스크톱): GPU 19밀리초, CPU 196밀리초.
- CPU 만 쓰면 제어 주기가 30Hz 가 아니라 10~15Hz 다. 팔이 학습 때보다 느리게 움직이지만 이번 단계
  (방향·크기 확인)에는 문제 없다. 그래픽카드가 있으면 `--device cpu` 를 빼는 편이 낫다.
- 원격으로 나누면 매 스텝 **2.8MB** 의 사진을 보내야 한다. 기가비트 유선에서도 왕복에 22밀리초가 들어
  33밀리초 예산을 거의 다 먹는다. 무선은 불가능하다.

원격이 꼭 필요하면: 서버 `--host 0.0.0.0 --allow-ip <노트북 IP>`, 브리지 `--host <서버 IP>`.
유선 기가비트만 쓸 것. 서버는 받은 데이터를 그대로 실행 가능한 형태로 푸는 구조라, 열어 둘 때는
`--allow-ip` 로 상대를 반드시 제한한다.

---

## 2. 노트북에 설치할 것

**파이썬 3.12 이상** (3.11 이하는 설치 자체가 거부된다). 3.12.10 이 이 데스크톱과 같은 버전이다.

이식 폴더를 노트북에 복사한 뒤 **그 폴더 안에서** 가상환경을 만든다.

```powershell
cd C:\lehome_portable
```

```powershell
py -3.12 -m venv .venv
```

```powershell
.venv\Scripts\activate
```

```powershell
pip install "lerobot[feetech]==0.6.1" opencv-python
```

- `[feetech]` 를 빼면 안 된다. 모터 통신 SDK 가 이 안에 들어 있어, 없으면 팔 연결 순간 오류가 난다.
- `[hardware]` 는 이름과 달리 모터 SDK 가 없다. 반드시 `[feetech]`.
- 그래픽카드가 없으면 용량이 작은 CPU 전용 파이토치를 먼저 깔아도 된다.

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

---

## 3. 노트북으로 옮길 파일

데스크톱에서 아래를 실행하면 필요한 것만 한 폴더에 모아 준다.

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\H\Desktop\lehome-win\make_portable.ps1
```

만들어지는 폴더(242MB)
| 항목 | 내용 |
|---|---|
| `model\` | 학습된 모델 (197MB). 정규화 통계가 안에 들어 있어 **학습 데이터는 필요 없다** |
| `12_policy_server.py` | 모델 서버 |
| `31_real_robot_bridge.py` | 실물 연결 브리지 |
| `torch_hub\resnet18-f37072fd.pth` | 모델이 쓰는 영상 인식 부품 (45MB). 없으면 첫 실행에서 인터넷을 받으러 간다 |
| `REAL_ROBOT_HANDOFF.md` | 실물 작업 전체 인수인계 문서 (먼저 읽을 것) |
| `REAL_ROBOT_RUNBOOK.md` · `COMMANDS.txt` | 실행 순서와 명령 모음 |

`resnet18` 파일은 노트북의 `%USERPROFILE%\.cache\torch\hub\checkpoints\` 안에 넣는다.
그러면 인터넷 없이도 동작한다.

---

## 4. USB 연결 주의

- 팔 2개 + 카메라 3개 = USB 기기 5개. **카메라 3대를 같은 허브에 몰면 열리지 않을 수 있다.**
  노트북의 서로 다른 USB 단자에 나눠 꽂을 것. 브리지가 실행 시 각 카메라의 실제 형식을 출력하니
  `MJPG` 로 나오는지 확인한다. `YUY2` 로 나오면 대역폭이 모자라 3대가 함께 못 열린다.
- 팔은 윈도우 11 이면 대체로 드라이버가 자동으로 잡힌다. 장치 관리자의 포트 항목에 안 보이면
  WCH 사의 `CH343SER` 드라이버를 설치한다.
- 리눅스면 시리얼 포트 권한이 필요하다. `sudo usermod -aG dialout $USER` 후 재로그인.

---

## 5. 영점(캘리브레이션)은 노트북에서 새로 잡는다

- 데스크톱에 있는 옛 파일(`follower_01.json` 등)을 이름만 바꿔 복사하지 말 것.
  영점 값은 **팔에 연결할 때 파일에서 모터로 기록**되므로, 다른 팔의 값이면 오류 없이 조용히 어긋난 각도로 움직인다.
- 같은 팔을 그대로 옮기는 경우에만 파일 복사가 유효하다. 그때도 `--check` 로 각도를 눈으로 확인할 것.
- 파일 이름은 반드시 `lehome_bi_left.json` / `lehome_bi_right.json`.

---

## 6. 설치가 끝났는지 확인하는 순서

```powershell
python -c "import scservo_sdk, serial, cv2, torch; print('설치 OK')"
```

```powershell
python 12_policy_server.py model --n-action-steps 5 --device cpu
```

다른 창에서

```powershell
python 31_real_robot_bridge.py --selftest
```

- 마지막 명령이 "12관절 명령 생성·변환 정상" 을 출력하면 소프트웨어 쪽은 끝이다.
- 여기까지는 로봇도 카메라도 필요 없다. 실물 작업은 `REAL_ROBOT_RUNBOOK.md` **1단계(배선·포트 확인)부터**
  순서대로 진행한다. 통신 확인 이후 단계는 COM 포트 이름과 영점 파일이 있어야 한다.
- 2단계(모터 번호)는 조립이 정상이면 건너뛴다. 3단계(영점)는 이 문서 5절대로 노트북에서 새로 잡는다.
- 5·6단계(서버·자가검사)는 방금 이 절에서 마쳤다. 서버 창을 켜 둔 채로 두면 다시 하지 않아도 된다.

---

## 7. 하면 안 되는 것

- `--ensemble` 옵션. 계산이 5배로 늘어 주기를 전혀 못 맞춘다.
- `--host 0.0.0.0` 을 `--allow-ip` 없이 쓰는 것. 같은 네트워크의 누구나 노트북에서 코드를 실행할 수 있다.
- 학습 데이터 폴더(`distill_lerobot_*`) 복사. 수십 GB 인데 추론에는 전혀 쓰이지 않는다.
- `training_state` 폴더 복사. 394MB 이고 학습 재개용이라 실물 구동에는 불필요하다.
