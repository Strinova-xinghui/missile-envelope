"""工作流的本地网页表单（只用标准库 http.server，不引第三方依赖）。

启动：python scripts/workflow.py web   （或 python scripts/workflow_web.py）
默认监听 127.0.0.1:8765，浏览器打开后填参数 → 生成 → 直接看对比图。

安全：只绑定 127.0.0.1；只接受本机请求；生成的产物固定落在本仓库 figures/ 与 results/ 下，
不做任意路径写入。
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "src"))

HOST = "127.0.0.1"
PORT = 8765
_LOCK = threading.Lock()

FORM_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>导弹弹道工作流</title>
<style>
  body {{ font-family: "Microsoft YaHei", system-ui, sans-serif; margin: 24px; color: #222; }}
  h1 {{ font-size: 20px; }}
  form {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px;
         max-width: 1100px; padding: 16px; border: 1px solid #dde3ea; border-radius: 8px; background: #fafbfc; }}
  label {{ display: flex; flex-direction: column; font-size: 12px; color: #556; gap: 4px; }}
  input, select {{ padding: 6px 8px; font-size: 14px; border: 1px solid #cfd8e3; border-radius: 4px; }}
  button {{ grid-column: 1 / -1; padding: 10px; font-size: 15px; background: #1f4e79; color: #fff;
            border: 0; border-radius: 6px; cursor: pointer; }}
  button:hover {{ background: #163a5c; }}
  .note {{ font-size: 12px; color: #667; margin: 10px 0 18px; max-width: 1100px; }}
  .err {{ background: #fdecea; border-left: 4px solid #c62828; padding: 12px; margin: 12px 0;
          white-space: pre-wrap; font-family: Consolas, monospace; font-size: 12px; max-width: 1100px; }}
</style></head><body>
<h1>导弹弹道工作流：自定义输入 → 仿真 → 对比图</h1>
<p class="note">输入约定：<b>vt 为负=迎头</b>（距离闭合），正=尾追；高抛角必须 &lt; 40°；
ΔV/BC 范围决定等时线网格（工况数 = 行×列，建议 ≤ 4000 以保证响应速度）。
当前基准：ΔV={dv0:.0f} m/s、BC={bc0:.0f}（CxK={cxk0:.3f}）、干重 {m0:.3f} kg。</p>
{error}
<form method="post" action="/run">
  <label>发射方速度 vm0 [m/s]<input name="vm0" type="number" step="1" value="{vm0}"></label>
  <label>目标速度 vt [m/s]（负=迎头）<input name="vt" type="number" step="1" value="{vt}"></label>
  <label>发射高度 [m]<input name="alt" type="number" step="100" value="{alt}"></label>
  <label>目标高度 [m]<input name="target_alt" type="number" step="100" value="{target_alt}"></label>
  <label>初始水平距离 [m]<input name="range" type="number" step="500" value="{rng}"></label>
  <label>标准弹<select name="standard">{standard_opts}</select></label>
  <label>燃烧档<select name="burn">{burn_opts}</select></label>
  <label>高抛判据<select name="loft_rule">{loft_rule_opts}</select></label>
  <label>高抛角 [度] (&lt;40，留空=用标准弹)<input name="loft" type="number" step="0.5" value="{loft}"></label>
  <label>命中半径 [m]<input name="hit_radius" type="number" step="1" value="{hit_radius}"></label>
  <label>等时线步长 [s]<input name="iso_step" type="number" step="1" value="{iso_step}"></label>
  <label>ΔV 下限 [m/s]<input name="dv_min" type="number" step="10" value="{dv_min}"></label>
  <label>ΔV 上限 [m/s]<input name="dv_max" type="number" step="10" value="{dv_max}"></label>
  <label>ΔV 步长 [m/s]<input name="dv_step" type="number" step="5" value="{dv_step}"></label>
  <label>BC 下限 [kg/m²]<input name="bc_min" type="number" step="50" value="{bc_min}"></label>
  <label>BC 上限 [kg/m²]<input name="bc_max" type="number" step="50" value="{bc_max}"></label>
  <label>BC 步长 [kg/m²]<input name="bc_step" type="number" step="10" value="{bc_step}"></label>
  <label>同时画 blkx 复算点
    <select name="show_blkx"><option value="1" {blkx_on}>是</option><option value="0" {blkx_off}>否</option></select>
  </label>
  <button type="submit">生成对比图</button>
</form>
</body></html>
"""

RESULT_TEMPLATE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>结果 - 导弹弹道工作流</title>
<style>
  body {{ font-family: "Microsoft YaHei", system-ui, sans-serif; margin: 24px; color: #222; }}
  h1 {{ font-size: 20px; }} h2 {{ font-size: 16px; margin-top: 26px; }}
  .meta {{ font-size: 13px; color: #445; margin-bottom: 10px; }}
  img {{ max-width: 100%; border: 1px solid #dde3ea; border-radius: 6px; }}
  table {{ border-collapse: collapse; font-size: 13px; margin-top: 8px; }}
  th, td {{ border: 1px solid #dde3ea; padding: 4px 10px; text-align: center; }}
  th {{ background: #eef2f7; }}
  a.back {{ display: inline-block; margin: 16px 0; }}
</style></head><body>
<h1>结果</h1>
<div class="meta">{meta}</div>
<h2>主对比图</h2><img src="/fig/{main_png}" alt="main">
<h2>细节图</h2><img src="/fig/{detail_png}" alt="detail">
<h2>各型弹（参考图口径）</h2>
{table_ref}
<h2>各型弹（blkx 复算口径）</h2>
{table_blkx}
<h2>产物</h2><div class="meta">{files}</div>
<a class="back" href="/">← 返回修改输入</a>
</body></html>
"""


def _fnum(form, key, default):
    try:
        return float(form.get(key, [default])[0])
    except (TypeError, ValueError):
        return float(default)


def _table(rows):
    if not rows:
        return "<p class='meta'>（未生成）</p>"
    head = ("<tr><th>弹</th><th>ΔV [m/s]</th><th>BC</th><th>CxK</th>"
            "<th>状态</th><th>命中时间 [s]</th><th>命中点速度 [m/s]</th><th>最大高度 [m]</th></tr>")
    body = "".join(
        f"<tr><td>{r['name']}</td><td>{r['dv']:.1f}</td><td>{r['bc']:.0f}</td><td>{r['cxk']:.3f}</td>"
        f"<td>{r['status']}</td><td>{('' if r['t_hit'] is None else format(r['t_hit'], '.2f'))}</td>"
        f"<td>{r['v_impact']:.0f}</td><td>{r['max_alt']:.0f}</td></tr>" for r in rows)
    return f"<table>{head}{body}</table>"


class Handler(BaseHTTPRequestHandler):
    server_version = "MissileWorkflow/1.0"

    def log_message(self, fmt, *args):  # 静音默认访问日志，只在出错时打印
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._send(200, self._form_html().encode("utf-8"))
            return
        if parsed.path.startswith("/fig/"):
            name = Path(parsed.path[5:]).name
            target = ROOT / "figures" / name
            if target.exists() and target.suffix == ".png":
                self._send(200, target.read_bytes(), "image/png")
                return
            name = Path(parsed.path[5:]).name
            target = ROOT / "results" / name
            if target.exists() and target.suffix in (".png", ".csv", ".json"):
                ctype = {"png": "image/png", "csv": "text/csv; charset=utf-8",
                         "json": "application/json"}.get(target.suffix.lstrip("."), "application/octet-stream")
                self._send(200, target.read_bytes(), ctype)
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/run":
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))

        cfg = {
            "scenario": {
                "vm0": _fnum(form, "vm0", 300.0),
                "vt": _fnum(form, "vt", -300.0),
                "alt": _fnum(form, "alt", 10000.0),
                "target_alt": _fnum(form, "target_alt", 10000.0),
                "range": _fnum(form, "range", 50000.0),
            },
            "standard": {
                "name": form.get("standard", ["PL-12"])[0],
                "burn": form.get("burn", ["finite"])[0],
            },
            "sim": {
                # 标准弹先解析；下面的显式覆盖排在它之后（覆盖优先）
                "loft_rule": form.get("loft_rule", ["game"])[0],
            },
            "sweep": {
                "dv_min": _fnum(form, "dv_min", 810.0),
                "dv_max": _fnum(form, "dv_max", 1110.0),
                "dv_step": _fnum(form, "dv_step", 20.0),
                "bc_min": _fnum(form, "bc_min", 2450.0),
                "bc_max": _fnum(form, "bc_max", 3800.0),
                "bc_step": _fnum(form, "bc_step", 50.0),
            },
            "compare": {
                "iso_step": _fnum(form, "iso_step", 1.0),
                "show_blkx": form.get("show_blkx", ["1"])[0] == "1",
                "show_reference": True,
                "tag": "web",
            },
        }
        loft = _fnum(form, "loft", None)
        if loft is not None:
            if not (0.0 <= loft < 40.0):
                self._send(400, self._form_html("高抛角必须在 [0, 40) 度范围内").encode("utf-8"))
                return
            cfg["sim"]["theta_loft_deg"] = loft
        hr = _fnum(form, "hit_radius", None)
        if hr is not None and hr > 0:
            cfg["sim"]["hit_radius"] = hr
        cells = ((cfg["sweep"]["dv_max"] - cfg["sweep"]["dv_min"]) / max(cfg["sweep"]["dv_step"], 1e-9) + 1) * \
                ((cfg["sweep"]["bc_max"] - cfg["sweep"]["bc_min"]) / max(cfg["sweep"]["bc_step"], 1e-9) + 1)
        if cells > 8000:
            self._send(400, self._form_html(f"工况数过多（约 {int(cells)}），请增大步长或缩小范围").encode("utf-8"))
            return

        try:
            with _LOCK:
                import workflow

                summary = workflow.run_workflow(cfg, verbose=False)
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            self._send(500, self._form_html(f"运行失败：\n{tb}").encode("utf-8"))
            return

        main_png = Path(summary["_paths"]["main_png"]).name
        detail_png = Path(summary["_paths"]["detail_png"]).name
        res = summary["results"]
        meta = (f"命中率 {res['hit_rate'] * 100:.1f}%（{res['n_hit']}/{summary['grid']['n_cases']}）；"
                f"命中时间 {res['t_hit_min']:.1f}~{res['t_hit_max']:.1f} s；"
                f"单调性违例 {res['monotonic_issues']}；仿真耗时 {summary['wall_time_s']:.1f} s")
        files = " ｜ ".join(f"<a href='/fig/{Path(p).name}'>{Path(p).name}</a>"
                           for p in summary["_paths"].values())
        html = RESULT_TEMPLATE.format(
            meta=meta, main_png=main_png, detail_png=detail_png,
            table_ref=_table(summary.get("missiles_reference", [])),
            table_blkx=_table(summary.get("missiles_blkx", [])),
            files=files,
        )
        self._send(200, html.encode("utf-8"))

    def _form_html(self, error: str | None = None) -> str:
        from missile_sim import standard as std_mod
        from missile_sim.config import ballistic_coefficient, delta_v_equiv, load_config

        m = load_config()
        err_html = f"<div class='err'>{error}</div>" if error else ""
        show_blkx = True
        try:
            names = std_mod.pool_names()
        except Exception:                                  # noqa: BLE001
            names = [m.standard.name or "PL-12"]
        cur_std = m.standard.name or (names[0] if names else "")
        opts = lambda vals, cur: "".join(                 # noqa: E731
            f'<option value="{v}"{" selected" if v == cur else ""}>{v}</option>' for v in vals)
        return FORM_TEMPLATE.format(
            dv0=delta_v_equiv(m), bc0=ballistic_coefficient(m.drag.cxk, m), cxk0=m.drag.cxk,
            m0=m.mass.mass_end,
            vm0=m.scenario.vm0, vt=m.scenario.vt, alt=m.scenario.alt,
            target_alt=m.scenario.target_alt if m.scenario.target_alt is not None else m.scenario.alt,
            rng=m.scenario.range, loft="", hit_radius="",
            iso_step=1.0, dv_min=810.0, dv_max=1110.0, dv_step=20.0,
            bc_min=2450.0, bc_max=3800.0, bc_step=50.0,
            standard_opts=opts(names, cur_std),
            burn_opts=opts(("finite", "instant"), m.standard.burn),
            loft_rule_opts=opts(("game", "heuristic"), m.sim.loft_rule),
            error=err_html, blkx_on="selected" if show_blkx else "", blkx_off="" if show_blkx else "selected",
        )


def serve(host: str = HOST, port: int = PORT) -> int:
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{httpd.server_port}/"
    print(f"工作流网页已启动：{url}")
    print("（Ctrl+C 结束；只监听本机回环地址）")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
