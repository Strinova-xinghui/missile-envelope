#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""组装「免安装」分发包 —— 对方双击 `启动.bat` 直接进 UI，什么都不用装。

    python make_dist.py --prepare     # 一次性：下载内嵌 Python + 装依赖（约 90 MB，需联网）
    python make_dist.py               # 组装 dist/导弹包线图/
    python make_dist.py --zip         # 组装并打成 zip

产物结构（根目录**只有一个文件**，其余都在二级目录 `app/` 里）::

    dist/导弹包线图/
    ├── 启动.bat                     ← 对方只需要双击这个
    └── app/
        ├── run_ui.py                启动逻辑（重定向内核缓存 → 注册中文字体 → 起 WebUI）
        ├── python/                  内嵌 Python 3.14 + numpy/matplotlib，不碰系统环境
        ├── src/missile_sim/         外壳代码
        ├── vendor/wt-missile/       求解器内核（只读副本）
        ├── kernel-cache/            预编译 C 内核（对方没装 MSVC 也能吃 compiled-c）
        ├── fonts/                   中文字体子集（对方是英文系统也不出方块）
        ├── configs/ figures/ results/ docs/
        └── 使用说明.txt

为什么这些文件是这么摆的
------------------------
* `src/missile_sim/spec.py` 用 `Path(__file__).resolve().parents[2]` 推仓库根 ⇒ 只要
  `app/` 下保持 `src/ vendor/ figures/ results/` 的相对结构，所有路径**自动正确**，
  业务代码一行都不用改。这也是为什么 `app/` 不能随便拆。
* 内核在 `%LOCALAPPDATA%\\wt-missile\\compiled-fast\\<hash>.dll` 找编译产物。把
  `LOCALAPPDATA` 指到包内 `kernel-cache/`，预编译内核就随包走 —— 对方没有 C 编译器也
  能拿到 `compiled-c`（本机 MSVC 19.44，内嵌 Python 同为 MSC v.1944，ABI 对得上）。
  对方机器上加载失败时会自动退回纯 Python，**结果一模一样，只是慢 20 倍**。
* `figures/` 里只挑新外壳的产物。仓库里还堆着旧外壳的 `workflow_*` / `fig_*_baseline`
  等历史图，那些不该发给别人。
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
PACKAGING = ROOT / "packaging"      # 面向**收件人**的文案模板
APP_NAME = "导弹包线图"
BUNDLE = DIST / APP_NAME
APP = BUNDLE / "app"

# 内嵌 Python（华为云镜像；python.org 直连在本机反复中断）
PY_VERSION = "3.14.7"
PY_URLS = [
    f"https://mirrors.huaweicloud.com/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip",
    f"https://registry.npmmirror.com/-/binary/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip",
    f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip",
]
PYPI_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"
DEPS = ["numpy", "matplotlib"]

# 中文字体：思源黑体（SIL OFL 1.1，可再分发）。整份 17 MB 太大，子集化到常用汉字。
FONT_SRC = Path(r"C:\Windows\Fonts\NotoSansSC-VF.ttf")
FONT_OUT = "NotoSansSC-subset.ttf"

# 只带新外壳的产物 —— 仓库 figures/ 里还有旧外壳的历史图，不发出去。
FIGURES_KEEP = [
    "fig_isotime_plane_default.png",         # 图1：ΔV–BC 包线图
    "fig_isotime_plane_default.pdf",
    "fig_isotime_plane_default.svg",
    "fig_bg_plane_default.png",              # 图2：β–γ 能力平面
    "fig_bg_plane_default.pdf",
    "fig_bg_plane_default.svg",
    "fig_traj_default.png",                  # 图3：机动想定轨迹（直飞 → crank → 39）
    "fig_traj_default.pdf",
    "fig_traj_default.svg",
    "fig_traj_preview_default.png",          # 图3 的输入阶段 3D 预览（沙盒/查看器的静态版）
    "fig_traj_preview_default.pdf",
    "fig_traj_preview_default.svg",
]
RESULTS_KEEP = [
    "plane_default.json",
    "plane_default_cases.csv",
    "plane_default_isolines.csv",
    "bg_default.json",                       # 图2 的 manifest / 逐型表 / 网格 / 等时线
    "bg_default_points.csv",
    "bg_default_cases.csv",
    "bg_default_isolines.csv",
    "compare_default.csv",
    "reference_fig.png",                      # 用户给的参考图，交流时用来对比
    # --- 图3 / 空战沙盒：`/sandbox` 与 `/api/sandbox/<key>` **只读**这几份产物 ----
    "traj_default.json",                     # 锚点/分段/marks
    "traj_default_missile.csv",              # 导弹逐点（沙盒回放 + 悬停读数）
    "traj_default_target.csv",               # 敌机逐点
    "traj_default_segments.csv",             # 目标航向分段（配色依据）
    # --- 图4：`/fig4` 与 `/api/fig4/<tag>` **只读**产物，不解算 ----
    "fig4_default.json",                     # 11 个标称三参数点 + 逐列拟合
    "fig4_default_cases.csv",
    # --- 11 型权威表：文档/对比用，也是 `-k pool_mapping` 黄金值的出处 ----
    "missile_standards.json",
]
#: `fig4_cube_<弹名>_<指纹>.json` 的文件名里带**指纹**（`cube_key()` = 场景/档位/网格/
#: 弹名/求解器 sha 的哈希[:8]），所以按 glob 带 —— 内核或预设一动指纹就变，不用回来改这里。
#: ⚠ 少了它 `/api/fig4/<tag>/layers` 会从"200 秒开"退化成"202 + 现扫几百个工况"。
RESULTS_GLOBS = ["fig4_cube_*.json"]

#: `configs/` **整目录**拷（而不是挑文件）：`web_default.json` 是 WebUI 的机器配置，
#: `presets.json` 是共享环境预设层（`presets.ENV_PRESET_PATH`）—— **少它 `GET /`
#: 会直接 500**（`presets.resolve()` → `FileNotFoundError`）。以后 configs/ 里再加
#: 什么，只要不是下面这些"私货"名字，就自动跟着走。
CONFIGS_DENY = ("*.local.json", "secrets*", "*token*", "*.key", "*.pfx")

#: 不随包的测试模块：这两个是 `spikes/` 的**探究套件**，判据要读 `spikes/**` 的产物。
#: `spikes/` 不随包 ⇒ 它们在包里必然报错（实测 27 项红），而那是"探究记录没带"，
#: 不是"这一包坏了"。排除后包内自检是干净的（实测 455 通过 / 0 失败）。
TESTS_EXCLUDE = ("test_fig3d_spike.py", "test_bg3d_spike.py")

LAUNCHER_BAT = """@echo off
chcp 65001 >nul
title 导弹包线图
cd /d "%~dp0"
echo.
echo   导弹包线图 —— 正在启动，请稍候...
echo.
echo   [许可提醒] 本包含 War Thunder 游戏数据（权利归 Gaijin），
echo              仅限自用与小范围交流，不可公开分发；详见 app\\README.md。
echo.
"%~dp0app\\python\\python.exe" "%~dp0app\\run_ui.py" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
  echo.
  echo   [启动失败] 错误码 %RC%
  echo   请把上面的报错信息截图发给作者。
  echo.
  pause
)
"""

RUN_UI_PY = '''# -*- coding: utf-8 -*-
"""分发包启动器。只做三件事，业务逻辑一律不碰（都在 src/missile_sim/ 里）。

1. 把内核缓存目录指到包内 —— **必须在 import missile_sim 之前**，
   否则 wt_missile 已经按默认的 %LOCALAPPDATA% 找过一遍了。
2. 注册随包的中文字体，让英文系统上也不出方块字。
3. 起 WebUI 并自动打开浏览器。
"""

import os
import sys
import traceback
from pathlib import Path

APP = Path(__file__).resolve().parent

# --- 1) 内核缓存重定向 -------------------------------------------------
# 内核只认 LOCALAPPDATA 这一个环境变量（wt_missile 里写死的），所以只能改它。
# 包里预置了本机编译好的 <hash>.dll；对方没装 MSVC 也能直接吃 compiled-c。
os.environ["LOCALAPPDATA"] = str(APP / "kernel-cache")

# 兜底：万一 ._pth 没生效（被编辑过 / 被解压工具改名），这里再补一次路径。
for rel in ("src", os.path.join("vendor", "wt-missile")):
    p = str(APP / rel)
    if p not in sys.path:
        sys.path.insert(0, p)


def register_cjk_font():
    """把随包字体插到 fonts.sans-serif 最前面。失败不致命 —— 退回系统字体。"""
    font = APP / "fonts" / "NotoSansSC-subset.ttf"
    if not font.exists():
        return None
    try:
        from matplotlib import font_manager

        font_manager.fontManager.addfont(str(font))
        name = font_manager.FontProperties(fname=str(font)).get_name()
        from missile_sim import figures

        if name not in figures._CN_FONTS:
            figures._CN_FONTS.insert(0, name)
        return name
    except Exception as exc:                       # 字体坏了不该让整个程序起不来
        print(f"  [警告] 中文字体注册失败（将用系统字体）：{exc}")
        return None


def main():
    name = register_cjk_font()
    print(f"  中文字体：{name or '（随包字体不可用，改用系统字体）'}")

    from missile_sim import solver, webui

    ident = solver.identity()
    print(f"  求解器  ：{ident.get('model')} v{ident.get('version')}")
    print(f"  身份    ：{str(ident.get('sha256') or '')[:16]}…")
    print(f"  后端    ：{probe_backend(solver)}")

    cfg = APP / "configs" / "web_default.json"
    argv = ["--config", str(cfg), *sys.argv[1:]]
    if "--no-browser" not in argv:          # 转发 --port 之类，但默认仍自动开浏览器
        argv.append("--browser")
    print("  正在启动界面，浏览器会自动打开；关掉这个窗口即退出程序。\\n")
    return webui.main(argv)


def probe_backend(solver):
    """**真跑一次最小工况**看这一包会走哪个内核后端（`backend` 只认真跑过的证据）。

    内嵌 Python + 随包 DLL 的组合在对方机器上能不能加载，只有真跑一次才知道；
    加载失败会自动退回纯 Python（**结果一样，只是慢**），这里如实打印出来。
    """
    from missile_sim.spec import Scene

    try:
        shot = solver.run(Scene(duration_s=0.5), missile="cn_pl12", tier="fast")
    except Exception as exc:                       # 探测本身不该拦住启动
        return f"探测失败（{type(exc).__name__}: {exc}）"
    if not shot.ok:
        return f"探测失败（{shot.error}）"
    if shot.fallback_reason:
        return f"{shot.backend}（回退原因：{shot.fallback_reason}）"
    return shot.backend


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        print("\\n  [启动失败] 详细信息如下：\\n")
        traceback.print_exc()
        raise SystemExit(1)
'''



def log(msg):
    print(f"  {msg}")


def human(n):
    return f"{n / 1048576:.1f} MB"


def tree_size(path):
    return sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())


def rmtree_force(path):
    """删目录，遇到只读属性先清掉再试。

    从 `E:\\WT` 或 git checkout 出来的文件可能带**只读**位，裸 `shutil.rmtree`
    在 Windows 上会直接 `WinError 5` 拒绝访问 —— 而且是在组装到一半时才炸。
    """
    def onexc(func, p, exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except Exception as retry:
            raise RuntimeError(
                f"删不掉 {p}（{retry}）—— 多半还有进程占着它，"
                f"先关掉所有 python.exe 窗口再重跑。"
            ) from retry
    shutil.rmtree(path, onexc=onexc)


def copy_tree(src, dst, *, ignore_pycache=True):
    """拷目录。`__pycache__` 由调用方决定要不要留（site-packages 要留，源码不必）。"""
    ign = shutil.ignore_patterns("__pycache__", "*.pyc") if ignore_pycache else None
    shutil.copytree(src, dst, ignore=ign, dirs_exist_ok=True)


# --------------------------------------------------------------------------
# 1) 准备内嵌 Python（一次性）
# --------------------------------------------------------------------------
def prepare_python(force=False):
    target = BUILD / "py-embed"
    if target.exists() and not force:
        log(f"内嵌 Python 已就绪：{target}")
        return target

    BUILD.mkdir(parents=True, exist_ok=True)
    zip_path = BUILD / "py-embed.zip"

    if not zip_path.exists() or force:
        last = None
        for url in PY_URLS:
            log(f"下载 {url}")
            try:
                with urllib.request.urlopen(url, timeout=180) as resp, \
                        open(zip_path, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                log(f"  ✅ {human(zip_path.stat().st_size)}")
                last = None
                break
            except Exception as exc:
                last = exc
                log(f"  ❌ {exc}")
        if last is not None:
            raise SystemExit("所有镜像都下不动，请手动下载 embed-amd64.zip 放到 "
                             f"{zip_path}")
    else:
        log(f"复用已下载的 {zip_path.name}")

    if target.exists():
        rmtree_force(target)
    log(f"解压到 {target}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target)

    site = target / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    log(f"装依赖 {DEPS}（走 {PYPI_MIRROR}）")
    cmd = [sys.executable, "-m", "pip", "install", "--target", str(site),
           "--upgrade", "--no-warn-script-location", "-i", PYPI_MIRROR, *DEPS]
    rc = subprocess.call(cmd)
    if rc != 0:
        raise SystemExit(f"pip 失败（exit {rc}）")
    log(f"  ✅ {human(tree_size(site))}")

    # 让内嵌解释器能看见 site-packages。路径**相对于 python.exe**，挪包也不会坏。
    write_pth(target)
    log("完成。")
    return target


def write_pth(python_dir):
    """`._pth` 是分发包里唯一把解释器接到项目上的东西。

    内嵌 Python 一旦存在 `._pth` 就进入隔离模式：**忽略 PYTHONPATH**、
    不自动 `import site`。所以 `..\\src` 这类相对路径只能写在这里。
    """
    pth = python_dir / f"python{sys.version_info.major}{sys.version_info.minor}._pth"
    pth.write_text(
        "python314.zip\n"
        ".\n"
        "Lib\\site-packages\n"
        "..\\src\n"
        "..\\vendor\\wt-missile\n",
        encoding="utf-8",
        newline="\n",
    )
    return pth


# --------------------------------------------------------------------------
# 2) 中文字体子集
# --------------------------------------------------------------------------
def make_font_subset():
    out = BUILD / FONT_OUT
    if out.exists():
        log(f"字体子集已就绪：{human(out.stat().st_size)}")
        return out
    if not FONT_SRC.exists():
        log(f"⚠ 找不到 {FONT_SRC}，跳过随包字体（英文系统上中文会出方块）")
        return None

    from fontTools import subset

    chars = set()
    for hi in range(0xB0, 0xF8):                 # GB2312 一/二级汉字
        for lo in range(0xA1, 0xFF):
            try:
                chars.add(bytes([hi, lo]).decode("gb2312"))
            except Exception:
                pass
    chars |= {chr(c) for c in range(0x20, 0x7F)}
    chars |= {chr(c) for c in range(0x370, 0x400)}          # 希腊字母 Δ β
    chars |= set("·—…（）【】、。！？；：《》〈〉“”‘’～￥±×÷≤≥≈∞←→↑↓")

    opts = subset.Options()
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(str(FONT_SRC), opts)
    sub = subset.Subsetter(options=opts)
    sub.populate(text="".join(sorted(chars)))
    sub.subset(font)
    subset.save_font(font, str(out), opts)
    log(f"字体子集 {len(chars)} 字 → {human(out.stat().st_size)}")
    return out


# --------------------------------------------------------------------------
# 3) 组装
# --------------------------------------------------------------------------
def build_tree(python_dir, font_subset, *, clean=True):
    if clean and BUNDLE.exists():
        rmtree_force(BUNDLE)
    APP.mkdir(parents=True, exist_ok=True)

    # --- 源码与只读内核 ---
    copy_tree(ROOT / "src" / "missile_sim", APP / "src" / "missile_sim")
    log("src/missile_sim/")
    copy_tree(ROOT / "vendor" / "wt-missile", APP / "vendor" / "wt-missile")
    log("vendor/wt-missile/")

    # --- 内嵌 Python（site-packages 的 __pycache__ 要留着，能省首次启动时间）---
    copy_tree(python_dir, APP / "python", ignore_pycache=False)
    write_pth(APP / "python")
    log(f"python/ {human(tree_size(APP / 'python'))}")

    # --- 配置：整目录（`presets.json` 是共享环境预设层，少它首页 500）---
    cfg_dir = APP / "configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_files = sorted(p for p in (ROOT / "configs").glob("*")
                       if p.is_file() and not any(p.match(pat) for pat in CONFIGS_DENY))
    if not cfg_files:
        raise SystemExit(f"{ROOT / 'configs'} 里一个配置文件都没有，组装必炸")
    for p in cfg_files:
        shutil.copy2(p, cfg_dir / p.name)
    log("configs/" + "、".join(p.name for p in cfg_files))

    # --- 字体 ---
    if font_subset and font_subset.exists():
        (APP / "fonts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(font_subset, APP / "fonts" / FONT_OUT)
        log(f"fonts/{FONT_OUT}")

    # --- 预编译 C 内核 ---
    src_kernel = Path(os.environ.get("LOCALAPPDATA", "")) / "wt-missile" / "compiled-fast"
    if src_kernel.is_dir():
        dst_kernel = APP / "kernel-cache" / "wt-missile" / "compiled-fast"
        dst_kernel.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in src_kernel.iterdir():
            if f.is_file() and f.suffix in (".dll", ".sha256"):
                shutil.copy2(f, dst_kernel / f.name)
                n += 1
        log(f"kernel-cache/ {n} 个文件（对方没装 MSVC 也能吃 compiled-c）")
    else:
        log(f"⚠ 本机没有编译内核（{src_kernel}），分发包将只有纯 Python 档")

    # --- 只挑新外壳的产物 ---
    for name in FIGURES_KEEP:
        s = ROOT / "figures" / name
        if s.exists():
            (APP / "figures").mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, APP / "figures" / name)
    log(f"figures/ {len(list((APP / 'figures').glob('*')))} 个文件")
    for name in RESULTS_KEEP:
        s = ROOT / "results" / name
        if s.exists():
            (APP / "results").mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, APP / "results" / name)
    for pat in RESULTS_GLOBS:                    # 指纹命名的产物（fig4 立方体缓存）
        for s in sorted((ROOT / "results").glob(pat)):
            if s.is_file():
                (APP / "results").mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, APP / "results" / s.name)
    log(f"results/ {len(list((APP / 'results').glob('*')))} 个文件")

    # --- 文档：给**收件人**看的，不是仓库那套 ---
    # 仓库 README 面向开发者，引用了 NOTES.md / docs/RESTART-PLAN.md / make_dist.py
    # 这些**包里根本没有**的东西；照抄过去对方按图索骥只会扑空。
    # 只带这两份：SOLVER-API 是"换内核唯一要读的"，BETA-GAMMA 是"β/γ 到底是什么"
    # （它引用的 tests/ 与 src/ 包里都有，能顺着查）。
    (APP / "docs").mkdir(parents=True, exist_ok=True)
    for name in ("SOLVER-API.md", "BETA-GAMMA.md"):
        s = ROOT / "docs" / name
        if s.exists():
            shutil.copy2(s, APP / "docs" / name)
    shutil.copy2(PACKAGING / "README.app.md", APP / "README.md")
    plain = (PACKAGING / "使用说明.txt").read_bytes().replace(b"\r\n", b"\n")
    (APP / "使用说明.txt").write_bytes(plain.replace(b"\n", b"\r\n"))  # 记事本友好
    log("README.md（面向收件人）+ docs/SOLVER-API.md + docs/BETA-GAMMA.md + 使用说明.txt")

    # --- 自检脚本：对方能自己验证这一包是好的 ---
    # ⚠ 两个 `*_spike` 模块是**开发期的探究套件**，判据要读 `spikes/**` 的产物（`spikes/`
    # 不随包：那是探索记录，不是交付物）。留着它们，收件人跑自检会看到 27 条红字，
    # 而且与"这一包好不好"无关 ⇒ 复制时排除（理由也写进 docs/DISTRIBUTION.md）。
    (APP / "tests").mkdir(parents=True, exist_ok=True)
    for p in sorted((ROOT / "tests").iterdir()):
        if p.is_file() and p.name not in TESTS_EXCLUDE:
            shutil.copy2(p, APP / "tests" / p.name)
    log(f"tests/ {len(list((APP / 'tests').glob('*')))} 个文件"
        f"（排除 {len(TESTS_EXCLUDE)} 个 spike 模块：{'、'.join(TESTS_EXCLUDE)}）")

    # --- 启动器（根目录**唯一**的文件 + app/ 里的实际逻辑）---
    (APP / "run_ui.py").write_text(RUN_UI_PY, encoding="utf-8", newline="\n")
    (BUNDLE / "启动.bat").write_text(LAUNCHER_BAT, encoding="utf-8", newline="\r\n")
    log("启动.bat（根目录）+ app/run_ui.py")


#: 组装完**必须**存在的文件。每一条都对应一个会真的读它的入口（括号里是哪个入口）——
#: 少一条就在组装期炸掉，而不是等对方双击后才发现页面打不开。
REQUIRED_IN_BUNDLE = [
    "python/python.exe",                                    # 启动.bat 直接调它
    "run_ui.py",
    "configs/web_default.json",                             # webui.CONFIG_PATH
    "configs/presets.json",                                 # presets.ENV_PRESET_PATH → GET / 必需
    "src/missile_sim/webui.py",
    "src/missile_sim/webui_static/index.html",               # GET /
    "src/missile_sim/webui_static/app.css",
    "src/missile_sim/webui_static/app.js",
    "src/missile_sim/webui_static/viewer3d.js",              # GET /viewer3d
    "src/missile_sim/webui_static/fig4.js",                  # GET /fig4
    "src/missile_sim/webui_static/sandbox.js",               # GET /sandbox
    "vendor/wt-missile/wt_missile.py",
    "vendor/wt-missile/inputs/resources/2.59.0.28/presets.json",   # 离线求解的前提
    "figures/fig_isotime_plane_default.png",
    "figures/fig_bg_plane_default.png",
    "figures/fig_traj_default.png",
    "results/plane_default.json",
    "results/bg_default.json",
    "results/traj_default.json",                            # GET /sandbox + /api/sandbox/<key>
    "results/traj_default_missile.csv",
    "results/traj_default_target.csv",
    "results/traj_default_segments.csv",
    "results/fig4_default.json",                            # GET /fig4 + /api/fig4/<tag>
    "results/missile_standards.json",
    "README.md",
    "使用说明.txt",
]


def _expected_cf_hash():
    """随包内核的 C 源码指纹 —— 决定 `kernel-cache/` 里该有哪个 dll。算不出来就 None。"""
    try:
        for p in (str(ROOT / "vendor" / "wt-missile"), str(ROOT / "src")):
            if p not in sys.path:
                sys.path.insert(0, p)
        import wt_missile
        return str(wt_missile._CF_HASH)
    except Exception:                                        # noqa: BLE001
        return None


def verify_bundle():
    """组装完**逐条核**关键文件 + 预编译内核是否与被发出去的那份内核对得上。

    这一条是本脚本唯一的"对外契约"检查：`REQUIRED_IN_BUNDLE` 里任何一条缺失都直接抛，
    不静默跳过 —— 上一版的 `configs/presets.json` 就是漏在这里（首页会 500）。
    """
    missing = [rel for rel in REQUIRED_IN_BUNDLE if not (APP / rel).is_file()]
    cubes = sorted((APP / "results").glob("fig4_cube_*.json"))
    if not cubes:
        missing.append("results/fig4_cube_*.json（图4 等时面缓存；少了会退化成现扫几百个工况）")
    if missing:
        raise SystemExit("分发包缺必带文件（组装中止）：\n  - " + "\n  - ".join(missing))
    log(f"必带文件 {len(REQUIRED_IN_BUNDLE)} 条全部在位 + 图4 立方体 {len(cubes)} 份")

    dlls = sorted(p.name for p in (APP / "kernel-cache" / "wt-missile" / "compiled-fast").glob("*.dll"))
    want = _expected_cf_hash()
    if want and f"{want}.dll" in dlls:
        log(f"预编译内核命中：{want[:16]}…（对方没装 MSVC 也是 compiled-c）")
    elif dlls:
        log(f"⚠ kernel-cache 里的 dll 与随包内核**指纹不符**（包里 {[d[:16] for d in dlls]}，"
            f"内核要 {str(want)[:16]}…）⇒ 对方会退回纯 Python（结果一样，慢 20 倍）")
    else:
        log("⚠ 没有预编译内核 ⇒ 对方会退回纯 Python（结果一样，慢 20 倍）")


def prune_bundle():
    """删掉运行时确实用不到的东西。

    ⚠ **每一条都要有实测依据，别凭感觉删。** `PIL` 和 `fontTools` 看着像可选依赖，
    其实是 matplotlib 的**硬依赖**（`colors.py` 直接 `from PIL import Image`，
    `dviread.py` 直接 `import fontTools.agl`）—— 删掉任何一个，整套出图当场报废，
    而且只在第一次出图时报错，很容易漏掉。

    实测安全：numpy / matplotlib 自带的 `tests/` 目录、pip 留下的 `bin/` 脚本。
    """
    sp = APP / "python" / "Lib" / "site-packages"
    freed = 0
    for pkg in ("numpy", "matplotlib"):
        for d in (sp / pkg).rglob("tests"):
            if d.is_dir():
                freed += tree_size(d)
                shutil.rmtree(d, ignore_errors=True)
    bin_dir = sp / "bin"
    if bin_dir.is_dir():
        freed += tree_size(bin_dir)
        shutil.rmtree(bin_dir, ignore_errors=True)
    log(f"裁剪 {human(freed)}（numpy/matplotlib 的 tests 目录 + pip 脚本）")


def smoke_test():
    """用**分发包自己的**解释器跑三次最小出图，三条路都要真的走通。

    裁错了、`._pth` 写错了、字体/路径不对 —— 都在这里当场炸掉，而不是等对方双击才发现。
    故意带上 pdf+svg：那两条路径会走 fontTools，是最容易被误删的依赖。
    第三条（图2 粗网格）**必须跑一次仿真**：它验的是 `CxAoA` 注入 ——
    那个注入曾经是静默 no-op（见 docs/BETA-GAMMA.md §4.2），只有真跑一次才抓得住。
    """
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(APP / "kernel-cache")     # 必须和 run_ui.py 里一致
    env["PYTHONUTF8"] = "1"
    exe = str(APP / "python" / "python.exe")
    fmt = ["--formats", "png,pdf,svg"]
    cases = [
        ("图1", "_smoke", ["--missiles", "PL-12", "--no-iso", "--tag", "_smoke"]),
        ("图2（不扫描）", "_smokebg",
         ["--figure", "bg", "--bg-no-scan", "--tag", "_smokebg"]),
        # 粗到 2×2：只为了验"β/γ 真的落到了求解器上"，不追求图好看
        ("图2（粗扫）", "_smokescan",
         ["--figure", "bg", "--beta-step", "900", "--gamma-step", "40",
          "--no-cache", "--tag", "_smokescan"]),
    ]
    for label, tag, args in cases:
        cmd = [exe, "-m", "missile_sim"] + args + fmt
        r = subprocess.run(cmd, cwd=str(APP), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            print(r.stdout[-2000:])
            print(r.stderr[-2000:])
            raise SystemExit(f"冒烟测试失败（{label}）—— 分发包不自洽，别发出去")
        made = sorted(p.suffix.lstrip(".") for p in (APP / "figures").glob(f"*{tag}.*"))
        if made != ["pdf", "png", "svg"]:
            raise SystemExit(f"冒烟测试（{label}）只出了 {made}，期望 png/pdf/svg 三种")
    log("冒烟测试通过（图1 + 图2 不扫描 + 图2 粗扫，png + pdf + svg 均能出图）")

    for p in list((APP / "figures").glob("*_smoke*")) + \
            list((APP / "results").glob("*_smoke*")):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


def report():
    print()
    print("=" * 66)
    total = tree_size(BUNDLE)
    print(f"  分发包：{BUNDLE}")
    print(f"  总大小：{human(total)}")
    print()
    for d in sorted(APP.iterdir()):
        if d.is_dir():
            print(f"    app/{d.name + '/':<22} {human(tree_size(d)):>10}")
        else:
            print(f"    app/{d.name:<22} {human(d.stat().st_size):>10}")
    print()
    print("  根目录文件：" + ", ".join(sorted(p.name for p in BUNDLE.iterdir() if p.is_file())))
    print("=" * 66)


def main(argv=None):
    ap = argparse.ArgumentParser(description="组装免安装分发包")
    ap.add_argument("--prepare", action="store_true",
                    help="只准备内嵌 Python（下载 + 装依赖），不组装")
    ap.add_argument("--force", action="store_true", help="重新下载／重装内嵌 Python")
    ap.add_argument("--zip", action="store_true", help="组装后打成 zip")
    ap.add_argument("--no-clean", action="store_true", help="不删已有的 dist 目录（增量覆盖）")
    args = ap.parse_args(argv)

    print("内嵌 Python")
    python_dir = prepare_python(force=args.force)
    if args.prepare:
        return 0

    print("\n中文字体")
    font = make_font_subset()

    print("\n组装")
    build_tree(python_dir, font, clean=not args.no_clean)

    print("\n核对必带文件")
    verify_bundle()

    print("\n裁剪")
    prune_bundle()

    print("\n冒烟测试")
    smoke_test()

    report()

    if args.zip:
        print("\n打包 zip")
        out = shutil.make_archive(str(DIST / APP_NAME), "zip", root_dir=DIST,
                                  base_dir=APP_NAME)
        print(f"  {out}  ({human(Path(out).stat().st_size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
