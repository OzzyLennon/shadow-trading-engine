# 未来交易基础设施规划

## 🚨 核心风险：Legging Risk（腿风险）

### 现状问题

Blue Engine当前模拟交易逻辑：
```python
# 买入正股
stock_order(stock, shares)
# 做空ETF
short_order(etf, shares)
```

**致命隐患**：两笔订单非原子操作，存在时间差。

### 风险场景

| 时间 | 事件 | 后果 |
|------|------|------|
| T+0ms | 买入10万寒武纪 ✅ | 持有多头敞口 |
| T+50ms | ETF涨停/融券池空 ❌ | 对冲失败 |
| 结果 | 单边多头暴露 | 策略失效，变成赌博 |

---

## 🛠️ 优化方案

### 1. 原子化双轨下单 (Atomic Paired Routing)

**原理**：多头和空头订单必须"同生共死"

```python
class AtomicOrderRouter:
    """
    原子化订单路由器
    确保对冲订单要么全部成交，要么全部撤销
    """
    
    def execute_paired_order(self, long_order, short_order):
        """
        执行配对订单
        """
        # 1. 预锁定双边的流动性
        long_locked = self.check_liquidity(long_order)
        short_locked = self.check_liquidity(short_order)
        
        if not (long_locked and short_locked):
            # 任意一边流动性不足，全部撤销
            return "CANCELLED - Liquidity Check Failed"
        
        # 2. 同时下单（毫秒级）
        long_id = self.submit_order(long_order)
        short_id = self.submit_order(short_order)
        
        # 3. 监控成交状态
        for _ in range(100):  # 100次轮询
            long_status = self.get_order_status(long_id)
            short_status = self.get_order_status(short_id)
            
            # 如果任意一边失败，立即撤销另一边
            if long_status == "FAILED":
                self.cancel_order(short_id)
                return "CANCELLED - Long Leg Failed"
            if short_status == "FAILED":
                self.cancel_order(long_id)
                return "CANCELLED - Short Leg Failed"
            
            # 双边成交，完成对冲
            if long_status == "FILLED" and short_status == "FILLED":
                return "SUCCESS - Both Legs Filled"
            
            time.sleep(0.01)  # 10ms轮询
        
        # 超时，撤销所有
        self.cancel_order(long_id)
        self.cancel_order(short_id)
        return "CANCELLED - Timeout"
```

---

### 2. 执行算法 (Execution Algos)

#### 2.1 TWAP (时间加权平均价格)

**适用场景**：大额订单，避免冲击成本

```python
class TWAPExecutor:
    """
    时间加权平均执行器
    将大单拆成小单，均匀分布在时间窗口内
    """
    
    def execute(self, order, duration_minutes=30):
        """
        order: 总订单
        duration_minutes: 执行时长
        """
        total_shares = order['shares']
        slices = duration_minutes  # 每分钟执行一次
        shares_per_slice = total_shares // slices
        
        filled_shares = 0
        for minute in range(slices):
            # 每分钟执行一小部分
            slice_order = {
                'symbol': order['symbol'],
                'shares': shares_per_slice,
                'side': order['side']
            }
            
            result = self.submit_market_order(slice_order)
            filled_shares += result['filled']
            
            log(f"TWAP Slice {minute+1}/{slices}: {result['filled']} shares @ {result['price']}")
            
            time.sleep(60)  # 等待1分钟
        
        return {'total_filled': filled_shares}
```

#### 2.2 VWAP (成交量加权平均价格)

**适用场景**：跟随市场成交量节奏

```python
class VWAPExecutor:
    """
    成交量加权平均执行器
    根据市场成交量分布调整下单节奏
    """
    
    def execute(self, order, volume_profile):
        """
        volume_profile: 预测的日内成交量分布
        例如: [0.05, 0.08, 0.12, ..., 0.15, 0.10, ...]
        """
        total_shares = order['shares']
        
        for minute, volume_pct in enumerate(volume_profile):
            # 按成交量比例下单
            shares_this_minute = int(total_shares * volume_pct)
            
            if shares_this_minute > 0:
                slice_order = {
                    'symbol': order['symbol'],
                    'shares': shares_this_minute,
                    'side': order['side']
                }
                self.submit_limit_order(slice_order)
            
            time.sleep(60)
```

---

### 3. 完整架构图

```
┌─────────────────────────────────────────────────────────┐
│                  Blue Engine Strategy                    │
│              (低波蓄势 + 动量突破 + Beta对冲)             │
└─────────────────────┬───────────────────────────────────┘
                      │ 信号触发
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Order Router (订单路由层)                    │
│  ┌─────────────────────────────────────────────────┐   │
│  │  Atomic Paired Router (原子配对路由)             │   │
│  │  - 预锁定流动性                                   │   │
│  │  - 同生共死机制                                   │   │
│  │  - 超时撤销                                       │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Execution Algos (执行算法层)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │   TWAP       │  │    VWAP      │  │   POV        │ │
│  │ (时间加权)   │  │ (成交量加权) │  │ (成交量比例) │ │
│  └──────────────┘  └──────────────┘  └──────────────┘ │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              Broker API (券商接口层)                      │
│  - 恒生/金证柜台                                          │
│  - QMT/PTrade                                            │
│  - CTP (期货)                                            │
└─────────────────────────────────────────────────────────┘
```

---

## 📋 实施路线图

| 阶段 | 内容 | 状态 |
|------|------|------|
| **Phase 1** | 模拟盘验证策略 | ✅ 已完成 |
| **Phase 2** | 接入券商API | 🔜 待实施 |
| **Phase 3** | 实现Atomic Router | 🔜 待实施 |
| **Phase 4** | 实现TWAP/VWAP | 🔜 待实施 |
| **Phase 5** | 实盘小资金测试 | 🔜 待实施 |

---

## ⚠️ 关键注意事项

1. **模拟盘 vs 实盘**
   - 模拟盘不需要考虑流动性和滑点
   - 实盘必须使用执行算法

2. **券商限制**
   - 融券池容量有限
   - ETF做空可能受限
   - 需要提前预约融券

3. **监管合规**
   - 算法交易需要报备
   - 禁止频繁撤单
   - 禁止幌骗交易

---

*文档创建时间: 2026-03-18*
*最后更新: 2026-03-18*
