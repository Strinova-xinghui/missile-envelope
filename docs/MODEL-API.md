# 模型接入 API（第三方/更新模型怎么接进来）

> 面向"从开源拿到一个更新版模型，想直接跑本仓库的三段式流水线"的场景。
> 适用版本：`flash-next`/`pro-api` 分支起的结构化模型 API。
> 权威实现见 `src/missile_sim/model/spec.py`（契约）、`registry.py`（注册表）、`io.py`（输入映射）。

---

## 1. 一句话

流水线只认三样东西：

```
上游（输入层）  ──►  EngineInputs  ──┐
                                    ├──►  Engine.simulate  ──►  NativeResult  ──► 输出层
运行环境（env） ──►  EngineEnv   ──┘
```

**换模型 = 写一个满足 `Engine` 协议的类 + 在注册表里登记一张 `ModelSpec`。**
不需要改扫描器、缓存、记录、绘图。

---

## 2. 三条纪律（都踩过坑）

1. **ΔV/BC → 引擎参数的映射只有一处**（`io.build_inputs` / `io.inputs_from_case`）。
   引擎**不许**自己再算 `dv_blk`/`bc_blk`/`thrust_scale`/`cx_scale`——历史上有两份实现，
   口径分叉导致过静默数值错误（`dv_blk=536.9` 让 `t_hit` 从 45.1 s 变 25.6 s）。
   引擎拿到的是**已经算好的乘数**，直接施加。
2. **引擎身份必须自报**（`EngineStamp`）：名字、语义版本、`calc_version`、保真度清单。
   产物里没有它，图就会被误读成"游戏实测"。
3. **缓存按模型分版本**：`ModelSpec.calc_version` 是该模型缓存的唯一失效开关。
   动 Flash 不要碰 Pro 的号——Pro 那 1824 条要跑 44 min。

---

## 3. 最小可运行例子

目录（`$WT_MODELS_PATH` 指向的任意目录下）：

```
my-models/
└── my_model/
    ├── __init__.py
    └── engine.py          # 可选；小模型直接写在 __init__.py 里也行
```

`my_model/__init__.py`：

```python
from missile_sim.model.spec import Capability, EngineStamp, ModelSpec, SelfTestReport
from missile_sim.model.native import NativeResult


MODEL_SPEC = ModelSpec(
    name="my-model",                 # 注册名（--model 的取值）；连字符/下划线等价
    label="我的模型",
    version="1.0.0",                 # 模型自己的语义版本（进产物追溯）
    calc_version=1,                  # 缓存 schema 号：改数值口径就 +1
    entry="my_model:MyEngine",       # "模块:对象"；对象是类（会实例化）或实例
    source="https://github.com/…",   # 出处
    capabilities=Capability(
        dims="2d",                   # "2d" | "3d"
        target_maneuvers=True,
        vectorized_batch=False,      # 有 simulate_many 才置 True（网格快车道）
        trajectory=True,
        observation_modes=("ideal",),
        wind=False,
        tvc=False,
    ),
    requirements={"native_pkg": False, "numpy": True, "datamine": True},
    note="一句话说明它与 pro/flash 的差别",
)


class MyEngine:
    spec = MODEL_SPEC

    # ---- 必实现 ----------------------------------------------------

    def runtime_info(self) -> dict:
        """身份块，进 manifest / 每条记录。"""
        return {"kind": "my-model", "engine": MODEL_SPEC.name,
                "engine_version": MODEL_SPEC.version,
                "calc_version": MODEL_SPEC.calc_version}

    def simulate(self, inp, env=None) -> NativeResult:
        """跑一个工况。`inp: EngineInputs`（乘数已算好），返回 `NativeResult`。"""
        r = NativeResult(
            ok=True, hit=True, event="proximity_fuse",
            t_end=42.0, t_hit=42.0, v_impact=600.0, max_alt_m=12000.0,
            thrust_scale=inp.thrust_scale, cx_scale=inp.cx_scale,
            dv_blk=inp.dv_blk, bc_blk=inp.bc_blk,
            resource=f"my-model:{inp.standard}",
        )
        r.engine = self.stamp(inp).to_dict()
        return r

    def selftest(self, env=None) -> SelfTestReport:
        """接入即验（`pipeline.py models --check` 会调它）。不许抛异常。"""
        rep = SelfTestReport(name=MODEL_SPEC.name, ok=True)
        rep.add("参数块完整", True)
        return rep

    # ---- 可选 ------------------------------------------------------

    def stamp(self, inp=None) -> EngineStamp:
        return EngineStamp(name=MODEL_SPEC.name, version=MODEL_SPEC.version,
                           calc_version=MODEL_SPEC.calc_version,
                           fidelity={"recovered": [...], "not_recovered": [...],
                                     "derived": [...]})

    def simulate_many(self, inputs, env=None, progress=None):
        """有向量化批量才声明 `vectorized_batch=True`；网格扫描会优先用它。"""

    def inputs(self, env, inp):
        """输入补全钩子（默认原样返回）。"""
        return inp

    def close(self):
        """释放资源（进程池等）。"""


ENGINE = MyEngine()          # 注册表要的就是这个名字
```

启用：

```powershell
$env:WT_MODELS_PATH = "D:\my-models"        # 可多个目录，用 ; 分隔
python scripts\pipeline.py models --check   # 看看它有没有接好
python scripts\pipeline.py models --write   # 把版本矩阵写进 results/models.json
python scripts\pipeline.py model --model my-model --standard PL-12
python scripts\pipeline.py scan  --model my-model --run-id my_probe
```

---

## 4. 契约细节

### 4.1 `EngineInputs`（输入；`simulate` 的入参）

上游一次性给全，引擎只读：

| 组 | 字段 | 说明 |
| --- | --- | --- |
| 身份 | `missile` `version` `standard` `tag` `profile_hash` | 进缓存键与产物 |
| 弹体 | `mass` `geometry` `aero` `autopilot` `loft` `gains` `limits` `fuse` | 结构化参数块，见 `spec.py` |
| 映射 | `dv_target` `bc_target` `dv_blk` `bc_blk` `thrust_scale` `cx_scale` `cxk_used` | **唯一算法**的产物 |
| 场景 | `range_m` `alt_m` `target_alt_m` `vm0` `vt` `wind_m_s` `ground_height_m` `target_maneuvers` | |
| 技术 | `dt` `duration_s` `sample_period_s` `observation_mode` `hit_radius_m` `proximity_fuse` `save_trajectory` | 不影响物理口径 |

* `inp.check()` 返回问题列表（空 = 通过）；**开工前先跑**。
* `inp.cache_key()` 是缓存键；**不要**自己拼键。
* `inp.target_alt` / `inp.target_velocity` / `inp.launch_velocity` 是便捷派生。
* `save_trajectory` **不进缓存键**（同一个物理工况不该因为它有第二份缓存）。

### 4.2 `NativeResult`（输出）

字段见 `native.py`。要点：

* `t_hit` 未命中填 `nan`；`hit` 是权威布尔量。
* `samples` 只在 `save_trajectory` 时产出，键名按 `record.SAMPLE_FIELDS`
  （`t/x/y/v/mass/thrust/range`）。
* 设 `result.engine = <EngineStamp>.to_dict()`，否则产物里没有身份戳。
* `resource` 用来标注特殊来源（如原生侧的 `INJECTED`）。

### 4.3 `EngineEnv`（运行环境）

由 `env.build_env(spec, cfg)` 构造并**随调用传入**。按 `ModelSpec.requirements` 只填该模型真要的东西
（`native_pkg=False` 时不会碰原生包路径）。

| 字段 | 用途 |
| --- | --- |
| `pkg` / `workdir` | 原生运行包根；`workdir` 是子进程需要 `chdir` 的地方 |
| `version` | 数据源版本 |
| `dt` / `dt_inner` | 外层步长 / 内层子步 |
| `pool_jobs` | 并发度 |
| `datamine_root` | 权威 blkx 所在仓库 |
| `options` | 模型自定义键（`env.get("key")`） |

### 4.4 并发与缓存由谁负责

* `EngineRunner`（`model/runner.py`）**对任何模型都可用**：进程池 + 缓存 + 进度。
  它只认 `Engine` 协议 + `EngineInputs`，输入与身份用普通 `dict` 跨进程。
* 声明了 `capabilities.vectorized_batch=True` 的模型**不会被套进程池**
  （向量化批量通常比多进程更快、更省内存）。
* 缓存路径由注册表给（`pro` → `results/pro_cache.json`，`flash` → `results/flash_cache.json`，
  其他 → `results/cache/<name>.json`），`schema` 取 `ModelSpec.calc_version`。
  **schema 不符 ⇒ 整个缓存作废**（这是防止旧公式结果污染新结果的唯一开关）。

---

## 5. 版本管理

| 想做的事 | 改哪里 |
| --- | --- |
| 只改模型实现、数值不变 | 不动 `calc_version` |
| 改了任何影响"输入→结果"数值的东西 | `calc_version += 1`（该模型缓存整体作废重算） |
| 发布一个新模型 | 新增一个注册名 + `ModelSpec`，不要覆盖旧的 |
| 想知道当前有哪些模型/版本 | `python scripts\pipeline.py models --verbose`、`results/models.json` |
| 追溯某张图是谁算的 | 产物 `manifest.runtime` 与每条记录的 `model` 块 |

**同一个注册名换实现**会让旧缓存与新缓存混在一起——所以"换实现"应当**换版本号**，
并在 `ModelSpec.note` / `source` 里写清出处。

---

## 6. 边界（API 不保证的事）

1. **API 只保证契约、身份与可替换性，不保证模型质量**。新模型算得对不对，只能靠
   `selftest` + 与 Pro 的误差报告来判定。
2. `selftest` 的覆盖范围由模型自己决定；调用方不应把它当作"数值已验收"。
3. 三维/导引头/数据链等能力靠 `Capability` **声明**，API 不做强制校验
   （`selftest` 里可以自证）。
4. float32、原生分支顺序、离散积分细节**不在**契约里；API 不承诺与游戏逐位一致。
