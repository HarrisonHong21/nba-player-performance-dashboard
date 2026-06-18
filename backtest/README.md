# SPY Intraday Backtest — ORB vs. VWAP Reversion vs. EMA Trend

An honest backtest comparing three commonly-cited day-trading methods on SPY,
across two bar granularities. **Educational only — not financial advice.**

## What it tests

| Strategy | Type | Logic |
|----------|------|-------|
| **Opening Range Breakout (ORB)** | Breakout | First 30 min sets the range. Take the first break — long above the high, short below the low. Stop = opposite side. Exit at the close. One trade/day. |
| **VWAP Reversion** | Mean reversion | Intraday cumulative VWAP with an expanding ±σ band. Fade extensions: long 1.5σ below VWAP, short 1.5σ above. Exit on reversion to VWAP, a 3σ stop, or the close. |
| **EMA Trend (9/21)** | Momentum / trend | Always-in fast/slow EMA crossover, computed per session. Long when fast EMA > slow, short when below, flip on the cross. Flat at the close. |

All strategies are **intraday only — flat overnight**, with a **4 bps
round-trip slippage cost** on every trade. Each trade is sized at full equity,
so "total return" is compounded.

## Data

- `data/spy_30min.json` — 30-min bars, real volume from 2026-01-30 → 06-17 (**96 sessions**).
- `data/spy_5min.json` — 5-min bars, real volume from 2026-02-23 → 06-17 (**81 sessions**).
- Both pulled from the broker market-data feed. Gap-fill bars (volume 0) are
  dropped automatically. The EMA trend strategy needs many bars per session, so
  it only runs on the 5-min file.

## Results

### 30-minute bars (Jan 30 – Jun 17, 96 sessions) — buy & hold **+7.15%**

| Strategy | Trades | Win % | Profit factor | Total return | Max DD |
|---|---|---|---|---|---|
| Opening Range Breakout | 96 | 49.0% | 1.08 | **+1.33%** | −4.35% |
| VWAP Reversion | 182 | 39.6% | 0.59 | **−10.53%** | −11.21% |

### 5-minute bars (Feb 23 – Jun 17, 81 sessions) — buy & hold **+7.77%**

| Strategy | Trades | Win % | Profit factor | Total return | Max DD |
|---|---|---|---|---|---|
| Opening Range Breakout | 81 | 45.7% | 0.87 | **−2.33%** | −5.24% |
| VWAP Reversion | 525 | 31.0% | 0.49 | **−23.00%** | −23.48% |
| EMA Trend (9/21) | 268 | 31.3% | 0.71 | **−9.18%** | −10.95% |

![equity curve, 5-min](results/equity_curve_5min.png)

## Takeaways

- **Finer bars killed the ORB "edge."** On 30-min bars ORB looked marginally
  positive (+1.33%); on realistic 5-min bars it went **negative (−2.33%)**. The
  coarse-bar profit was partly an artifact of optimistic fills and not modeling
  intrabar stop/target sequencing. This is the classic way a backtest lies to
  you — **the edge was in the resolution, not the market.**
- **More trading = more bleeding.** VWAP reversion fired 182 trades on 30-min
  and **525** on 5-min, and the finer version lost more than twice as much
  (−23%). Costs + fading a trending tape compound against you.
- **The momentum version lost too (−9.18%).** Intraday EMA crossovers get
  whipsawed in chop, and because the strategy is flat overnight it **misses
  SPY's overnight drift** — which is where much of the +7.77% buy-&-hold return
  actually accrued. Trend-following's whole premise needs sustained moves; a
  single ticker intraday rarely supplies them.
- **None of the three beat simply holding SPY.** All three *lost money* on the
  honest 5-min test while buy & hold made ~+7.8%.

The bottom line from earlier holds, now measured twice: **there is no "proven
to make money" intraday setup.** Edges are thin, regime-dependent, costed away,
and fragile to backtest assumptions.

## Caveats

- **Small sample, one regime** (~3–5 months of a generally rising market).
- **Fills are optimistic** (breakouts assumed to fill at the exact level).
- **Single configs, no parameter search** — and you should resist running one,
  or you'll overfit a curve to this specific window.
- 5-min still doesn't capture tick-level sequencing; it's closer to reality
  than 30-min, not reality itself.

## Bonus: buying options into macro events (`event_study.py`)

A separate test of the popular idea *"buy options before FOMC / CPI and ride the
event."* It checks SPY's realized move on **8 real 2026 macro-event days** (5 CPI
prints, 3 FOMC decisions) against the move the option market prices in.

**The structural catch:** scheduled events are *known*, so the option already
prices the expected move (the "implied move"). You only profit if the realized
move beats what you paid — and sellers add a volatility risk premium, so on
average implied > realized. This is **IV crush**: the event happens, uncertainty
resolves, vol collapses, and your option loses value even if you guessed
direction right.

### What actually happened (Jan 30 – Jun 17, 2026)

- Realized daily vol: **0.93%**. Avg move on **non-event** days: **0.74%**.
- Avg move on **event** days: **0.60%** — *lower* than normal days. Most of these
  events were duds (4 of 5 CPIs moved <0.6%); only 3 of 8 produced a big move.

| Strategy (modeled) | Win rate | Net per event | Total (8 events) |
|---|---|---|---|
| Long ATM straddle, IV ×1.00 (fair) | 37.5% | −0.15% | **−1.23%** |
| Long ATM straddle, IV ×1.15 | 37.5% | −0.27% | −2.13% |
| Long ATM straddle, IV ×1.30 | 37.5% | −0.38% | −3.04% |
| Directional ATM call (always long) | 12.5% | −0.30% | −2.38% |

![event option study](results/event_options.png)

Only **3 of 8** events (Mar-18 FOMC, Jun-10 CPI, Jun-17 FOMC) cleared even the
cheapest breakeven. The straddle lost money in *every* IV scenario — including
the "fair" one with no premium — because realized event moves came in *below*
the priced-in move. The directional call did worse still: you must be right on
*direction too*, and SPY mostly fell on these days, so it won just 12.5%.

### Takeaways

- **The market already knows the event is coming.** That's the whole problem —
  the premium bakes in the expected move, so being right that "CPI will move the
  market" isn't enough; you need it to move *more than priced*.
- **You're fighting a negative edge.** Long event vol on indices is, on average,
  a losing trade because of the variance risk premium + IV crush.
- **Direction is a second coin flip** stacked on top of the premium hurdle.
- **Geopolitics is excluded on purpose.** You can't schedule a surprise — and
  *unscheduled* shocks are the only ones not already priced in. By the time
  you've read the headline, the move (and the IV spike) has happened.

### Big caveats

- **Implied move is modeled, not observed.** The live option chain needed
  re-auth, so implied move = realized vol × an IV-premium factor (swept 1.0–1.3).
  Re-auth the broker and the script can use real ATM straddle prices for exact
  premiums. The *structural* conclusion (must beat the priced-in move) holds
  regardless.
- **Tiny sample** (8 events, one calm-ish regime). A single fat-tail surprise
  (a hot CPI, a war headline) can pay for many losers — long-vol payoffs are
  lottery-shaped. This window simply didn't deliver one.
- ATM straddle premium approximated as `0.8 × σ × spot`; payoff assumes you
  capture full intrinsic at expiry (generous to the buyer).

## Run it

```bash
pip install pandas numpy matplotlib
python3 backtest/backtest.py       # intraday: ORB / VWAP / EMA trend
python3 backtest/event_study.py    # event-driven options
```

Outputs in `results/`: `summary.csv`, `event_straddle_summary.csv`,
per-strategy/per-dataset trade CSVs, and the equity / event charts.
