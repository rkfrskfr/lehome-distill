"""37단: 4종 옷 스모크 — 씬 빌드·체크포인트 매핑·판정기가 종류마다 도는지 확인.
    "C:/isaacsim/python.bat" 37_type_smoke.py Pant_Long Pant_Long_Seen_0
"""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
GTYPE = sys.argv[1] if len(sys.argv) > 1 else "Pant_Long"
GDIR = sys.argv[2] if len(sys.argv) > 2 else f"{GTYPE}_Seen_0"
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
out = {"type": GTYPE, "garment": GDIR}
try:
    import numpy as np
    from isaacsim.core.api import World
    sys.path.insert(0, HERE)
    import lehome_scene as LS
    LS.pick_garment = lambda gt, say=print, _g=GDIR, _t=GTYPE: os.path.join(
        LS.ASSETS, "objects", "Challenge_Garment", "Release", _t, _g)
    logs = []
    def say(*a):
        logs.append(" ".join(str(x) for x in a))
    world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0")
    scene = LS.build_scene(world, say=say, garment_type=GTYPE, settle_steps=120)
    g = scene["gcfg"]
    out["gtype_resolved"] = LS.garment_type_of(g)
    out["n_thr"] = len(g["success_distance"])
    out["mapped"] = list(scene["check_idx"])
    rng = np.random.RandomState(0)
    LS.reset_episode(world, scene, rng, settle_steps=180, render=False,
                     say=say, mode="initial")
    # 리셋 후 시간에 따른 z 추적 — 떨어지는 중인지, 안정된 것인지 구분
    traj = []
    for k in range(6):
        for _ in range(60):
            world.step(render=False)
        q = scene["view"].get_world_positions().cpu().numpy().reshape(-1, 3)
        traj.append([round(float(q[:, 2].mean()), 3), round(float(q[:, 2].min()), 3)])
    out["z_after_reset_every_1s"] = traj
    conds, dists, thrs, names = LS.check_conditions(scene["view"], g, scene["check_idx"])
    p = scene["view"].get_world_positions().cpu().numpy().reshape(-1, 3)
    out["rest_z_mean"] = round(float(p[:, 2].mean()), 3)
    out["rest_z_min"] = round(float(p[:, 2].min()), 3)
    out["span_xy"] = [round(float(p[:, 0].max() - p[:, 0].min()), 3),
                      round(float(p[:, 1].max() - p[:, 1].min()), 3)]
    out["cond_names"] = names
    out["dists_cm"] = [round(x, 1) for x in dists]
    out["thr_cm"] = [round(t, 1) for t in thrs]
    out["conds_at_rest"] = conds
    out["scene_log"] = logs
    out["ok"] = True
except Exception:
    import traceback
    out["ok"] = False; out["error"] = traceback.format_exc()[-1500:]
print("SMOKE " + json.dumps(out, ensure_ascii=False))
fp = os.path.join(HERE, "type_smoke.json")
old = json.load(open(fp, encoding="utf-8")) if os.path.exists(fp) else {}
old[GDIR] = out
json.dump(old, open(fp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
app.close()
