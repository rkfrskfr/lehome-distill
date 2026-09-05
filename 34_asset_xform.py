"""34단: 옷 에셋 내부 변환 조사 — 쿠킹 좌표 +23cm z 의 출처 (에셋 xform? 쿠킹?)."""
import glob, json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import numpy as np
from pxr import Usd, UsdGeom, Gf
HERE = os.path.dirname(os.path.abspath(__file__))
g = sys.argv[1] if len(sys.argv) > 1 else "Top_Long_Seen_8"
d = os.path.join(HERE, "Assets", "objects", "Challenge_Garment", "Release", "Top_Long", g)
usd = glob.glob(os.path.join(d, "*_obj_exp.usd"))[0]
cfg = json.load(open(glob.glob(os.path.join(d, "*_obj_exp.json"))[0], encoding="utf-8"))
print("scale", cfg["scale"], "initial_pos_range", cfg["initial_pos_range"], "initial_rot_range", cfg.get("initial_rot_range"))
stage = Usd.Stage.Open(usd)
print("upAxis", UsdGeom.GetStageUpAxis(stage), "metersPerUnit", UsdGeom.GetStageMetersPerUnit(stage))
print("defaultPrim", stage.GetDefaultPrim().GetPath() if stage.GetDefaultPrim() else None)
out = {"scale": cfg["scale"], "initial_pos_range": cfg["initial_pos_range"], "upAxis": str(UsdGeom.GetStageUpAxis(stage)), "mpu": UsdGeom.GetStageMetersPerUnit(stage), "prims": []}
xc = UsdGeom.XformCache()
for p in stage.Traverse():
    if p.IsA(UsdGeom.Xformable):
        x = UsdGeom.Xformable(p)
        ops = [(o.GetOpName(), o.Get()) for o in x.GetOrderedXformOps()]
        m = xc.GetLocalToWorldTransform(p)
        t = m.ExtractTranslation()
        out["prims"].append({"path": str(p.GetPath()), "type": p.GetTypeName(), "ops": [(n, str(v)) for n, v in ops], "world_t": [round(v, 4) for v in (t[0], t[1], t[2])]})
    if p.IsA(UsdGeom.Mesh):
        pts = np.array(UsdGeom.Mesh(p).GetPointsAttr().Get())
        print("  mesh pts", pts.shape, "centroid", np.round(pts.mean(0), 4), "z range", round(float(pts[:,2].min()),4), round(float(pts[:,2].max()),4), "y range", round(float(pts[:,1].min()),4), round(float(pts[:,1].max()),4))
        ext = UsdGeom.Mesh(p).GetExtentAttr().Get()
        out["mesh"] = {"n": int(pts.shape[0]), "centroid": np.round(pts.mean(0), 4).tolist(), "zrange": [round(float(pts[:,2].min()),4), round(float(pts[:,2].max()),4)], "yrange": [round(float(pts[:,1].min()),4), round(float(pts[:,1].max()),4)], "extent": str(ext)}
json.dump(out, open(os.path.join(HERE, "asset_xform.json"), "w"), indent=1)
app.close()
