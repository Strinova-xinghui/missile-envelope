# -*- coding: utf-8 -*-
"""模型层共享常量（无依赖，避免循环 import）。

**版本号是唯一失效开关**：任何影响"输入 → 结果"数值的改动都必须 +1，
否则旧缓存会被当成有效结果复用（本项目踩过：坏条目让 t_hit 从 45.1 变 25.6）。

**按档位分版本**（2026-09-26 整体换成 wt-missile 两档）：
  * `standard` / `fast` 是**同一物理的两个算术后端**（纯 Python vs C 编译内核），
    结果逐位不同 ⇒ 必须各有一张 `ModelSpec`、各有一个缓存文件；
  * 旧 `pro`（原生 ELF 执行）与 `flash`（本仓库公式引擎）**已不再注册**，但版本号、
    缓存文件与引擎代码都保留：历史资产不丢，且仍可与新档位对拍。

历史（wt-missile 两档）：
  1 = 初版：整体替换 Pro/Flash；standard=纯 Python、fast=C 编译内核（缺编译器自动回退）

历史（Pro，代码与缓存保留）：
  1 = 初版（乘数在外部算、BC 参照面积用错、两级弹漏级）
  2 = 乘数改由 profile 自算；BC 用迎面面积 π(d/2)²；逐级齐奥尔科夫斯基
  3 = 三段式重构（model/ 三层）：数值未变，但产物 schema 增记录/版本戳字段
  4 = NativeResult 增 `samples` 轨迹采样（缓存条目结构变了，旧条目缺这一项）
  5 = 轨迹默认不入缓存（单条记录的 95% 是轨迹；1824 工况会把缓存撑到 73 MB）
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]     # src/missile_sim/model/constants.py → 仓库根
DEFAULT_CACHE = ROOT / "results" / "pro_cache.json"
FLASH_CACHE = ROOT / "results" / "flash_cache.json"

# 求解器只读副本（**已入库**；两档都靠它跑）。约定见 vendor/wt-missile/VENDOR.md
VENDOR_DIR = ROOT / "vendor" / "wt-missile"

# 信源包默认位置（可用 WT_NATIVE_PKG 覆盖）；只放路径，不放内容。
# 旧 Pro 档专用 —— 新两档不需要它（求解器自带 168 份 .28 资源）。
DEFAULT_PKG = r"E:\WT\wt-missile-backend-runtime-1.0.1"
ENV_PKG = "WT_NATIVE_PKG"

VERSION_28 = "2.59.0.28"
ELF_SHA256_28 = "94de54548da8eb616f391d04e117ca11c8cf7143e7c6be6dfb9468c40512591a"
ELF_REL = Path("inputs") / "elf" / ELF_SHA256_28 / "aces"

# 原生包支持的 profile（= blkx 文件名去后缀）；不含 Derby / R-Darter
NATIVE_PROFILES = {
    VERSION_28: ("us_aim_120a", "us_aim_120c_5", "us_aim_120d", "jp_aam4", "fr_mica_em",
                 "cn_pl12", "cn_pl12a", "su_r_77", "su_r_77_1", "su_r_73", "su_rvv_ae"),
}

# 外部输入容差与默认值
DT_DEFAULT = 0.01          # 旧原生档的合法上限（AERO_PLAN §20.4）；新引擎把它当"未指定"
DT_RANGE = (0.00025, 0.01)
HIT_EVENTS = ("contact", "proximity_fuse")

# 求解器的**客户端对象时钟**（2.59.0.28 ELF 0x925a4f0，read by 0x201fa17）。
# 金标数值即在此钟下验证；它同时是"能走 C 快路径"的条件之一 —— 非默认步长会触发边界切分，
# 求解器会主动回退 Python 并在 `fastmode.compiled_fallback_reason` 里如实报告。
SOLVER_DT = 0.02083333395421505

# ---------------------------------------------------------------- 计算器版本（按档位）
CALC_VERSION_STANDARD = 1   # results/cache/standard.json；改数值口径才 +1
CALC_VERSION_FAST = 1       # results/cache/fast.json（同物理、不同算术路径 ⇒ 单独分区）

# 旧档位（**已不再注册**）：引擎代码与缓存都保留，禁止改动它们的数值口径
CALC_VERSION_PRO = 5        # 与 results/pro_cache.json 一致 —— **禁止轻易改**
CALC_VERSION_FLASH = 1      # results/flash_cache.json

# 兼容别名：默认指当前正式档位（standard）。新代码请用 `calc_version(backend)`。
CALC_VERSION = CALC_VERSION_STANDARD
CACHE_SCHEMA = CALC_VERSION_STANDARD

BACKEND_VERSIONS = {
    "standard": CALC_VERSION_STANDARD,
    "fast": CALC_VERSION_FAST,
    "pro": CALC_VERSION_PRO,
    "flash": CALC_VERSION_FLASH,
}


def calc_version(backend: str = "standard") -> int:
    """该档位的计算器版本（= 缓存 schema）。未知档位按 standard 处理（最保守）。"""
    return BACKEND_VERSIONS.get(str(backend).strip().lower(), CALC_VERSION_STANDARD)
