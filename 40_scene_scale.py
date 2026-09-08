"""40단: 씬 절대 크기 — 테이블·로봇·옷을 같은 자로 재서 '아동복' 이 맞는지 확인."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
out = {}
try:
    import numpy as np
    from pxr import Usd, UsdGeom, Gf
    sys.path.insert(0, HERE)
    import lehome_scene as LS
    stage = Usd.Stage.Open(LS.SCENE_USD)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"], useExtentsHint=True)
    for p in Usd.PrimRange(stage.GetPseudoRoot()):
        n = p.GetPath().pathString
        if "Table" in n and p.IsA(UsdGeom.Xformable):
            b = cache.ComputeWorldBound(p).ComputeAlignedRange()
            if b.IsEmpty(): continue
            mn, mx = b.GetMin(), b.GetMax()
            size = [round((mx[i] - mn[i]) * 100, 1) for i in range(3)]
            if max(size) > 10:
                out[n] = {"size_cm": size,
                          "top_z_cm": round(float(mx[2]) * 100, 1)}
    # 로봇 팔 길이 (베이스 -> 그리퍼 끝, 홈 자세 기준 대신 링크 바운딩으로)
    rs = Usd.Stage.Open(LS.ROBOT_USD)
    rc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"], useExtentsHint=True)
    rb = rc.ComputeWorldBound(rs.GetPseudoRoot()).ComputeAlignedRange()
    if not rb.IsEmpty():
        mn, mx = rb.GetMin(), rb.GetMax()
        out["ROBOT_extent_cm"] = [round((mx[i] - mn[i]) * 100, 1) for i in range(3)]
except Exception:
    import traceback; out["error"] = traceback.format_exc()[-800:]
print("SCENE " + json.dumps(out, ensure_ascii=False))
json.dump(out, open(os.path.join(HERE, "scene_scale.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
app.close()
