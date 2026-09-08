"""39단: 4종 48벌 전체의 실제 크기 (cm) — 실물 옷을 고를 때 쓸 규격표."""
import glob, json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import numpy as np
from pxr import Usd, UsdGeom
HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "Assets", "objects", "Challenge_Garment", "Release")
out = {}
for t in ("Top_Long", "Top_Short", "Pant_Long", "Pant_Short"):
    rows = []
    for d in sorted(glob.glob(os.path.join(R, t, f"{t}_*"))):
        if not os.path.isdir(d):
            continue
        u = glob.glob(os.path.join(d, "*_obj_exp.usd"))
        c = glob.glob(os.path.join(d, "*_obj_exp.json"))
        if not u or not c:
            continue
        cfg = json.load(open(c[0], encoding="utf-8"))
        s = float(cfg["scale"][0])
        stage = Usd.Stage.Open(u[0])
        mesh = next(p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
        pts = np.array(UsdGeom.Mesh(mesh).GetPointsAttr().Get(), dtype=np.float64)
        raw_cm = pts.ptp(0) * 100.0            # 원본(스케일 전)
        sc_cm = pts.ptp(0) * s * 100.0         # 시뮬에 실제로 쓰이는 크기
        rows.append({"garment": os.path.basename(d), "scale": s,
                     "sim_cm": [round(float(x), 1) for x in sc_cm],
                     "orig_cm": [round(float(x), 1) for x in raw_cm]})
    out[t] = rows
    if rows:
        a = np.array([r["sim_cm"] for r in rows])
        print(f"\n=== {t} ({len(rows)}벌) scale={rows[0]['scale']}")
        print(f"  시뮬 크기 x: {a[:,0].min():.0f}~{a[:,0].max():.0f}cm  "
              f"y: {a[:,1].min():.0f}~{a[:,1].max():.0f}cm  두께 z: {a[:,2].min():.1f}~{a[:,2].max():.1f}cm")
        b = np.array([r["orig_cm"] for r in rows])
        print(f"  원본(스케일 전) x: {b[:,0].min():.0f}~{b[:,0].max():.0f}cm  y: {b[:,1].min():.0f}~{b[:,1].max():.0f}cm")
        for r in rows[:3]:
            print(f"    {r['garment']}: {r['sim_cm'][0]}x{r['sim_cm'][1]}cm")
json.dump(out, open(os.path.join(HERE, "garment_sizes.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
app.close()
