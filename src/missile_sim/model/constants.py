# -*- coding: utf-8 -*-
"""模型层共享常量（无依赖，避免循环 import）。

`CALC_VERSION` 是**唯一失效开关**：任何影响"输入 → 结果"数值的改动都必须 +1，
否则旧缓存会被当成有效结果复用（本项目踩过：坏条目让 t_hit 从 45.1 变 25.6）。

历史：
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

# 信源包默认位置（可用 WT_NATIVE_PKG 覆盖）；只放路径，不放内容
DEFAULT_PKG = r"E:\WT\wt-missile-backend-runtime-1.0.1"
ENV_PKG = "WT_NATIVE_PKG"

VERSION_28 = "2.59.0.28"
ELF_SHA256_28 = "94de54548da8eb616f391d04e117ca11c8cf7143e7c6be6dfb9468c40512591a"
ELF_REL = Path("inputs") / "elf" / ELF_SHA256_28 / "aces"

# 信源包默认位置（可用 WT_NATIVE_PKG 覆盖）；只放路径，不放内容
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
DT_DEFAULT = 0.01          # 原生合法上限，速度优先（AERO_PLAN §20.4）
DT_RANGE = (0.00025, 0.01)
HIT_EVENTS = ("contact", "proximity_fuse")

# 计算器版本（= 缓存 schema）。改数值口径必须 +1；只改结构与产物字段也 +1（会作废缓存）。
CALC_VERSION = 5
CACHE_SCHEMA = CALC_VERSION
