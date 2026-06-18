"""
Event-driven options backtest: buying SPY options into macro events.

Idea under test: buy an ATM option (or straddle) right before a scheduled
macro catalyst (FOMC, CPI) and exit after, betting the event moves the market.

The catch this models: scheduled events are *known*, so the option is already
priced to the expected move ("implied move"). You only profit if the realized
move beats what you paid -- and option sellers price in a volatility risk
premium, so on average implied > realized. This script measures SPY's actual
move on real 2026 event days and compares it to a modeled implied move.

IMPORTANT MODELING NOTE
-----------------------
Live option IV could not be pulled (broker token expired), so the implied move
is *modeled* from SPY's own realized volatility times an "event IV premium"
factor, NOT observed from the option chain. Re-auth the broker and you can swap
in real ATM straddle prices. Treat absolute P&L as illustrative; the structural
conclusion (you must beat the priced-in move) is robust.

Educational only -- NOT financial advice.

Run:  python3 backtest/event_study.py
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "results")
DATA = os.path.join(HERE, "data", "spy_30min.json")

# Round-trip cost for an option position: wider than the stock version because
# option spreads are far worse than SPY's. ~1% of premium round trip.
OPTION_COST_FRAC = 0.01

# Real scheduled macro events inside the data window (2026). CPI release dates
# are the standard ~mid-month BLS prints; FOMC are decision days (2pm ET).
EVENTS = {
    "2026-02-11": "CPI",
    "2026-03-11": "CPI",
    "2026-03-18": "FOMC",
    "2026-04-10": "CPI",
    "2026-04-29": "FOMC",
    "2026-05-13": "CPI",
    "2026-06-10": "CPI",
    "2026-06-17": "FOMC",
}

# Sensitivity sweep: how much more vol the market prices into an event option
# than SPY's plain realized daily vol. 1.0 = no premium (fair); >1 = the usual
# variance-risk-premium world. ATM weekly event IV on SPY is typically ~1.1-1.4x.
IV_PREMIUM_FACTORS = [1.0, 1.15, 1.30]

# ATM straddle premium ~= 0.8 * sigma * S for a 1-period horizon
# (since E|move| under a normal = sqrt(2/pi)*sigma ~= 0.798*sigma).
STRADDLE_COEF = 0.8
CALL_COEF = 0.4  # a single ATM option is ~half a straddle


def daily_bars() -> pd.DataFrame:
    raw = json.load(open(DATA))
    df = pd.DataFrame(raw["bars"])
    df = df[~df.get("interpolated", False).fillna(False).astype(bool)]
    for c in ["open_price", "high_price", "low_price", "close_price", "volume"]:
        df[c] = df[c].astype(float)
    df = df[df["volume"] > 0]
    dt = pd.to_datetime(df["begins_at"], utc=True).dt.tz_convert("America/New_York")
    df["date"] = dt.dt.date
    d = (df.groupby("date")
           .agg(o=("open_price", "first"), h=("high_price", "max"),
                l=("low_price", "min"), c=("close_price", "last"))
           .reset_index())
    d["date"] = d["date"].astype(str)
    d["prev_c"] = d["c"].shift(1)
    d["ret"] = d["c"].pct_change()
    return d


def pct(x) -> str:
    return f"{x * 100:+.2f}%"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    d = daily_bars()

    # Realized daily vol (close-to-close) over the whole sample.
    sigma_d = d["ret"].std(ddof=0)

    # Split event vs non-event days; |close-to-close| move is the "event move".
    d["is_event"] = d["date"].isin(EVENTS)
    d["abs_move"] = (d["c"] / d["prev_c"] - 1).abs()
    ev = d[d["is_event"]].copy()
    non = d[~d["is_event"] & d["prev_c"].notna()]

    print("=" * 74)
    print(f"SPY daily sample: {d['date'].iloc[0]} -> {d['date'].iloc[-1]} "
          f"({len(d)} sessions)")
    print(f"Realized daily vol (sigma) ........ {pct(sigma_d)}")
    print(f"Avg |move|, non-event days ........ {pct(non['abs_move'].mean())}")
    print(f"Avg |move|, event days ............ {pct(ev['abs_move'].mean())}  "
          f"({len(ev)} events)")
    print("=" * 74)

    # Per-event realized close-to-close move.
    ev["dir"] = np.sign(d.loc[ev.index, "c"] - d.loc[ev.index, "prev_c"])
    print("\nPer-event realized move (prior close -> event-day close):")
    for _, r in ev.iterrows():
        print(f"  {r['date']}  {EVENTS[r['date']]:<5}  {pct(r['c']/r['prev_c']-1):>8}")

    # ---- Long-straddle P&L model, swept over IV premium ----------------------
    # Premium paid (as % of spot) ~= STRADDLE_COEF * sigma_implied.
    # Payoff (% of spot) held through the event ~= |realized move| (intrinsic;
    # ignores residual time value -> generous to the buyer).
    rows = []
    print("\nLong ATM straddle into each event (hold through, sell after):")
    print(f"{'IV premium':>11} | {'implied move':>12} | {'avg payoff':>10} | "
          f"{'net/event':>10} | {'win rate':>8} | {'total (8 ev)':>12}")
    for f in IV_PREMIUM_FACTORS:
        sigma_imp = sigma_d * f
        premium = STRADDLE_COEF * sigma_imp                     # % of spot
        payoffs = ev["abs_move"].values                          # % of spot
        net = payoffs - premium - premium * OPTION_COST_FRAC     # cost on premium
        win = (net > 0).mean()
        rows.append({
            "iv_premium_factor": f,
            "implied_move_pct": round(STRADDLE_COEF * sigma_imp * 100, 3),
            "avg_payoff_pct": round(payoffs.mean() * 100, 3),
            "net_per_event_pct": round(net.mean() * 100, 3),
            "win_rate": round(float(win), 3),
            "total_8ev_pct": round(float(net.sum()) * 100, 3),
        })
        print(f"{f:>11.2f} | {pct(premium):>12} | {pct(payoffs.mean()):>10} | "
              f"{pct(net.mean()):>10} | {win*100:>7.1f}% | {pct(net.sum()):>12}")

    # ---- Directional long-call-only (always bet up) -------------------------
    # You also have to be right on direction. Payoff = max(0, up move) - call.
    print("\nDirectional ATM call (always long, must also be right on direction):")
    for f in IV_PREMIUM_FACTORS:
        sigma_imp = sigma_d * f
        call_prem = CALL_COEF * sigma_imp
        signed = (d.loc[ev.index, "c"] / d.loc[ev.index, "prev_c"] - 1).values
        payoff = np.maximum(0.0, signed)
        net = payoff - call_prem - call_prem * OPTION_COST_FRAC
        print(f"  IV x{f:.2f}: call premium {pct(call_prem)}, "
              f"net/event {pct(net.mean())}, total {pct(net.sum())}, "
              f"win {np.mean(net>0)*100:.1f}%")

    pd.DataFrame(rows).to_csv(os.path.join(OUT_DIR, "event_straddle_summary.csv"),
                             index=False)

    print("\n" + "=" * 74)
    print("Educational only -- not financial advice. Implied move is MODELED from")
    print("realized vol (live option IV unavailable); re-auth broker to use real")
    print("ATM straddle prices. Geopolitics is excluded -- it can't be scheduled,")
    print("which is exactly why you can't systematically pre-position for it.")

    _plot(ev, sigma_d)


def _plot(ev: pd.DataFrame, sigma_d: float):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        print(f"(skipping chart: {e})"); return
    labels = [f"{r['date'][5:]}\n{EVENTS[r['date']]}" for _, r in ev.iterrows()]
    moves = (ev["abs_move"] * 100).values
    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.bar(labels, moves, color="#1f77b4", label="realized |move|")
    for f, color, ls in [(1.0, "#2ca02c", "--"), (1.15, "#ff7f0e", "--"),
                         (1.30, "#d62728", "--")]:
        be = STRADDLE_COEF * sigma_d * f * 100
        ax.axhline(be, color=color, ls=ls,
                   label=f"straddle breakeven, IV x{f:.2f} ({be:.2f}%)")
    ax.set_ylabel("move / breakeven (% of spot)")
    ax.set_title("SPY realized move on macro-event days vs. priced-in straddle breakeven")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = os.path.join(OUT_DIR, "event_options.png")
    fig.savefig(out, dpi=120)
    print(f"Saved chart -> {out}")


if __name__ == "__main__":
    main()
