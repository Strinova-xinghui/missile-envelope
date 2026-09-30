# -*- coding: utf-8 -*-
"""命令行入口：`python -m missile_sim`。

三条纪律：

1. **屏幕上出现的每个参数都真的生效**。旧外壳里 `--aero/--burn/--loft` 这类"配置说了什么"
   的旋钮对 wt-missile 求解器是惰性的，新外壳**不提供**它们 —— 少一个参数，就少一次
   "以为自己改了物理"的误读。
2. **优先级严格分层**：命令行 > `--input` JSON > 数据类默认值。所以所有 argparse 参数
   默认值都是 `None`（布尔开关用 `default=None` 的 `store_false`），"没给"就不会覆盖 JSON。
3. 未知键**报错**，不静默丢弃（JSON 里写错的字段名会被当场指出）。

两张图由 `--figure` 选：`plane`（ΔV–BC，默认）/ `bg`（β–γ）/ `traj`（机动想定轨迹）/
`both`（前两张）/ `all`（三张）。三者的 JSON 输入字段集不同，所以 `--input` 的键校验
跟着 `--figure` 走。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields, replace
from pathlib import Path

from . import pool
from .spec import DEFAULT_MISSILE, SOLVER_DT, TIERS, Scene
from .workflow import (BgRequest, PlaneRequest, TrajRequest, run_bg, run_plane,
                       run_traj)

PROG = "python -m missile_sim"

EPILOG = f"""示例：
  {PROG}                                   # 图1：11 弹散点 + PL-12 基准的 1 s 等时线（fast 档）
  {PROG} --missiles PL-12,R-77-1,120C       # 自选弹池参与对比
  {PROG} --standard R-77-1 --tier standard  # 换基准弹与档位
  {PROG} --no-iso                           # 只出散点（秒级，用来先看轴对不对）
  {PROG} --figure bg                        # 图2：β–γ 能力平面 + 仿真等时线
  {PROG} --figure bg --bg-no-scan           # 图2 只出参考图那一套（散点 + 等 n* 线）
  {PROG} --figure traj                      # 图3：crank → 39 的机动想定轨迹（基准弹一枚）
  {PROG} --figure traj --traj-preview       # 图3 输入阶段的 3D 航迹预览（不跑求解器，秒级）
  {PROG} --figure all --tag all             # 三张图一起出
  {PROG} --input configs/default.json       # 从 JSON 读输入（命令行仍可覆盖）

输入/输出契约与"换求解器"的步骤见 docs/SOLVER-API.md；β–γ 的口径见 docs/BETA-GAMMA.md。
"""

_SCENE_FIELDS = tuple(f.name for f in fields(Scene))
_PLANE_FIELDS = tuple(f.name for f in fields(PlaneRequest) if f.name != "scene")
_BG_FIELDS = tuple(f.name for f in fields(BgRequest) if f.name != "scene")
_TRAJ_FIELDS = tuple(f.name for f in fields(TrajRequest) if f.name != "scene")

#: ⚠ 图2 的**参考工况**在 JSON / CLI / 表单上叫 `bg_alt_m` / `bg_speed_ms`，不叫 `alt_m`。
#: 原因是硬撞名：`BgRequest.alt_m`（参考工况高度，只影响等 n* 线）与 `Scene.alt_m`
#: （载机发射高度）语义完全不同。若两边都叫 `alt_m`，argparse 的两个选项会写同一个 `dest`、
#: JSON 的 `alt_m` 会被当成场景字段 —— 改"参考高度"顺手改掉"发射高度"而且不报错。
#: 这张映射表是**唯一的改名落点**（`_request` 读、`_from_json` 写都经过它）。
_BG_ALIASES = {"alt_m": "bg_alt_m", "speed_ms": "bg_speed_ms"}
#: 图2 在 CLI / JSON / 表单上的外部名，`_BG_FIELDS` 折出来的那一套。
#: 测试用它来断言"每个字段都有一个同名 `dest`"（漏一个就是"参数写了不生效"）。
_BG_EXTERNAL = tuple(_BG_ALIASES.get(n, n) for n in _BG_FIELDS)

#: 图3 的机动想定参数一律加 `traj_` 前缀（`--traj-crank-deg`），
#: 但这些名字**只活在 CLI / JSON / 表单这一层**，`TrajRequest` 的字段名保持短名
#: （`crank_deg`）—— 与图2 的 `bg_alt_m` 是同一套机制、同一个落点：
#: `tier` / `standard` / `tag` / `formats` 不给别名，直接共用全局选项。
_TRAJ_ALIASES = {
    "t_crank": "traj_t_crank", "crank_deg": "traj_crank_deg",
    "crank_g": "traj_crank_g", "beam_deg": "traj_beam_deg", "beam_g": "traj_beam_g",
    "lock_distance_m": "traj_lock_m", "react_delay_s": "traj_react_delay",
    "weave": "traj_weave", "weave_amp_deg": "traj_weave_amp",
    "weave_hz": "traj_weave_hz", "t_beam_s": "traj_t_beam",
    "preview": "traj_preview",
}
_TRAJ_EXTERNAL = tuple(_TRAJ_ALIASES.get(n, n) for n in _TRAJ_FIELDS)
_JSON_ONLY = ("input", "list_missiles", "quiet", "figure")


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
                   help="双方水平距离 [m]（斜距由高度差现算）")
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

    p = ap.add_argument_group("网格与出图（图1 = ΔV–BC）")
    p.add_argument("--iso-step", dest="iso_step", type=float, default=None,
                   help="等时线步长 [s]（默认 1）")
    p.add_argument("--dv-step", dest="dv_step", type=float, default=None,
                   help="ΔV 网格步长（默认 10）")
    p.add_argument("--bc-step", dest="bc_step", type=float, default=None,
                   help="BC 网格步长（默认 25）")
    p.add_argument("--xlim", type=_pair, default=None, help="覆盖自适应横轴，如 800,1110")
    p.add_argument("--ylim", type=_pair, default=None, help="覆盖自适应纵轴，如 2450,3850")
    p.add_argument("--no-iso", dest="with_iso", action="store_false", default=None,
                   help="图1 只出散点，不扫描等时线")
    p.add_argument("--no-colorbar", dest="colorbar", action="store_false", default=None)
    p.add_argument("--formats", default=None, help="导出格式（默认 png,pdf,svg）")
    p.add_argument("--tag", default=None, help="产物名后缀（默认 default）")
    p.add_argument("--no-cache", dest="cache", action="store_false", default=None)

    b = ap.add_argument_group("图2（β–γ 能力平面）")
    b.add_argument("--figure", choices=("plane", "bg", "traj", "both", "all"), default=None,
                   help="出哪张图：plane = 图1（默认），bg = 图2，traj = 图3，"
                        "both = 图1+图2，all = 三张都出")
    b.add_argument("--bg-no-scan", dest="with_scan", action="store_false", default=None,
                   help="图2 不跑仿真层，只出参考图那一套（散点 + 等 n* 线）")
    b.add_argument("--beta-step", dest="beta_step", type=float, default=None,
                   help="β 网格步长（默认 30）")
    b.add_argument("--gamma-step", dest="gamma_step", type=float, default=None,
                   help="γ 网格步长（默认 2）")
    b.add_argument("--bg-dv", dest="dv_pin", type=float, default=None,
                   help="图2 仿真层固定住的 ΔV [m/s]（默认取基准弹标称值）")
    b.add_argument("--bg-n", dest="n_ref", type=float, default=None,
                   help="图2 机动惩罚比 R / β_eff 的参考过载 [G]（默认 20）")
    b.add_argument("--bg-alt", dest="bg_alt_m", type=float, default=None,
                   help="图2 参考工况高度 [m]（默认 10000；只影响 n* 那族线）")
    b.add_argument("--bg-speed", dest="bg_speed_ms", type=float, default=None,
                   help="图2 参考工况速度 [m/s]（默认 800；只影响 n* 那族线）")

    j = ap.add_argument_group("图3（机动想定：直飞 → crank → 39，只跑基准弹一枚）")
    j.add_argument("--traj-t-crank", dest="traj_t_crank", type=float, default=None,
                   help="发射后多久开始 crank [s]（默认 8）")
    j.add_argument("--traj-crank-deg", dest="traj_crank_deg", type=float, default=None,
                   help="crank 离轴角 [°]（默认 70；对应航向 180 − 该值）")
    j.add_argument("--traj-crank-g", dest="traj_crank_g", type=float, default=None,
                   help="crank 段转向过载 [G]（默认 9）")
    j.add_argument("--traj-beam-deg", dest="traj_beam_deg", type=float, default=None,
                   help="39 位离轴角 [°]（默认 90 = 正侧方）")
    j.add_argument("--traj-beam-g", dest="traj_beam_g", type=float, default=None,
                   help="转 39 段转向过载 [G]（默认 9）")
    j.add_argument("--traj-lock-m", dest="traj_lock_m", type=float, default=None,
                   help="导引头开机距离 [m]（默认取基准弹 blk 的 guidance.lockDistance）")
    j.add_argument("--traj-react-delay", dest="traj_react_delay", type=float, default=None,
                   help="看到 RWR 告警后的反应时间 [s]（默认 1.0）")
    j.add_argument("--traj-weave", dest="traj_weave", action="store_const", const=True,
                   default=None, help="开启目标俯仰震荡（默认关：用户经验值待提供）")
    j.add_argument("--traj-no-weave", dest="traj_weave", action="store_const", const=False,
                   help="显式关闭震荡（覆盖 --input 里的 weave=true）")
    j.add_argument("--traj-weave-amp", dest="traj_weave_amp", type=float, default=None,
                   help="震荡幅度 [°]（默认 4）")
    j.add_argument("--traj-weave-hz", dest="traj_weave_hz", type=float, default=None,
                   help="震荡频率 [Hz]（默认 0.1）")
    j.add_argument("--traj-t-beam", dest="traj_t_beam", type=float, default=None,
                   help="钉死开机时刻 [s]（复现/预览用；默认在不含 39 腿的轨迹上反求）")
    j.add_argument("--traj-preview", dest="traj_preview", action="store_true", default=None,
                   help="只出输入阶段的 3D 目标航迹预览（不跑求解器，秒级）")

    m = ap.add_argument_group("其他")
    m.add_argument("--input", type=Path, default=None, help="从 JSON 读输入（命令行覆盖它）")
    m.add_argument("--list-missiles", action="store_true", help="打印弹池后退出")
    m.add_argument("--quiet", action="store_true", help="不打印进度")
    return ap


def _from_json(path: Path, req_fields, aliases: dict | None = None) -> tuple:
    """返回 `(scene, 其余字段)`。未知键**报错**，不静默丢弃。

    `aliases` 把**外部名**折回 **dataclass 字段名**（图2 的 `bg_alt_m` → `alt_m`）。
    折名发生在 `_SCENE_FIELDS` 扫描**之前**，所以 `bg_alt_m` 不会被当成场景字段。

    ⚠ 两个拼写都收：**外部名**（`bg_alt_m` / `traj_t_crank`）与 **dataclass 字段名**
    （`alt_m` / `t_crank`）。`aliases` 的方向是 **字段名 → 外部名**（`_external_name()`
    就靠它），所以这里的折叠必须写成 `field, external`——曾经写反成 `external, canon`，
    结果 `bg_alt_m` 折出来还是 `bg_alt_m`，`cls(**extra)` 直接 `TypeError`：
    **凡是带别名的键，`--input` 一律炸**（而默认 JSON 里正好没有别名键，所以一直没暴露）。
    """
    blob = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(blob, dict):
        raise ValueError(f"{path} 的顶层必须是对象")
    out = dict(blob)
    scene_raw = dict(out.pop("scene", {}) or {})
    # ① 先折**外部名**：它们存在的唯一理由就是"与场景字段撞名"（`bg_alt_m` vs `alt_m`），
    #    所以折出来的字段名要**锁定给请求**，绝不能再被下面那步当场景字段收走。
    claimed = set()
    for field, external in (aliases or {}).items():
        if external in out:
            if field in out:
                hint = ("（两者同名，平铺的那个会被当成场景字段）"
                        if field in _SCENE_FIELDS else "（两种写法指同一个字段）")
                raise ValueError(f"{path} 里 {external} 与 {field} 只能给一个{hint}")
            out[field] = out.pop(external)
            claimed.add(field)
    # ② 顶层平铺的场景字段（`"alt_m": 7000` 就是**载机高度**）。撞名字段只认外部名，
    #    所以 `bg_alt_m` 改了参考工况、`scene.alt_m` 才是发射高度，两者互不干扰。
    for k in list(out):
        if k in _SCENE_FIELDS and k not in claimed:
            scene_raw[k] = out.pop(k)
    known = tuple(req_fields) + tuple((aliases or {}).values())
    unknown = [k for k in out if k not in _canonical_keys(req_fields, aliases)]
    if unknown:
        raise ValueError(f"{path} 里有不认识的键：{', '.join(sorted(unknown))}；"
                         f"可用：{', '.join(_SCENE_FIELDS + known)}")
    bad_scene = [k for k in scene_raw if k not in _SCENE_FIELDS]
    if bad_scene:
        raise ValueError(f"{path} 的 scene 里有不认识的键：{', '.join(sorted(bad_scene))}")
    return Scene.from_dict(scene_raw), out


def _canonical_keys(req_fields, aliases: dict | None) -> frozenset:
    """`_from_json` 的键白名单：**dataclass 字段名**与**外部名**都算合法写法。"""
    return frozenset(set(req_fields) | set((aliases or {}).values()))


def _request(args, cls, req_fields, aliases: dict | None = None):
    """命令行 + JSON → 请求对象。命令行只覆盖**它显式给了的**字段。

    `req_fields` 是 **dataclass 字段名**；`aliases` 把其中几个映射到 CLI 上的外部名
    （`alt_m` → `bg_alt_m`）。这样"字段叫什么"与"命令行上叫什么"只有一个落点。

    `--figure both` 时以图1 的字段集为准读 JSON（两张图的 JSON 字段不同名，
    给 `both` 用一套输入本来就只是个方便；要精细控制就分两次跑）。
    """
    scene, extra = (_from_json(args.input, req_fields, aliases)
                    if args.input is not None else (Scene(), {}))
    req = cls(scene=scene, **extra)
    scene_over = {k: getattr(args, k) for k in _SCENE_FIELDS
                  if getattr(args, k, None) is not None}
    if scene_over:
        scene = replace(scene, **scene_over)
    rest = {}
    for k in req_fields:
        if k == "formats":
            continue
        val = getattr(args, _external_name(k, aliases), None)
        if val is not None:
            rest[k] = val
    if args.formats:
        rest["formats"] = tuple(s.strip() for s in str(args.formats).split(",") if s.strip())
    return replace(req, scene=scene, **rest)


def _external_name(field: str, aliases: dict | None) -> str:
    """dataclass 字段名 → CLI `dest` / JSON 键（就是外部名）。"""
    return (aliases or {}).get(field, field)


def _print_missiles() -> int:
    print(f"弹池（{len(pool.names())} 型，默认基准弹 {DEFAULT_MISSILE}）：")
    for p in pool.points():
        print(f"  {p.key:<9} {pool._full(p):<16} ΔV={p.dv:8.2f}  BC={p.bc:8.1f}"
              f"  干重={p.dry_kg:6.1f} kg  CxK={p.cxk:g}  口径={p.caliber_m * 1000:.0f} mm")
    print(f"\n资源版本：{pool.version()}（来自 vendor/wt-missile，ΔV/BC 为现算的权威值）")
    return 0


def _show(out: dict, say) -> None:
    say("产物：")
    for key, val in sorted(out["_paths"].items()):
        for item in (val if isinstance(val, list) else [val]):
            say(f"  {key:<9} {item}")


def _progress(args):
    if args.quiet:
        return None

    def progress(done, total):
        step = max(1, total // 10)
        if done % step == 0 or done == total:
            print(f"    扫描 {done}/{total}", flush=True)

    return progress


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.list_missiles:
            return _print_missiles()
        which = args.figure or "plane"
        say = (lambda _m: None) if args.quiet else (lambda m: print(m, flush=True))
        if which in ("plane", "both", "all"):
            req = _request(args, PlaneRequest, _PLANE_FIELDS)
            say("=== 图1：ΔV–BC 包线图 ===")
            out = run_plane(req, progress=_progress(args), log=say)
            _show(out, say)
        if which in ("bg", "both", "all"):
            req2 = _request(args, BgRequest, _BG_FIELDS, _BG_ALIASES)
            say("=== 图2：β–γ 能力平面 ===")
            out2 = run_bg(req2, progress=_progress(args), log=say)
            _show(out2, say)
        if which in ("traj", "all"):
            req3 = _request(args, TrajRequest, _TRAJ_FIELDS, _TRAJ_ALIASES)
            say("=== 图3：机动想定轨迹（crank → 39）===")
            out3 = run_traj(req3, progress=_progress(args), log=say)
            _show(out3, say)
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
