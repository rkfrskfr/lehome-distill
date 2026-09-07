"""36단: 교사-학생 격차의 정체 — 어떤 조건에서, 어떤 옷에서, 얼마나 모자라서 실패하는가."""
import glob, json, os, sys
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "Assets", "objects", "Challenge_Garment", "Release", "Top_Long")

def thr(g):
    cf = glob.glob(os.path.join(ROOT, g, "*_obj_exp.json"))[0]
    c = json.load(open(cf, encoding="utf-8"))
    s = float(c["scale"][0])
    return [t * s for t in c["success_distance"]]

# d0=d(0,4)<=t0, d1=d(2,3)<=t1, d2=d(1,5)<=t2, d3=d(0,1)>=t3, d4=d(4,5)>=t4
LE = [True, True, True, False, False]
NAMES = ["몸통접기 d(0,4)", "소매A d(2,3)", "소매B d(1,5)", "어깨벌어짐 d(0,1)", "밑단벌어짐 d(4,5)"]

def load(tags):
    fr = []
    for t in tags:
        p = os.path.join(HERE, f"bench_{t}.csv")
        if os.path.exists(p):
            d = pd.read_csv(p); d = d[d.success.astype(str).str.isdigit()].copy()
            d["success"] = d.success.astype(int); d["tag"] = t; fr.append(d)
    return pd.concat(fr, ignore_index=True) if fr else None

def analyse(name, d):
    print(f"\n{'='*70}\n{name}: {d.success.sum()}/{len(d)} = {100*d.success.mean():.1f}%")
    rows, margins = [], {i: [] for i in range(5)}
    for _, r in d.iterrows():
        t = thr(r.garment)
        ok = []
        for i in range(5):
            v = float(r[f"d{i}"])
            passed = (v <= t[i]) if LE[i] else (v >= t[i])
            ok.append(passed)
            if not passed:
                margins[i].append(abs(v - t[i]))
        rows.append(ok)
    ok = np.array(rows)
    fail = d.success.values == 0
    print(f"실패 {fail.sum()}판 중 조건별 미달 비율:")
    for i in range(5):
        n = (~ok[fail, i]).sum()
        m = np.median(margins[i]) if margins[i] else 0
        print(f"  {NAMES[i]:20s} {n:4d}판 ({100*n/max(fail.sum(),1):5.1f}%)  "
              f"미달 중앙값 {m:5.1f}cm")
    npass = ok.sum(1)
    print("통과 조건 수 분포:", {k: int(v) for k, v in zip(*np.unique(npass, return_counts=True))})
    near = ((npass == 4) & fail).sum()
    print(f"아깝게 실패(4/5) {near}판 = 전체 실패의 {100*near/max(fail.sum(),1):.0f}%")
    return ok, npass

comb = load(["combo_n5", "combo_n5b"])
teach = load(["teacher_v3"])
ok_s, np_s = analyse("학생 act_student_combo", comb)
ok_t, np_t = analyse("교사 pi0.5", teach)

print(f"\n{'='*70}\n옷별 격차 (학생 240판 / 교사 120판)")
gs = comb.groupby("garment").success.mean() * 100
gt = teach.groupby("garment").success.mean() * 100
cmp = pd.DataFrame({"학생": gs.round(0), "교사": gt.round(0)})
cmp["격차"] = (cmp["교사"] - cmp["학생"]).round(0)
print(cmp.sort_values("격차", ascending=False).to_string())

print(f"\n{'='*70}\n시간")
for nm, d in (("학생", comb), ("교사", teach)):
    s = d[d.success == 1]; f = d[d.success == 0]
    print(f"{nm}: 성공 중앙 {s.sec.median():.0f}초 / 실패 중앙 {f.sec.median():.0f}초, "
          f"실패 중 600스텝 완주 {100*(f.step == -1).mean():.0f}%")
