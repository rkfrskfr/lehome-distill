"""벤치마크 CSV 요약 — 옷별/Seen-Unseen/신뢰구간/실패 원인."""
import math
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
tag = sys.argv[1] if len(sys.argv) > 1 else "full"
d = pd.read_csv(os.path.join(HERE, f"bench_{tag}.csv"))
d = d[d["success"].astype(str).str.isdigit()].copy()
d["success"] = d["success"].astype(int)

print(f"=== bench_{tag}.csv : 총 {len(d)}판 ===")
g = d.groupby("garment").agg(n=("success", "size"), ok=("success", "sum"),
                             avg_pass=("n_pass", "mean"),
                             med_sec=("sec", "median"))
g["rate%"] = (100 * g["ok"] / g["n"]).round(0)
print(g.to_string())

seen = d[d["garment"].str.contains("_Seen_")]
unseen = d[d["garment"].str.contains("_Unseen_")]
print()
if len(seen):
    print(f"Seen   : {seen.success.sum()}/{len(seen)} = {100*seen.success.mean():.1f}%")
if len(unseen):
    print(f"Unseen : {unseen.success.sum()}/{len(unseen)} = {100*unseen.success.mean():.1f}%")
p, n = d.success.mean(), len(d)
se = math.sqrt(p * (1 - p) / n) if n else 0
print(f"전체   : {d.success.sum()}/{n} = {100*p:.1f}%  "
      f"(95% CI {100*(p-1.96*se):.1f}~{100*(p+1.96*se):.1f}%)")

print()
print("통과 조건 개수 분포:", d.n_pass.value_counts().sort_index().to_dict())

fail = d[d.success == 0]
if len(fail):
    thr = {"d0": "몸통접기(<=)", "d1": "소매A(<=)", "d2": "소매B(<=)",
           "d3": "벌어짐A(>=)", "d4": "벌어짐B(>=)"}
    print()
    print(f"실패 {len(fail)}판의 평균 거리:")
    for k, v in thr.items():
        print(f"  {k} {v}: {fail[k].mean():.1f}")

ok = d[d.success == 1]
if len(ok):
    print()
    print(f"성공 판 소요 스텝: 중앙값 {ok.step.median():.0f}, "
          f"최소 {ok.step.min():.0f}, 최대 {ok.step.max():.0f}")
