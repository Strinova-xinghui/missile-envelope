# 分发：免安装版打包

对方拿到 `导弹包线图.zip` → 解压 → **双击 `启动.bat`** → 浏览器自动打开界面。
**不需要装 Python、不需要联网、不需要 C 编译器。**

## 一条命令

```powershell
python make_dist.py --prepare    # 一次性：下载内嵌 Python + 装依赖（约 90 MB，需联网）
python make_dist.py              # 组装 + 裁剪 + 冒烟测试 → dist/导弹包线图/
python make_dist.py --zip        # 顺便打成 zip
```

`--prepare` 的产物落在 `build/`（已 gitignore），之后组装不再联网。
组装脚本会**自己跑一次冒烟测试**：用分发包自己的解释器出 png/pdf/svg 三种格式，
任何一处裁错、路径写错、字体缺失都会当场炸掉，不会等对方双击才发现。

## 产物结构

根目录**只有一个文件**，其余都在二级目录 `app/` 里：

```text
dist/导弹包线图/
├── 启动.bat                    ← 对方只需要双击这个
└── app/
    ├── run_ui.py               启动逻辑（重定向内核缓存 → 注册中文字体 → 起 WebUI）
    ├── python/                 内嵌 Python 3.14.7 + numpy/matplotlib，不碰系统环境
    ├── src/missile_sim/        外壳代码
    ├── vendor/wt-missile/      求解器内核（只读副本）
    ├── kernel-cache/           预编译 C 内核（对方没装 MSVC 也能吃 compiled-c）
    ├── fonts/                  中文字体子集（对方是英文系统也不出方块）
    ├── configs/ figures/ results/ docs/
    ├── README.md
    └── 使用说明.txt
```

实测体积（2026-09-27，Python 3.14.7 / numpy 2.5.3 / matplotlib 3.11.2）：

| 项 | 大小 |
| --- | --- |
| `app/python/`（解释器 + 依赖，已裁 `tests`） | 124.1 MB |
| `app/vendor/` | 3.2 MB |
| `app/fonts/`（思源黑体子集，7036 字） | 3.6 MB |
| `app/figures/` + `app/results/` | 1.3 MB |
| **解压后合计** | **132.7 MB** |
| **zip** | **53.8 MB** |

## 三个设计要点（都是被坑出来的）

**1. 目录形状不能改。** `src/missile_sim/spec.py` 用 `Path(__file__).resolve().parents[2]`
推仓库根 —— 只要 `app/` 下保持 `src/ vendor/ figures/ results/` 的相对结构，
所有路径自动正确，业务代码一行都不用动。这也是为什么不能把 `src/` 拍平。

**2. 内核缓存靠改 `LOCALAPPDATA` 重定向。** `wt_missile` 在
`%LOCALAPPDATA%\wt-missile\compiled-fast\<hash>.dll` 找编译产物，而且**只认这一个
环境变量**（源码里写死的）。`run_ui.py` 在 import 之前把它指到包内 `kernel-cache/`，
本机编译的内核就随包走。ABI 对得上：本机 MSVC 19.44，内嵌 Python 也是 `MSC v.1944`，
且 embeddable 自带 `vcruntime140.dll`。

⚠ 必须**在 `import missile_sim` 之前**设置 —— 一旦 `wt_missile` 被导入，它已经按默认
路径找过一遍并缓存了失败结果。

**3. 中文字体必须随包。** 对方若是英文 Windows，`Microsoft YaHei` / `SimHei` / `SimSun`
一个都没有，图上全是豆腐块。包里带思源黑体 `NotoSansSC-VF.ttf` 的子集
（GB2312 一二级汉字 + 希腊字母 + 常用符号，7036 字），17 MB → 3.6 MB。
字体是 **SIL OFL 1.1**，可以再分发；`run_ui.py` 用 `font_manager.addfont()` 注册后
插到 `figures._CN_FONTS` 最前面，注册失败不致命（退回系统字体并打警告）。

## 裁剪：哪些能删，哪些绝对不能

`prune_bundle()` 只删两样：numpy / matplotlib 自带的 `tests/` 目录，和 pip 留下的
`bin/` 脚本 —— 合计约 20 MB。

⚠ **`PIL` 和 `fontTools` 看着像可选依赖，其实是 matplotlib 的硬依赖**，实测删掉当场报废：

* `matplotlib/colors.py` 第 53 行 `from PIL import Image`
* `matplotlib/dviread.py` 第 32 行 `import fontTools.agl`

两者合计 32 MB，删不得。其余大头也都有硬依赖：`numpy.libs/`（20 MB OpenBLAS）是
numpy 的 C 扩展链接的，`matplotlib/mpl-data/fonts/`（7 MB）含 mathtext 要用的
DejaVu 系列。**想再瘦身必须先跑冒烟测试，别凭感觉删。**

## 附带的两个坑

* **只读属性**：`results/reference_fig.png` 是从 `E:\WT` 那边拷来的，带只读位，
  裸 `shutil.rmtree()` 在 Windows 上直接 `WinError 5` 把组装打断在半路。
  脚本里用 `rmtree_force()`（`onexc` 回调先 `chmod S_IWRITE` 再删）。
* **参数转发**：`启动.bat` 里的 `%*` 要真能传到 `webui.main()`。第一版 `run_ui.py`
  把 argv 写死成 `["--config", ..., "--browser"]`，`--port` 之类全被吞掉。
  现在转发 `sys.argv[1:]`，只在没显式给 `--no-browser` 时补 `--browser`。

## 对方机器上的预期

* **能跑**：Windows x64。内嵌解释器与 `python.exe` 都是 amd64。
* **速度**：吃上随包内核时全尺寸扫描（1632 工况）约 40 s；内核加载失败会自动退回
  纯 Python，**结果完全相同，约 5 分钟**。界面上有进度条。
* **不联网也能用**：除首次 pip 装依赖（只在打包机上进行）外，运行时零网络请求。
* **只听 `127.0.0.1`**，无鉴权，适合本机自用与内网演示。

## 验证记录

```text
分发包自己的解释器 + LOCALAPPDATA 指向包内 kernel-cache：
  python -m missile_sim --formats png,pdf,svg --tag smoke
  → 命中 1632/1632（100%）；等时线 13 层；backend = compiled-c；43.6 s

双击路径（cmd /c 启动.bat --port 8799 --no-browser）：
  → HTTP 200 · 19770 字节 · 页面含「等时线」「PL-12」

组装脚本内置冒烟测试：
  → png + pdf + svg 均能出图
```
