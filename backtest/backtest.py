"""
SPY intraday backtest harness.

Strategies:
  1. Opening Range Breakout (ORB)  -- range breakout
  2. VWAP Reversion                -- mean reversion
  3. EMA Trend (momentum)          -- always-in fast/slow EMA crossover

Runs on whatever bar files are configured in DATASETS below. ORB and VWAP run
on every dataset so you can see how granularity changes the result; the EMA
trend-follower needs many bars per session, so it only runs on intraday files
fine enough to support it (e.g. 5-min).

All strategies are intraday only (flat overnight) with a round-trip slippage
cost. Educational only -- NOT financial advice.

Run:  python3 backtest/backtest.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")

DATASETS = [
    ("30-min", os.path.join(HERE, "data", "spy_30min.json")),
    ("5-min", os.path.join(HERE, "data", "spy_5min.json")),
]

# Round-trip cost (entry+exit) as a fraction of notional. ~4 bps is a
# realistic retail slippage budget for a penny-wide name like SPY.
ROUND_TRIP_COST = 0.0004

_INTERVAL_MIN = {"minute": 1, "5minute": 5, "10minute": 10, "30minute": 30, "hour": 60}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_data(path: str) -> tuple[pd.DataFrame, int]:
    raw = json.load(open(path))
    bar_min = _INTERVAL_MIN.get(raw.get("interval", ""), None)
    df = pd.DataFrame(raw["bars"])
    if "interpolated" in df.columns:
        df = df[~df["interpolated"].fillna(False).astype(bool)]
    for col in ["open_price", "high_price", "low_price", "close_price", "volume"]:
        df[col] = df[col].astype(float)
    df = df[df["volume"] > 0].copy()
    dt = pd.to_datetime(df["begins_at"], utc=True).dt.tz_convert("America/New_York")
    df["dt"] = dt
    df["date"] = dt.dt.date
    df = df.rename(columns={"open_price": "o", "high_price": "h",
                            "low_price": "l", "close_price": "c", "volume": "v"})
    df = df.sort_values("dt").reset_index(drop=True)
    return df[["dt", "date", "o", "h", "l", "c", "v"]], bar_min


# ---------------------------------------------------------------------------
@dataclass
class Trade:
    date: object
    direction: str
    entry: float
    exit: float
    reason: str
    ret: float = field(init=False)

    def __post_init__(self):
        g = (self.exit - self.entry) / self.entry
        if self.direction == "short":
            g = -g
        self.ret = g - ROUND_TRIP_COST


# ---------------------------------------------------------------------------
# 1. Opening Range Breakout
# ---------------------------------------------------------------------------
def opening_range_breakout(df: pd.DataFrame, or_minutes: int = 30) -> list[Trade]:
    """First `or_minutes` of the session sets the range. Trade the first break
    of it; stop = opposite side; exit at the session close. One trade/day."""
    trades: list[Trade] = []
    for _, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        open_t = day["dt"].iloc[0]
        in_or = (day["dt"] - open_t) < pd.Timedelta(minutes=or_minutes)
        or_bars, rest = day[in_or], day[~in_or].reset_index(drop=True)
        if len(or_bars) == 0 or len(rest) < 2:
            continue
        or_high, or_low = or_bars["h"].max(), or_bars["l"].min()
        eod_close = day["c"].iloc[-1]

        entry_idx, entered = None, None
        for i in range(len(rest)):
            if rest["h"].iloc[i] >= or_high:
                entered, entry_idx = ("long", or_high), i
                break
            if rest["l"].iloc[i] <= or_low:
                entered, entry_idx = ("short", or_low), i
                break
        if entered is None:
            continue
        direction, entry = entered
        stop = or_low if direction == "long" else or_high
        exit_price, reason = eod_close, "eod_close"
        for j in range(entry_idx, len(rest)):
            bar = rest.iloc[j]
            if direction == "long" and bar["l"] <= stop:
                exit_price, reason = stop, "stop"; break
            if direction == "short" and bar["h"] >= stop:
                exit_price, reason = stop, "stop"; break
        trades.append(Trade(day["date"].iloc[0], direction, entry, exit_price, reason))
    return trades


# ---------------------------------------------------------------------------
# 2. VWAP Reversion
# ---------------------------------------------------------------------------
def vwap_reversion(df: pd.DataFrame, k_entry: float = 1.5, k_stop: float = 3.0,
                   warmup: int = 6) -> list[Trade]:
    trades: list[Trade] = []
    for _, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        if len(day) < warmup + 2:
            continue
        tp = (day["h"] + day["l"] + day["c"]) / 3.0
        vwap = (tp * day["v"]).cumsum() / day["v"].cumsum()
        dev = tp - vwap
        sigma = dev.expanding(min_periods=3).std(ddof=0)
        pos = None
        for i in range(len(day)):
            price, w, s = day["c"].iloc[i], vwap.iloc[i], sigma.iloc[i]
            last = i == len(day) - 1
            if np.isnan(s) or s == 0:
                continue
            if pos is None:
                if last or i < warmup:
                    continue
                if price <= w - k_entry * s:
                    pos = ("long", price)
                elif price >= w + k_entry * s:
                    pos = ("short", price)
            else:
                d, entry = pos
                hit, reason = False, ""
                if last:
                    hit, reason = True, "eod_close"
                elif d == "long":
                    if price >= w: hit, reason = True, "revert_vwap"
                    elif price <= w - k_stop * s: hit, reason = True, "stop"
                else:
                    if price <= w: hit, reason = True, "revert_vwap"
                    elif price >= w + k_stop * s: hit, reason = True, "stop"
                if hit:
                    trades.append(Trade(day["date"].iloc[i], d, entry, price, reason))
                    pos = None
    return trades


# ---------------------------------------------------------------------------
# 3. EMA Trend (momentum) -- always-in fast/slow crossover, flat overnight
# ---------------------------------------------------------------------------
def ema_trend(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> list[Trade]:
    trades: list[Trade] = []
    for _, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        if len(day) < slow + 2:
            continue
        ef = day["c"].ewm(span=fast, adjust=False).mean()
        es = day["c"].ewm(span=slow, adjust=False).mean()
        pos = None  # (direction, entry_price)
        for i in range(len(day)):
            price = day["c"].iloc[i]
            last = i == len(day) - 1
            if i < slow:           # warmup: let EMAs separate
                continue
            desired = "long" if ef.iloc[i] > es.iloc[i] else "short"
            if last:
                if pos is not None:
                    trades.append(Trade(day["date"].iloc[i], pos[0], pos[1], price, "eod_close"))
                    pos = None
                continue
            if pos is None:
                pos = (desired, price)
            elif desired != pos[0]:                  # cross -> flip
                trades.append(Trade(day["date"].iloc[i], pos[0], pos[1], price, "cross"))
                pos = (desired, price)
    return trades


# ---------------------------------------------------------------------------
# Metrics / reporting
# ---------------------------------------------------------------------------
def summarize(trades: list[Trade], label: str) -> dict:
    if not trades:
        return {"strategy": label, "trades": 0}
    rets = np.array([t.ret for t in trades])
    wins, losses = rets[rets > 0], rets[rets <= 0]
    equity = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(equity)
    gw, gl = wins.sum(), -losses.sum()
    return {
        "strategy": label,
        "trades": len(trades),
        "win_rate": len(wins) / len(rets),
        "avg_trade": rets.mean(),
        "avg_win": wins.mean() if len(wins) else 0.0,
        "avg_loss": losses.mean() if len(losses) else 0.0,
        "profit_factor": (gw / gl) if gl > 0 else float("inf"),
        "total_return": equity[-1] - 1,
        "max_drawdown": float(((equity - peak) / peak).min()),
        "best": rets.max(),
        "worst": rets.min(),
        "equity": equity,
    }


def buy_hold(df: pd.DataFrame) -> float:
    return df["c"].iloc[-1] / df["o"].iloc[0] - 1


def pct(x) -> str:
    return f"{x * 100:+.2f}%"


def print_report(s: dict):
    if s["trades"] == 0:
        print(f"    {s['strategy']:<24} (not run / no trades)")
        return
    print(f"    {s['strategy']:<24} "
          f"n={s['trades']:>4}  win={s['win_rate']*100:4.1f}%  "
          f"PF={s['profit_factor']:.2f}  "
          f"ret={pct(s['total_return']):>8}  "
          f"maxDD={pct(s['max_drawdown']):>8}")


# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    all_rows, chart_stats = [], None
    for tag, path in DATASETS:
        if not os.path.exists(path):
            continue
        df, bar_min = load_data(path)
        days = df["date"].nunique()
        print("=" * 78)
        print(f"[{tag}] {df['dt'].min():%Y-%m-%d} -> {df['dt'].max():%Y-%m-%d}  "
              f"({days} sessions, {len(df)} bars)   cost={ROUND_TRIP_COST*100:.2f}% RT")
        print(f"    Buy & hold: {pct(buy_hold(df))}")

        runs = [
            ("Opening Range Breakout", opening_range_breakout(df)),
            ("VWAP Reversion", vwap_reversion(df, warmup=6 if bar_min and bar_min <= 10 else 3)),
        ]
        # EMA trend needs enough bars per session (>= slow+2); skip coarse data.
        if bar_min and bar_min <= 10:
            runs.append(("EMA Trend (9/21)", ema_trend(df)))

        stats = []
        for label, trades in runs:
            s = summarize(trades, label)
            stats.append(s)
            print_report(s)
            row = {k: v for k, v in s.items() if k != "equity"}
            row["dataset"] = tag
            all_rows.append(row)
            # dump trades
            pd.DataFrame([{
                "date": t.date, "direction": t.direction,
                "entry": round(t.entry, 2), "exit": round(t.exit, 2),
                "reason": t.reason, "ret_pct": round(t.ret * 100, 3),
            } for t in trades]).to_csv(
                os.path.join(OUT_DIR, f"trades_{tag}_{label.split()[0].lower()}.csv"),
                index=False)
        if tag == "5-min":
            chart_stats = (df, stats)

    pd.DataFrame(all_rows).to_csv(os.path.join(OUT_DIR, "summary.csv"), index=False)
    print("=" * 78)
    print("Educational only -- not financial advice.")
    if chart_stats:
        _plot(*chart_stats)


def _plot(df: pd.DataFrame, stats: list[dict]):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(skipping chart: {e})"); return
    colors = {"Opening Range Breakout": "#1f77b4", "VWAP Reversion": "#d62728",
              "EMA Trend (9/21)": "#2ca02c"}
    fig, ax = plt.subplots(figsize=(9, 5))
    for s in stats:
        if s["trades"] == 0:
            continue
        eq = np.concatenate([[1.0], s["equity"]])
        ax.plot(eq, label=f"{s['strategy']} ({pct(s['total_return'])})",
                color=colors.get(s["strategy"], "gray"))
    ax.axhline(1.0, color="gray", lw=0.8, ls="--")
    ax.set_title("SPY intraday strategies on 5-min bars — compounded equity (start = 1.0)")
    ax.set_xlabel("Trade #"); ax.set_ylabel("Equity multiple")
    ax.legend(); fig.tight_layout()
    out = os.path.join(OUT_DIR, "equity_curve_5min.png")
    fig.savefig(out, dpi=120)
    print(f"Saved chart -> {out}")


if __name__ == "__main__":
    main()
