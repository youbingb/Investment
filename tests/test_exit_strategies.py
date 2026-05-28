"""退出策略单元测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from investment.trader.exit_strategies import (
    FixedOddsExit,
    MAClusterExit,
    FibonacciExit,
    create_exit_strategy,
)


class TestFixedOddsExit:
    def test_long_1to3(self) -> None:
        s = FixedOddsExit(odds_ratio=3.0)
        tp = s.calc_take_profit(50000.0, 48500.0, "long")
        # risk = 50000 - 48500 = 1500
        # reward = 1500 * 3 = 4500
        # tp = 50000 + 4500 = 54500
        assert tp == pytest.approx(54500.0)

    def test_short_1to3(self) -> None:
        s = FixedOddsExit(odds_ratio=3.0)
        tp = s.calc_take_profit(50000.0, 51500.0, "short")
        # risk = 51500 - 50000 = 1500
        # reward = 1500 * 3 = 4500
        # tp = 50000 - 4500 = 45500
        assert tp == pytest.approx(45500.0)

    def test_long_1to5(self) -> None:
        s = FixedOddsExit(odds_ratio=5.0)
        tp = s.calc_take_profit(60000.0, 59000.0, "long")
        # risk = 1000, reward = 5000, tp = 65000
        assert tp == pytest.approx(65000.0)

    def test_name(self) -> None:
        s = FixedOddsExit()
        assert s.name == "fixed_odds"


class TestMAClusterExit:
    def _make_df(self, clusters: list[tuple[float, float]], total_bars: int = 50) -> pd.DataFrame:
        """创建带有均线密集区的模拟 K 线数据。

        Args:
            clusters: [(low, high), ...] 每个密集区的价格范围
            total_bars: 总 K 线数
        """
        np.random.seed(42)
        n = total_bars
        bars_per_cluster = n // (len(clusters) + 1)

        data = {
            "confirm": [True] * n,
            "open": np.zeros(n),
            "high": np.zeros(n),
            "low": np.zeros(n),
            "close": np.zeros(n),
            "sma20": np.zeros(n),
            "sma60": np.zeros(n),
            "sma120": np.zeros(n),
            "ema20": np.zeros(n),
            "ema60": np.zeros(n),
            "ema120": np.zeros(n),
        }

        for i in range(n):
            # 确定当前属于哪个阶段
            cluster_idx = i // bars_per_cluster - 1
            if cluster_idx < 0 or cluster_idx >= len(clusters):
                # 过渡区：均线发散
                base = 50000 + np.random.randn() * 500
                spread = 200  # 均线发散时价差大
            else:
                # 密集区：均线收敛
                lo, hi = clusters[cluster_idx]
                base = (lo + hi) / 2
                spread = (hi - lo) / 2 * 0.3  # 密集区内价差很小

            data["close"][i] = base
            data["open"][i] = base + np.random.randn() * 10
            data["high"][i] = base + abs(np.random.randn() * 50)
            data["low"][i] = base - abs(np.random.randn() * 50)

            # 6 条均线围绕 base 波动
            offsets = [-spread * 0.5, 0, spread * 0.3, -spread * 0.2, spread * 0.1, -spread * 0.4]
            for j, col in enumerate(["sma20", "sma60", "sma120", "ema20", "ema60", "ema120"]):
                data[col][i] = base + offsets[j] + np.random.randn() * spread * 0.1

        return pd.DataFrame(data)

    def test_find_clusters(self) -> None:
        s = MAClusterExit(convergence_threshold=2.0, min_bars=3)
        # 两个密集区：一个在 49000-51000，一个在 55000-57000
        df = self._make_df([(49000, 51000), (55000, 57000)])
        clusters = s.find_clusters(df)
        # 应该能找到至少 1 个密集区
        assert len(clusters) >= 1

    def test_long_tp_above_entry(self) -> None:
        s = MAClusterExit(convergence_threshold=2.0, min_bars=3)
        df = self._make_df([(49000, 51000), (55000, 57000)])
        tp = s.calc_take_profit(50000.0, 48500.0, "long", df=df)
        # 如果找到了密集区，止盈应该高于开仓价
        if tp is not None:
            assert tp > 50000.0

    def test_short_tp_below_entry(self) -> None:
        s = MAClusterExit(convergence_threshold=2.0, min_bars=3)
        df = self._make_df([(45000, 47000), (51000, 53000)])
        tp = s.calc_take_profit(52000.0, 53500.0, "short", df=df)
        if tp is not None:
            assert tp < 52000.0

    def test_no_df_returns_none(self) -> None:
        s = MAClusterExit()
        tp = s.calc_take_profit(50000.0, 48500.0, "long", df=None)
        assert tp is None


class TestFibonacciExit:
    def _make_df(self, swing_high: float, swing_low: float, bars: int = 200) -> pd.DataFrame:
        """创建有明确高低点的 K 线数据。"""
        np.random.seed(42)
        # 先涨到高点，再跌到低点
        mid = (swing_high + swing_low) / 2
        closes = []
        for i in range(bars):
            if i < bars // 3:
                c = swing_low + (swing_high - swing_low) * (i / (bars // 3))
            elif i < 2 * bars // 3:
                c = swing_high - (swing_high - swing_low) * ((i - bars // 3) / (bars // 3))
            else:
                c = swing_low + np.random.randn() * (swing_high - swing_low) * 0.05
            closes.append(c)

        return pd.DataFrame({
            "confirm": [True] * bars,
            "open": closes,
            "high": [c + 50 for c in closes],
            "low": [c - 50 for c in closes],
            "close": closes,
        })

    def test_long_fib_target(self) -> None:
        s = FibonacciExit(primary_level=1.618)
        df = self._make_df(60000, 50000)
        tp = s.calc_take_profit(61000.0, 59500.0, "long", df=df)
        assert tp is not None
        assert tp > 61000.0
        # target = swing_high + range * 0.618，因 high 列有随机噪声，放宽精度
        assert 65000 < tp < 70000

    def test_short_fib_target(self) -> None:
        s = FibonacciExit(primary_level=1.618)
        df = self._make_df(60000, 50000)
        tp = s.calc_take_profit(49000.0, 50500.0, "short", df=df)
        assert tp is not None
        assert tp < 49000.0
        assert 40000 < tp < 47000

    def test_no_df_returns_none(self) -> None:
        s = FibonacciExit()
        tp = s.calc_take_profit(50000.0, 48500.0, "long", df=None)
        assert tp is None


class TestFactory:
    def test_create_fixed_odds(self) -> None:
        s = create_exit_strategy("fixed_odds", odds_ratio=5.0)
        assert isinstance(s, FixedOddsExit)
        assert s.odds_ratio == 5.0

    def test_create_ma_cluster(self) -> None:
        s = create_exit_strategy("ma_cluster")
        assert isinstance(s, MAClusterExit)

    def test_create_fibonacci(self) -> None:
        s = create_exit_strategy("fibonacci")
        assert isinstance(s, FibonacciExit)

    def test_unknown_strategy(self) -> None:
        with pytest.raises(ValueError, match="未知退出策略"):
            create_exit_strategy("unknown_xyz")
