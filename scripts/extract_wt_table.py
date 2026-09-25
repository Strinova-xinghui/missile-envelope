"""从 E:\\WT\\WT.xlsx 的 "AAM (ARH)" 表提取公式与数值，按表内公式复算 ΔV 与 BC，并与参考图坐标对照。

表内公式（第 13/14/18/19/20/87 行）：
    Isp1 = t1·F1/(9.81·m1)
    ΔV1  = Isp1·9.81·ln(m0/(m0-m1))
    Isp2 = t2·F2/(9.81·m2)
    ΔV2  = Isp2·9.81·ln((m0-m1)/(m0-m1-m2))
    Total ΔV = ΔV1 + ΔV2（无二级则为 ΔV1）
    BC   = (m0 - m1 - m2) / (k · (d/2000)^2 · π)

输出：
    results/wt_table_aam_arh.json   逐列原始参数、公式与复算值（含与缓存值的差异）
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
XLSX = Path(r"E:\WT\WT.xlsx")
SHEET = "AAM (ARH)"
OUT = ROOT / "results" / "wt_table_aam_arh.json"

# 表内行号（1-based）
ROW = {
    "name": 1,
    "m0": 3, "m1": 4, "m2": 5, "d_mm": 6, "length": 7,
    "f1": 10, "t1": 11, "t1_delay": 15,
    "f2": 16, "t2": 17,
    "dv_total": 20, "bc": 87, "k": 86,
}


def as_number(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("-", "", "n/a"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def compute(m0, m1, m2, f1, t1, f2, t2, k, d_mm):
    if not (m0 and m1 and k and d_mm):
        return None
    isp1 = t1 * f1 / (9.81 * m1) if (t1 and f1) else None
    dv1 = isp1 * 9.81 * math.log(m0 / (m0 - m1)) if isp1 else None
    isp2 = dv2 = None
    if m2 and f2 and t2:
        isp2 = t2 * f2 / (9.81 * m2)
        dv2 = isp2 * 9.81 * math.log((m0 - m1) / (m0 - m1 - m2))
    if dv1 is None and dv2 is None:
        dv = None
    else:
        dv = (dv1 or 0.0) + (dv2 or 0.0)
    bc = (m0 - m1 - (m2 or 0.0)) / (k * (d_mm / 2000.0) ** 2 * math.pi)
    return {"isp1": isp1, "dv1": dv1, "isp2": isp2, "dv2": dv2, "dv_total": dv, "bc": bc}


def _close(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def main() -> int:
    import openpyxl

    wb_f = openpyxl.load_workbook(XLSX, read_only=True, data_only=False)
    wb_v = openpyxl.load_workbook(XLSX, read_only=True, data_only=True)
    ws_f, ws_v = wb_f[SHEET], wb_v[SHEET]

    def cell(ws, row, col):
        return ws.cell(row=row, column=col).value

    # 弹名（第 1 行），跳过 A 列标签
    cols = []
    for c in range(2, ws_f.max_column + 1):
        nm = cell(ws_f, ROW["name"], c)
        if nm:
            cols.append((c, str(nm).strip()))

    rows_out = []
    print(f"{'弹':<28} {'ΔV表内':>8} {'ΔV复算':>8} {'BC表内':>9} {'BC复算':>9} {'一致':>5}")
    for c, name in cols:
        rec = {"col": openpyxl.utils.get_column_letter(c), "name": name}
        for key, r in ROW.items():
            if key == "name":
                continue
            rec[key] = cell(ws_v, r, c) if key in ("dv_total", "bc") else cell(ws_f, r, c)
            rec[f"{key}_formula"] = cell(ws_f, r, c)
        got = compute(as_number(rec["m0"]), as_number(rec["m1"]), as_number(rec["m2"]),
                      as_number(rec["f1"]), as_number(rec["t1"]),
                      as_number(rec["f2"]), as_number(rec["t2"]),
                      as_number(rec["k"]), as_number(rec["d_mm"]))
        rec["computed"] = got
        v_dv = as_number(rec["dv_total"])
        v_bc = as_number(rec["bc"])
        rec["match"] = bool(
            got and _close(got["dv_total"], v_dv, 0.5) and _close(got["bc"], v_bc, 1.0)
        )
        rows_out.append(rec)
        def fmt(x, spec):
            return format(x, spec) if isinstance(x, (int, float)) else str(x)

        if got:
            print(f"{name[:28]:<28} {fmt(v_dv, '8.1f')} {fmt(got['dv_total'], '8.1f')} "
                  f"{fmt(v_bc, '9.1f')} {fmt(got['bc'], '9.1f')} "
                  f"{'OK' if rec['match'] else 'DIFF':>5}")
        else:
            print(f"{name[:28]:<28} {fmt(v_dv, '8.1f')} {'—':>8} {fmt(v_bc, '9.1f')} {'—':>9} {'缺数据':>5}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"source": str(XLSX), "sheet": SHEET, "rows": rows_out},
                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\n已写出 {OUT}")
    ok = sum(1 for r in rows_out if r.get("match"))
    print(f"公式复算与表内缓存值一致：{ok}/{len(rows_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
