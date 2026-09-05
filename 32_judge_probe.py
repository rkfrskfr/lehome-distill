"""32단: 성공 판정기 진단 — 옷별 check_point 매핑과 휴지(펼친) 상태의 조건 거리.

감사 지적: Seen_8 은 모든 에피소드에서 d3 = d(0,1) 이 3.7~4.4cm 로 거의 상수인데
임계값은 10.8cm → 정책과 무관하게 절대 통과 불가. 어깨 두 점(0,1)이 같은 자리로
매핑됐을 가능성(용접/최근접 매핑 붕괴)을 확인한다.

    "C:/isaacsim/python.bat" 32_judge_probe.py [--garments Top_Long_Seen_8,Top_Long_Seen_3]
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))


def arg(n, d):
    return sys.argv[sys.argv.index(n) + 1] if n in sys.argv else d


GARMENTS = arg("--garments", "Top_Long_Seen_8,Top_Long_Seen_3,Top_Long_Seen_2").split(",")

from isaacsim import SimulationApp  # noqa: E402
app = SimulationApp({"headless": True})
try:
    import numpy as np
    from isaacsim.core.api import World
    sys.path.insert(0, HERE)
    import lehome_scene as LS

    report = {}
    for gi, g in enumerate(GARMENTS):
        LS.pick_garment = lambda gt, say=print, _g=g: os.path.join(
            LS.ASSETS, "objects", "Challenge_Garment", "Release", "Top_Long", _g)
        world = World(stage_units_in_meters=1.0, backend="torch", device="cuda:0")
        scene = LS.build_scene(world, say=lambda *a: None, garment_type="Top_Long")
        gcfg, idx = scene["gcfg"], list(scene["check_idx"])
        raw_idx = [int(x) for x in gcfg["check_point"]]
        scale = float(gcfg["scale"][0])
        thr = [t * scale for t in gcfg["success_distance"]]
        rest = scene["raw_scaled"]           # 쿠킹 입자 휴지 좌표 (m)
        p = rest[idx] * 100.0
        pairs = [(0, 4), (2, 3), (1, 5), (0, 1), (4, 5)]
        d = [float(np.linalg.norm(p[a] - p[b])) for a, b in pairs]
        # 메시 좌표(용접 전) 기준 거리도 비교 — 매핑이 틀렸는지 판별
        from pxr import Usd, UsdGeom
        raw = np.array(UsdGeom.Mesh(scene["mesh_prim"]).GetPointsAttr().Get(),
                       dtype=np.float32) * scale
        pm = raw[raw_idx] * 100.0
        dm = [float(np.linalg.norm(pm[a] - pm[b])) for a, b in pairs]
        # 최근접 매핑 잔차: 메시 점 -> 매핑된 쿠킹 점 거리
        resid = [float(np.linalg.norm(rest[idx[k]] - raw[raw_idx[k]]) * 100) for k in range(6)]
        info = {"check_point(mesh)": raw_idx, "mapped(cooked)": idx,
                "distinct_mapped": len(set(idx)) == 6,
                "thr_cm": [round(t, 1) for t in thr],
                "rest_d_cooked_cm [d0,d1,d2,d3,d4]": [round(x, 1) for x in d],
                "rest_d_mesh_cm": [round(x, 1) for x in dm],
                "map_residual_cm": [round(x, 2) for x in resid],
                "spread_conds_pass_at_rest": [d[3] >= thr[3], d[4] >= thr[4]],
                "n_mesh_pts": int(raw.shape[0]), "n_cooked": int(rest.shape[0])}
        report[g] = info
        print(f"\n=== {g} ===")
        for k, v in info.items():
            print(f"  {k}: {v}")
        world.clear()
        del world
    json.dump(report, open(os.path.join(HERE, "judge_probe.json"), "w",
                           encoding="utf-8"), indent=1)
except Exception:
    import traceback; traceback.print_exc()
app.close()
