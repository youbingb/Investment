"""Streamlit 可视化：历史回测仪表盘。

启动：
    streamlit run scripts/dashboard.py

依赖（在 pyproject [project.optional-dependencies].viz）：
    streamlit >= 1.30
    plotly >= 5.18

侧边栏：
- symbol / timeframe（从 data/cache 自动列出）
- 规则多选（默认全选 REGISTRY）
- 时间窗（UTC）
- horizons / exit_after

主区域 4 块：
1. 资金曲线 + 最大回撤区域
2. 按规则统计表（含 payoff_ratio / profit_factor）
3. K 线 + 信号散点（long ▲ short ▼）
4. 每笔 exit_return 直方图
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from investment.data.kline_store import KlineStore  # noqa: E402
from investment.indicators import compute_all  # noqa: E402
from investment.runner.backtest import (  # noqa: E402
    DEFAULT_EXIT_HORIZON,
    DEFAULT_HORIZONS,
    BacktestResult,
    backtest_with_returns,
)
from investment.signals.loader import REGISTRY  # noqa: E402


st.set_page_config(page_title="Investment 回测仪表盘", layout="wide")


# ---------- 数据装载 ----------

@st.cache_data(show_spinner=False)
def _list_cached() -> list[tuple[str, str]]:
    store = KlineStore()
    pairs: list[tuple[str, str]] = []
    for p in sorted(store.cache_dir.glob("*.parquet")):
        stem = p.stem
        if "_" not in stem:
            continue
        symbol, tf = stem.rsplit("_", 1)
        pairs.append((symbol, tf))
    return pairs


@st.cache_data(show_spinner=False)
def _load_df(symbol: str, tf: str) -> pd.DataFrame:
    df = KlineStore().load(symbol, tf)
    if df.empty:
        return df
    return compute_all(df)


def _run_backtest(
    df: pd.DataFrame,
    symbol: str,
    tf: str,
    rule_names: list[str],
    horizons: tuple[int, ...],
    exit_after: int,
) -> BacktestResult:
    rules = [REGISTRY[n]() for n in rule_names if n in REGISTRY]
    horizons = tuple(sorted(set(horizons) | {exit_after}))
    return backtest_with_returns(
        df, rules,
        symbol=symbol, timeframe=tf,
        horizons=horizons, exit_horizon=exit_after,
    )


# ---------- 图表 ----------

def _equity_drawdown_fig(result: BacktestResult) -> go.Figure | None:
    curve = result.equity_curve()
    if not curve:
        return None
    ts = [c[0] for c in curve]
    nav = [c[1] for c in curve]
    # 峰值序列
    peaks: list[float] = []
    p = nav[0]
    for v in nav:
        p = max(p, v)
        peaks.append(p)
    dd = [(n - pk) / pk if pk > 0 else 0.0 for n, pk in zip(nav, peaks)]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=ts, y=nav, mode="lines", name="NAV",
                              line=dict(color="#2b8a3e", width=2)))
    fig.add_trace(go.Scatter(x=ts, y=peaks, mode="lines", name="峰值",
                              line=dict(color="#94d2bd", dash="dot")))
    # 回撤画在副 y 轴
    fig.add_trace(go.Scatter(
        x=ts, y=[d * 100 for d in dd], mode="lines", name="回撤 %",
        line=dict(color="#c92a2a"), fill="tozeroy", yaxis="y2",
    ))
    fig.update_layout(
        height=420,
        xaxis_title="时间",
        yaxis=dict(title="NAV", side="left"),
        yaxis2=dict(title="回撤 %", overlaying="y", side="right", range=[-50, 0]),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def _stats_table(result: BacktestResult) -> pd.DataFrame:
    """生成展示用表格：百分比字段已乘 100，方便 Streamlit format 直接打印。"""
    stats = result.stats_by_rule()
    rows = []
    for name, s in stats.items():
        rows.append({
            "规则": name,
            "命中": int(s["count"]),
            "完整窗口": int(s["trades"]),
            "胜率 %": s["win_rate"] * 100 if not math.isnan(s["win_rate"]) else float("nan"),
            "平均收益 %": s["avg_return"] * 100 if not math.isnan(s["avg_return"]) else float("nan"),
            "平均盈 %": s["avg_win"] * 100 if not math.isnan(s["avg_win"]) else float("nan"),
            "平均亏 %": s["avg_loss"] * 100 if not math.isnan(s["avg_loss"]) else float("nan"),
            "赔率": s["payoff_ratio"],
            "盈亏比": s["profit_factor"],
            "平均 MFE %": s["avg_mfe"] * 100 if not math.isnan(s["avg_mfe"]) else float("nan"),
            "平均 MAE %": s["avg_mae"] * 100 if not math.isnan(s["avg_mae"]) else float("nan"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("命中", ascending=False).reset_index(drop=True)


def _candles_with_signals(df: pd.DataFrame, result: BacktestResult) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["ts"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="K 线",
        increasing_line_color="#2b8a3e", decreasing_line_color="#c92a2a",
    ))
    long_ts, long_px = [], []
    short_ts, short_px = [], []
    for o in result.outcomes:
        if o.signal.direction == "long":
            long_ts.append(o.signal.bar_ts)
            long_px.append(float(o.signal.price))
        elif o.signal.direction == "short":
            short_ts.append(o.signal.bar_ts)
            short_px.append(float(o.signal.price))
    if long_ts:
        fig.add_trace(go.Scatter(
            x=long_ts, y=long_px, mode="markers", name="long",
            marker=dict(symbol="triangle-up", size=11, color="#1c7ed6",
                        line=dict(width=1, color="white")),
        ))
    if short_ts:
        fig.add_trace(go.Scatter(
            x=short_ts, y=short_px, mode="markers", name="short",
            marker=dict(symbol="triangle-down", size=11, color="#f76707",
                        line=dict(width=1, color="white")),
        ))
    fig.update_layout(
        height=520,
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


def _returns_histogram(result: BacktestResult) -> go.Figure | None:
    rets = [o.exit_return for o in result.outcomes if o.exit_return is not None]
    if not rets:
        return None
    pct = [r * 100 for r in rets]
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=pct, nbinsx=40, name="exit_return",
        marker=dict(color="#5c7cfa"),
    ))
    fig.add_vline(x=0, line=dict(color="#868e96", dash="dash"))
    avg = sum(pct) / len(pct)
    fig.add_vline(x=avg, line=dict(color="#c92a2a"),
                  annotation_text=f"均值 {avg:+.2f}%", annotation_position="top")
    fig.update_layout(
        height=360,
        xaxis_title="每笔 exit_return (%)",
        yaxis_title="笔数",
        margin=dict(l=10, r=10, t=30, b=10),
    )
    return fig


# ---------- 主流程 ----------

def main() -> None:
    st.title("Investment · 回测仪表盘")

    pairs = _list_cached()
    if not pairs:
        st.error("data/cache 下没有任何 parquet。先跑 `python scripts/fetch_history.py BTC-USDT 1H 1000`")
        return

    with st.sidebar:
        st.header("回测参数")
        symbols = sorted({s for s, _ in pairs})
        symbol = st.selectbox("Symbol", symbols, index=0)
        tfs = sorted({tf for s, tf in pairs if s == symbol})
        tf = st.selectbox("Timeframe", tfs, index=0)

        df = _load_df(symbol, tf)
        if df.empty:
            st.error("缓存文件存在但为空")
            return

        ts_min = df["ts"].iloc[0].to_pydatetime()
        ts_max = df["ts"].iloc[-1].to_pydatetime()
        date_range = st.date_input(
            "时间窗（UTC）",
            value=(ts_min.date(), ts_max.date()),
            min_value=ts_min.date(),
            max_value=ts_max.date(),
        )

        all_rules = sorted(REGISTRY.keys())
        selected_rules = st.multiselect(
            "启用规则", all_rules, default=all_rules,
        )

        horizons_text = st.text_input(
            "horizons（逗号分隔）", value=",".join(str(h) for h in DEFAULT_HORIZONS),
        )
        try:
            horizons = tuple(int(x.strip()) for x in horizons_text.split(",") if x.strip())
        except ValueError:
            st.error("horizons 必须是逗号分隔的正整数")
            return

        exit_after = st.number_input(
            "exit_after（持仓 K 数）", min_value=1, max_value=200,
            value=DEFAULT_EXIT_HORIZON, step=1,
        )

        run = st.button("跑回测", type="primary", use_container_width=True)

    # 时间窗裁剪
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start = pd.Timestamp(date_range[0], tz="UTC")
        end = pd.Timestamp(date_range[1], tz="UTC") + pd.Timedelta(days=1)
        df_win = df[(df["ts"] >= start) & (df["ts"] < end)].reset_index(drop=True)
    else:
        df_win = df

    st.caption(
        f"{symbol} · {tf} · 缓存 {len(df)} 根 / 窗内 {len(df_win)} 根 "
        f"({df_win['ts'].iloc[0]} → {df_win['ts'].iloc[-1]})"
        if not df_win.empty else f"{symbol} · {tf} · 窗内 0 根"
    )

    if not run:
        st.info("左侧调好参数后点 “跑回测”")
        return

    if df_win.empty:
        st.error("时间窗内没数据")
        return
    if not selected_rules:
        st.error("至少选一条规则")
        return

    with st.spinner("回测中..."):
        result = _run_backtest(
            df_win, symbol, tf, selected_rules,
            horizons=horizons, exit_after=int(exit_after),
        )

    # ---- 头部指标 ----
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("命中", len(result.signals))
    c2.metric("交易笔数", len([o for o in result.outcomes if o.exit_return is not None]))
    c3.metric("累计收益", f"{result.total_return*100:+.2f}%")
    c4.metric("最大回撤", f"{result.max_drawdown*100:+.2f}%")
    # 整体 win_rate
    trades = [o for o in result.outcomes if o.exit_return is not None]
    wins = sum(1 for o in trades if o.is_win)
    wr = (wins / len(trades) * 100) if trades else float("nan")
    c5.metric("整体胜率", "-" if math.isnan(wr) else f"{wr:.1f}%")

    st.divider()

    # ---- 资金曲线 ----
    st.subheader("资金曲线 + 回撤")
    fig = _equity_drawdown_fig(result)
    if fig is None:
        st.info("无完整窗口的信号，资金曲线为空")
    else:
        st.plotly_chart(fig, use_container_width=True)

    # ---- 规则统计表 ----
    st.subheader("按规则统计")
    stats_df = _stats_table(result)
    if stats_df.empty:
        st.info("无统计数据")
    else:
        st.dataframe(
            stats_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "胜率 %": st.column_config.NumberColumn(format="%.1f"),
                "平均收益 %": st.column_config.NumberColumn(format="%+.2f"),
                "平均盈 %": st.column_config.NumberColumn(format="%+.2f"),
                "平均亏 %": st.column_config.NumberColumn(format="%+.2f"),
                "赔率": st.column_config.NumberColumn(format="%.2f"),
                "盈亏比": st.column_config.NumberColumn(format="%.2f"),
                "平均 MFE %": st.column_config.NumberColumn(format="%+.2f"),
                "平均 MAE %": st.column_config.NumberColumn(format="%+.2f"),
            },
        )

    # ---- K 线 + 信号 ----
    st.subheader("K 线 + 信号散点")
    candle_fig = _candles_with_signals(df_win, result)
    st.plotly_chart(candle_fig, use_container_width=True)

    # ---- 收益分布 ----
    st.subheader("每笔 exit_return 分布")
    hist = _returns_histogram(result)
    if hist is None:
        st.info("无完整窗口的信号")
    else:
        st.plotly_chart(hist, use_container_width=True)


if __name__ == "__main__":
    main()
