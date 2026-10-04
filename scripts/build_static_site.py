# -*- coding: utf-8 -*-
"""薄壳 CLI：调用 `missile_sim.sitebuild` 生成纯静态图册（路径 A）。

逻辑放在 `src/missile_sim/sitebuild.py` 里，因为 `scripts/` **不随分发包**，
而那条判据（`tests/test_static_site.py`）必须在**包内自检**里也能跑。

    python scripts\\build_static_site.py
    python scripts\\build_static_site.py --out D:\\site --source-url https://github.com/<owner>/missile-sim
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from missile_sim import sitebuild  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把成品图打成纯静态站（路径 A / 静态托管版）")
    ap.add_argument("--out", default=str(ROOT / "build" / "site"), help="输出目录（默认 build/site）")
    ap.add_argument("--app", action="store_true",
                    help="组装**静态托管版**（左栏只留弹池的页面 + catalog.json/notes.json，"
                         "可直接丢 GitHub Pages / Cloudflare）；默认只出图册")
    ap.add_argument("--source-url", default=None,
                    help="公开源码仓库地址；给了才会在页脚出现链接（不给就不写占位 URL）")
    args = ap.parse_args(argv)
    out = Path(args.out) if not args.app else Path(args.out)
    try:
        res = (sitebuild.build_static_app(out, source_url=args.source_url, root=ROOT)
               if args.app else sitebuild.build(out, source_url=args.source_url, root=ROOT))
    except sitebuild.GateError as exc:
        print(f"[拒绝出站] {exc}")
        return 2
    total = sum(p.stat().st_size for p in res["written"])
    kind = "静态托管版" if args.app else "静态图册"
    print(f"{kind}：{out.resolve()}")
    for p in res["written"]:
        print(f"  {p.stat().st_size:>9,} B  {p.name}")
    print(f"共 {len(res['written'])} 个文件 · {total / 1024:.0f} KB")
    if args.app:
        pay = res["payload"]
        print(f"  目录：{pay['computable']}/{pay['count']} 可算、不可算 {len(pay['unsupported'])} 条"
              f"；图注 fig1 {len(res['notes']['fig1'])} 条 / fig2 {len(res['notes']['fig2'])} 条")
        print("  发布：整个目录丢 GitHub Pages 或 Cloudflare Pages 即可（页面零 /api、零后端）")
    if not args.source_url:
        print("（未给 --source-url，页面里没有源码链接）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
