# WSL 打通：续接清单（2026-10-05）

用户选择：**后端先在本地 WSL 跑**；已确认 WSL 本体**未安装**，需要用户以管理员身份安装 + 重启。

## 用户做（重启前）
```powershell
# 管理员 PowerShell
wsl --install
```
装完**重启**；重启后 Ubuntu 首次启动会让你建 UNIX 用户名/密码。

## 用户做（重启后，Ubuntu 里）
```bash
sudo apt update && sudo apt install -y python3-venv python3-pip git curl
python3 --version   # 需要 >= 3.12
```

## 然后由 Lead / 子代理接着做（步骤 2 起，原任务说明已在会话里）
1. `~/missile-work/` 下 `python3 -m venv .venv && . .venv/bin/activate`（**别在 /mnt 的 Windows 工作树里建 venv**）
2. `pip install --upgrade pip`；`pip install "git+https://github.com/Strinova-xinghui/missile-solver@main"`
3. `git clone --depth 1 https://github.com/Strinova-xinghui/missile-backend.git`；`pip install -r missile-backend/requirements.txt`
4. 起服务（后台 + 日志落盘）：
   ```bash
   export DATA_DIR="/mnt/e/导弹包线图-release/vendor/wt-missile/inputs/resources/2.59.0.28"   # 中文路径务必加引号
   cd missile-backend && uvicorn app.main:app --host 127.0.0.1 --port 8099
   ```
   `verify_data(DATA_DIR)` 不过会**拒绝启动**（特性，不是 bug）。
5. **两侧验证**（缺一不可）：
   - WSL 侧：`curl -s http://127.0.0.1:8099/v1/health`；`curl -s -H "Content-Type: application/json" --data-binary '{"kind":"plane","keys":["PL-12","MICA"],"tier":"standard","iso_step":5.0}' http://127.0.0.1:8099/v1/overlay`
   - **Windows 侧**：`curl.exe -s http://127.0.0.1:8099/v1/health` 与同一条 overlay ⇒ 证明 **WSL2 的 localhost 转发**通（这是"本地联调"能否成立的关键）
6. 落盘：在 `missile-backend` 仓加 `docs/WSL.md`（发行版与版本、依赖安装、DATA_DIR 的 WSL 路径、启动命令、从 Windows 验证的命令、坑），只提交这一个文件并 `git push origin main`（只推 main）。
   提交身份：`卡拉彼丘活了喵` / `310905939+Strinova-xinghui@users.noreply.github.com`。

## 环境事实（2026-10-05 探测，四项独立证据）
- `wsl -l -v` / `--status` / `--version` 全部 exit 1，原文：未安装适用于 Linux 的 Windows 子系统，可通过 `wsl.exe --install` 安装。
- 注册表 `HKCU\...\Lxss` 不存在；`Get-AppxPackage *WindowsSubsystemForLinux*` 为空；`WslService` 服务不存在。
- Windows `10.0.26300`（26H2），探测 shell **非管理员**。
- 游戏数据目录 `E:\导弹包线图-release\vendor\wt-missile\inputs\resources\2.59.0.28` **存在**（只读未动）。
- 探测原始记录：`E:\导弹包线图\docs\WSL-PROBE-NOTES.md`（另一个 worktree 里）。

## 纪律（沿用）
不改系统配置、不重启、不动防火墙（都由用户决定）；服务后台跑并给出「怎么停」；任一步失败贴**原始报错**并停下，不许「应该可以」；前提不存在时不产出"证据"（没起服务就不跑 curl、没 clone 就不写 `docs/WSL.md`）。

## 与 W3b 的接口
WSL 服务起来后，把 `api_base = http://127.0.0.1:8099` 交给 W3b（前端等时线叠加 / 图3 等时面 + 时间滑块）做真联调；**线上站（GitHub Pages）仍保持纯静态、零后端依赖**，`backend.js` 只在显式配置时才由 `sitebuild` 生成（构建期注入）。
