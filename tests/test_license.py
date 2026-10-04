"""许可正文与文档口径的判据（秒级；仓库里与**包内**都跑）。

**定稿（2026-10-04）**：本项目按 **`AGPL-3.0-only`** 发布 —— 正文是 GNU AGPL-3 官方全文逐字
（来源 <https://www.gnu.org/licenses/agpl-3.0.txt>，只加首行版权归属），**`only`，不是 `or-later`**。
本文件钉四件事：

1. `ROOT/LICENSE` 必须存在、是一份**真正文**（够长、不是占位、不是被截断的空壳）；
2. 它必须是**拍的那一份**：`_CHOSEN_MARKERS` 里的 AGPL 特征串一个都不能少，
   而且**不是** MIT、**也不是**中途选过又撤掉的 PolyForm Noncommercial；
3. 面向使用者的文档必须写明 AGPL 口径（**允许商用** / 分发与"通过网络提供服务"都要给源码 /
   衍生不得闭源）、指向 `LICENSE`，且**不许再声称** MIT 或 PolyForm；
4. 第三方义务（内嵌 Python / numpy / matplotlib / 字体 / Gaijin 数据）不被我们的许可吃掉。

反证层（`test_checker_flags_the_mit_body`）：**两条** —— 喂 MIT 正文**必红**，喂 **PolyForm
正文也必红**（NC 与 AGPL 不兼容，钉错口径必须能抓出来）。否则上面几条就是橡皮图章。

⚠ 包内与仓库里**读的是不同文件**（`packaging/README.app.md` → 包内 `app/README.md`、
`packaging/使用说明.txt` → 包内 `app/使用说明.txt`、仓库根 `LICENSE` → 包内 `app/LICENSE`），
所以路径走"候选列表取第一个存在的" —— 两边都跑得动，两边都必须过关。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: **拍板协议的特征串**：逐条都必须出现在正文里（改协议时**先改这里**）。
_CHOSEN_MARKERS: tuple = (
    "GNU AFFERO GENERAL PUBLIC LICENSE",
    "Version 3, 19 November 2007",
    "Affero",
    "Remote Network Interaction",
)

#: 别的协议的特征串：出现就说明"正文不是拍的那一份"（MIT = 2026-10-02 的旧版；
#: PolyForm Noncommercial = 中途选过又撤掉的"完全非商用"版，**与 AGPL 不兼容**）。
_FOREIGN_LICENSE_MARKERS = (
    ("Permission is hereby granted, free of charge", "MIT 的授权句"),
    ("MIT License", "MIT 的标题"),
    ("PolyForm Noncommercial", "PolyForm Noncommercial 的标题"),
    ("Noncommercial Purposes", "PolyForm 的 Noncommercial Purposes 段"),
    ("Apache License", "Apache-2.0 的标题"),
)

#: 占位/模板特征串：这份文件必须是**生效的正文**，不是"这不是许可证"那类占位。
_PLACEHOLDER_MARKERS = ("这不是许可证", "not a license", "TODO", "[year]", "[fullname]")

#: 面向使用者的文档必须指向正文，且**不许**再声称旧协议 / 撤掉的候选。
_DOC_MUST_REFERENCE = "LICENSE"

#: 文档里必须点名的许可（AGPL）与必须交代的"商用"维度。
_DOC_LICENSE = re.compile(r"AGPL-3\.0-only|AGPL")
_DOC_COMMERCIAL = re.compile("商用|商业")

#: 文档里**不许**出现的字样：旧协议（MIT）与撤掉的候选（PolyForm）。
#: ⚠ 只禁**协议名**那种写法：`MIT` 单独出现是第三方的许可名（`fonttools` / `pyparsing` / `six` 是 MIT），
#: 那是必须写出来的。
_DOC_FORBIDDEN = (
    (re.compile(r"MIT License"), "MIT License（旧协议）"),
    (re.compile(r"OSI Approved :: MIT"), "MIT classifier（旧协议）"),
    (re.compile(r"PolyForm"), "PolyForm（撤掉的候选，不能出现在面向使用者的文档里）"),
)

#: 第三方义务：这些名字必须出现在面向使用者的文档里（各自许可照旧生效，不被我们的许可覆盖）。
_THIRD_PARTY = ("PSF", "numpy", "matplotlib", "OFL", "Gaijin")

_MIT_BODY = """MIT License

Copyright (c) 2026 MK

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
"""

#: 中途选过又**撤掉**的候选（PolyForm Noncommercial）—— 反证要能把它也抓出来：
#: 它一样很长、一样有版权行，但**口径与 AGPL 相反**（禁一切商用 vs 允许商用但要求开源）。
_POLYFORM_BODY = """Copyright (c) 2026 MK

Required Notice: Copyright (c) 2026 MK

# PolyForm Noncommercial License 1.0.0

<https://polyformproject.org/licenses/noncommercial/1.0.0>

## Acceptance

In order to get any license under these terms, you must agree to them as both
strict obligations and conditions to all your licenses.

## Noncommercial Purposes

Any noncommercial purpose is a permitted purpose.

""" + ("Any commercial purpose is not a permitted purpose. " * 30) + "\n"


def license_body_problems(text: str) -> list:
    """许可正文的问题列表（空列表 = 通过）。**这条判据的牙齿就在这里**。"""
    out = []
    if len(text.strip()) < 800:
        out.append(f"正文只有 {len(text.strip())} 个字符 —— 太短，不像完整正文（占位？被截断？）")
    for bad, why in _FOREIGN_LICENSE_MARKERS:
        if bad in text:
            out.append(f"正文里出现了{why}（`{bad}`）—— 不是拍板的那一份（AGPL-3.0-only）")
    if re.search(r"\bMIT\b", text) and "License" in text:
        out.append("正文里出现了 `MIT` —— 不是拍板的那一份（AGPL-3.0-only）")
    for bad in _PLACEHOLDER_MARKERS:
        if bad in text:
            out.append(f"正文里出现了占位/模板痕迹 `{bad}` —— 这不是生效的正文")
    for marker in _CHOSEN_MARKERS:
        if marker not in text:
            out.append(f"缺少拍板协议（AGPL-3.0-only）的特征串 `{marker}`")
    return out


def _user_docs(*names: str) -> list:
    """取文档：仓库里是 `packaging/<name>`，包内是 `<name>`（同一份的两个落点，取存在的那个）。"""
    out = []
    for name in names:
        for cand in (ROOT / "packaging" / name, ROOT / name):
            if cand.is_file():
                out.append(cand)
                break
    return out


def test_license_body_is_the_agpl_one():
    """`LICENSE` 必须是一份真正文，而且**就是拍的那一份**（AGPL-3.0-only）。"""
    path = ROOT / "LICENSE"
    assert path.is_file(), (
        f"{path} 不存在 —— 仓库根有 `LICENSE`，免安装分发包里应当有 `app/LICENSE`"
        "（`make_dist.py` 负责拷，`REQUIRED_IN_BUNDLE` 里登记着）"
    )
    text = path.read_bytes().decode("utf-8", errors="replace")
    problems = license_body_problems(text)
    assert not problems, (
        "许可正文不是拍板的那一份（2026-10-04 定稿 AGPL-3.0-only）：\n  - " + "\n  - ".join(problems)
    )
    assert len(text) > 30000, f"AGPL-3 官方全文 34 KB 左右，这里只有 {len(text)} 字节 —— 像是被截断了"


def test_checker_flags_the_mit_body():
    """**反证两条**：喂 MIT 正文必红；喂 **PolyForm 正文也必红**（撤掉的候选不能过）。

    两条反证缺一不可 —— 只查 MIT 的话，"换成一个跟 AGPL 口径相反的许可"照样能通过。
    """
    mit = license_body_problems(_MIT_BODY)
    assert mit, "MIT 正文居然通过了 —— 判据没有牙齿"
    assert any("MIT" in p for p in mit), f"报红了但没点名 MIT：{mit}"
    assert license_body_problems(""), "空正文必须报红"
    # "够长但没换"的正文（MIT 全文）也要红 —— 只查长度的判据会漏掉这种
    padded = _MIT_BODY + ("\n" + "x" * 2000)
    assert any("MIT" in p for p in license_body_problems(padded)), "长但仍是 MIT 的正文没被点名"

    poly = license_body_problems(_POLYFORM_BODY)
    assert poly, "PolyForm Noncommercial 正文居然通过了 —— 钉错口径抓不出来（NC 与 AGPL 不兼容）"
    assert any("PolyForm" in p for p in poly), f"报红了但没点名 PolyForm：{poly}"
    assert not license_body_problems(
        "Copyright (c) 2026 MK\n\n" + "GNU AFFERO GENERAL PUBLIC LICENSE\n"
        + "Version 3, 19 November 2007\nAffero\nRemote Network Interaction\n" + "y" * 900
    ), "AGPL 特征串齐全的正文不该报红（否则判据过严，正常正文也会红）"


def test_user_facing_docs_state_the_agpl_stance_and_not_the_superseded_ones():
    """面向使用者的文档：必须写 AGPL 口径、指向 `LICENSE`、交代"商用"；不许提旧协议/撤掉候选。"""
    docs = _user_docs("README.md", "README.app.md", "使用说明.txt")
    assert docs, f"{ROOT} 下找不到面向使用者的文档（README / README.app.md / 使用说明.txt）"
    for path in docs:
        text = path.read_text(encoding="utf-8", errors="replace")
        assert _DOC_MUST_REFERENCE in text, f"{path.name} 没有指向 `{_DOC_MUST_REFERENCE}`（正文在哪就说不清）"
        assert _DOC_LICENSE.search(text), f"{path.name} 里没有出现 AGPL（现在的许可）"
        assert _DOC_COMMERCIAL.search(text), f"{path.name} 没交代「能不能商用」这件事"
        for pattern, why in _DOC_FORBIDDEN:
            hit = pattern.search(text)
            assert not hit, (
                f"{path.name} 里还写着 {why}（第 {text[:hit.start()].count(chr(10)) + 1} 行附近）—— "
                f"2026-10-04 已定稿 AGPL-3.0-only，这一处得跟着改"
            )
        assert re.search(r"第\s*13\s*条|Remote Network Interaction", text), (
            f"{path.name} 没写 AGPL 第 13 条那条网络服务义务 —— 那是用户选 AGPL 的根本理由，"
            f"面向使用者的口径必须点出来"
        )


def test_third_party_obligations_are_not_swallowed_by_our_license():
    """第三方义务（PSF / numpy / matplotlib / OFL / Gaijin 数据）必须仍在文档里。"""
    docs = _user_docs("README.md", "README.app.md")
    assert docs, f"{ROOT} 下找不到 README"
    for path in docs:
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [t for t in _THIRD_PARTY if t not in text]
        assert not missing, (
            f"{path.name} 里没有提到第三方权利方 {missing} —— 他们各自的许可照旧生效、"
            f"分发时要带上声明（README §9.6 / 包内「许可与分发边界」）"
        )
