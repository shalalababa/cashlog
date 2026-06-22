# Cashlog

本地优先的记账工具，替代 `记账单.xlsx`。SQLite 为数据真源，xlsx/JSON 为同步目标。
完整方案见 [docs/PLAN.md](docs/PLAN.md)。

## 技术栈
- 后端：Python + FastAPI + SQLite（`backend/`）
- 前端：React + TypeScript + Vite（`frontend/`）

## 首次准备
```bash
# 后端依赖
cd backend && pip install -r requirements.txt
# 从现有 记账单.xlsx 导入并建库（生成 backend/data/cashlog.db + JSON 镜像 + 迁移报告）
python -m scripts.migrate
# 前端依赖
cd ../frontend && npm install
```

## 日常运行
```bash
# 终端 1：启动后端 API（http://127.0.0.1:8000）
cd backend && python -m scripts.serve
# 终端 2：启动前端开发服务器（http://localhost:5173，自动代理 /api）
cd frontend && npm run dev
```
或构建前端后由后端同源托管：
```bash
cd frontend && npm run build      # 产物 frontend/dist
cd ../backend && python -m scripts.serve   # 访问 http://127.0.0.1:8000
```

## 与 xlsx 同步
```bash
cd backend
python -m scripts.sync_to_xlsx                 # 同步到表格（DB → 记账单.xlsx，写前自动备份）
python -m scripts.sync_from_xlsx               # 从表格同步（预览 diff，只读）
python -m scripts.sync_from_xlsx --apply       # 应用新增+修改
```

## 测试
```bash
cd backend && python -m pytest tests -q
```

## 进度
P1 数据核心、P2 xlsx 双向同步、P3 日常录入（列表/筛选/排序/新增编辑/智能补全/分类管理）已完成。
后续：P4 AA 套件、P5 统计与可视化、P6 预算/仪表板。
