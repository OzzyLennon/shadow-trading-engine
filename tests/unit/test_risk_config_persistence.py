# -*- coding: utf-8 -*-
"""
回归测试：AI Sentinel 的风控熔断开关不能被 ai_brain 全量覆写清空。

背景（2026-11-02 实测）：
  ai_sentinel.py 把 red_engine_allow / blue_engine_allow / global_market_status
  写进 daily_config.json（交易引擎据此决定是否锁死）。
  ai_brain.py 每天 08:30 全量重写同一个文件，原实现会把这些字段清掉，
  导致熔断信号在引擎启动前（09:25）丢失，引擎退回默认「允许交易」。

  这个 bug 静默发生：代码看起来都对，测试全绿，但风控是哑的。
  所以这里直接测「保存后字段还在不在」，而不是测函数返回值。
"""

import json
import os
import sys
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


RISK_KEYS = (
    'red_engine_allow',
    'blue_engine_allow',
    'global_market_status',
    'red_reasoning',
    'blue_reasoning',
    'allow_trading',
    'market_regime',
    'risk_updated_at',
)


@pytest.fixture
def brain_module(tmp_path, monkeypatch):
    """加载 ai_brain，并把 CONFIG_FILE 指向临时文件。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ai_brain_under_test", os.path.join(PROJECT_ROOT, "ai_brain.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cfg = tmp_path / "daily_config.json"
    monkeypatch.setattr(module, "CONFIG_FILE", str(cfg))
    return module, cfg


def _write(cfg, **risk):
    payload = {
        'market_sentiment': '看空',
        'risk_level': '极高',
        'trade_ratio': 0.05,
    }
    payload.update(risk)
    with open(cfg, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)


def test_fuse_survives_brain_rewrite(brain_module):
    """熔断信号写入后，ai_brain 的全量覆写不得把它清掉。"""
    brain, cfg = brain_module

    # 1) AI Sentinel 写入熔断信号
    _write(
        cfg,
        red_engine_allow=False,
        blue_engine_allow=False,
        global_market_status='BLACK_SWAN',
        red_reasoning='模拟黑天鹅',
        blue_reasoning='模拟黑天鹅',
        allow_trading=False,
        market_regime='BLACK_SWAN',
        risk_updated_at='2026-11-02T08:40:00',
    )

    # 2) ai_brain 用一份「不含风控字段」的参数全量覆写
    brain_out = {
        'market_sentiment': '看空',
        'risk_level': '极高',
        'trade_ratio': 0.05,
    }
    brain.save_daily_config(brain_out)

    with open(cfg, 'r', encoding='utf-8') as f:
        after = json.load(f)

    assert after['red_engine_allow'] is False, "熔断信号被 ai_brain 清空了"
    assert after['blue_engine_allow'] is False, "熔断信号被 ai_brain 清空了"
    assert after['global_market_status'] == 'BLACK_SWAN'
    assert after['red_reasoning'] == '模拟黑天鹅'
    assert after['risk_updated_at'] == '2026-11-02T08:40:00'

    # 3) ai_brain 自己的参数也要正常落盘，不能为了保风控把参数搞丢
    assert after['market_sentiment'] == '看空'
    assert after['trade_ratio'] == 0.05


def test_normal_state_also_preserved(brain_module):
    """非熔断状态同样要保留（避免「今天没熔断就把开关删了」的反向 bug）。"""
    brain, cfg = brain_module

    _write(
        cfg,
        red_engine_allow=True,
        blue_engine_allow=True,
        global_market_status='NORMAL',
        red_reasoning='正常',
        blue_reasoning='正常',
    )

    brain.save_daily_config({'market_sentiment': '看多', 'trade_ratio': 0.1})

    with open(cfg, 'r', encoding='utf-8') as f:
        after = json.load(f)

    assert after['red_engine_allow'] is True
    assert after['global_market_status'] == 'NORMAL'
    assert after['market_sentiment'] == '看多'


def test_engine_reads_fuse_from_config(brain_module):
    """端到端：引擎侧读到的必须是 False（真被锁住），而不是默认值 True。"""
    brain, cfg = brain_module

    _write(
        cfg,
        red_engine_allow=False,
        blue_engine_allow=False,
        global_market_status='BLACK_SWAN',
    )
    brain.save_daily_config({'market_sentiment': '看空', 'trade_ratio': 0.05})

    from core.config import load_env, load_config_with_fallback

    load_env()
    loaded = load_config_with_fallback(config_file=str(cfg))

    assert loaded.red_engine_allow is False, "引擎读到的还是默认值 True —— 风控是哑的"
    assert loaded.blue_engine_allow is False
    assert loaded.global_market_status == 'BLACK_SWAN'


def test_missing_config_file_is_tolerated(brain_module):
    """配置文件不存在时不能崩（首次运行场景）。"""
    brain, cfg = brain_module

    assert not os.path.exists(cfg)
    brain.save_daily_config({'market_sentiment': '看空', 'trade_ratio': 0.05})

    with open(cfg, 'r', encoding='utf-8') as f:
        after = json.load(f)
    assert after['market_sentiment'] == '看空'
