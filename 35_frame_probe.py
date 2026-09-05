"""35단: 옷 배치 프레임 진단 — 쿠킹 좌표 +23cm z 의 정체와 실제 낙하 높이."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
try:
    import numpy as np, torch
    from isaacsim.core.api import World
    from pxr import Usd, UsdGeom
    sys.path.insert(0, HERE)
    import lehome_scene as LS
    g = sys.argv[1] if len(sys.argv) > 1 else "Top_Long_Seen_8"
    LS.pick_garment = lambda gt, say=print, _g=g: os.path.join(LS.ASSETS, "objects", "Challenge_Garment", "Release", "Top_Long", _g)
    world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0")
    scene = LS.build_scene(world, say=lambda *a: None, garment_type="Top_Long", settle_steps=0)
    view, mesh_prim, cloth = scene["view"], scene["mesh_prim"], scene["cloth"]
    out = {"garment": g}
    xf = UsdGeom.Xformable(mesh_prim)
    m = xf.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
    out["mesh_prim_world_translate"] = [round(float(v), 4) for v in m.ExtractTranslation()]
    out["mesh_prim_xform_ops"] = [(o.GetOpName(), str(o.Get())) for o in xf.GetOrderedXformOps()]
    try:
        p, q = cloth.get_world_pose()
        out["cloth_get_world_pose"] = [round(float(v), 4) for v in np.asarray(p.cpu() if hasattr(p, "cpu") else p).reshape(-1)]
    except Exception as e:
        out["cloth_get_world_pose"] = repr(e)
    cooked = scene["raw_scaled"]; baked = scene["baked"]
    out["cooked_centroid(after world.reset, before place)"] = np.round(cooked.mean(0), 4).tolist()
    out["baked_centroid(placed = cooked + g_pos)"] = np.round(baked.mean(0), 4).tolist()
    v0 = view.get_world_positions().cpu().numpy().reshape(-1, 3)
    out["view_centroid_right_after_place"] = np.round(v0.mean(0), 4).tolist()
    usd_pts = np.array(UsdGeom.Mesh(mesh_prim).GetPointsAttr().Get(), dtype=np.float64)
    out["usd_points_centroid_after_place(local)"] = np.round(usd_pts.mean(0), 4).tolist()
    out["usd_points_n"] = int(usd_pts.shape[0])
    # 몇 스텝 굴려 낙하 확인
    zs = []
    for i in range(240):
        world.step(render=False)
        if i % 30 == 29:
            zs.append(round(float(view.get_world_positions().cpu().numpy().reshape(-1, 3)[:, 2].mean()), 4))
    out["z_mean_every_0.5s"] = zs
    usd_pts2 = np.array(UsdGeom.Mesh(mesh_prim).GetPointsAttr().Get(), dtype=np.float64)
    out["usd_points_centroid_after_settle(local)"] = np.round(usd_pts2.mean(0), 4).tolist()
    # 테이블 상판 높이
    tbl = None
    for pr in Usd.PrimRange(scene["stage"].GetPrimAtPath("/World")):
        if "table" in pr.GetPath().pathString.lower() and pr.IsA(UsdGeom.Xformable):
            t = UsdGeom.Xformable(pr).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
            tbl = (pr.GetPath().pathString, [round(float(x), 4) for x in t]); break
    out["table_prim"] = tbl
    json.dump(out, open(os.path.join(HERE, "frame_probe.json"), "w"), indent=1)
except Exception:
    import traceback; traceback.print_exc()
    open(os.path.join(HERE, "frame_probe.err"), "w").write(traceback.format_exc())
app.close()
