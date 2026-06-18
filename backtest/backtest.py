"""
SPY intraday backtest: Opening Range Breakout (ORB) vs. VWAP Reversion.

Data: 30-minute SPY bars (regular trading hours), pulled from the broker
market-data feed and stored in backtest/data/spy_30min.json.

Both strategies are intraday only (flat overnight). Results are educational
and illustrative -- NOT financial advice. A 30-minute bar is coarse; finer
data and a larger sample would tighten these numbers.

Run:  python3 backtest/backtest.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "data", "spy_30min.json")
OUT_DIR = os.path.join(HERE, "results")

# --- Cost model ------------------------------------------------------------
# Round-trip cost (entry + exit) as a fraction of notional. SPY is extremely
# liquid (penny-wide spreads), but we charge slippage so results aren't
# fantasy fills. 0.0004 = 4 bps round trip (~2 bps per side).
ROUND_TRIP_COST = 0.0004


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(path: str = DATA_PATH) -> pd.DataFrame:
    raw = json.load(open(path))
    bars = raw["bars"]
    df = pd.DataFrame(bars)
    # Drop interpolated gap-fill bars (no real trading; volume 0).
    if "interpolated" in df.columns:
        interp = df["interpolated"].fillna(False).astype(bool)
        df = df[~interp]
    df = df[df["volume"].astype(float) > 0].copy()

    for col in ["open_price", "high_price", "low_price", "close_price", "volume"]:
        df[col] = df[col].astype(float)

    # begins_at is UTC; convert to US/Eastern so a "trading day" is correct
    # across the EST/EDT changeover and we can find each session's open.
    dt = pd.to_datetime(df["begins_at"], utc=True).dt.tz_convert("America/New_York")
    df["dt"] = dt
    df["date"] = dt.dt.date
    df = df.rename(
        columns={
            "open_price": "o",
            "high_price": "h",
            "low_price": "l",
            "close_price": "c",
            "volume": "v",
        }
    )
    df = df.sort_values("dt").reset_index(drop=True)
    return df[["dt", "date", "o", "h", "l", "c", "v"]]


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    date: object
    direction: str          # "long" or "short"
    entry: float
    exit: float
    reason: str             # how the trade closed
    ret: float = field(init=False)   # net return after costs (decimal)

    def __post_init__(self):
        gross = (self.exit - self.entry) / self.entry
        if self.direction == "short":
            gross = -gross
        self.ret = gross - ROUND_TRIP_COST


# ---------------------------------------------------------------------------
# Strategy 1: Opening Range Breakout
# ---------------------------------------------------------------------------
def opening_range_breakout(df: pd.DataFrame) -> list[Trade]:
    """First 30-min bar sets the range. Take the first break of that range
    (long above the high, short below the low). Stop = opposite side of the
    range. If not stopped, exit at the day's last close. One trade/day max."""
    trades: list[Trade] = []
    for _, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        if len(day) < 3:
            continue  # need an opening range + room to trade
        or_bar = day.iloc[0]
        or_high, or_low = or_bar["h"], or_bar["l"]
        rest = day.iloc[1:]
        eod_close = day.iloc[-1]["c"]

        entered = None  # (direction, entry_price)
        for _, bar in rest.iterrows():
            if bar["h"] >= or_high:                 # upside break first
                entered = ("long", or_high)
                break
            if bar["l"] <= or_low:                  # downside break first
                entered = ("short", or_low)
                break
        if entered is None:
            continue  # inside-range day, no signal

        direction, entry = entered
        stop = or_low if direction == "long" else or_high
        # Walk forward from the entry bar looking for a stop hit.
        exit_price, reason = eod_close, "eod_close"
        post = rest.reset_index(drop=True)
        # find index of the entry bar within `post`
        if direction == "long":
            start_idx = post.index[post["h"] >= or_high][0]
        else:
            start_idx = post.index[post["l"] <= or_low][0]
        for j in range(start_idx, len(post)):
            bar = post.iloc[j]
            if direction == "long" and bar["l"] <= stop:
                exit_price, reason = stop, "stop"
                break
            if direction == "short" and bar["h"] >= stop:
                exit_price, reason = stop, "stop"
                break

        trades.append(Trade(day.iloc[0]["date"], direction, entry, exit_price, reason))
    return trades


# ---------------------------------------------------------------------------
# Strategy 2: VWAP Reversion
# ---------------------------------------------------------------------------
def vwap_reversion(df: pd.DataFrame, k_entry: float = 1.5, k_stop: float = 3.0) -> list[Trade]:
    """Intraday cumulative VWAP with an expanding standard-deviation band.
    Fade extensions: go long when price is k_entry sigma BELOW VWAP, short
    when k_entry sigma ABOVE. Exit on reversion to VWAP, a k_stop sigma stop,
    or the close. Re-entry allowed after a flat. Flat overnight."""
    trades: list[Trade] = []
    for _, day in df.groupby("date"):
        day = day.reset_index(drop=True)
        if len(day) < 5:
            continue
        tp = (day["h"] + day["l"] + day["c"]) / 3.0          # typical price
        cum_v = day["v"].cumsum()
        vwap = (tp * day["v"]).cumsum() / cum_v
        dev = tp - vwap
        # expanding std of deviation from VWAP (population), min 3 bars
        sigma = dev.expanding(min_periods=3).std(ddof=0)

        pos = None  # (direction, entry_price)
        warmup = 3  # let VWAP/sigma stabilise before trading
        for i in range(len(day)):
            price = day["c"].iloc[i]
            w, s = vwap.iloc[i], sigma.iloc[i]
            last_bar = i == len(day) - 1
            if np.isnan(s) or s == 0:
                continue

            if pos is None:
                if last_bar or i < warmup:
                    continue
                if price <= w - k_entry * s:
                    pos = ("long", price)
                elif price >= w + k_entry * s:
                    pos = ("short", price)
            else:
                direction, entry = pos
                exit_now, reason = False, ""
                if last_bar:
                    exit_now, reason = True, "eod_close"
                elif direction == "long":
                    if price >= w:
                        exit_now, reason = True, "revert_vwap"
                    elif price <= w - k_stop * s:
                        exit_now, reason = True, "stop"
                else:  # short
                    if price <= w:
                        exit_now, reason = True, "revert_vwap"
                    elif price >= w + k_stop * s:
                        exit_now, reason = True, "stop"
                if exit_now:
                    trades.append(Trade(day["date"].iloc[i], direction, entry, price, reason))
                    pos = None
    return trades


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def summarize(trades: list[Trade], label: str) -> dict:
    if not trades:
        return {"strategy": label, "trades": 0}
    rets = np.array([t.ret for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    equity = np.cumprod(1 + rets)
    peak = np.maximum.accumulate(equity)
    max_dd = float(((equity - peak) / peak).min())
    gross_win = wins.sum()
    gross_loss = -losses.sum()
    return {
        "strategy": label,
        "trades": len(trades),
        "win_rate": float(len(wins) / len(rets)),
        "avg_trade": float(rets.mean()),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "expectancy": float(rets.mean()),
        "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
        "total_return": float(equity[-1] - 1),  # compounded, full-equity per trade
        "max_drawdown": max_dd,
        "best": float(rets.max()),
        "worst": float(rets.min()),
        "equity": equity,
    }


def buy_hold(df: pd.DataFrame) -> float:
    first_open = df.iloc[0]["o"]
    last_close = df.iloc[-1]["c"]
    return last_close / first_open - 1


def pct(x) -> str:
    return f"{x * 100:+.2f}%"


def print_report(stats: dict):
    if stats["trades"] == 0:
        print(f"  {stats['strategy']}: no trades")
        return
    print(f"  {stats['strategy']}")
    print(f"    Trades .............. {stats['trades']}")
    print(f"    Win rate ............ {stats['win_rate'] * 100:.1f}%")
    print(f"    Avg trade ........... {pct(stats['avg_trade'])}")
    print(f"    Avg win / loss ...... {pct(stats['avg_win'])} / {pct(stats['avg_loss'])}")
    print(f"    Profit factor ....... {stats['profit_factor']:.2f}")
    print(f"    Total return (comp) . {pct(stats['total_return'])}")
    print(f"    Max drawdown ........ {pct(stats['max_drawdown'])}")
    print(f"    Best / worst trade .. {pct(stats['best'])} / {pct(stats['worst'])}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    df = load_data()
    days = df["date"].nunique()
    print("=" * 60)
    print("SPY intraday backtest  |  30-min bars  |  flat overnight")
    print(f"Period: {df['dt'].min():%Y-%m-%d} -> {df['dt'].max():%Y-%m-%d}"
          f"  ({days} sessions, {len(df)} bars)")
    print(f"Cost assumption: {ROUND_TRIP_COST * 100:.2f}% round trip")
    print("=" * 60)

    orb = opening_range_breakout(df)
    vwap = vwap_reversion(df)
    s_orb = summarize(orb, "Opening Range Breakout")
    s_vwap = summarize(vwap, "VWAP Reversion")

    print("\nBenchmark")
    print(f"    Buy & hold .......... {pct(buy_hold(df))}")
    print()
    print_report(s_orb)
    print()
    print_report(s_vwap)
    print("\n" + "=" * 60)
    print("Educational only -- not financial advice. Coarse 30-min bars and a")
    print("~6-month sample; treat as a sketch, not a green light to trade.")

    # write per-trade CSVs
    for trades, name in [(orb, "orb"), (vwap, "vwap")]:
        rows = [
            {
                "date": t.date,
                "direction": t.direction,
                "entry": round(t.entry, 2),
                "exit": round(t.exit, 2),
                "reason": t.reason,
                "ret_pct": round(t.ret * 100, 3),
            }
            for t in trades
        ]
        pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, f"trades_{name}.csv"), index=False)

    # summary CSV
    summ = pd.DataFrame(
        [{k: v for k, v in s.items() if k != "equity"} for s in (s_orb, s_vwap)]
    )
    summ.to_csv(os.path.join(OUT_DIR, "summary.csv"), index=False)

    _plot(s_orb, s_vwap)


def _plot(s_orb: dict, s_vwap: dict):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        print(f"(skipping chart: {e})")
        return
    fig, ax = plt.subplots(figsize=(9, 5))
    for s, color in [(s_orb, "#1f77b4"), (s_vwap, "#d62728")]:
        if s["trades"] == 0:
            continue
        eq = np.concatenate([[1.0], s["equity"]])
        ax.plot(eq, label=f"{s['strategy']} ({pct(s['total_return'])})", color=color)
    ax.axhline(1.0, color="gray", lw=0.8, ls="--")
    ax.set_title("SPY intraday strategies — compounded equity (start = 1.0)")
    ax.set_xlabel("Trade #")
    ax.set_ylabel("Equity multiple")
    ax.legend()
    fig.tight_layout()
    out = os.path.join(OUT_DIR, "equity_curve.png")
    fig.savefig(out, dpi=120)
    print(f"\nSaved chart -> {out}")


if __name__ == "__main__":
    main()
