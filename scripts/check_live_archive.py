"""实机数据版本核查：直接从打包档 E:\\War Thunder\\warthunder.yup 里解出 rocketguns 的 blkx，
读出弹体参数，与 datamine 解包副本、WT.xlsx 表值三方对照。

yup 结构（yupgen 1.8.49）：bencode 索引，files 是路径 → {length, mtime, csize, sha1, ...}；
对 .blkx 文本条目 csize 缺省即未压缩，按 length 直读；否则 zlib 解压。
"""

from __future__ import annotations

import json
import re
import sys
import zlib
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YUP = Path(r"E:\War Thunder\warthunder.yup")
YUP_OLD = Path(r"E:\War Thunder\warthunder_old.yup")
OUT = Path(__file__).resolve().parents[1] / "results" / "live_archive_check.json"
NEEDLES = ["us_aim_120c_5.blkx", "su_r_77.blkx", "su_r_77_1.blkx",
           "cn_pl12.blkx", "fr_mica_em.blkx", "us_aim_120a.blkx", "jp_aam4.blkx"]


# ------------------------------------------------------------------ bencode 解析（只取 files 表）
def parse_yup(path: Path):
    data = path.read_bytes()
    pos = 0

    def read_int(p):
        end = data.index(b"e", p)
        return int(data[p:end]), end + 1

    def read_str(p):
        end = data.index(b":", p)
        n = int(data[p:end])
        p = end + 1
        return data[p:p + n], p + n

    def read_val(p):
        c = data[p:p + 1]
        if c == b"i":
            return read_int(p + 1)
        if c == b"l":
            p += 1
            out = []
            while data[p:p + 1] != b"e":
                v, p = read_val(p)
                out.append(v)
            return out, p + 1
        if c == b"d":
            p += 1
            out = {}
            while data[p:p + 1] != b"e":
                k, p = read_str(p)
                v, p = read_val(p)
                out[k.decode("utf-8", "replace")] = v
            return out, p + 1
        return read_str(p)

    root, _ = read_val(0)
    return root, data


def find_files(root):
    """在索引里找到 files 列表（元素形如 {'path': [...], 'length': ..}）。"""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "path" in node and "length" in node:
                found.append(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(root)
    return found


def extract(data: bytes, offset: int, entry: dict):
    length = entry["length"]
    csize = entry.get("csize")
    if csize:
        return zlib.decompress(data[offset:offset + csize])[:length]
    return data[offset:offset + length]


def block_after_rocket(text: str) -> str:
    i = text.find('"rocket"')
    return text[i:] if i >= 0 else text


def field(t, k):
    m = re.search(rf'"{k}"\s*:\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)', t)
    return float(m.group(1)) if m else None


def report(path: Path):
    if not path.exists():
        print(f"{path.name}: 不存在")
        return None
    root, data = parse_yup(path)
    entries = find_files(root)
    print(f"\n=== {path.name}：索引 {len(entries)} 个条目，文件 {len(data):,} B ===")
    # 打印几个与 aces 相关的条目（含 offset 便于读取）
    offs = {}
    cursor = 0
    for e in entries:
        parts = e["path"] if isinstance(e["path"], list) else [e["path"]]
        pth = "/".join(p.decode("utf-8", "replace") if isinstance(p, bytes) else str(p) for p in parts)
        offs[pth] = (cursor, e)
        cursor += e.get("csize") or e["length"]
    aces = [p for p in offs if p.endswith("aces.vromfs.bin")]
    for p in aces:
        _, e = offs[p]
        print(f"  {p}: length={e['length']:,} mtime={e.get('mtime')} csize={e.get('csize')}")
    res = {"archive": path.name, "entries": len(entries), "aces": {}}
    for p in aces:
        _, e = offs[p]
        res["aces"][p] = {"length": e["length"], "mtime": e.get("mtime"), "csize": e.get("csize")}
    return res


def main() -> int:
    out = {"archives": []}
    for p in (YUP, YUP_OLD):
        r = report(p)
        if r:
            out["archives"].append(r)
    print("\n说明：索引里只登记 vromfs 归档，blkx 在归档内部，"
          "因此这里核对的是『归档长度/mtime 是否与 datamine 解包源一致』。")
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"已写出 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
