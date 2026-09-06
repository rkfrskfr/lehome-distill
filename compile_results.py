"""여러 벤치마크 CSV 를 한 표로 — 신판정(2026-09-05 17:00 이후) / 구판정 구분.

    python compile_results.py            -> RESULTS.md 갱신 + 콘솔 출력
    python compile_results.py --tags a,b -> 지정 태그만

태그별 CSV 는 bench_<tag>.csv. 없는 태그는 건너뛴다(진행 중이면 현재까지 행만 집계).
"""
import math
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# (태그, 설명, 판정기 버전)
CANDIDATES = [
    # 신 = 판정기 v3 + 초기 자세 수정(09-05 20:35) 이후 / 구 = 그 이전 환경
    ("teacher_v3", "원본 모델 π0.5 2.83B (공식 리더보드 긴팔 74.5%)", "신"),
    ("fix_n5", "고친 환경 재수집 데이터로 새로 학습한 소형 모델", "신"),
    ("final_n5_rep", "이전 최고 소형 모델 재평가 (수정 전 데이터 267판·증강 ON, 시드 201~212)", "신"),
    ("cur_n5", "수정 전 랜덤화 데이터 505판 학습 모델 (60k 스텝)", "신"),
    ("cur_n5b", "같은 505판 모델 2차 평가 (시드 701~712; 1차와 합쳐 n=240)", "신"),
    ("cur40k_n5", "같은 모델의 40k 스텝 체크포인트 (체크포인트 선택 확인)", "신"),
    ("combo_n5", "505판 + 고친 환경 169판 = 674판 학습 모델", "신"),
    ("combo_n5b", "같은 674판 모델 2차 평가 (시드 801~812)", "신"),
    ("seed2_n5", "이전 최고 레시피 + 학습 시드 2000 (시드 분산)", "신"),
    ("noaug_full_n5", "증강 OFF 동일 데이터 (증강 효과 확인)", "신"),
    ("teacher_v3_oldinit", "원본 모델, 판정기 v3 + 34cm 낙하(초기 자세 수정 전)", "중간"),
    ("cur_n5_oldinit", "505판 모델, 판정기 v3 + 34cm 낙하", "중간"),
    ("final_n5", "이전 최고 소형 모델 (구판정 원본 수치 47.5%)", "구"),
    ("teach_full", "원본 모델 (구판정, 4벌 부분 평가)", "구"),
]


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (100 * (c - h), 100 * (c + h))


def md_table(df, index=False):
    """tabulate 없이 마크다운 표."""
    cols = ([df.index.name or ""] if index else []) + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        vals = ([str(idx)] if index else []) + [str(v) for v in row.tolist()]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


def load(tag):
    p = os.path.join(HERE, f"bench_{tag}.csv")
    if not os.path.exists(p):
        return None
    d = pd.read_csv(p)
    d = d[d["success"].astype(str).str.isdigit()].copy()
    d["success"] = d["success"].astype(int)
    return d


def main():
    tags = [c for c in CANDIDATES]
    if "--tags" in sys.argv:
        want = sys.argv[sys.argv.index("--tags") + 1].split(",")
        tags = [c for c in CANDIDATES if c[0] in want] + \
               [(t, "", "?") for t in want if t not in {c[0] for c in CANDIDATES}]
    rows, per_g = [], {}
    for tag, desc, ver in tags:
        d = load(tag)
        if d is None or len(d) == 0:
            continue
        seen = d[d.garment.str.contains("_Seen_")]
        unseen = d[d.garment.str.contains("_Unseen_")]
        ex8 = d[~d.garment.str.endswith("_Seen_8")]
        k, n = int(d.success.sum()), len(d)
        lo, hi = wilson(k, n)
        npass = pd.to_numeric(d.get("n_pass"), errors="coerce") if "n_pass" in d else None
        rows.append({
            "태그": tag, "설명": desc, "판정": ver,
            "전체": f"{100*k/n:.1f}% ({k}/{n})", "95% CI": f"{lo:.0f}~{hi:.0f}",
            "Seen": f"{100*seen.success.mean():.1f}%" if len(seen) else "-",
            "Unseen": f"{100*unseen.success.mean():.1f}%" if len(unseen) else "-",
            "Seen_8 제외": f"{100*ex8.success.mean():.1f}%" if len(ex8) else "-",
            # 성공률이 낮을 때의 변별 지표: 5개 조건 중 평균 통과 수, 4개 이상 통과 비율
            "평균 통과조건": f"{npass.mean():.2f}/5" if npass is not None and npass.notna().any() else "-",
            "≥4/5": f"{100*(npass >= 4).mean():.0f}%" if npass is not None and npass.notna().any() else "-",
            "판수": n, "완료": "✅" if n >= 120 else f"진행 {n}/120",
        })
        per_g[tag] = d.groupby("garment").success.agg(["sum", "size"])
    if not rows:
        print("결과 CSV 없음"); return
    t = pd.DataFrame(rows)
    out = ["# 결과 요약 (자동 생성: compile_results.py)", "",
           "판정 = 신: 2026-09-05 17:00 기준점 매핑 수정 후 / 구: 수정 전. 구·신 수치는 직접 비교하지 않음.",
           "", md_table(t), "", "## 옷별 성공 (성공/시도)", ""]
    garments = sorted({g for v in per_g.values() for g in v.index},
                      key=lambda s: (("Unseen" in s), int(s.rsplit("_", 1)[1])))
    m = pd.DataFrame(index=garments)
    for tag, v in per_g.items():
        m[tag] = [f"{int(v.loc[g,'sum'])}/{int(v.loc[g,'size'])}" if g in v.index else "-" for g in garments]
    out += [md_table(m, index=True), ""]
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "RESULTS.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")


if __name__ == "__main__":
    main()
