#!/bin/bash
# ============================================
# Alpha Factory 统一调度器
# ============================================
# 用法: ./run_alpha_factory.sh <stage>
#   stage: mine    - 因子挖掘
#          wfa     - WFA验证
#          trade   - 交易执行
#          all     - 完整流程
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RESEARCH_DIR="$SCRIPT_DIR/research"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# 阶段1: 因子挖掘
run_mine() {
    log "🚀 阶段1: 因子挖掘启动..."
    cd "$RESEARCH_DIR"
    python3 factor_generator.py 2>&1 | tee "$LOG_DIR/factor_mining.log"
    log "✅ 因子挖掘完成"
}

# 阶段2: WFA验证
run_wfa() {
    log "🔬 阶段2: WFA验证启动..."
    cd "$RESEARCH_DIR"
    python3 auto_wfa_runner.py 2>&1 | tee "$LOG_DIR/wfa_validation.log"
    log "✅ WFA验证完成"
}

# 阶段3: 交易执行
run_trade() {
    log "💰 阶段3: 交易引擎启动..."
    cd "$SCRIPT_DIR"
    python3 alpha_factory_daemon.py 2>&1 | tee "$LOG_DIR/trading.log"
    log "✅ 交易引擎已停止"
}

# 完整流程
run_all() {
    log "🎯 执行完整 Alpha Factory 流程..."
    run_mine
    run_wfa
    # trade 是长期运行的守护进程，不在这里启动
    log "✅ 挖掘+验证完成，请手动启动交易引擎"
}

# 主入口
case "${1:-all}" in
    mine)
        run_mine
        ;;
    wfa)
        run_wfa
        ;;
    trade)
        run_trade
        ;;
    all)
        run_all
        ;;
    *)
        echo "用法: $0 {mine|wfa|trade|all}"
        exit 1
        ;;
esac
