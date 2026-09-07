"""38단: 4종 옷 형상 대조 — 배치 높이가 왜 종류마다 다른지 (USD 만 읽음, 물리 없음)."""
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
    d = os.path.join(R, t, f"{t}_Seen_0")
    usd = glob.glob(os.path.join(d, "*_obj_exp.usd"))[0]
    cfg = json.load(open(glob.glob(os.path.join(d, "*_obj_exp.json"))[0], encoding="utf-8"))
    s = float(cfg["scale"][0])
    pr = cfg["initial_pos_range"]
    gz = (pr[2] + pr[5]) / 2
    stage = Usd.Stage.Open(usd)
    mesh = next(p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh))
    pts = np.array(UsdGeom.Mesh(mesh).GetPointsAttr().Get(), dtype=np.float64) * s
    rot = cfg["initial_rot_range"][2]
    if abs(rot) > 1e-6:   # z 축 회전 적용 후의 형상
        a = np.deg2rad(rot); c, sn = np.cos(a), np.sin(a)
        Rz = np.array([[c, -sn, 0], [sn, c, 0], [0, 0, 1]])
        pts_r = pts @ Rz.T
    else:
        pts_r = pts
    out[t] = {
        "scale": s, "n_pts": int(pts.shape[0]),
        "centroid_cm": np.round(pts.mean(0) * 100, 1).tolist(),
        "z_range_cm": [round(float(pts[:, 2].min() * 100), 1), round(float(pts[:, 2].max() * 100), 1)],
        "z_range_after_rot_cm": [round(float(pts_r[:, 2].min() * 100), 1), round(float(pts_r[:, 2].max() * 100), 1)],
        "xy_span_cm": [round(float(pts_r[:, 0].ptp() * 100), 1), round(float(pts_r[:, 1].ptp() * 100), 1)],
        "drop_z": gz, "rot_z_deg": rot,
        "lowest_after_place_m": round(gz + float(pts_r[:, 2].min()), 3),
        "table_top_m": 0.521,
    }
    out[t]["clearance_cm"] = round((out[t]["lowest_after_place_m"] - 0.521) * 100, 1)
    print(t, json.dumps(out[t], ensure_ascii=False))
json.dump(out, open(os.path.join(HERE, "geom_check.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
app.close()
