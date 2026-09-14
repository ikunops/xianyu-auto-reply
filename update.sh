#!/bin/bash
# ==========================================
# 闲鱼自动回复系统 - 一键更新脚本（源码重建）
#
# 功能：
# 1. 拉取本仓库最新源码（git pull），再用 docker compose 从源码重建应用镜像并重启
# 2. 与 deploy.sh 共用根目录 docker-compose.yml 与 .env（源码构建，不拉取任何预构建应用镜像）
# 3. 不影响 MySQL / Redis 的数据（数据卷保留）
# 4. 自动检测并清理加密版（enc）的容器和镜像（保留数据卷）
#
# 用法：
#   bash update.sh [update|logs|status|clean-enc|help]
# ==========================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$WORK_DIR/docker-compose.yml"
ENV_FILE="$WORK_DIR/.env"
CMD="${1:-update}"

export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-xianyu-auto-reply}"

# 应用服务列表（不含 mysql / redis）
APP_SERVICES=(
    "frontend"
    "backend-web"
    "websocket"
    "scheduler"
)

# 加密版相关容器名（包含基础设施容器，数据卷会保留）
ENC_CONTAINERS=(
    "xianyu-enc-frontend"
    "xianyu-enc-backend-web"
    "xianyu-enc-websocket"
    "xianyu-enc-scheduler"
    "xianyu-enc-mysql"
    "xianyu-enc-redis"
)

# 加密版应用镜像名
ENC_IMAGE_NAMES=(
    "xianyu-enc-frontend"
    "xianyu-enc-backend-web"
    "xianyu-enc-websocket"
    "xianyu-enc-scheduler"
)

print_banner() {
    echo "=========================================="
    echo "  闲鱼自动回复系统 - 一键更新（源码重建）"
    echo "=========================================="
    echo ""
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}[错误] Docker 未安装，请先安装 Docker${NC}"
        exit 1
    fi

    if docker compose version &> /dev/null; then
        DC_CMD=(docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")
        DC_NAME="docker compose"
    elif command -v docker-compose &> /dev/null; then
        DC_CMD=(docker-compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE")
        DC_NAME="docker-compose"
    else
        echo -e "${RED}[错误] Docker Compose 未安装${NC}"
        exit 1
    fi

    echo -e "${CYAN}[信息] Docker: $(docker --version)${NC}"
    echo -e "${CYAN}[信息] Compose: $DC_NAME${NC}"
    echo -e "${CYAN}[信息] 项目目录: $WORK_DIR${NC}"
    echo ""
}

# 生成 .env（与 deploy.sh 保持一致的默认值）
generate_env_file() {
    cat > "$ENV_FILE" << 'ENVEOF'
# ==========================================
# 闲鱼自动回复系统 - 环境变量配置（源码构建部署）
# ==========================================

# MySQL数据库配置（Docker内置，自动创建）
MYSQL_ROOT_PASSWORD=xianyu@2026
MYSQL_DATABASE=xianyu_data
MYSQL_USER=xianyu
MYSQL_PASSWORD=xianyu@2026

# Redis缓存配置（Docker内置）
REDIS_PASSWORD=xianyu@2026
REDIS_DB=0

# 说明：JWT 密钥由数据库统一托管（首次启动自动生成并持久化），无需在此配置

# 端口配置（对外暴露端口；backend-web 默认 8098，避免与其他常用服务冲突）
FRONTEND_PORT=9000
BACKEND_WEB_PORT=8098
WEBSOCKET_PORT=8090
SCHEDULER_PORT=8091

# 基础镜像（默认官方镜像；国内网络拉取缓慢时，可换成本地镜像加速源）
MYSQL_IMAGE=mysql:8.0
REDIS_IMAGE=redis:7-alpine

# 日志级别
LOG_LEVEL=INFO

# SQL 日志开关：true=打印每条执行的完整 SQL（便于排查）；高并发生产环境可设为 false
SQL_ECHO=true

# IM Token 缓存（xy_token_cache 表）随机过期时间区间（小时），不配置默认 5~10 小时
TOKEN_CACHE_TTL_MIN_HOURS=5
TOKEN_CACHE_TTL_MAX_HOURS=10

# Token过期时间（分钟）
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_MINUTES=10080

# 定时任务间隔（分钟）
REDELIVERY_INTERVAL=5
RATE_INTERVAL=20

# 验证码并发数
MAX_CAPTCHA_CONCURRENT=3

# WebSocket 启动时是否自动连接账号
AUTO_START_WEBSOCKET=true
# 滑块验证 DrissionPage 兜底引擎（主引擎失败后重试）：开关 / 超时秒 / 无头
CAPTCHA_DRISSIONPAGE_FALLBACK_ENABLED=true
CAPTCHA_DRISSIONPAGE_TIMEOUT=25
CAPTCHA_DRISSIONPAGE_HEADLESS=true

# 分销卡券上游服务基址（「分销卡券」页面提货 + 个人设置一键创建对接卡密秘钥共用此基址）
CARD_DOCK_BASE_URL=
# 个人设置「对接卡密秘钥」一键创建密钥的鉴权 key（基址复用 CARD_DOCK_BASE_URL）
EXTERNAL_API_KEY=

# 前端公网访问地址（用于生成前端页面分享链接，留空则使用默认）
FRONTEND_PUBLIC_URL=
# 启动时是否自动启动 Goofish 定时采集任务
AUTO_START_CRAWL_JOBS=true
ENVEOF
}

check_deploy_files() {
    if [ ! -f "$ENV_FILE" ]; then
        echo -e "${YELLOW}[信息] 未找到 .env 配置文件，自动生成默认配置...${NC}"
        generate_env_file
        echo -e "${GREEN}✓ 已生成 .env 文件${NC}"
        echo ""
    fi

    if [ ! -f "$COMPOSE_FILE" ]; then
        echo -e "${RED}[错误] 未找到 $COMPOSE_FILE（源码构建编排文件缺失，请检查仓库完整性）${NC}"
        exit 1
    fi
}

# 创建宿主机挂载目录
create_mount_dirs() {
    mkdir -p \
        "$WORK_DIR/xianyu_auto_reply/mysql/data" \
        "$WORK_DIR/xianyu_auto_reply/redis/data" \
        "$WORK_DIR/xianyu_auto_reply/logs/backend_web" \
        "$WORK_DIR/xianyu_auto_reply/logs/websocket" \
        "$WORK_DIR/xianyu_auto_reply/logs/scheduler" \
        "$WORK_DIR/xianyu_auto_reply/static" \
        "$WORK_DIR/xianyu_auto_reply/backups" \
        "$WORK_DIR/xianyu_auto_reply/browser_data"
}

# 检测并清理加密版容器和镜像（保留数据卷）
cleanup_enc_version() {
    echo -e "${YELLOW}[信息] 检测加密版部署残留...${NC}"

    local enc_found=0

    for container in "${ENC_CONTAINERS[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            enc_found=1
            break
        fi
    done

    if [ $enc_found -eq 0 ]; then
        echo -e "${GREEN}✓ 未检测到加密版容器，无需清理${NC}"
        echo ""
        return
    fi

    echo -e "${YELLOW}[信息] 检测到加密版容器，开始清理（保留数据卷）...${NC}"

    for container in "${ENC_CONTAINERS[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            echo -e "${CYAN}  停止并删除容器: ${container}${NC}"
            docker stop "$container" 2>/dev/null || true
            docker rm "$container" 2>/dev/null || true
        fi
    done

    local removed=0
    for name in "${ENC_IMAGE_NAMES[@]}"; do
        local image_ids
        image_ids=$(docker images --filter "reference=*/${name}*" --format '{{.ID}}' 2>/dev/null | sort -u)
        for id in $image_ids; do
            if docker rmi "$id" --force 2>/dev/null; then
                removed=$((removed+1))
            fi
        done
    done
    echo -e "${GREEN}✓ 已清理 ${removed} 个加密版应用镜像${NC}"

    local enc_network
    for enc_network in $(docker network ls --format '{{.Name}}' | grep -i "enc" | grep -i "xianyu"); do
        echo -e "${CYAN}  删除网络: ${enc_network}${NC}"
        docker network rm "$enc_network" 2>/dev/null || true
    done

    echo -e "${GREEN}✓ 加密版清理完成（数据卷已保留）${NC}"
    echo ""
}

read_env_value() {
    local key="$1"
    grep -E "^${key}=" "$ENV_FILE" | tail -n 1 | cut -d '=' -f2- | tr -d '\r'
}

# 拉取最新源码
pull_latest_source() {
    if [ ! -d "$WORK_DIR/.git" ]; then
        echo -e "${YELLOW}[提示] 当前目录不是 git 仓库，跳过源码拉取，直接用现有源码重建${NC}"
        echo ""
        return
    fi

    echo -e "${YELLOW}[信息] 拉取最新源码...${NC}"
    if git -C "$WORK_DIR" pull --ff-only; then
        echo -e "${GREEN}✓ 源码已是最新${NC}"
    else
        echo -e "${YELLOW}[警告] git pull 失败（本地有改动或分支冲突？），继续使用现有源码重建${NC}"
    fi
    echo ""
}

# 从源码重建并重启应用服务
rebuild_app_services() {
    echo -e "${YELLOW}[信息] 从源码重新构建应用镜像...${NC}"
    "${DC_CMD[@]}" build "${APP_SERVICES[@]}"
    echo -e "${GREEN}✓ 镜像构建完成${NC}"

    echo -e "${YELLOW}[信息] 重建应用容器（不影响 MySQL/Redis 数据卷）...${NC}"
    "${DC_CMD[@]}" up -d "${APP_SERVICES[@]}"
    echo -e "${YELLOW}[信息] 等待服务启动...${NC}"
    sleep 15
    "${DC_CMD[@]}" ps
    echo ""
}

print_success_info() {
    local frontend_port backend_web_port websocket_port scheduler_port
    frontend_port="$(read_env_value FRONTEND_PORT)"
    backend_web_port="$(read_env_value BACKEND_WEB_PORT)"
    websocket_port="$(read_env_value WEBSOCKET_PORT)"
    scheduler_port="$(read_env_value SCHEDULER_PORT)"

    frontend_port="${frontend_port:-9000}"
    backend_web_port="${backend_web_port:-8098}"
    websocket_port="${websocket_port:-8090}"
    scheduler_port="${scheduler_port:-8091}"

    echo -e "${GREEN}=========================================="
    echo "  更新完成！（源码重建）"
    echo "==========================================${NC}"
    echo ""
    echo "服务访问地址："
    echo "  前端:        http://服务器IP:${frontend_port}"
    echo "  Backend-Web: http://服务器IP:${backend_web_port}"
    echo "  WebSocket:   http://服务器IP:${websocket_port}"
    echo "  Scheduler:   http://服务器IP:${scheduler_port}"
    echo ""
    echo "常用命令："
    echo "  查看状态: bash $0 status"
    echo "  查看日志: bash $0 logs"
    echo "  再次更新: bash $0 update"
    echo "  清理加密版: bash $0 clean-enc"
    echo ""
}

# 主更新流程
run_update() {
    print_banner
    check_docker
    check_deploy_files
    create_mount_dirs
    cleanup_enc_version
    pull_latest_source
    rebuild_app_services
    print_success_info
}

# 仅清理加密版
run_clean_enc() {
    print_banner
    check_docker
    cleanup_enc_version
    echo -e "${GREEN}加密版清理完成。数据卷已保留。${NC}"
    echo ""
    echo -e "${YELLOW}[提示] 如需同时删除加密版的数据卷（会丢失所有数据），请手动执行：${NC}"
    echo "  docker volume rm xianyu_auto_reply_enc_mysql_data xianyu_auto_reply_enc_redis_data"
    echo ""
}

show_help() {
    echo "用法: bash update.sh [update|logs|status|clean-enc|help]"
    echo ""
    echo "  update    - git pull 最新源码后从源码重建应用容器，不影响 MySQL/Redis 数据（默认）"
    echo "  logs      - 查看实时日志"
    echo "  status    - 查看服务状态"
    echo "  clean-enc - 仅清理加密版容器和镜像（保留数据卷）"
    echo "  help      - 查看帮助"
}

case "$CMD" in
    update)
        run_update
        ;;
    logs)
        check_docker
        check_deploy_files
        "${DC_CMD[@]}" logs -f --tail=100
        ;;
    status)
        check_docker
        check_deploy_files
        "${DC_CMD[@]}" ps
        ;;
    clean-enc)
        check_docker
        run_clean_enc
        ;;
    help|-h|--help)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac
