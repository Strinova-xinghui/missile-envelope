# -*- coding: utf-8 -*-
"""命令行入口：`python -m missile_sim`。

三条纪律：

1. **屏幕上出现的每个参数都真的生效**。旧外壳里 `--aero/--burn/--loft` 这类"配置说了什么"
   的旋钮对 wt-missile 求解器是惰性的，新外壳**不提供**它们 —— 少一个参数，就少一次
   "以为自己改了物理"的误读。
2. **优先级严格分层**：命令行 > `--input` JSON > 数据类默认值。所以所有 argparse 参数
   默认值都是 `None`（布尔开关用 `default=None` 的 `store_false`），"没给"就不会覆盖 JSON。
3. 未知键**报错**，不静默丢弃（JSON 里写错的字段名会被当场指出）。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

from . import pool
from .spec import DEFAULT_MISSILE, SOLVER_DT, TIERS, Scene
from .workflow import PlaneRequest, run_plane

PROG = "python -m missile_sim"

EPILOG = f"""示例：
  {PROG}                                   # 11 弹散点 + PL-12 基准的 1 s 等时线（fast 档）
  {PROG} --missiles PL-12,R-77-1,120C       # 自选弹池参与对比
  {PROG} --standard R-77-1 --tier standard  # 换基准弹与档位
  {PROG} --no-iso                           # 只出散点（秒级，用来先看轴对不对）
  {PROG} --input configs/default.json       # 从 JSON 读输入（命令行仍可覆盖）

输入/输出契约与"换求解器"的步骤见 docs/SOLVER-API.md。
"""

_SCENE_FIELDS = tuple(f.name for f in fields(Scene))
_REQ_FIELDS = tuple(f.name for f in fields(PlaneRequest) if f.name != "scene")
_JSON_ONLY = ("input", "list_missiles", "quiet")


def _pair(text: str) -> tuple:
    parts = [p for p in str(text).replace("，", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(f"要写成 `a,b` 两段，收到 {text!r}")
    return (float(parts[0]), float(parts[1]))


def _missiles(text: str):
    return [s for s in str(text).replace(",", " ").split() if s]


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog=PROG, description="导弹 (ΔV, BC) 包线图",
                                 epilog=EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_argument_group("几何（不给就用 Scene 默认值）")
    g.add_argument("--range", dest="range_m", type=float, default=None,
                   help="双方**水平**距离 [m]（斜距由高度差现算）")
    g.add_argument("--alt", dest="alt_m", type=float, default=None, help="发射高度 [m]")
    g.add_argument("--target-alt", dest="target_alt_m", type=float, default=None,
                   help="目标高度 [m]（默认与发射同高）")
    g.add_argument("--bearing", dest="target_bearing_deg", type=float, default=None,
                   help="目标方位角 [°]：0 = +x，正 → +z")

    v = ap.add_argument_group("速度（标量 + 航向 + 俯仰；航向 0 = +x，正 → +z）")
    v.add_argument("--vm0", type=float, default=None, help="载机速度 [m/s]")
    v.add_argument("--launch-heading", dest="launch_heading_deg", type=float, default=None,
                   help="载机航向 [°]")
    v.add_argument("--launch-pitch", dest="launch_pitch_deg", type=float, default=None,
                   help="载机速度俯仰 [°]（正 = 爬升）")
    v.add_argument("--target-speed", dest="target_speed_ms", type=float, default=None,
                   help="敌机速度 [m/s]")
    v.add_argument("--target-heading", dest="target_heading_deg", type=float, default=None,
                   help="敌机航向 [°]（180 = 迎面）")
    v.add_argument("--target-pitch", dest="target_pitch_deg", type=float, default=None,
                   help="敌机速度俯仰 [°]（正 = 爬升）")

    t = ap.add_argument_group("技术参数")
    t.add_argument("--duration", dest="duration_s", type=float, default=None,
                   help="请求时域上限 [s]")
    t.add_argument("--dt", dest="dt_s", type=float, default=None,
                   help=f"物理步长 [s]（默认 {SOLVER_DT:g}，客户端对象时钟）")
    t.add_argument("--observation", choices=("ideal", "locked"), default=None,
                   help="观测模式（默认 ideal）")
    t.add_argument("--hit-radius", dest="hit_radius_m", type=float, default=None,
                   help="几何接触半径 [m]（0 = 只用求解器自己的近炸判定）")

    s = ap.add_argument_group("弹池与档位")
    s.add_argument("--standard", default=None, help=f"基准弹（默认 {DEFAULT_MISSILE}）")
    s.add_argument("--missiles", type=_missiles, default=None,
                   help="参与散点的弹（逗号分隔；默认全 11 型）")
    s.add_argument("--tier", choices=TIERS, default=None,
                   help="计算档位：fast = C 内核（默认），standard = 纯 Python 逐物理步")
    s.add_argument("--jobs", type=int, default=None, help="并发进程数（默认 8）")

    p = ap.add_argument_group("网格与出图")
    p.add_argument("--iso-step", dest="iso_step", type=float, default=None,
                   help="等时线步长 [s]（默认 1）")
    p.add_argument("--dv-step", dest="dv_step", type=float, default=None,
                   help="ΔV 网格步长（默认 10）")
    p.add_argument("--bc-step", dest="bc_step", type=float, default=None,
                   help="BC 网格步长（默认 25）")
    p.add_argument("--xlim", type=_pair, default=None, help="覆盖自适应横轴，如 800,1110")
    p.add_argument("--ylim", type=_pair, default=None, help="覆盖自适应纵轴，如 2450,3850")
    p.add_argument("--no-iso", dest="with_iso", action="store_false", default=None,
                   help="只出散点，不扫描等时线")
    p.add_argument("--no-colorbar", dest="colorbar", action="store_false", default=None)
    p.add_argument("--formats", default=None, help="导出格式（默认 png,pdf,svg）")
    p.add_argument("--tag", default=None, help="产物名后缀（默认 default）")
    p.add_argument("--no-cache", dest="cache", action="store_false", default=None)

    m = ap.add_argument_group("其他")
    m.add_argument("--input", type=Path, default=None, help="从 JSON 读输入（命令行覆盖它）")
    m.add_argument("--list-missiles", action="store_true", help="打印弹池后退出")
    m.add_argument("--quiet", action="store_true", help="不打印进度")
    return ap


def _from_json(path: Path) -> tuple:
    """返回 `(scene, 其余字段)`。未知键**报错**，不静默丢弃。"""
    blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict):
        raise ValueError(f"{path} 的顶层必须是对象")
    out = dict(blob)
    scene_raw = dict(out.pop("scene", {}) or {})
    for k in list(out):
        if k in _SCENE_FIELDS:                 # 允许场景字段平铺在顶层
            scene_raw[k] = out.pop(k)
    unknown = [k for k in out if k not in _REQ_FIELDS]
    if unknown:
        raise ValueError(f"{path} 里有不认识的键：{', '.join(sorted(unknown))}；"
                         f"可用：{', '.join(_SCENE_FIELDS + _REQ_FIELDS)}")
    bad_scene = [k for k in scene_raw if k not in _SCENE_FIELDS]
    if bad_scene:
        raise ValueError(f"{path} 的 scene 里有不认识的键：{', '.join(sorted(bad_scene))}")
    return Scene.from_dict(scene_raw), out


def _request(args) -> PlaneRequest:
    """命令行 + JSON → `PlaneRequest`。命令行只覆盖**它显式给了的**字段。"""
    scene, extra = _from_json(args.input) if args.input is not None else (Scene(), {})
    req = PlaneRequest(scene=scene, **extra)
    scene_over = {k: getattr(args, k) for k in _SCENE_FIELDS
                  if getattr(args, k, None) is not None}
    if scene_over:
        scene = replace(scene, **scene_over)
    rest = {k: getattr(args, k) for k in _REQ_FIELDS
            if k != "formats" and getattr(args, k, None) is not None}
    if args.formats:
        rest["formats"] = tuple(s.strip() for s in str(args.formats).split(",") if s.strip())
    return replace(req, scene=scene, **rest)


def _print_missiles() -> int:
    print(f"弹池（{len(pool.names())} 型，默认基准弹 {DEFAULT_MISSILE}）：")
    for p in pool.points():
        print(f"  {p.key:<9} {pool._full(p):<16} ΔV={p.dv:8.2f}  BC={p.bc:8.1f}"
              f"  干重={p.dry_kg:6.1f} kg  CxK={p.cxk:g}  口径={p.caliber_m * 1000:.0f} mm")
    print(f"\n资源版本：{pool.version()}（来自 vendor/wt-missile，ΔV/BC 为现算的权威值）")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.list_missiles:
            return _print_missiles()
        req = _request(args)
        say = (lambda _m: None) if args.quiet else (lambda m: print(m, flush=True))

        def progress(done, total):
            step = max(1, total // 10)
            if done % step == 0 or done == total:
                print(f"    扫描 {done}/{total}", flush=True)

        out = run_plane(req, progress=None if args.quiet else progress, log=say)
        print("产物：")
        for key, val in sorted(out["_paths"].items()):
            for item in (val if isinstance(val, list) else [val]):
                print(f"  {key:<9} {item}")
        return 0
    except pool.PoolError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        print("提示：`python -m missile_sim --list-missiles` 可以看全部可选弹。",
              file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":                       # pragma: no cover
    raise SystemExit(main())
