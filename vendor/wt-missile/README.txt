Win / Linux 共用最简计算器（2.59.0.28）

文件：wt_missile.py + example.json + inputs/resources/2.59.0.28。
保留资源目录结构。包含 .28 目录内全部 168 份资源，其中 156 个预设可计算；未支持的型号仍明确拒绝。不含 .22 资源。

需要 Python 3.12+、NumPy 2.5.3：
  python -m pip install numpy==2.5.3

标准计算（不需要编译器）：
  python -X utf8 wt_missile.py example.json --output result.json

fast 计算（第一次需要 C 编译器，之后复用本机编译缓存）：
  python -X utf8 wt_missile.py example.json --fastmode --output result.json

Linux：确保 cc 可用。
Windows：推荐 64 位 Python + MinGW-w64。w64devkit 可从 https://github.com/skeeto/w64devkit/releases/tag/v2.10.0 获取，解压到 C:\w64devkit。
在当前 PowerShell 设置：$env:PATH = "C:\w64devkit\bin;" + $env:PATH
如果系统用 py 启动 Python，把上述 python 换成 py。

结果 summary.fastmode.backend 为 compiled-c 才表示启用编译加速；python-legacy 表示回退，原因在 compiled_fallback_reason。
默认逐物理步输出可加速；显式周期采样等不支持的输入条件会回退既有 Python fast。

Python 调用：
  import json
  from wt_missile import calculate
  with open("example.json", encoding="utf-8") as f:
      result = calculate(json.load(f), fastmode=True)

Windows x64 Python + MinGW 已在 Wine 下验证，原生 Windows 10/11 尚未实机验证。Linux 已验证。
此包不含预编译库、Python、NumPy 或编译器。首次 fast 在当地编译，不依赖游戏 ELF。
