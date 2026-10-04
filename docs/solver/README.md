# 求解器交付材料（留档，**不随**图册与免安装包发布）

这三份文档是**求解器方随内核交付的讲解**，不是本仓撰写；本目录只为留档与可追溯。
`docs/solver/**` **不随免安装包**（`make_dist.py` 的 `DOCS_KEEP` 只复制 `docs/` 一级文件），
也**不随静态图册**（对外口径页只讲 γ，见 `docs/HOSTING.md` §6.0）。

| 本目录文件名 | 交付物里的原名 | 来源交付物 | 内容 |
| --- | --- | --- | --- |
| `README-2.59.0.28.md` | `README.md` | `wt-missile-win-linux-28-minimal.zip`（= 我们 vendored 的那一份） | 最小内核包 README：输入/输出字段语义、终止事件、fast 缓存与回退、计时拟合 |
| `CALCULATION-FORMULAS.md` | 同名 | `wt-missile-website-20260925-220549.tar.gz` 的 `docs/` | 公式版讲解：几何/PN/loft/PID/发动机/大气/面积惯量/阻力升力/转弯能力指标 |
| `LOFT-LOGIC.md` | 同名 | 同上 | 高抛逻辑讲解：AIM-120D 参数、状态机、阈值实验与退出案例 |

三份文件**原样复制、一字未改**（仅 `doc.md` 按交付物原名改回 `README-2.59.0.28.md`）。
交付物本体未入仓，只记名字与校验和（完整 SHA-256 见 `vendor/wt-missile/VENDOR.md`）：

| 交付物 | 大小 | SHA-256（前 8 / 后 6） |
| --- | ---: | --- |
| `wt-missile-win-linux-28-minimal.zip` | 628,565 B | `4eea9890…17f780` |
| `wt-missile-backend-runtime-research-1.0.1.tar.gz` | 62,635,898 B | `1100ac29…e1ee42` |
| `wt-missile-website-20260925-220549.tar.gz` | 62,790,230 B | `20214535…462f427` |

取得日期 2026-10-04；内核归属（自 2026-10-01 起归本项目作者）见 `vendor/wt-missile/VENDOR.md`。

⚠ **引用这几份文档时的边界**：它们引用的是求解器方研究树里的路径（`tools/simulator/native.py`、`runs/…`、
`../runs/loft-audit-259028-20260925/audit.json` 等），**那些路径不在本仓**。本仓对应的实现是
`vendor/wt-missile/wt_missile.py`，对应的口径文档是 `docs/BETA-GAMMA.md` 与 `docs/SOLVER-API.md`。
