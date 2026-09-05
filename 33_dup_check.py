"""33단: 용접 규칙 검증 — 메시의 중복 점 수가 쿠킹으로 사라진 점 수와 같은가.
같다면 '첫 등장만 유지' 규칙으로 인덱스 대응을 정확히 복원할 수 있다 (시뮬 불필요)."""
import json, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from isaacsim import SimulationApp
app = SimulationApp({"headless": True})
import numpy as np
from pxr import Usd, UsdGeom
HERE = os.path.dirname(os.path.abspath(__file__))
root = os.path.join(HERE, "Assets", "objects", "Challenge_Garment", "Release", "Top_Long")
known = {"Top_Long_Seen_0": 202, "Top_Long_Seen_2": 117, "Top_Long_Seen_4": 32,
         "Top_Long_Seen_8": 0, "Top_Long_Seen_1": 0}
out = {}
for g in sorted(os.listdir(root)):
    d = os.path.join(root, g)
    if not os.path.isdir(d): continue
    usd = [os.path.join(r, f) for r, _, fs in os.walk(d) for f in fs if f.endswith((".usd", ".usda", ".usdc"))]
    if not usd: continue
    stage = Usd.Stage.Open(usd[0])
    mesh = next((p for p in stage.Traverse() if p.IsA(UsdGeom.Mesh)), None)
    pts = np.array(UsdGeom.Mesh(mesh).GetPointsAttr().Get(), dtype=np.float64)
    # 정확히 같은 좌표(첫 등장 유지) 기준 중복 수 / 1e-6 허용 기준 중복 수
    _, first = np.unique(pts, axis=0, return_index=True)
    dup_exact = pts.shape[0] - first.size
    q = np.round(pts * 1e5).astype(np.int64)
    _, first2 = np.unique(q, axis=0, return_index=True)
    dup_tol = pts.shape[0] - first2.size
    cfg = json.load(open(os.path.join(d, "config.json"), encoding="utf-8")) if os.path.exists(os.path.join(d, "config.json")) else {}
    out[g] = {"n": int(pts.shape[0]), "dup_exact": int(dup_exact), "dup_tol": int(dup_tol),
              "welded_known": known.get(g)}
    print(g, out[g])
json.dump(out, open(os.path.join(HERE, "dup_check.json"), "w"), indent=1)
app.close()
