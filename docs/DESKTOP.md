# Cashlog 桌面版（Tauri）

桌面版是一个轻量外壳：启动时拉起与网页/开发模式**完全相同**的本地 FastAPI 后端，
并让 WebView 指向该后端（默认绑定一个**空闲端口**，避免与其它本地服务在固定端口上冲突；
窗口在确认后端 `/api/health` 健康后才创建——若 10 秒内未就绪则直接退出，绝不把窗口指向
一个未确认是 Cashlog 的端口）。后端的数据库、JSON 镜像、xlsx 路径都由 `cashlog.config`
解析，所以桌面版读写的就是同一套 SQLite / JSON / xlsx 文件 ——
满足 P6 验收「桌面版能读写同一 SQLite/JSON/xlsx 路径」。

**安装后的桌面版是自包含的**：后端被 PyInstaller 打成一个单文件
`cashlog-backend` 可执行程序，作为 Tauri 的 `externalBin` 随应用一起安装，运行时由
外壳自动拉起 —— 终端用户**无需预装 Python**。开发模式下若没有构建该 sidecar，外壳会
回退到用系统 `python -m scripts.serve` 从源码运行。

**界面也由后端提供**：构建好的 React 单页应用（`frontend/dist`）被一并打进 sidecar，
后端把它挂在 `/`（与 `/api` 同源，所以前端的相对 `/api/...` 调用免 CORS 直接可用）。
因此 WebView 直接指向后端就能看到完整界面，而不是一个裸的 404。Tauri 自身的
`frontendDist` 只是一个占位页（`src-tauri/placeholder/`），永不展示 ——
**界面的唯一来源是 sidecar**，所以改了前端后要重新构建 sidecar（见下文打包步骤）。

脚手架位于 [frontend/src-tauri/](../frontend/src-tauri/)（Tauri v2）。

## 数据位置

| 运行形态 | 默认数据目录 |
| --- | --- |
| 源码 / 开发（`python -m scripts.serve`） | 仓库内 `backend/data/`，工作簿在仓库根的 `记账单.xlsx` |
| 打包后的桌面版（frozen sidecar） | `%LOCALAPPDATA%\Cashlog\`（Windows）/ `~/.cashlog/`（其它平台） |

三个环境变量可覆盖（被 sidecar 继承，所以在外壳进程里设置即可）：

- `CASHLOG_DB` —— 数据库文件路径；JSON 镜像与备份目录跟随它。
- `CASHLOG_DATA_DIR` —— 数据目录（未设 `CASHLOG_DB` 时生效）。
- `CASHLOG_WORKBOOK` —— xlsx 工作簿路径（仅 frozen，默认在数据目录内）。
- `CASHLOG_PORT` —— 固定后端端口（默认取空闲端口）。设了它才会启用「附着到已在运行的后端」
  的开发便利；端口被占用且非 Cashlog 时外壳会 fail-closed 退出。

> 想让桌面版直接读写仓库里的现有账本：设 `CASHLOG_DATA_DIR` 指向
> `…\cashlog\backend\data`，并设 `CASHLOG_WORKBOOK` 指向仓库根的 `记账单.xlsx`。

## 一次性准备

1. 安装 Rust 工具链：<https://www.rust-lang.org/tools/install>（提供 `cargo` / `rustc`）。
2. 安装平台依赖（Windows 需要 WebView2 运行时，macOS 需要 Xcode CLT，Linux 需要
   `webkit2gtk` 等，详见 Tauri 官方先决条件）。
3. 安装前端依赖（含 `@tauri-apps/cli`）：
   ```bash
   cd frontend && npm install
   ```
4. 可选：替换应用图标（当前仓库已带一套默认图标；如需换图，从一张 ≥1024×1024 的 PNG 生成）：
   ```bash
   cd frontend && npm run tauri icon path/to/cashlog-logo.png
   ```

## 开发运行

```bash
cd frontend
npm run tauri dev
```

外壳启动逻辑：先取一个空闲端口（设了 `CASHLOG_PORT` 则用固定端口，并会先用 `/api/health`
探测、附着到已手动启动的 `scripts.serve`），把端口通过 `CASHLOG_PORT` 传给后端并拉起它 ——
优先用同目录下打好的 sidecar，否则回退到系统 `python -m scripts.serve`（默认在仓库
`backend/`，可用 `CASHLOG_BACKEND_DIR` 指定）。回退路径需要先安装后端依赖
（`cd backend && pip install -r requirements.txt`）。等后端在该端口 `/api/health` 健康后
才创建窗口；超时则 fail-closed 退出。

> 走 python 回退（未构建 sidecar）时，界面由源码后端从仓库的 `frontend/dist` 提供，
> 所以开发模式下要先 `cd frontend && npm run build` 产出 dist，否则后端 `/` 是 404、
> 窗口会空白。要热重载前端，仍可单独跑 `npm run dev` 并直接用浏览器开发，桌面外壳主要
> 用来验证打包形态。

## 打包（自包含安装包）

### 1. 构建后端 sidecar

```bash
cd backend
python scripts/build_sidecar.py
```

脚本会先在 `frontend/` 跑 `npm run build` 产出 `frontend/dist`（必要时自动 `npm install`），
再在 `backend/.sidecar-venv/` 建一个**隔离的** virtualenv（不含系统 site-packages，
从而绕开会让 PyInstaller 拒绝运行的过时 `pathlib` backport），装好运行依赖 + PyInstaller，
用 [`cashlog-sidecar.spec`](../backend/cashlog-sidecar.spec) 打包，并把产物按 Rust 目标三元组
命名拷到 `frontend/src-tauri/binaries/cashlog-backend-<target-triple>[.exe]` ——
这正是 Tauri `externalBin` 期望的位置与命名。

> spec 会把 `docs/schema.sql`、`docs/migrations/` 以及构建好的前端 `frontend/dist`
> 一并打进去（运行时从 `sys._MEIPASS` 读取）：前两者让首次启动空数据库时能自建 schema
> 并 seed 默认分类，后者就是桌面版展示的界面（后端挂在 `/`）。**改了前端代码后必须重跑
> 这一步**，否则 sidecar 里仍是旧界面。

### 2. 打包桌面应用

```bash
cd frontend
npm run tauri build      # 编译外壳、打包 sidecar(externalBin) 与占位前端，产出 MSI/NSIS
```

> 前端界面在第 1 步已构建并打进 sidecar，所以这里 Tauri 的 `frontendDist` 用的是占位页；
> 真正的界面随 sidecar 一起安装。若没先跑第 1 步，Tauri 会因为找不到 `externalBin`
> 而报错，提示你先构建 sidecar。

产物在 `frontend/src-tauri/target/release/bundle/`（`.msi` 与 `-setup.exe`）。安装后
`cashlog.exe` 与 `cashlog-backend.exe` 同目录，双击即用，无需系统 Python。

> sidecar 二进制（`frontend/src-tauri/binaries/`）与构建 venv 都已 gitignore，
> 是按机器/平台重新生成的产物，不入库。换平台或改了后端代码后，重跑第 1 步即可。
