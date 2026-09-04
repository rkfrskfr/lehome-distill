"""LeHome 무대 조립 공용 모듈 — 10_scene.py 에서 검증된 레시피 (STAGE10 GO).

build_scene(world) 하나로 방+로봇2+옷을 세우고, 팔은 홈 자세, 옷은 정착 상태로 만든다.
검증된 함정 회피가 전부 들어 있다:
  - 행렬 xformOp 배치 (XformCommonAPI 는 이 USD 에서 조용히 실패)
  - 도 단위 드라이브 게인 (라디안 그대로 쓰면 57배 폭발)
  - 고정 베이스 표준 패턴 (컨테이너 루트API + 계층 내 FixedJoint)
  - 중복점 없는 옷 선택 + reset 후 뷰 주입 + 원점 피벗
  - 팔 홈 순간이동 (스윙이 옷을 쓸어버림)
"""

import glob as _glob
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "Assets")
ROBOT_USD = os.path.join(ASSETS, "robots", "lerobot", "so101_follower_good.usd")
SCENE_USD = os.path.join(ASSETS, "scenes", "marble", "Scene_00_Apartment.usd")

import os as _os

# 공식값은 z=0.5 (테이블 상판 0.521 보다 2.1cm 아래 = 베이스가 상판에 살짝 잠김).
# 초기엔 "파묻힌다"고 보고 0.522 로 올렸으나, 그 판단은 드라이브 단위·고정베이스
# 버그를 잡기 전 것이었다. 로봇을 올리면 정책이 학습한 관절각으로 천에 못 닿는다.
ROBOT_Z = float(_os.environ.get("LEHOME_ROBOT_Z", "0.5"))
LEFT_POS = (-0.23, -0.25, ROBOT_Z)
RIGHT_POS = (0.23, -0.25, ROBOT_Z)
INIT_PAN = 1.1363
HOME = [-1.2363, -1.7135, 1.4979, 1.0534, -0.085, -0.01176]

_DEG = 57.29577951308232
DRIVE_STIFFNESS = 17.8 / _DEG
DRIVE_DAMPING = 0.60 / _DEG
DRIVE_MAX_FORCE = 10.0


def home_q(name):
    sign = -1.0 if name == "Left_Robot" else 1.0
    q = np.array(HOME, dtype=np.float32)
    q[0] = sign * abs(HOME[0])
    return q


def list_garments(garment_type="Top_Long", kind="Seen"):
    """해당 종류의 옷 폴더 전체 (쿠킹 기준 배치라 중복점 제약 없음)."""
    root = os.path.join(ASSETS, "objects", "Challenge_Garment", "Release", garment_type)
    return sorted(_glob.glob(os.path.join(root, f"{garment_type}_{kind}_*")))


def pick_garment(garment_type="Top_Long", say=print):
    cands = list_garments(garment_type)
    if not cands:
        raise RuntimeError(f"{garment_type}: 옷 없음")
    say(f"[scene] 옷 선택: {os.path.basename(cands[0])}")
    return cands[0]


def build_scene(world, say=print, garment_type="Top_Long", settle_steps=240,
                bind_garment_material=True):
    """무대를 세우고 정착시킨다. dict 반환: robots, cloth, view, mesh_prim, gcfg."""
    import torch
    from pxr import Usd, UsdGeom, UsdPhysics, UsdLux, UsdShade, Gf, PhysxSchema
    from isaacsim.core.api.materials import ParticleMaterial
    from isaacsim.core.api.robots import Robot
    from isaacsim.core.prims import SingleClothPrim, SingleParticleSystem
    from isaacsim.core.utils.stage import add_reference_to_stage, get_current_stage
    from isaacsim.core.utils.types import ArticulationAction

    pc = world.get_physics_context()
    pc.enable_gpu_dynamics(True)
    pc.set_broadphase_type("GPU")
    stage = get_current_stage()

    # 공식(Isaac Lab) 씬 파라미터 일치 패치 — 특히 GPU aggregate 페어 버퍼가
    # 기본값(1024)으로는 공식의 1/32768 이라 접촉이 조용히 누락될 수 있다.
    try:
        scene_prim = stage.GetPrimAtPath(pc.prim_path)
        if not scene_prim.IsValid():
            scene_prim = stage.GetPrimAtPath("/physicsScene")
        psapi = PhysxSchema.PhysxSceneAPI.Apply(scene_prim)
        psapi.CreateBounceThresholdAttr(0.5)
        psapi.CreateEnableSceneQuerySupportAttr(False)
        psapi.CreateGpuMaxRigidContactCountAttr(2**23)
        psapi.CreateGpuMaxRigidPatchCountAttr(5 * 2**15)
        psapi.CreateGpuFoundLostPairsCapacityAttr(2**21)
        psapi.CreateGpuFoundLostAggregatePairsCapacityAttr(2**25)
        psapi.CreateGpuTotalAggregatePairsCapacityAttr(2**21)
        say("[scene] PhysX 씬 버퍼 공식 일치 패치 적용")
    except Exception as e:
        say(f"[scene] 씬 패치 실패(계속): {e!r}")

    # 방 (테이블 충돌은 USD 내장 — 추가 금지)
    add_reference_to_stage(SCENE_USD, "/World/Scene")
    dome = UsdLux.DomeLight.Define(stage, "/World/Light")
    dome.CreateIntensityAttr(1200.0)
    dome.CreateColorAttr(Gf.Vec3f(0.75, 0.75, 0.75))

    # 로봇 2대
    robots = {}
    for name, pos in (("Left_Robot", LEFT_POS), ("Right_Robot", RIGHT_POS)):
        path = f"/World/Robot/{name}"
        add_reference_to_stage(ROBOT_USD, path)
        xformable = UsdGeom.Xformable(stage.GetPrimAtPath(path))
        xformable.ClearXformOpOrder()
        mat = (Gf.Matrix4d().SetRotate(Gf.Rotation(Gf.Vec3d(0, 0, 1), 180.0))
               * Gf.Matrix4d().SetTranslate(Gf.Vec3d(*pos)))
        xformable.AddTransformOp().Set(mat)

        art_path = None
        for p in Usd.PrimRange(stage.GetPrimAtPath(path)):
            if p.HasAPI(UsdPhysics.ArticulationRootAPI):
                art_path = str(p.GetPath())
                break
        for p in Usd.PrimRange(stage.GetPrimAtPath(path)):
            if p.IsA(UsdPhysics.RevoluteJoint):
                d = (UsdPhysics.DriveAPI(p, "angular")
                     if p.HasAPI(UsdPhysics.DriveAPI, "angular")
                     else UsdPhysics.DriveAPI.Apply(p, "angular"))
                d.CreateStiffnessAttr().Set(DRIVE_STIFFNESS)
                d.CreateDampingAttr().Set(DRIVE_DAMPING)
                d.CreateMaxForceAttr().Set(DRIVE_MAX_FORCE)
            if p.HasAPI(UsdPhysics.RigidBodyAPI):
                rb = PhysxSchema.PhysxRigidBodyAPI.Apply(p)
                rb.CreateDisableGravityAttr().Set(True)
                rb.CreateMaxDepenetrationVelocityAttr().Set(1.0)

        base_prim = stage.GetPrimAtPath(art_path)
        base_prim.RemoveAPI(UsdPhysics.ArticulationRootAPI)
        cont = stage.GetPrimAtPath(path)
        UsdPhysics.ArticulationRootAPI.Apply(cont)
        pa = PhysxSchema.PhysxArticulationAPI.Apply(cont)
        pa.CreateSolverPositionIterationCountAttr().Set(16)
        pa.CreateSolverVelocityIterationCountAttr().Set(16)
        fj = UsdPhysics.FixedJoint.Define(stage, f"{path}/root_fix")
        fj.CreateBody1Rel().SetTargets([art_path])
        fj.CreateLocalPos0Attr().Set(Gf.Vec3f(pos[0], pos[1], pos[2]))
        fj.CreateLocalRot0Attr().Set(Gf.Quatf(0.0, 0.0, 0.0, 1.0))
        fj.CreateLocalPos1Attr().Set(Gf.Vec3f(0.0, 0.0, 0.0))
        fj.CreateLocalRot1Attr().Set(Gf.Quatf(1.0, 0.0, 0.0, 0.0))
        robots[name] = Robot(prim_path=path, name=name)

    # 옷
    gdir = pick_garment(garment_type, say)
    garment_usd = _glob.glob(os.path.join(gdir, "*_obj_exp.usd"))[0]
    gcfg = json.load(open(_glob.glob(os.path.join(gdir, "*_obj_exp.json"))[0],
                          encoding="utf-8"))
    g_scale = float(gcfg["scale"][0])
    pr = gcfg["initial_pos_range"]
    g_pos = np.array([(pr[0] + pr[3]) / 2, (pr[1] + pr[4]) / 2, (pr[2] + pr[5]) / 2],
                     dtype=np.float32)
    add_reference_to_stage(garment_usd, "/World/garment")
    mesh_prim = next(p for p in Usd.PrimRange(stage.GetPrimAtPath("/World/garment"))
                     if p.IsA(UsdGeom.Mesh))
    raw = np.array(UsdGeom.Mesh(mesh_prim).GetPointsAttr().Get(), dtype=np.float32)
    say(f"  메시 점 {raw.shape[0]} (쿠킹 시 중복점이 용접되면 입자 수가 줄 수 있음)")

    ps = SingleParticleSystem(
        prim_path="/World/particleSystem", name="ps",
        enable_ccd=True, contact_offset=0.008, rest_offset=0.004,
        particle_contact_offset=0.005, fluid_rest_offset=0.0025,
        solid_rest_offset=0.0025, max_velocity=5.0,
        solver_position_iteration_count=32,
        global_self_collision_enabled=True,
        non_particle_collision_enabled=True,
    )
    pmat = ParticleMaterial(
        prim_path="/World/particleMaterial", name="pmat",
        friction=0.5, damping=0.05, adhesion=0.1, adhesion_offset_scale=0.0,
        cohesion=0.0, particle_adhesion_scale=0.2, particle_friction_scale=0.6,
        drag=0.0, lift=0.0, gravity_scale=2.0,
    )
    cloth = SingleClothPrim(
        prim_path=str(mesh_prim.GetPath()), particle_system=ps,
        particle_material=pmat, name="garment_cloth", particle_mass=1e-2,
        stretch_stiffness=1e8, bend_stiffness=5000.0, shear_stiffness=5000.0,
        spring_damping=10.0, self_collision=True, self_collision_filter=True,
        scale=np.array([g_scale] * 3, dtype=np.float32),
    )

    # 옷 시각 재질 (정책이 RGB 를 보므로 텍스처 충실도가 중요)
    if bind_garment_material and gcfg.get("visual_usd_paths"):
        try:
            vis = gcfg["visual_usd_paths"][0]
            vis_path = os.path.join(HERE, vis.lstrip("/").replace("/", os.sep))
            add_reference_to_stage(vis_path, "/World/garmentMat")
            mat_prim = next((p for p in Usd.PrimRange(
                stage.GetPrimAtPath("/World/garmentMat"))
                if p.IsA(UsdShade.Material)), None)
            if mat_prim is not None:
                UsdShade.MaterialBindingAPI.Apply(mesh_prim).Bind(
                    UsdShade.Material(mat_prim))
                say(f"[scene] 옷 재질 바인딩: {os.path.basename(vis_path)}")
            else:
                say("[scene] 경고: 재질 USD 안에 Material 없음")
        except Exception as e:
            say(f"[scene] 재질 바인딩 실패(계속): {e!r}")

    if _os.environ.get("LEHOME_GRIPPER_FRICTION") == "1":
        set_gripper_friction(stage, say)

    for r in robots.values():
        world.scene.add(r)
    world.scene.add(cloth)
    world.reset()

    # **쿠킹된 입자 좌표를 기준으로 삼는다.** 메시 점 순서를 흉내내지 않으므로
    # 중복점 용접 여부와 무관하게 모든 옷에 통하고, check_point 인덱스도 공식과
    # 같은 '쿠킹 순서'를 가리켜 의미가 정확해진다. (이전엔 용접 순서를 추측하느라
    # 중복 없는 옷 3벌만 쓸 수 있었다.)
    import torch
    view = cloth._cloth_prim_view
    cooked = view.get_world_positions().cpu().numpy().reshape(-1, 3).astype(np.float32)
    say(f"  쿠킹 입자 {cooked.shape[0]}개 (메시 점 대비 {cooked.shape[0]-raw.shape[0]:+d})")
    # 쿠킹 좌표는 메시 원점 기준(= raw*scale). 목표 위치만 더하면 배치 완료.
    rest = cooked
    baked = rest + np.asarray(g_pos, dtype=np.float32)
    t = torch.tensor(baked[None], device="cuda:0", dtype=torch.float32)
    view.set_world_positions(t)
    view.set_velocities(torch.zeros_like(t))

    # 팔 홈 순간이동 + 정착
    for name, r in robots.items():
        n_dof = len(list(r.dof_names))
        r.set_joint_positions(torch.tensor(home_q(name), device="cuda:0"))
        r.set_joint_velocities(torch.zeros(n_dof, device="cuda:0"))
    for _ in range(settle_steps):
        for name, r in robots.items():
            r.apply_action(ArticulationAction(joint_positions=torch.tensor(
                home_q(name), device="cuda:0")))
        world.step(render=False)

    p = view.get_world_positions().cpu().numpy().reshape(-1, 3)
    say(f"[scene] 정착: 옷 z_mean={p[:, 2].mean():.3f} "
        f"span=({p[:, 0].max()-p[:, 0].min():.3f},{p[:, 1].max()-p[:, 1].min():.3f})")
    check_idx = map_check_points(gcfg, raw, rest, say=say)
    return {"robots": robots, "cloth": cloth, "view": view,
            "mesh_prim": mesh_prim, "gcfg": gcfg, "stage": stage,
            "baked": baked, "raw_scaled": rest, "check_idx": check_idx}


_TEX_DIR = os.path.join(ASSETS, "textures", "surface")
_TABLE_TEX_INPUT = None   # None=미탐색, False=탐색 실패, 그 외=UsdShade.Input
_GARMENT_TEX_INPUT = None
_GARMENT_TEX_CANDS = None


def _find_tex_input(root_prim, say=print):
    """프림 서브트리에서 텍스처 입력(diffuse_texture/file)을 가진 셰이더를 찾는다.
    공식 포크 _randomize_table038_texture 와 동일한 입력 이름 규약."""
    from pxr import Usd, UsdShade
    for p in Usd.PrimRange(root_prim):
        if p.IsA(UsdShade.Shader):
            s = UsdShade.Shader(p)
            tex_in = s.GetInput("diffuse_texture") or s.GetInput("file")
            if tex_in:
                return tex_in
    return None


def randomize_table_texture(stage, rng, say=print):
    """테이블(Table038) 텍스처를 Assets/textures/surface/{1..100}.png 중
    하나로 교체 (공식 포크 visual_augmentation 이식). 에피소드마다 호출."""
    from pxr import Usd, UsdGeom, UsdShade, Sdf
    global _TABLE_TEX_INPUT
    if _TABLE_TEX_INPUT is None:
        mesh = None
        for p in Usd.PrimRange(stage.GetPrimAtPath("/World/Scene")):
            if "Table038" in p.GetName() and p.IsA(UsdGeom.Mesh):
                mesh = p
                break
        mat = (UsdShade.MaterialBindingAPI(mesh).ComputeBoundMaterial()[0]
               if mesh is not None else None)
        tex_in = _find_tex_input(mat.GetPrim(), say) if mat else None
        if tex_in is None:
            say("[tex] Table038 텍스처 셰이더 탐색 실패 — 테이블 랜덤화 건너뜀")
            _TABLE_TEX_INPUT = False
        else:
            say(f"[tex] Table038 셰이더: {tex_in.GetAttr().GetPath()}")
            _TABLE_TEX_INPUT = tex_in
    if _TABLE_TEX_INPUT is False:
        return
    idx = int(rng.randint(1, 101))
    _TABLE_TEX_INPUT.Set(Sdf.AssetPath(os.path.join(_TEX_DIR, f"{idx}.png")))
    say(f"[reset] 테이블 텍스처: {idx}.png")


def randomize_garment_texture(stage, rng, say=print):
    """옷 재질의 BaseColor 를 Release/Color_Texture/*/BaseColor.jpg 중 하나로
    교체. 교사(π0.5)의 옷 분류가 흔들릴 수 있으므로 기본은 꺼져 있고
    LEHOME_RAND_GARMENT_TEX=1 일 때만 쓴다."""
    from pxr import Sdf
    global _GARMENT_TEX_INPUT, _GARMENT_TEX_CANDS
    if _GARMENT_TEX_INPUT is None:
        root = stage.GetPrimAtPath("/World/garmentMat")
        tex_in = _find_tex_input(root, say) if root.IsValid() else None
        if tex_in is None:
            say("[tex] 옷 텍스처 셰이더 탐색 실패 — 옷 랜덤화 건너뜀")
            _GARMENT_TEX_INPUT = False
        else:
            say(f"[tex] 옷 셰이더: {tex_in.GetAttr().GetPath()}")
            _GARMENT_TEX_INPUT = tex_in
        _GARMENT_TEX_CANDS = sorted(_glob.glob(os.path.join(
            ASSETS, "objects", "Challenge_Garment", "Release",
            "Color_Texture", "*", "BaseColor.jpg")))
        say(f"[tex] 옷 텍스처 후보 {len(_GARMENT_TEX_CANDS)}개")
    if _GARMENT_TEX_INPUT is False or not _GARMENT_TEX_CANDS:
        return
    pick = _GARMENT_TEX_CANDS[int(rng.randint(0, len(_GARMENT_TEX_CANDS)))]
    _GARMENT_TEX_INPUT.Set(Sdf.AssetPath(pick))
    say(f"[reset] 옷 텍스처: {os.path.basename(os.path.dirname(pick))}")


def _euler_deg_to_R(e):
    """xyz 오일러(도) -> 회전행렬 (LeHome euler_angles_to_quat 규약과 동일 순서)."""
    import numpy as np
    rx, ry, rz = np.radians(e)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return (Rz @ Ry @ Rx).astype(np.float32)


def reset_episode(world, scene, rng, settle_steps=180, render=False, say=print,
                  mode="soft"):
    """에피소드 리셋.

    mode="initial": initial_pos/rot_range 사용 (공식 GPU 경로의 실효 동작).
        공식 reset() 은 set_world_pose 로 랜덤화를 시도하지만 쿠킹된 입자에는
        반영되지 않으므로, 실제로는 매 판 같은 초기 자세에서 시작한다.
    mode="soft": soft_reset_pos/rot_range 에서 균등 샘플 (±20도 기울임 포함).
        공식 의도대로라면 이쪽이지만 GPU 에서는 실제로 적용되지 않는다.
    """
    import numpy as np
    import torch
    from isaacsim.core.utils.types import ArticulationAction

    g = scene["gcfg"]
    if mode == "initial":
        pr, rr = g["initial_pos_range"], g["initial_rot_range"]
    else:
        pr = g.get("soft_reset_pos_range", g["initial_pos_range"])
        rr = g.get("soft_reset_rot_range", g["initial_rot_range"])
    pos = np.array([rng.uniform(pr[i], pr[i + 3]) for i in range(3)], dtype=np.float32)
    eul = np.array([rng.uniform(rr[i], rr[i + 3]) for i in range(3)], dtype=np.float32)
    # 낙하 높이 조절: 공식 z=0.63 은 상판(0.521) 위 11cm 에서 떨어뜨려 옷이 구겨진다.
    # 낮추면 더 평평하게 안착해 랜드마크 간 거리가 커진다 (일부 옷은 평평한
    # 상태에서도 '벌어짐' 조건이 미달이라 이게 성패를 가든다).
    # LEHOME_DROP_Z_RANGE="0.545,0.63" 이면 판마다 균등 샘플 (수집 다양화용),
    # 아니면 LEHOME_DROP_Z 고정값.
    _dzr = _os.environ.get("LEHOME_DROP_Z_RANGE")
    _dz = _os.environ.get("LEHOME_DROP_Z")
    if _dzr:
        _lo, _hi = (float(x) for x in _dzr.split(","))
        pos[2] = float(rng.uniform(_lo, _hi))
    elif _dz:
        pos[2] = float(_dz)

    # 조명 랜덤화 (LEHOME_RAND_LIGHT=1): 공식 포크 visual_augmentation 의
    # 범위(강도 800~2000, 색 온도 변화)를 따른다. 에피소드마다 1회.
    if _os.environ.get("LEHOME_RAND_LIGHT") == "1":
        from pxr import UsdLux as _UL, Gf as _Gf
        from isaacsim.core.utils.stage import get_current_stage as _gcs
        _dome = _UL.DomeLight(_gcs().GetPrimAtPath("/World/Light"))
        _inten = float(rng.uniform(800.0, 2000.0))
        _col = 0.6 + 0.4 * rng.uniform(size=3)
        _dome.GetIntensityAttr().Set(_inten)
        _dome.GetColorAttr().Set(_Gf.Vec3f(float(_col[0]), float(_col[1]),
                                           float(_col[2])))
        say(f"[reset] 조명 랜덤: 강도 {_inten:.0f}, 색 {np.round(_col, 2).tolist()}")

    # 돔라이트 회전 + 옷 재질 거칠기 (둘 다 물리 무관, 렌더만)
    if _os.environ.get("LEHOME_RAND_LIGHT") == "1":
        from isaacsim.core.utils.stage import get_current_stage as _gcs_d
        randomize_dome_rotation(_gcs_d(), rng, say)
        jitter_garment_material(_gcs_d(), rng, say)

    # 텍스처 랜덤화 (에피소드마다 1회)
    if _os.environ.get("LEHOME_RAND_TABLE_TEX") == "1":
        from isaacsim.core.utils.stage import get_current_stage as _gcs_t
        randomize_table_texture(_gcs_t(), rng, say)
    if _os.environ.get("LEHOME_RAND_GARMENT_TEX") == "1":
        from isaacsim.core.utils.stage import get_current_stage as _gcs_g
        randomize_garment_texture(_gcs_g(), rng, say)

    pts = scene["raw_scaled"] @ _euler_deg_to_R(eul).T + pos
    pts = pts.astype(np.float32)

    view = scene["view"]
    t = torch.tensor(pts[None], device="cuda:0", dtype=torch.float32)
    view.set_world_positions(t)
    view.set_velocities(torch.zeros_like(t))

    for name, r in scene["robots"].items():
        n_dof = len(list(r.dof_names))
        r.set_joint_positions(torch.tensor(home_q(name), device="cuda:0"))
        r.set_joint_velocities(torch.zeros(n_dof, device="cuda:0"))
    for _ in range(settle_steps):
        for name, r in scene["robots"].items():
            r.apply_action(ArticulationAction(joint_positions=torch.tensor(
                home_q(name), device="cuda:0")))
        world.step(render=render)

    # ⚠ 카메라 annotator 갱신 필수. 렌더 없이 리셋하면 첫 관측이 '이전 판의
    # 마지막 화면(접힌 옷)'이 되어 정책이 옷 종류를 오분류한다 (실측: 0/8 pant_long).
    for _ in range(12):
        world.step(render=True)

    p = view.get_world_positions().cpu().numpy().reshape(-1, 3)
    say(f"[reset] pos={np.round(pos, 3).tolist()} rot={np.round(eul, 1).tolist()} "
        f"-> z_mean={p[:, 2].mean():.3f} "
        f"span=({p[:, 0].max()-p[:, 0].min():.3f},{p[:, 1].max()-p[:, 1].min():.3f})")
    return 0.44 < p[:, 2].mean() < 0.60


CAMS = {
    "observation.images.top_rgb": {
        "prim": "/World/Robot/Right_Robot/base/top_camera",
        "pos": (0.245, -0.44, 0.56),
        "rot_wxyz": (0.1650476, -0.9862856, 0.0, 0.0),
        "focal": 28.7, "aperture": 38.11,
    },
    "observation.images.left_rgb": {
        "prim": "/World/Robot/Left_Robot/gripper/left_wrist_camera",
        "pos": (-0.001, 0.1, -0.04),
        "rot_wxyz": (-0.404379, -0.912179, -0.0451242, 0.0486914),
        "focal": 36.5, "aperture": 36.83,
    },
    "observation.images.right_rgb": {
        "prim": "/World/Robot/Right_Robot/gripper/right_wrist_camera",
        "pos": (-0.001, 0.1, -0.04),
        "rot_wxyz": (-0.404379, -0.912179, -0.0451242, 0.0486914),
        "focal": 36.5, "aperture": 36.83,
    },
}


def add_cameras(stage, say=print):
    """공식 카메라 3대 (11단 검증 레시피). {키: Camera} 반환."""
    import numpy as np
    from pxr import UsdGeom
    from isaacsim.sensors.camera import Camera

    cams = {}
    for key, c in CAMS.items():
        cam = Camera(prim_path=c["prim"], resolution=(640, 480))
        cam.initialize()
        cam.set_local_pose(np.array(c["pos"], dtype=np.float32),
                           np.array(c["rot_wxyz"], dtype=np.float32),
                           camera_axes="ros")
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath(c["prim"]))
        usd_cam.CreateFocalLengthAttr().Set(c["focal"])
        usd_cam.CreateHorizontalApertureAttr().Set(c["aperture"])
        usd_cam.CreateClippingRangeAttr().Set((0.01, 50.0))
        usd_cam.CreateFStopAttr().Set(0.0)
        cams[key] = cam
        say(f"[cam] {key} OK")
    return cams


def map_check_points(gcfg, raw, rest, say=print):
    """check_point 인덱스(메시 순서)를 쿠킹된 입자 인덱스로 변환.

    쿠커가 중복점을 용접하면 입자 인덱스가 밀린다. 공식 JSON 의 인덱스는
    **메시 순서**를 가리킨다 (실측: Seen_4 를 쿠킹순서로 읽으면 p0/p1 이 같은
    어깨에 겹쳐 d(0,1)=0.5cm 로 통과 불가, 메시순서면 좌/우 어깨 16.7cm 로 정상).
    """
    import numpy as np
    scale = float(gcfg["scale"][0])
    scaled = raw * scale
    mapped = []
    for mi in gcfg["check_point"]:
        mi = int(mi)
        if mi >= scaled.shape[0]:
            raise RuntimeError(f"check_point {mi} 가 메시 점 수 초과")
        j = int(np.argmin(np.linalg.norm(rest - scaled[mi], axis=1)))
        mapped.append(j)
    if raw.shape[0] != rest.shape[0]:
        say(f"[scene] check_point 재매핑(용접 {raw.shape[0]-rest.shape[0]}): "
            f"{list(gcfg['check_point'])} -> {mapped}")
    return mapped


def check_success_top(view, gcfg, say=print, idx=None):
    """상의 접기 성공 판정 (success_checker_garment_fold 이식, cm 단위)."""
    import numpy as np
    idx = list(idx) if idx is not None else list(gcfg["check_point"])
    thr = [t * float(gcfg["scale"][0]) for t in gcfg["success_distance"]]
    p = view.get_world_positions().cpu().numpy().reshape(-1, 3)[idx] * 100.0

    def d(a, b):
        return float(np.linalg.norm(p[a] - p[b]))

    conds = [d(0, 4) <= thr[0], d(2, 3) <= thr[1], d(1, 5) <= thr[2],
             d(0, 1) >= thr[3], d(4, 5) >= thr[4]]
    dists = [d(0, 4), d(2, 3), d(1, 5), d(0, 1), d(4, 5)]
    say(f"[success] d={[round(x, 1) for x in dists]} thr={[round(t, 1) for t in thr]} "
        f"conds={conds}")
    return all(conds)


def reinject_garment(world, scene, settle_steps=60, render=True, say=print):
    """카메라 초기화 등이 입자 상태를 원시 좌표로 되돌리는 경우가 있어(11단 실측),
    구운 좌표를 다시 주입하고 짧게 재정착시킨다. 팔은 홈 유지."""
    import torch
    from isaacsim.core.utils.types import ArticulationAction
    view = scene["view"]
    baked = scene["baked"]
    t = torch.tensor(baked[None], device="cuda:0", dtype=torch.float32)
    view.set_world_positions(t)
    view.set_velocities(torch.zeros_like(t))
    for _ in range(settle_steps):
        for name, r in scene["robots"].items():
            r.apply_action(ArticulationAction(joint_positions=torch.tensor(
                home_q(name), device="cuda:0")))
        world.step(render=render)
    import numpy as _np
    p = view.get_world_positions().cpu().numpy().reshape(-1, 3)
    say(f"[scene] 재주입 후: z_mean={p[:, 2].mean():.3f} "
        f"중심=({p[:, 0].mean():+.3f},{p[:, 1].mean():+.3f})")
    return 0.44 < p[:, 2].mean() < 0.60

def _quat_mul(a, b):
    """wxyz 쿼터니언 곱."""
    import numpy as np
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2], dtype=np.float32)


def jitter_cameras(cams, stage, rng, say=print, pos_m=0.005, rot_deg=1.0,
                   focal_pct=0.03):
    """카메라 포즈·초점 지터 (논문 §3.3 episode-level augmentation).

    실물 리그의 캘리브 오차를 모사하고, 렌더 세부에 대한 과적합(논문 §9.1: 리사이즈
    경로만 바꿔도 성능이 떨어지고 보조헤드가 두 이미지를 완벽 구분)을 억제한다.
    ⚠ 교사는 공식 카메라 포즈로 학습됐으므로 신선 수집에서는 **약하게**,
    성공 리플레이(성공만 보관)에서는 세게 걸어도 된다.
    """
    import numpy as np
    from pxr import UsdGeom
    for key, cam in cams.items():
        c = CAMS[key]
        pos = np.array(c["pos"], dtype=np.float32) + rng.uniform(
            -pos_m, pos_m, size=3).astype(np.float32)
        ang = np.radians(rng.uniform(-rot_deg, rot_deg, size=3)) * 0.5
        dq = np.array([1.0, ang[0], ang[1], ang[2]], dtype=np.float32)
        dq /= np.linalg.norm(dq)
        q = _quat_mul(np.array(c["rot_wxyz"], dtype=np.float32), dq)
        q /= np.linalg.norm(q)
        cam.set_local_pose(pos, q, camera_axes="ros")
        usd_cam = UsdGeom.Camera(stage.GetPrimAtPath(c["prim"]))
        usd_cam.GetFocalLengthAttr().Set(
            float(c["focal"] * (1.0 + rng.uniform(-focal_pct, focal_pct))))
    say(f"[aug] 카메라 지터 (±{pos_m*1000:.0f}mm, ±{rot_deg}deg, ±{focal_pct*100:.0f}% 초점)")


def perstep_light(stage, rng, base=None):
    """스텝 단위 조명 흔들기 (논문 §3.3 per-step scope). 몇 프레임마다 호출.
    에피소드 단위 랜덤화만으로는 '이 판은 이런 색' 이라는 고정 신호가 남는다."""
    from pxr import UsdLux, Gf
    dome = UsdLux.DomeLight(stage.GetPrimAtPath("/World/Light"))
    cur = dome.GetIntensityAttr().Get() or 1200.0
    dome.GetIntensityAttr().Set(float(cur * (1.0 + rng.uniform(-0.08, 0.08))))
    c = dome.GetColorAttr().Get() or Gf.Vec3f(0.75, 0.75, 0.75)
    j = rng.uniform(-0.03, 0.03, size=3)
    dome.GetColorAttr().Set(Gf.Vec3f(
        float(min(1.2, max(0.3, c[0] + j[0]))),
        float(min(1.2, max(0.3, c[1] + j[1]))),
        float(min(1.2, max(0.3, c[2] + j[2])))))

def set_gripper_friction(stage, say=print, static=1.2, dynamic=1.0):
    """그리퍼 링크에 물리재질 부여 (기본 PhysX 0.5 → 실물 고무 패드 수준).

    공식 로봇 USD 에는 물리재질이 없어 전 링크가 기본 마찰 0.5 다. 실물 SO-101 의
    집게에는 마찰이 큰 패드가 있으므로 천 파지에는 이쪽이 현실적이다.
    ⚠ 공식 설정 이탈이므로 대외 수치는 기본값 기준으로 보고할 것
    (LEHOME_GRIPPER_FRICTION=1 일 때만 적용).
    """
    from pxr import Usd, UsdShade, UsdPhysics, PhysxSchema
    mat_path = "/World/gripperMaterial"
    mat = UsdShade.Material.Define(stage, mat_path)
    pm = UsdPhysics.MaterialAPI.Apply(mat.GetPrim())
    pm.CreateStaticFrictionAttr().Set(static)
    pm.CreateDynamicFrictionAttr().Set(dynamic)
    pm.CreateRestitutionAttr().Set(0.0)
    n = 0
    for robot in ("Left_Robot", "Right_Robot"):
        root = stage.GetPrimAtPath(f"/World/Robot/{robot}")
        if not root.IsValid():
            continue
        for prim in Usd.PrimRange(root):
            name = prim.GetName().lower()
            if ("gripper" in name or "jaw" in name or "finger" in name) and                     prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdShade.MaterialBindingAPI.Apply(prim).Bind(
                    mat, materialPurpose="physics")
                n += 1
    say(f"[scene] 그리퍼 마찰 재질 적용: {n}개 콜라이더 (static={static})")
    return n


def randomize_dome_rotation(stage, rng, say=print):
    """돔라이트 회전 (논문 §3.3 episode-level). 그림자·하이라이트 방향이 바뀐다."""
    from pxr import UsdGeom, Gf
    prim = stage.GetPrimAtPath("/World/Light")
    if not prim.IsValid():
        return
    x = UsdGeom.Xformable(prim)
    x.ClearXformOpOrder()
    x.AddRotateYOp().Set(float(rng.uniform(0.0, 360.0)))


def jitter_garment_material(stage, rng, say=print):
    """옷 재질 거칠기/금속성 흔들기 (논문 §3.3: roughness perturbation).
    물리에는 영향 없고 렌더만 바뀌므로 리플레이에서도 안전하다."""
    from pxr import Usd, UsdShade
    root = stage.GetPrimAtPath("/World/garmentMat")
    if not root.IsValid():
        return
    for prim in Usd.PrimRange(root):
        if prim.IsA(UsdShade.Shader):
            sh = UsdShade.Shader(prim)
            for name, lo, hi in (("reflection_roughness_constant", 0.3, 0.9),
                                 ("metallic_constant", 0.0, 0.15)):
                inp = sh.GetInput(name)
                if inp:
                    inp.Set(float(rng.uniform(lo, hi)))
