# -*- coding: utf-8 -*-
"""**运行环境的显式构造**——把散在运行器里的隐式依赖收成 `EngineEnv`。

以前这些是隐式的：原生包路径藏在 `ProRunner.__init__`（`resolve_pkg(None)` 读 `$WT_NATIVE_PKG`）、
子进程的工作目录藏在 `runner._worker_init` 的 `os.chdir`、步长藏在 `FlashRunner.__init__`。
第三方模型无从得知该去哪儿找数据、该不该 chdir、步长算谁的。

现在：环境由 `build_env(spec, cfg=None, **over)` 显式构造并**随调用传入**。
"""

from __future__ import annotations

import os
from pathlib import Path

from .constants import DEFAULT_PKG, ENV_PKG, VERSION_28
from .spec import EngineEnv, ModelSpec


def build_env(spec: ModelSpec | str | None = None, cfg=None, **over) -> EngineEnv:
    """按模型需求 + 配置构造运行环境。

    只填**该模型真的需要**的东西：`requirements.native_pkg` 为假时不碰原生包路径，
    免得"只跑 flash"却因为没装原生包而报错。
    """
    from .registry import spec_of

    sp = spec_of(spec) if spec is not None else None
    req = dict(sp.requirements) if sp is not None else {}
    env = EngineEnv()

    if req.get("native_pkg"):
        raw = os.environ.get(ENV_PKG, "").strip() or DEFAULT_PKG
        env.pkg = str(raw)
        env.workdir = str(raw)                  # 原生 resources 用**相对**路径找 inputs/
        env.version = VERSION_28
    else:
        env.version = sp.version if sp is not None else ""

    if req.get("datamine"):
        env.datamine_root = os.environ.get("WT_DATAMINE_ROOT", "").strip() or None

    if cfg is not None:
        env.pool_jobs = int(getattr(cfg, "pro_jobs", env.pool_jobs) or env.pool_jobs)
        d = getattr(cfg, "pro_dt", None)
        if d:
            env.dt = float(d)
    for k, v in over.items():
        if hasattr(env, k):
            setattr(env, k, v)
        else:
            env.options[k] = v
    if env.workdir is None and env.pkg:
        env.workdir = env.pkg
    return env


def env_workdir_exists(env: EngineEnv) -> bool:
    return bool(env.workdir) and Path(env.workdir).is_dir()
