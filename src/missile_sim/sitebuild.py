# -*- coding: utf-8 -*-
"""纯静态图册的生成逻辑（路径 A）—— 只读产物、不跑求解器、零第三方资源。

> 为什么这段逻辑在 `src/` 而不是 `scripts/`：`scripts/` **不随分发包**，
> 而 `tests/test_static_site.py` 的判据要能在**包内自检**里跑（包里有 `figures/`、`results/`、
> `LICENSE`，正好够用）。薄壳 CLI 留在 `scripts/build_static_site.py`。

只抄 `figures/` 里两个 `_static` 变体的三格式：

| 卡片 | 图 | 文件 | 为什么是这一版 |
| --- | --- | --- | --- |
| 图1 | ΔV–β 散点 | `fig_isotime_plane_static.*` | **不含等时线**的那一版（`with_iso=false`） |
| 图2 | β–ginv 能力平面 | `fig_bg_plane_static.*` | 纵轴 `ginv = 1/γ` 的**修正版**，且**未跑仿真**（`with_scan=false`） |

⚠ **构建期闸门**（不是文档提醒）：每张卡片都从对应产物 JSON 现读开关，发现 `with_iso` / `with_scan`
为真或 `iso_levels` 非空 ⇒ **拒绝出站**，免得把含等时线的版本当"静态版"发出去
（2026-10-04 的 `_static` 陈旧事故就是这一族）。

页面本身：无 CDN、无 web font、无 JS，亮色主题，与仓库前端口径一致；页头的内核版本 / 工况 /
轴范围**从 `results/*_static.json` 现读**（不写死）；文案里不许出现 markdown 星号；输出可复现
（页面里没有构建时间戳）。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import figures

#: 默认根目录：本文件在 `<root>/src/missile_sim/` 里（分发包里就是 `app/`），
#: 而 `figures/`、`results/`、`LICENSE` 都在那个根下。
DEFAULT_ROOT = Path(__file__).resolve().parents[2]
FORMATS = ("png", "pdf", "svg")

#: (figures/ 里的文件名主干, 产物 JSON, 图号, 标题, 副标题, 口径说明, 产物里的"有没有等时线"开关)
PLAN = (
    (
        "fig_isotime_plane_static",
        "plane_static.json",
        "图1",
        "理想总增速 ΔV — 简化弹道系数 β",
        "11 枚弹的标称点（自适应轴）",
        "横轴 = ΔV（理想（真空等效）总增速，越大越好）；纵轴 = β（简化弹道系数，越大越好）。"
        "本版只画标称点，「不含等时线」——等时线属于提交计算后出的那一版。",
        "with_iso",
    ),
    (
        "fig_bg_plane_static",
        "bg_static.json",
        "图2",
        "β — ginv 能力平面",
        "直飞保能 β vs 转向能力 ginv = 1/γ",
        "横轴 = β（直飞保能）；纵轴 = ginv = 1/γ（转向能力，取倒数后两根轴同为「向上更好」，"
        "不必再看符号）。本版「未跑仿真扫描」，所以没有等时线。",
        "with_scan",
    ),
)


class GateError(RuntimeError):
    """构建期闸门：要发的不是「无等时线」的那一版。"""


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_card_meta(meta_name: str, flag_key: str, *, root: Path = DEFAULT_ROOT) -> dict:
    """读某张图的产物元数据，并**在构建期**校验「这一版确实没有等时线」。"""
    path = Path(root) / "results" / meta_name
    if not path.is_file():
        raise GateError(f"产物不在：results/{meta_name}（先跑 scripts\\refresh_products.py）")
    d = _read_json(path)
    if d.get(flag_key) is not False or d.get("iso_levels"):
        raise GateError(
            f"results/{meta_name} 不是「无等时线」的那一版：{flag_key}={d.get(flag_key)!r}、"
            f"iso_levels={len(d.get('iso_levels') or [])} 层 ⇒ 拒绝出站")
    return d


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.3f}".rstrip("0").rstrip(".")
    return str(v)


def _scene_line(scene: dict) -> str:
    if not scene:
        return ""
    bits = []
    if scene.get("range_m") is not None:
        bits.append(f"发射距离 {_fmt(float(scene['range_m']) / 1000.0)} km（水平）")
    if scene.get("alt_m") is not None:
        bits.append(f"载机高度 {_fmt(float(scene['alt_m']) / 1000.0)} km")
    if scene.get("vm0") is not None:
        bits.append(f"载机 {_fmt(float(scene['vm0']))} m/s")
    if scene.get("target_bearing_deg") is not None:
        bits.append(f"目标方位 {_fmt(float(scene['target_bearing_deg']))}°")
    return " · ".join(bits)


def _identity_line(solver: dict) -> str:
    if not solver:
        return ""
    sha = str(solver.get("sha256") or "")
    return (f"内核 {solver.get('model', '?')} · wt-missile {solver.get('version', '?')}"
            + (f"（sha256 {sha[:8]}…）" if sha else ""))


def card_html(stem: str, no: str, title: str, sub: str, note: str, meta: dict,
              notes=()) -> str:
    ident = _identity_line(meta.get("solver") or {})
    scene = _scene_line(meta.get("scene") or {})
    axis = meta.get("axis") or {}
    rows = [("内核", ident), ("基准弹", str(meta.get("standard") or "")), ("工况", scene),
            ("档位", str(meta.get("tier") or ""))]
    if axis.get("xlim") and axis.get("ylim"):
        rows.append(("轴范围", "自适应 x [%s, %s] · y [%s, %s]" % (
            _fmt(axis["xlim"][0]), _fmt(axis["xlim"][1]),
            _fmt(axis["ylim"][0]), _fmt(axis["ylim"][1]))))
    if meta.get("tag"):
        rows.append(("产物", f"tag {meta['tag']}"))
    dl = "\n".join(f"        <dt>{k}</dt><dd>{v}</dd>" for k, v in rows if v)
    links = " · ".join(f'<a href="figures/{stem}.{e}">{e.upper()}</a>' for e in FORMATS)
    note_block = ""
    if notes:
        items = "\n".join(f"        <li>{line}</li>" for line in notes)
        note_block = f"""
      <details class="notes" open>
        <summary>图注（原先画在图里，现已移到页面）</summary>
        <ul>
{items}
        </ul>
      </details>"""
    return f"""    <section class="card" id="{stem}">
      <header class="cardhead">
        <span class="no">{no}</span>
        <h2>{title}</h2>
        <p class="sub">{sub}</p>
      </header>
      <a class="shot" href="figures/{stem}.png"><img src="figures/{stem}.png" alt="{no} {title}"></a>
      <p class="note">{note}</p>{note_block}
      <p class="links">下载：{links}</p>
      <dl class="meta">
{dl}
      </dl>
    </section>"""


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>导弹包线图 · 静态图册</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #f7f8f9; color: #1f2933;
         font-family: system-ui, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; }}
  .wrap {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px 56px; }}
  header.top h1 {{ margin: 0 0 6px; font-size: 26px; }}
  header.top .sub {{ margin: 0 0 4px; color: #52606d; }}
  header.top .meta {{ margin: 0 0 8px; color: #52606d; font-size: 13px; }}
  .card {{ background: #fff; border: 1px solid #e3e8ee; border-radius: 10px;
           padding: 18px 20px 14px; margin: 18px 0 0; }}
  .cardhead {{ display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }}
  .cardhead h2 {{ margin: 0; font-size: 19px; }}
  .cardhead .no {{ background: #eaf2fb; color: #2661d9; border-radius: 6px;
                   padding: 2px 8px; font-size: 13px; }}
  .cardhead .sub {{ margin: 0; color: #52606d; font-size: 13px; }}
  .shot {{ display: block; margin: 12px 0 4px; }}
  .shot img {{ width: 100%; height: auto; border: 1px solid #eef1f4; border-radius: 6px; }}
  .note {{ color: #3e4c59; font-size: 13px; line-height: 1.65; }}
  .notes {{ margin: 8px 0 2px; border-left: 3px solid #e3e8ee; padding: 2px 0 2px 10px; }}
  .notes summary {{ cursor: pointer; color: #52606d; font-size: 12.5px; }}
  .notes ul {{ margin: 6px 0 2px 16px; padding: 0; }}
  .notes li {{ color: #3e4c59; font-size: 12.5px; line-height: 1.7; }}
  .links {{ font-size: 13px; }}
  .meta {{ display: grid; grid-template-columns: max-content 1fr; gap: 2px 14px;
           font-size: 12.5px; color: #52606d; border-top: 1px dashed #e3e8ee; padding-top: 8px; }}
  .meta dt {{ color: #7b8794; }}
  .meta dd {{ margin: 0; }}
  footer {{ margin-top: 26px; color: #52606d; font-size: 12.5px; line-height: 1.7; }}
  footer a {{ color: #2661d9; }}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>导弹包线图 · 静态图册</h1>
    <p class="sub">图1（ΔV–β）与图2（β–ginv）的成品图，均为「不含等时线」的静态版。</p>
    <p class="meta">{head_meta}</p>
    <p class="nav"><a href="method.html">看图前必读：γ 与两张图的口径 →</a></p>
  </header>
{cards}
  <footer>
    <p>这两张图由本项目的求解器与出图管线生成，本页与图表按
      <strong>AGPL-3.0-only</strong> 发布，许可正文见同目录的 <code>LICENSE</code>。</p>
    <p>读法：两根轴都是「向上更好」；图2 的纵轴是 γ 的倒数（ginv = 1/γ），
      这样「右上角」就同时意味着最好，不必再判符号。</p>
    <p>图是仿真结果，不是游戏内实测；数据版本与内核指纹见每张图的元数据。{source_line}</p>
  </footer>
</div>
</body>
</html>
"""


METHOD_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>看图前必读：γ 与两张图的口径</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; background: #f7f8f9; color: #1f2933;
         font-family: system-ui, "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif; }
  .wrap { max-width: 860px; margin: 0 auto; padding: 28px 20px 56px; }
  header.top h1 { margin: 0 0 6px; font-size: 25px; }
  header.top .sub { margin: 0 0 4px; color: #52606d; }
  header.top .meta { margin: 0 0 8px; color: #52606d; font-size: 13px; }
  .card { background: #fff; border: 1px solid #e3e8ee; border-radius: 10px;
          padding: 16px 20px 12px; margin: 16px 0 0; }
  .card h2 { margin: 0 0 8px; font-size: 18px; }
  .card h3 { margin: 14px 0 6px; font-size: 15px; color: #243b53; }
  p, li { line-height: 1.75; font-size: 14px; }
  ul { margin: 6px 0 6px 18px; padding: 0; }
  code { background: #f1f4f8; border-radius: 4px; padding: 1px 5px;
         font-family: Consolas, "Courier New", monospace; font-size: 13px; }
  .fml { display: block; margin: 8px 0; padding: 10px 12px; background: #f8fafc;
         border: 1px dashed #d9e2ec; border-radius: 6px; font-size: 13.5px; }
  footer { margin-top: 22px; color: #52606d; font-size: 12.5px; line-height: 1.7; }
  footer a, a { color: #2661d9; }
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <h1>看图前必读：γ 与两张图的口径</h1>
    <p class="sub">本页只讲一件事：图2 纵轴的 γ（诱导阻力 / 升力那一项）是怎么来的、怎么读。</p>
    <p class="meta">{{facts_line}}</p>
  </header>

  <section class="card">
    <h2>0. 这两张图是什么</h2>
    <p>图1 画 ΔV–β（横轴理想总增速、纵轴弹道系数口径）；图2 画 β–ginv（横轴直飞保能、纵轴转向能力）。
       两图都是<strong>不含等时线</strong>的静态版：只放 11 枚弹的标称点，不随工况重算。</p>
    <p>本图册<strong>不含程序、不含任何游戏数据</strong>：它是成品图与口径说明。</p>
  </section>

  <section class="card">
    <h2>1. β 是什么（一句）</h2>
    <p class="fml"><code>β = m燃尽 / (SD · CxK)</code>　[kg/m²]</p>
    <p>就是通常说的弹道系数（BC）口径，<strong>直飞保能，越大越好</strong>。其中
       <code>SD = π·d²/4</code> 直接取求解器的 drag_area，<code>CxK</code> 是零升阻力系数。</p>
  </section>

  <section class="card">
    <h2>2. γ 是什么（本页的重点）</h2>

    <h3>2.1 一句话</h3>
    <p>γ 是把「用升力换取过载」折算成「诱导阻力损失」的<strong>单一系数</strong>，单位 [kg/m²]，
       <strong>越大越差</strong>（转向越贵）。</p>

    <h3>2.2 定义</h3>
    <p class="fml"><code>γ = m燃尽 · SD · CxK · CxAoA / (SL² · CyK²)</code>　[kg/m²]</p>
    <p>逐项：<code>SD = π·d²/4</code>（drag_area，口径面积）、
       <code>SL = 0.3 · d · L · wingAreaMult</code>（lift_area，升力面积）、
       <code>CxK</code> 零升阻力系数、<code>CxAoA</code> 诱导阻力系数、<code>CyK</code> 升力线斜率、
       <code>m燃尽</code> 燃尽质量。两个面积都直接取求解器的量，不另造口径。</p>

    <h3>2.3 为什么说它「对应单位过载」</h3>
    <p>求解器的阻力式把阻力写成两项（q 是动压、M 是马赫数、α 是迎角）：</p>
    <p class="fml"><code>D = q · SD · CxK · [ f(M) + CxAoA · F(M) · sin²α ]</code></p>
    <p>升力一侧是 <code>L = q · SL · CyK · sinα</code>，而过载按定义是 <code>n ≡ L / (m · g0)</code>；
       把 <code>sinα</code> 用 n 表示、再整式除以质量，就得到按过载表达的减速度损失：</p>
    <p class="fml"><code>a_loss = q · f(M) / β　+　γ · F(M) · (n · g0)² / q</code><br>
       <span style="color:#52606d">└── 基础项（∝ q）──┘　└──── 诱导阻力项（∝ 1/q）────┘</span></p>
    <p>⇒ 第二项的系数<strong>就是 γ</strong>：在 <code>n = 1</code>（单位过载）时它就给出该弹的诱导阻力损失水平。
       n 倍过载时按 <strong>n²</strong> 增长（因为 <code>sinα ∝ n</code>）。两项对动压的依赖方向相反，
       这就是「高空高速看 β、低空缠斗看 ginv」的根源。</p>

    <h3>2.4 为什么它能当坐标轴（是弹的固有量）</h3>
    <p>β、γ 都用<strong>标称</strong>值：<code>f(M)</code>、<code>F(M)</code> 这两个马赫修正留在「损失」那一侧，
       不并进系数本身；质量取燃尽质量。于是它们与高度、速度、过载都无关，只由弹自身几何与系数决定
       —— 否则同一枚弹每隔一个马赫数就换个值，没法当坐标轴。</p>

    <h3>2.5 为什么图上画的是 ginv = 1/γ</h3>
    <p>β 大 = 好，γ 大 = 差，两者方向相反。取倒数之后两根轴<strong>同为「向上＝更好」</strong>，
       右上角就是天然的双优区，读图不用再在脑子里翻符号。</p>
    <p><strong>ginv 只是读数方式</strong>：γ 的定义一个字没改，<code>ginv = 1/γ</code>（单位 [m²/kg]），
       换算只在唯一一处完成。</p>

    <h3>2.6 由它派生的几个量（读等 n* 线要用）</h3>
    <ul>
      <li><code>Q = √(β · γ · F/f)</code>　机动敏感度 [kg/m²]</li>
      <li><code>n* = q / (Q · g0)</code>　临界过载 [G]：机动损失恰好等于基础损失的那一点，越小越「贵」</li>
      <li><code>R = (n / n*)²</code>　机动惩罚比（R = 1 时两项等量）</li>
      <li><code>β_eff = β / (1 + R)</code>　把机动折回 BC 口径的等效弹道系数</li>
    </ul>
    <p>在 ginv 轴上，同一 n* 的点连起来是一条<strong>过原点的直线</strong>（因为 γ ∝ β），
       所以图2 里的虚线族是直线而不是曲线。</p>

    <h3>2.7 适用边界（不要越界引用）</h3>
    <p>上述关系只在<strong>升力线性段</strong>成立（<code>CyK · sinα ≤ CyMaxAoA</code>），并且是
       准平衡、无角速度的假设；<code>n</code> 取的是实际气动过载。</p>
  </section>

  <section class="card">
    <h2>3. 一个例子：{{standard}}</h2>
    <p>β = <strong>{{standard_beta}}</strong> kg/m²，γ = <strong>{{standard_gamma}}</strong> kg/m²，
       ginv = <strong>{{standard_ginv}}</strong> m²/kg；
       在参考工况（{{ref_line}}）下 n* = <strong>{{standard_nstar}}</strong> G。</p>
    <p>弹池范围：β ∈ [{{beta_min}}, {{beta_max}}] kg/m²、γ ∈ [{{gamma_min}}, {{gamma_max}}] kg/m²、
       ginv ∈ [{{ginv_min}}, {{ginv_max}}] m²/kg、ΔV ∈ [{{dv_min}}, {{dv_max}}] m/s。</p>
  </section>

  <section class="card">
    <h2>4. 已知限制</h2>
    <ul>
      <li>模拟器自身的<strong>绝对阻力水平未标定</strong>：β/γ 是标称系数，不等于实测气动数据。</li>
      <li>ΔV/BC 与乘数之间是<strong>等效映射</strong>（同样总增速 / 同样弹道系数），不代表真实气动外形。</li>
      <li>图是<strong>仿真结果</strong>，不是游戏内实测。</li>
    </ul>
  </section>

  <section class="card">
    <h2>5. 免责与许可</h2>
    <ul>
      <li>本项目是<strong>独立的社区研究项目</strong>，与 Gaijin Entertainment 及 War Thunder
          没有任何隶属、赞助、合作或背书关系；图中出现的型号名仅用于技术指代。</li>
      <li><strong>游戏数据（blk 参数）的权利归 Gaijin</strong>；本图册<strong>不分发任何游戏数据</strong>。</li>
      <li>本页与两张图按 <strong>AGPL-3.0-only</strong> 发布，许可正文见同目录的 LICENSE。</li>
      <li>供学习与研究使用；<strong>请勿用于 bug 上报</strong>。</li>
    </ul>
    <p class="src">{{source_line}}</p>
  </section>

  <p><a href="index.html">← 回到图册</a></p>
  <footer>口径来源：本仓库的 β–γ 定义（<code>src/missile_sim/bg.py</code> 头注）与求解器方随内核交付的公式说明；
    页面里的数字全部由生成本次图的产物现读注入，不是手抄。</footer>
</div>
</body>
</html>
"""

#: 口径页的占位符白名单（大小写敏感）。渲染后**任何 `{{` 残留都拒绝出站**。
PLACEHOLDER_NAMES = (
    "facts_line", "ref_line", "standard",
    "standard_beta", "standard_gamma", "standard_ginv", "standard_nstar",
    "beta_min", "beta_max", "gamma_min", "gamma_max", "ginv_min", "ginv_max",
    "dv_min", "dv_max", "source_line",
)


def read_site_facts(root=DEFAULT_ROOT) -> dict:
    """从两个 `_static` 产物现读口径页要注入的数字；缺字段/空点集一律 `GateError`。"""
    root = Path(root)
    plane = _read_json(root / "results" / "plane_static.json")
    bgp = _read_json(root / "results" / "bg_static.json")
    p_pts = plane.get("points") or []
    b_pts = bgp.get("points") or []
    dv = [float(p["dv"]) for p in p_pts if p.get("dv") is not None]
    beta = [float(p["bc"]) for p in p_pts if p.get("bc") is not None]
    gamma = [float(p["gamma"]) for p in b_pts if p.get("gamma") is not None]
    ginv = [float(p["ginv"]) for p in b_pts if p.get("ginv") is not None]
    nstar = [float(p["n_star"]) for p in b_pts if p.get("n_star") is not None]
    ref = bgp.get("reference") or {}
    std = str(bgp.get("standard") or plane.get("standard") or "")
    std_pt = next((p for p in b_pts
                   if str(p.get("label")) == std or str(p.get("key")) == std), None)
    if not (dv and beta and gamma and ginv and nstar) or std_pt is None or not ref:
        raise GateError("口径页要的产物字段不全（results/*_static.json 的 points / reference / standard）")

    solver = plane.get("solver") or {}
    sha = str(solver.get("sha256") or "")
    scene = plane.get("scene") or {}
    facts = " · ".join(x for x in (
        f"内核 {solver.get('model', '?')} · wt-missile {solver.get('version', '?')}"
        + (f"（sha256 {sha[:8]}…）" if sha else ""),
        ("工况：" + _scene_line(scene)) if scene else "",
        f"参考工况 {float(ref['alt_m']) / 1000.0:.0f} km / {float(ref['speed_ms']):.0f} m/s",
    ) if x)
    ref_line = (f"{float(ref['alt_m']) / 1000.0:.0f} km、{float(ref['speed_ms']):.0f} m/s"
                f"（Ma {float(ref['mach']):.3f}、q = {float(ref['q_pa']):,.0f} Pa）")
    return {
        "facts_line": facts,
        "ref_line": ref_line,
        "standard": std,
        "standard_beta": f"{float(std_pt['beta']):,.1f}",
        "standard_gamma": f"{float(std_pt['gamma']):,.2f}",
        "standard_ginv": f"{float(std_pt['ginv']):.5f}",
        "standard_nstar": f"{float(std_pt['n_star']):,.2f}",
        "beta_min": f"{min(beta):,.1f}", "beta_max": f"{max(beta):,.1f}",
        "gamma_min": f"{min(gamma):,.2f}", "gamma_max": f"{max(gamma):,.2f}",
        "ginv_min": f"{min(ginv):.5f}", "ginv_max": f"{max(ginv):.5f}",
        "dv_min": f"{min(dv):,.1f}", "dv_max": f"{max(dv):,.1f}",
        "n_points": len(p_pts),
        "standard_dv": float(std_pt["dv"]),
    }


def figure_notes(meta: dict, facts: dict) -> list:
    """这张图**原在图内、现已移到页面**的批注文本（**单一出处 = `figures`**，不在这里另写一份）。

    用户 2026-10-04 口径：坐标轴下方的批注全部移出图外 ⇒ 文本住 `figures`，
    图不再画它，页面负责渲染。图2 靠产物的 `figure == "beta-ginv"` 判别。
    """
    if str(meta.get("figure") or "") == "beta-ginv":
        return list(figures.BG_FOOTNOTES) + [
            figures.BG_READ_NOTE,
            figures.bg_scan_def(facts["standard_dv"]),
            figures.bg_scan_note(bool(meta.get("with_scan"))),
        ]
    return list(figures.plane_notes(int(facts["n_points"])))


def render_method(facts: dict, *, source_url: str | None = None, template: str | None = None) -> str:
    """把口径页模板 + 现读的数字渲染成 HTML；**有占位符残留就拒绝出站**。

    `template=None` 时用模块常量 `METHOD_PAGE`；显式传模板只给判据的反证演练用。
    """
    page = METHOD_PAGE if template is None else template
    values = dict(facts)
    values["source_line"] = (
        f'源码与复现命令：<a href="{source_url}">{source_url}</a>。' if source_url
        else "本图册未附带程序与数据；如需源码与复现步骤，见作者公布的仓库。")
    for name in PLACEHOLDER_NAMES:
        page = page.replace("{{" + name + "}}", str(values.get(name, "")))
    if "{{" in page:
        i = page.index("{{")
        raise GateError(f"口径页有未替换的占位符：{page[i:i + 40]!r}（白名单见 PLACEHOLDER_NAMES）")
    return page


def build(out_dir, *, source_url: str | None = None, plan=PLAN, root=DEFAULT_ROOT) -> dict:
    """组装静态图册；返回 {written: [...], source_url: ...}。**任一闸门不过就抛错、不留半成品。**"""
    root = Path(root)
    out = Path(out_dir)
    metas, notes = [], []
    for stem, meta_name, _no, _title, _sub, _note, flag_key in plan:
        for e in FORMATS:
            src = root / "figures" / f"{stem}.{e}"
            if not src.is_file():
                raise GateError(f"成品图不在：figures/{stem}.{e}（先跑 scripts\\refresh_products.py）")
        metas.append(read_card_meta(meta_name, flag_key, root=root))

    # 只读一次产物：卡片上的图注与 γ 口径页用的是同一批数字
    facts = read_site_facts(root=root)

    head_bits = []
    for m in metas:
        line = _identity_line(m.get("solver") or {})
        if line and line not in head_bits:
            head_bits.append(line)
    head_meta = " · ".join(head_bits) or "内核版本见各图元数据"
    scene = _scene_line((metas[0].get("scene") if metas else {}) or {})
    if scene:
        head_meta += " · 工况：" + scene

    cards = "\n".join(
        card_html(stem, no, title, sub, note, meta, notes=figure_notes(meta, facts))
        for (stem, _mn, no, title, sub, note, _fk), meta in zip(plan, metas))
    src_line = ""
    if source_url:
        src_line = f' 源码与复现命令：<a href="{source_url}">{source_url}</a>。'
    page = PAGE.format(head_meta=head_meta, cards=cards, source_line=src_line)
    # 口径页与首页一样，**先全部渲染好再落盘**：闸门不过就一个字节都不写
    method = render_method(facts, source_url=source_url)

    written = []
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    for stem, *_ in plan:
        for e in FORMATS:
            dst = out / "figures" / f"{stem}.{e}"
            shutil.copyfile(root / "figures" / f"{stem}.{e}", dst)
            written.append(dst)
    shutil.copyfile(root / "LICENSE", out / "LICENSE")
    written.append(out / "LICENSE")
    (out / "index.html").write_text(page, encoding="utf-8", newline="\n")
    written.append(out / "index.html")
    (out / "method.html").write_text(method, encoding="utf-8", newline="\n")
    written.append(out / "method.html")
    return {"written": written, "source_url": source_url, "notes": notes}


# ---------------------------------------------------------------- 静态托管版（Static 分支）

#: 静态托管版要一起发的**页面资源**（都在 `webui_static/` 下）。
#: 少一个 ⇒ 托管上直接白屏/无样式，所以组装期逐个查在不在。
APP_ASSETS = ("index.html", "app.css", "app.js", "figs2d.css", "figs2d.js", "fig3.css", "fig3.js")

#: 静态页里**不许**出现的东西 —— 托管的静态站没有后端，出现即等于坏链或没替换掉的模板。
#: `/api/` 与 `/static/`＝指向不存在的服务端；`__XXX__`＝服务端占位符没被冻结。
FORBIDDEN_IN_APP = ("/api/", "/static/", "__FIG1NOTES__", "__FIG2NOTES_STATIC__", "__FIG2NOTES_SCAN__",
                    "__PRESETS__", "__ENVPRESETS__", "__DEFAULTS__", "__META__", "__FIG3ROWS__",
                    "__PRESETCHIPS__", "__PRESETSELECT__", "__SOLVER__")
#: ⚠ `__CATALOG__` / `__NOTES__` **不在此列**：它们是本设计里页面合法使用的全局名
#: （`catalog.js` / `notes.js` 用 `<script src>` 赋的，见 `build_static_app`）——
#: 当初那张清单是"服务端占位符"，别把新的全局名一起禁掉（2026-10-05 自己踩过一次，闸门当场拦下）。

#: 图注 JSON 的标题（与页面里那条 `<summary>` 同一句话；文本本身仍来自 `figures`）。
NOTES_TITLE = "图注（原先画在图里，现已移到页面）"


def check_app_asset(name: str, text: str) -> list:
    """静态页资源的**路径/占位符闸门** —— 返回问题清单（空 = 过）。

    规则两条（都能被反证演练）：① 引用一律**相对**（不许 `/x`、不许 `http(s)://`）；
    ② 不许出现 `FORBIDDEN_IN_APP` 里的任何一条（后端路径或没冻结的服务端占位符）。
    """
    problems = []
    for token in FORBIDDEN_IN_APP:
        if token in text:
            problems.append(f"{name}: 出现 `{token}`（静态站没有后端/服务端占位符）")
    for ref in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', text):
        if ref.startswith(("/", "http://", "https://", "//")):
            problems.append(f"{name}: 引用不是相对路径：{ref}")
    return problems


def build_static_app(out_dir, *, root=DEFAULT_ROOT, source_url: str | None = None,
                     api_base: str | None = None, backend_enabled: bool = True,
                     assets=APP_ASSETS, plan=PLAN) -> dict:
    """组装**静态托管版**（GitHub Pages / Cloudflare）：页面 + 目录 + 图注 + 图件 + 许可 + γ 口径页。

    数据全部走**相对路径的静态 JSON**（`catalog.json` / `notes.json`）：页面零 `/api`、零后端，
    切弹池由客户端自渲染（`figs2d.js` / `fig3.js`）。目录与图注**复用壳那边的单一出处**
    （`webui.catalog_payload()` / `webui.page_figure_notes()`），本函数不另写一份口径。
    """
    from . import webui                                   # 惰性：只在组装静态站时才需要
    root, out = Path(root), Path(out_dir)
    src_dir = Path(root) / "src" / "missile_sim" / "webui_static"
    payload = webui.catalog_payload()
    # 用户 2026-10-05 口径：**静态站全红** —— 静态站是"什么都没有输入"的那一态，
    # 不存在"给定计算后的基准弹"，所以不许有绿标。目录里 `standard` 自带 `DEFAULT_MISSILE`，
    # 渲染器/壳据此把 PL-12 画成 `base_color`（绿）+ 标注「基准」⇒ 在这里**置空**，
    # 两个渲染器（`figs2d.js` / `fig3.js`）与壳的 chips 就都不再有基准弹。
    payload["standard"] = ""
    notes_all = webui.page_figure_notes()
    notes = {"title": NOTES_TITLE, "fig1": list(notes_all.get("fig1") or ()),
             "fig2": list(notes_all.get("fig2_static") or ())}
    if not payload.get("missiles") or not notes["fig1"] or not notes["fig2"]:
        raise GateError("静态托管版要的目录/图注拿不到（webui.catalog_payload / page_figure_notes）")

    # ① 先全部读进内存并过闸门 —— 不过就一个字节都不写（与图册同一条纪律）
    texts, problems = {}, []
    for name in assets:
        p = src_dir / name
        if not p.is_file():
            problems.append(f"页面资源不在：webui_static/{name}")
            continue
        texts[name] = p.read_text(encoding="utf-8")
        problems.extend(check_app_asset(name, texts[name]))
    facts = read_site_facts(root=root)
    metas = [read_card_meta(mn, fk, root=root) for _s, mn, _n, _t, _su, _no, fk in plan]
    if problems:
        raise GateError("静态托管版闸门不过：\n  " + "\n  ".join(problems))

    # ② 落盘
    written = []
    out.mkdir(parents=True, exist_ok=True)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    for name, text in texts.items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        written.append(out / name)
    for name, rec in (("catalog.json", payload), ("notes.json", notes),
                      ("catalog.js", payload), ("notes.js", notes)):
        text = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        if name.endswith(".js"):
            # ⚠ **双击 index.html（`file://`）时浏览器禁止 `fetch()` 读本地文件**（按跨源拦掉），
            # 所以数据必须能用 `<script src>` 载入：JSON 是 JS 字面量的子集，赋值给全局即可。
            # 页面取值顺序 = 先全局、缺了再 fetch（托管环境两条都通）。
            g = "__CATALOG__" if name == "catalog.js" else "__NOTES__"
            text = f"window.{g} = {text};\n"
        else:
            text += "\n"
        # ⚠ 用 write_bytes 而不是 write_text：后者在 Windows 上会把换行翻成 CRLF，而仓库 blob 是 LF
        # ⇒ "发布字节 = 构建字节" 不成立（2026-10-05 实测：只差一个尾随 CR，内容一致）。
        (out / name).write_bytes(text.encode("utf-8"))
        written.append(out / name)
    for stem, *_ in plan:
        for e in FORMATS:
            shutil.copyfile(root / "figures" / f"{stem}.{e}", out / "figures" / f"{stem}.{e}")
            written.append(out / "figures" / f"{stem}.{e}")
    (out / "method.html").write_text(render_method(facts, source_url=source_url),
                                     encoding="utf-8", newline="\n")
    written.append(out / "method.html")
    # `.nojekyll`：GitHub Pages 默认过一遍 Jekyll（会忽略下划线开头的文件、也会多一层处理）。
    # 我们不需要它，放一个空文件直接关掉 —— 发布到 `gh-pages` 分支时这个文件就在站点根。
    (out / ".nojekyll").write_text("", encoding="utf-8", newline="\n")
    written.append(out / ".nojekyll")
    shutil.copyfile(root / "LICENSE", out / "LICENSE")
    written.append(out / "LICENSE")
    # ⚠ 后端接线 = **构建期注入**（2026-10-05 裁决，见 docs/STAGE-C.md §2）：
    # 只有调用方**显式给了 `api_base`** 才生成 `backend.js`（`window.__BACKEND__`）并在 `index.html`
    # 里引用它；**没给就完全不生成、完全不引用** ⇒ 无后端时页面与"纯静态版"**逐字节等价、零请求** ✓
    # （运行时探测做不到这一点：浏览器要知道"文件在不在"必然发一次请求 ✗）。
    # `backend.js` 是生成文件，**不进 `assets`** ⇒ 上面那条资源闸门不扫它（URL 字面量不会落在被扫资产里）；
    # `app.js`/`figs2d.js`/`fig3.js` 只许引用 `window.__BACKEND__`（判据在 test_static_pool_page）。
    if api_base:
        if not str(api_base).startswith(("http://", "https://")):
            raise GateError(f"api_base 必须是 http(s) URL：{api_base!r}")
        backend_js = ('window.__BACKEND__ = ' +
                      json.dumps({"api_base": str(api_base).rstrip("/"),
                                  "enabled": bool(backend_enabled)},
                                 ensure_ascii=False, separators=(",", ":")) + ";\n")
        (out / "backend.js").write_bytes(backend_js.encode("utf-8"))
        written.append(out / "backend.js")
        idx = out / "index.html"
        html = idx.read_text(encoding="utf-8")
        tag = '<script src="./backend.js"></script>\n'
        if tag not in html:
            # 引用插在第一条页面脚本之前（顺序无所谓，但必须在 app.js 读取 __BACKEND__ 之前）
            html = html.replace('<script src="./catalog.js">',
                                tag + '<script src="./catalog.js">', 1)
            idx.write_bytes(html.encode("utf-8"))
    return {"written": written, "payload": payload, "notes": notes,
            "cards": [m.get("solver") for m in metas], "source_url": source_url,
            "backend": {"api_base": api_base, "enabled": bool(backend_enabled) if api_base else False}}
