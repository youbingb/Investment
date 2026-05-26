"""按 config/signals.yaml 装配启用的规则。

用法：
    from investment.signals.loader import load_rules
    rules = load_rules()       # 默认 config/signals.yaml
    for rule in rules:
        signal = rule.evaluate(df, symbol="BTC-USDT", timeframe="1H")

扩展：用户自定义规则放 src/investment/signals/custom/ 下，
然后在自己代码里 import 并写进 REGISTRY；或者直接通过 load_rules 的
extra_registry 参数传入。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from investment.logger import logger
from investment.signals.base import SignalRule
from investment.signals.examples.dot_pullback import DotPullbackRule
from investment.signals.examples.golden_cross import GoldenCrossRule
from investment.signals.examples.ma20_pullback import Ma20PullbackRule
from investment.signals.examples.ma_cluster_breakout import MaClusterBreakoutRule

#: 内置规则注册表（name → class）。
REGISTRY: dict[str, type[SignalRule]] = {
    GoldenCrossRule.name: GoldenCrossRule,
    DotPullbackRule.name: DotPullbackRule,
    MaClusterBreakoutRule.name: MaClusterBreakoutRule,
    Ma20PullbackRule.name: Ma20PullbackRule,
}

DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "signals.yaml"


def load_rules(
    config_path: Optional[Path] = None,
    extra_registry: Optional[dict[str, type[SignalRule]]] = None,
) -> list[SignalRule]:
    """读 yaml，返回 enabled 规则的实例列表。

    Args:
        config_path: 不传时用项目根的 ``config/signals.yaml``
        extra_registry: 调用方临时注入自定义规则（不污染全局 REGISTRY）

    yaml 中未知的规则名会被跳过 + 打 WARNING，不抛错（容忍配置和代码版本不同步）。
    """
    path = config_path or DEFAULT_CONFIG
    if not path.exists():
        logger.warning(f"signals 配置不存在：{path}，返回空列表")
        return []

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    registry: dict[str, type[SignalRule]] = {**REGISTRY, **(extra_registry or {})}
    rules_config = config.get("rules", {})
    if not isinstance(rules_config, dict):
        logger.warning(f"signals.yaml 的 rules 字段不是 dict：{rules_config!r}")
        return []

    enabled: list[SignalRule] = []
    for name, params in rules_config.items():
        if not isinstance(params, dict):
            logger.warning(f"规则 {name} 配置不是 dict，跳过")
            continue
        if not params.get("enabled", False):
            continue
        cls = registry.get(name)
        if cls is None:
            logger.warning(f"未知规则 {name!r}，跳过；可用：{sorted(registry)}")
            continue
        enabled.append(cls(params=params))
        logger.debug(f"加载规则 {name} 参数 {params}")

    return enabled


__all__ = ["load_rules", "REGISTRY", "DEFAULT_CONFIG"]
