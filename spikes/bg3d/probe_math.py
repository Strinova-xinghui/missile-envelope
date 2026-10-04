# -*- coding: utf-8 -*-
"""临时探针：marching tetrahedra 的解析真值 + 三轴解耦。跑完可删。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from missile_sim import bg, bg3d, pool, grid as grid_mod      # noqa: E402
from missile_sim.spec import PlaneGrid                        # noqa: E402

print("== 1) 表结构 ==")
print("mask 1  ->", bg3d._TET_TRIS[1], " mask 14 ->", bg3d._TET_TRIS[14])
print("mask 3  ->", bg3d._TET_TRIS[3], " mask 12 ->", bg3d._TET_TRIS[12])
assert len(bg3d._TET_TRIS[1]) == 1 and len(bg3d._TET_TRIS[14]) == 1
assert len(bg3d._TET_TRIS[3]) == 2 and len(bg3d._TET_TRIS[12]) == 2
for m in range(16):
    # 内侧角数 = popcount：1 个或 3 个 ⇒ 3 条棱被切 ⇒ 1 个三角形；2 个 ⇒ 4 条棱 ⇒ 2 个
    pop = bin(m).count("1")
    want = 0 if pop in (0, 4) else (2 if pop == 2 else 1)
    assert len(bg3d._TET_TRIS[m]) == want, (m, len(bg3d._TET_TRIS[m]), want)
print("   16 种组合的面数都符合 marching tetrahedra 的预期")

print("== 2) 平面场 f = β：等值面必须是 x=const 的矩形，面积 = γ跨度 × ΔV跨度 ==")
g = bg3d.make_grid3([0, 10], [0, 4], [0, 2], beta_step=1, ginv_step=1, dv_step=1)
B, G, D = np.meshgrid(g.beta, g.ginv, g.dv, indexing="ij")
F = B.astype(float)                                   # 只随 β 变
cube = np.transpose(F, (2, 1, 0))                     # (ΔV, γ, β)
surf = bg3d.marching_tetrahedra(cube, [5.5], grid=g, orient=True)
assert len(surf) == 1, surf
s = surf[0]
err = np.abs(s.vertices[:, 0] - 5.5).max()
area = bg3d.surface_area(s.vertices, s.triangles)
print(f"   n_tri={s.n_tri}  max|β-5.5|={err:.3e}  面积={area:.6f}  解析={(4 - 0) * (2 - 0):.6f}")
assert err < 1e-12
assert abs(area - 8.0) < 1e-12

print("== 3) 斜平面 f = β + 2γ + 3ΔV：顶点必须落在面上 ==")
F3 = B + 2.0 * G + 3.0 * D
cube3 = np.transpose(F3, (2, 1, 0))
surf3 = bg3d.marching_tetrahedra(cube3, [12.5, 20.0], grid=g)
for s in surf3:
    val = s.vertices[:, 0] + 2 * s.vertices[:, 1] + 3 * s.vertices[:, 2]
    print(f"   level={s.level}: n_tri={s.n_tri} max|f-level|={np.abs(val - s.level).max():.3e}")
    assert np.abs(val - s.level).max() < 1e-12

print("== 4) 球面 f = -(x²+y²+z²)：闭合性与体积 ==")
B2, G2, D2 = np.meshgrid(np.linspace(-2, 2, 41), np.linspace(-2, 2, 41),
                         np.linspace(-2, 2, 41), indexing="ij")
F4 = -(B2 ** 2 + G2 ** 2 + D2 ** 2)
g4 = bg3d.Bg3Grid(beta=tuple(np.linspace(-2, 2, 41)), ginv=tuple(np.linspace(-2, 2, 41)),
                  dv=tuple(np.linspace(-2, 2, 41)), beta_step=0.1, ginv_step=0.1, dv_step=0.1)
cube4 = np.transpose(F4, (2, 1, 0))
sph = bg3d.marching_tetrahedra(cube4, [-1.0], grid=g4)[0]
vol = bg3d.enclosed_volume(sph.vertices, sph.triangles)
exact_v = 4.0 / 3.0 * np.pi * 1.0 ** 3
r = np.linalg.norm(sph.vertices, axis=1)
print(f"   n_tri={sph.n_tri}  |r-1|max={np.abs(r - 1).max():.3e}  有向体积={vol:.5f}"
      f"  解析={exact_v:.5f}  相对误差={abs(abs(vol) - exact_v) / exact_v:.4%}")
# 朝向约定：法向指向 f 增大的一侧 ⇒ 对 f ≤ level 的区域是"外法向"…这里 f=-(r²)，
# f 增大 = 往里，所以有向体积是负的，|vol| 才是球体积。
assert vol < 0, "朝向约定变了（法向应指向 t_hit 增大侧）"
assert abs(abs(vol) - exact_v) / exact_v < 0.01, "球体积误差过大（蝴蝶结/朝向不稳）"

print("== 5) 空场 / 单层网格 ==")
assert bg3d.marching_tetrahedra(cube, [100.0], grid=g) == []
thin = bg3d.Bg3Grid(beta=(0.0, 1.0), ginv=(0.0, 1.0), dv=(0.0,), beta_step=1.0,
                    ginv_step=1.0, dv_step=1.0)
assert bg3d.marching_tetrahedra(np.zeros((1, 2, 2)), [0.5], grid=thin) == []
try:
    bg3d.make_grid3([0, 1], [0, 1], [5, 5], beta_step=1, ginv_step=1, dv_step=1)
except ValueError as exc:
    print(f"   退化范围被拒：{exc}")
else:
    raise AssertionError("退化范围应该报错")
print("   越界层级、单层网格、退化范围都按预期处理")

print("== 6) 真实弹池：三轴不变量（ΔV 必须只动 thrust_scale）==")
e = pool.standard_entry("PL-12")
p = bg.point_of(e)
m = pool.metrics_of(e)
eff = bg3d.axis_effects(p, m, beta=2600.0, ginv=90.0, dv=1100.0)
for name, row in eff.items():
    print(f"   {name:5s} → thrust×{row['thrust_scale']:.6f}  cx×{row['cx_scale']:.6f}"
          f"  cxaoa×{row['cxaoa_scale']:.6f}  (cx·cxaoa)×{row['cx_scale'] * row['cxaoa_scale']:.6f}")
assert abs(eff["dv"]["thrust_scale"] - 1100.0 / m.dv) < 1e-12
assert abs(eff["dv"]["cx_scale"] - 1.0) < 1e-12 and abs(eff["dv"]["cxaoa_scale"] - 1.0) < 1e-12
assert abs(eff["beta"]["thrust_scale"] - 1.0) < 1e-12
assert abs(eff["beta"]["cx_scale"] * eff["beta"]["cxaoa_scale"] - 1.0) < 1e-12
assert abs(eff["ginv"]["thrust_scale"] - 1.0) < 1e-12
assert abs(eff["ginv"]["cx_scale"] - 1.0) < 1e-12
assert abs(eff["ginv"]["cx_scale"] * eff["ginv"]["cxaoa_scale"] - 90.0 / p.ginv) < 1e-12
print("   三条不变量成立 ✓（ΔV 严格独立；β/γ 的不变量是 cx_scale·cxaoa_scale）")

print("== 7) 合成柱面：口径 2 必须「不是等值面」==")
betas = np.linspace(2500.0, 3000.0, 11)
ginvs = np.linspace(40.0, 100.0, 9)
t2 = np.add.outer((ginvs - 40.0) / 10.0, (betas - 2500.0) / 100.0) + 45.0  # (n_γ, n_β)
cyl = bg3d.extrude_isolines(t2, beta=betas, ginv=ginvs, level=46.0, dv_lo=600.0,
                            dv_hi=1100.0, base_dv=932.57)
print(f"   cylinder n_tri={cyl.n_tri} n_seg={cyl.n_seg} "
      f"面积={bg3d.surface_area(cyl.vertices, cyl.triangles):.3f}  base_dv={cyl.base_dv}")
assert cyl.kind == "cylinder"
zs = np.unique(cyl.vertices[:, 2])
assert set(np.round(zs, 6)) <= {600.0, 1100.0}, zs
try:
    bg3d.extrude_isolines(t2.T, beta=betas, ginv=ginvs, level=46.0, dv_lo=600.0,
                          dv_hi=1100.0, base_dv=932.57)
except ValueError as exc:
    print(f"   转置的层被拒：{str(exc)[:52]}…")
else:
    raise AssertionError("转置的二维层应该报错")
print("   柱面 ΔV 只取两端 ✓，转置层被当场拒绝 ✓")
print("\n全部探针通过")
