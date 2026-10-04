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
import shutil
from pathlib import Path

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


def card_html(stem: str, no: str, title: str, sub: str, note: str, meta: dict) -> str:
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
    return f"""    <section class="card" id="{stem}">
      <header class="cardhead">
        <span class="no">{no}</span>
        <h2>{title}</h2>
        <p class="sub">{sub}</p>
      </header>
      <a class="shot" href="figures/{stem}.png"><img src="figures/{stem}.png" alt="{no} {title}"></a>
      <p class="note">{note}</p>
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
        card_html(stem, no, title, sub, note, meta)
        for (stem, _mn, no, title, sub, note, _fk), meta in zip(plan, metas))
    src_line = ""
    if source_url:
        src_line = f' 源码与复现命令：<a href="{source_url}">{source_url}</a>。'
    page = PAGE.format(head_meta=head_meta, cards=cards, source_line=src_line)

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
    return {"written": written, "source_url": source_url, "notes": notes}
