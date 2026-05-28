"""平仓策略 — 根据不同方法计算止盈价。

来自币哥双均线交易系统的三种平仓法：
1. 赔率平仓法 (FixedOddsExit) — 固定赔率，如 1:3、1:5
2. 上一个均线密集平仓法 (MAClusterExit) — 止盈设在前一个均线密集区
3. 斐波那契平仓法 (FibonacciExit) — 突破历史新高时用 Fib 1.618/2.618

用法：
    strategy = FixedOddsExit(odds_ratio=3.0)
    tp = strategy.calc_take_profit(entry_price, stop_loss_price, direction)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from investment.logger import logger


class ExitStrategy(ABC):
    """退出策略抽象基类。"""

    name: str = ""

    @abstractmethod
    def calc_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: str,
        *,
        df: Optional[pd.DataFrame] = None,
        **kwargs,
    ) -> Optional[float]:
        """计算止盈价。

        Args:
            entry_price: 开仓价
            stop_loss_price: 止损价
            direction: "long" / "short"
            df: K 线数据（部分策略需要）
            **kwargs: 策略特定参数

        Returns:
            止盈价，None 表示无法计算
        """
        ...


# ============================================================
# 1. 赔率平仓法
# ============================================================

class FixedOddsExit(ExitStrategy):
    """赔率平仓法 — 固定赔率止盈。

    公式（做多）：take_profit = entry + (entry - stop_loss) × odds_ratio
    公式（做空）：take_profit = entry - (stop_loss - entry) × odds_ratio

    视频原文：
    "做这笔交易就是想做 1:5 赔率的交易，行情走到止盈位就平"
    "赔一块钱能赚五块钱，这就是高赔率"
    """

    name = "fixed_odds"

    def __init__(self, odds_ratio: float = 3.0) -> None:
        self.odds_ratio = odds_ratio

    def calc_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: str,
        **kwargs,
    ) -> float:
        risk = abs(entry_price - stop_loss_price)
        reward = risk * self.odds_ratio

        if direction == "long":
            return entry_price + reward
        else:  # short
            return entry_price - reward


# ============================================================
# 2. 上一个均线密集平仓法
# ============================================================

@dataclass
class MAClusterZone:
    """一个均线密集区的范围。"""
    start_idx: int
    end_idx: int
    high: float
    low: float
    center: float  # (high + low) / 2


class MAClusterExit(ExitStrategy):
    """上一个均线密集平仓法 — 止盈设在前一个均线密集区。

    原理：均线密集 = 市场平均筹码价格趋向一致，价格到达该区域时
    大概率有阻力或支撑。

    视频原文：
    "均线密集代表了市场平均筹码的价格，行情如果移动到这个位置
    大概率是有阻力或者是有支撑的"
    "我们就可以把止盈位置设置在上一个之前均线密集的地方"
    """

    name = "ma_cluster"

    def __init__(
        self,
        convergence_threshold: float = 0.5,
        min_bars: int = 3,
    ) -> None:
        """
        Args:
            convergence_threshold: 6 条均线的最大价差占比（%），
                                   低于此值视为密集。0.5 = 0.5%
            min_bars: 密集区最少持续 K 线数
        """
        self.convergence_threshold = convergence_threshold
        self.min_bars = min_bars

    def calc_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: str,
        *,
        df: Optional[pd.DataFrame] = None,
        **kwargs,
    ) -> Optional[float]:
        if df is None or df.empty:
            return None

        # 找到所有均线密集区
        clusters = self.find_clusters(df)
        if not clusters:
            logger.debug("未找到均线密集区，无法使用 ma_cluster 平仓法")
            return None

        # 找开仓价所在的密集区（或最近的密集区）
        current_price = entry_price
        entry_cluster = None
        for c in clusters:
            if c.low <= current_price <= c.high:
                entry_cluster = c
                break

        if entry_cluster is None:
            # 找最近的密集区
            distances = [(abs(c.center - current_price), c) for c in clusters]
            distances.sort(key=lambda x: x[0])
            entry_cluster = distances[0][1]

        # 找前一个密集区（方向相关）
        entry_idx = clusters.index(entry_cluster)
        target_cluster = None

        if direction == "long":
            # 做多：止盈在前方（价格更高）的密集区
            for i in range(entry_idx + 1, len(clusters)):
                if clusters[i].low > entry_price:
                    target_cluster = clusters[i]
                    break
        else:  # short
            # 做空：止盈在前方（价格更低）的密集区
            for i in range(entry_idx - 1, -1, -1):
                if clusters[i].high < entry_price:
                    target_cluster = clusters[i]
                    break

        if target_cluster is None:
            logger.debug("未找到合适的前一个均线密集区")
            return None

        # 取密集区的中心价作为止盈
        tp = target_cluster.center
        logger.info(
            f"均线密集平仓：目标密集区 [{target_cluster.low:.2f}, {target_cluster.high:.2f}] "
            f"止盈={tp:.2f}"
        )
        return tp

    def find_clusters(self, df: pd.DataFrame) -> list[MAClusterZone]:
        """在 K 线数据中查找所有均线密集区。"""
        ma_cols = [c for c in df.columns if c.startswith(("sma", "ema")) and c[3:].isdigit()]
        if len(ma_cols) < 3:
            # 用常见的均线列名
            ma_cols = [c for c in df.columns if any(
                p in c.lower() for p in ["sma20", "sma60", "sma120", "ema20", "ema60", "ema120"]
            )]
        if len(ma_cols) < 3:
            logger.warning(f"均线列不足，找到 {len(ma_cols)} 列: {ma_cols}")
            return []

        # 确保只用已确认的 K 线
        cdf = df[df["confirm"]].copy() if "confirm" in df.columns else df.copy()
        if len(cdf) < self.min_bars + 10:
            return []

        clusters: list[MAClusterZone] = []
        in_cluster = False
        start_idx = 0

        for i in range(len(cdf)):
            row = cdf.iloc[i]
            ma_values = [row[c] for c in ma_cols if pd.notna(row[c])]
            if len(ma_values) < 3:
                continue

            ma_max = max(ma_values)
            ma_min = min(ma_values)
            ma_center = (ma_max + ma_min) / 2

            # 判断是否密集：最大价差占中心价的百分比
            if ma_center > 0:
                spread_pct = (ma_max - ma_min) / ma_center * 100
            else:
                spread_pct = 999

            is_converged = spread_pct <= self.convergence_threshold

            if is_converged and not in_cluster:
                in_cluster = True
                start_idx = i
            elif not is_converged and in_cluster:
                in_cluster = False
                duration = i - start_idx
                if duration >= self.min_bars:
                    cluster_slice = cdf.iloc[start_idx:i]
                    all_highs = []
                    all_lows = []
                    for c in ma_cols:
                        vals = cluster_slice[c].dropna()
                        if not vals.empty:
                            all_highs.append(vals.max())
                            all_lows.append(vals.min())
                    if all_highs and all_lows:
                        zone_high = max(all_highs)
                        zone_low = min(all_lows)
                        clusters.append(MAClusterZone(
                            start_idx=start_idx,
                            end_idx=i - 1,
                            high=zone_high,
                            low=zone_low,
                            center=(zone_high + zone_low) / 2,
                        ))

        # 处理末尾仍在密集中的情况
        if in_cluster:
            duration = len(cdf) - start_idx
            if duration >= self.min_bars:
                cluster_slice = cdf.iloc[start_idx:]
                all_highs = []
                all_lows = []
                for c in ma_cols:
                    vals = cluster_slice[c].dropna()
                    if not vals.empty:
                        all_highs.append(vals.max())
                        all_lows.append(vals.min())
                if all_highs and all_lows:
                    zone_high = max(all_highs)
                    zone_low = min(all_lows)
                    clusters.append(MAClusterZone(
                        start_idx=start_idx,
                        end_idx=len(cdf) - 1,
                        high=zone_high,
                        low=zone_low,
                        center=(zone_high + zone_low) / 2,
                    ))

        logger.debug(f"找到 {len(clusters)} 个均线密集区")
        return clusters


# ============================================================
# 3. 斐波那契平仓法
# ============================================================

class FibonacciExit(ExitStrategy):
    """斐波那契平仓法 — 突破历史新高时用 Fib 回撤目标位。

    适用场景：价格突破历史前高，均线密集法和赔率法都不太适用时。

    视频原文：
    "一般行情突破了历史新高之后，基本上都会到达斐波那契
    1.618 和 2.618 两个位置"

    用法：从上一个周期高点到低点画斐波那契，取 1.618 和 2.618 作为目标。
    如果有多个目标，取第一个（保守）或分批止盈。
    """

    name = "fibonacci"

    # 斐波那契扩展目标位
    FIB_LEVELS = [1.0, 1.272, 1.618, 2.0, 2.618, 3.618, 4.236]

    def __init__(
        self,
        primary_level: float = 1.618,
        fallback_level: float = 2.618,
        lookback_bars: int = 200,
    ) -> None:
        """
        Args:
            primary_level: 首选 Fib 扩展目标（1.618）
            fallback_level: 备选目标（2.618）
            lookback_bars: 回溯多少根 K 线找前高前低
        """
        self.primary_level = primary_level
        self.fallback_level = fallback_level
        self.lookback_bars = lookback_bars

    def calc_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        direction: str,
        *,
        df: Optional[pd.DataFrame] = None,
        **kwargs,
    ) -> Optional[float]:
        if df is None or df.empty:
            return None

        cdf = df[df["confirm"]].copy() if "confirm" in df.columns else df.copy()
        if len(cdf) < 20:
            return None

        # 取最近 lookback_bars 根 K 线
        lookback = min(self.lookback_bars, len(cdf))
        recent = cdf.iloc[-lookback:]

        swing_high = recent["high"].max()
        swing_low = recent["low"].min()
        swing_range = swing_high - swing_low

        if swing_range <= 0:
            return None

        if direction == "long":
            # 做多：从低点到高点的 Fib 扩展
            # Fib 目标 = swing_low + swing_range × level
            # 但视频说的是从高点拉到低点再反转
            # 实际用法：突破前高后，目标 = 前高 + range × (level - 1)
            base = swing_high
            target = base + swing_range * (self.primary_level - 1.0)

            # 验证：目标必须高于开仓价
            if target <= entry_price:
                target = base + swing_range * (self.fallback_level - 1.0)
            if target <= entry_price:
                return None

            return target

        else:  # short
            # 做空：从高点到低点的 Fib 扩展
            base = swing_low
            target = base - swing_range * (self.primary_level - 1.0)

            # 验证：目标必须低于开仓价
            if target >= entry_price:
                target = base - swing_range * (self.fallback_level - 1.0)
            if target >= entry_price:
                return None

            return target


# ============================================================
# 工厂 + 默认组合
# ============================================================

EXIT_STRATEGIES = {
    "fixed_odds": FixedOddsExit,
    "ma_cluster": MAClusterExit,
    "fibonacci": FibonacciExit,
}


def create_exit_strategy(name: str, **kwargs) -> ExitStrategy:
    """根据名称创建退出策略实例。"""
    cls = EXIT_STRATEGIES.get(name)
    if cls is None:
        raise ValueError(f"未知退出策略: {name}，可选: {list(EXIT_STRATEGIES.keys())}")
    return cls(**kwargs)


__all__ = [
    "ExitStrategy",
    "FixedOddsExit",
    "MAClusterExit",
    "FibonacciExit",
    "EXIT_STRATEGIES",
    "create_exit_strategy",
]
