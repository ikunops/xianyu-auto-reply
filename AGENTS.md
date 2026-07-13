# AGENTS.md — 闲鱼自动回复系统 (xianyu-auto-reply)

## 项目概述

基于 FastAPI + React + MySQL + Redis + Playwright 的闲鱼多账号自动化系统。
主系统负责账号管理、消息收发、自动回复、自动发货、商品发布与后台管理；
`promotion` 子项目负责返佣账号、选品规则、素材库、发布规则等。

## 技术栈

- 后端：FastAPI + SQLAlchemy 2.0 + APScheduler + Loguru
- 前端：React 18 + TypeScript + Vite + TailwindCSS + Zustand
- 基础设施：MySQL 8.0 + Redis 7
- 浏览器自动化：Playwright / DrissionPage
- 部署：Docker / Docker Compose / Nuitka 打包 EXE

## 服务与端口

| 服务 | 端口 | 说明 |
|------|------|------|
| frontend | 9000 | 主系统前端 |
| backend-web | 8089 | 主系统 API 网关 |
| websocket | 8090 | 闲鱼连接、消息处理、登录、订单联动 |
| scheduler | 8091 | 定时任务（自动发货、评价、订单拉取、Cookie 刷新） |
| promotion/backend | 8092 | 返佣后端 |
| promotion/frontend | 9001 | 返佣前端 |

## 目录结构

```
backend-web/   主 Web API 服务
websocket/     闲鱼连接与消息处理服务
scheduler/     定时任务服务
common/        主系统与返佣系统共享模块（模型、数据库、工具）
frontend/      主系统前端
launcher/      Windows 桌面启动器（Nuitka 打包为 EXE）
promotion/     返佣子系统（backend + frontend）
scripts/       CI/CD 与工具脚本
docker/        Dockerfile 与 Nginx 配置
```

## 开发环境要求

- Python 3.11+（Windows 上注意：本机 PATH 优先级问题，旧的 `E:\学习\python.exe` 3.6.8 会干扰）
- Node.js 18+（本机装在 `D:\nodejs`，版本 24.18）
- MySQL 8.0+ / Redis 6+
- Chromium / Chrome（Playwright 相关功能）

## 构建与打包

### Docker 部署（推荐服务器）
```bash
bash build.sh rebuild      # 源码本地构建
bash deploy.sh             # 一键部署（拉取预构建镜像）
```

### Windows EXE 打包
```bash
EXE打包构建.bat            # 需要 Python 3.11 + Nuitka + VS Build Tools
```
注意：
- 前端构建用 `npm ci`，要求 `package.json` 与 `package-lock.json` 同步（改依赖后需先 `npm install`）
- `EXE打包构建.bat` 调用的 Nuitka 需要 C 编译器：优先 MSVC（Visual Studio Build Tools 2022），否则会尝试下载 MinGW
- 在中国大陆网络环境下，GitHub 下载 MinGW 常超时，需手动从镜像下载放到 Nuitka 缓存目录
- Nuitka C 编译阶段耗时长（1-3 小时），需保持终端开启

### 本地开发
```bash
python -m venv .venv && pip install -e .   # 各服务目录
python -m playwright install chromium
python main.py                              # 各服务
```

## 已修复的关键 Bug（2026-07）

1. **backend-web/app/services/xianyu_publisher.py**：`set_cookies` 被重复调用导致 Cookie 重复注入、发布/上架失败
2. **backend-web/app/services/product_publish_service.py**：`create()` 直接 `data["title"]` 无校验，缺字段即 500 崩溃
3. **websocket/app/api/routes/internal.py**：`deliver_order` 未检查 `auto_delivery_handler` 是否为 None，导致自动发货失败
4. **frontend/package.json**：`react-is` 版本 `^19.2.6` 与 React 18 冲突，改为 `^18.2.0`
5. **promotion/backend/main.py**：缺少 Nuitka 兼容加载逻辑（其他服务用 `importlib.util` 显式加载 `_bootstrap.py`）
6. **scheduler/app/services/scheduler/fetch_items_task.py**：账号间隔判断用 `is not`（对象身份）应为 `!=`
7. **scheduler/app/services/scheduler_service.py**：`stop()` 同步取消任务未 await，可能导致任务并发执行

## 开发约定

- 统一响应格式：`{ success, code, message, data }`，业务异常也返回 HTTP 200
- 数据库访问使用参数化查询，禁止字符串拼接 SQL
- 时间统一使用北京时间（`Asia/Shanghai`）
- 自动发货/自动评价等定时任务在 `scheduler` 服务实现，注意 Redis 分布式锁避免重复处理
- 不依赖外键约束，关系由代码维护

## 还原点

Git 分支 `backup-before-fix` 保存了修复前的干净状态，需要回退时：
```bash
git checkout backup-before-fix -- .
```
