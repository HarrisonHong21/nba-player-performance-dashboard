# Session Handoff — SPY Day-Trading / Options Exploration

A running notebook of everything covered in this session, so it can be picked up
in a fresh chat. **Everything below is educational, not financial advice.**

## Where the code lives

- **Repo:** `harrisonhong21/nba-player-performance-dashboard`
- **Branch:** `claude/day-trading-strategy-events-0b6ltj` (all work pushed here)
- **Dirs added:**
  - `backtest/` — intraday + event-driven backtests, data, results, README
  - `bracket/` — option bracket/OCO helper (simulation only) + README

To resume in another chat: open a session on this repo + branch, or move these
two folders into whatever repo you continue in.

---

## 1. Trading Q&A (start of session)

**Macro/earnings events:** Today is Thu 2026-06-18. The week's big catalyst (FOMC,
held at 3.50–3.75%) was already past. Morning data to watch was ~8:30 ET jobless
claims + Philly Fed (forecast +11.4 vs −0.4 prior), LEI at 10:00. Earnings light.
Use a live calendar (Econoday / Trading Economics) morning-of.

**Support/resistance on SPY (method):** mark prior swing highs/lows; look for
price *clusters* (more touches = stronger); respect round numbers; add prior-day
H/L/C + overnight range for intraday; confluence with VWAP / 20–50 MAs / pivots;
broken resistance becomes support and vice-versa. Treat as *zones*, not lines.
Levels at the time (prior close ~740.96, pre-mkt ~745.8): resistance ~750 → 755–756
→ ~760 (recent top); support ~740–742 → 737 → ~725 → 722.6.

**"Sevkota" = Ed Seykota.** A trend-following, *end-of-day* trader (Market Wizard),
NOT a day-trader. Priorities: long-term trend > chart pattern > entry > (distant)
fundamentals. He traded **liquid futures markets that trend** (FX, metals, grains,
commodities), mechanically, diversified, on the daily timeframe. Mapping him onto
SPY intraday is a mismatch — his edge is multi-day/week trends across many markets.

**"Proven to make money" reality:** No intraday method is proven profitable.
Studies show ~70–95% of active day traders lose; only ~1–3% are reliably
profitable. Survivors win on **risk management + consistency + psychology**, not a
magic setup: risk ≤1% per trade, defined stop before entry, positive expectancy,
master ONE setup, journal everything, paper-trade first.

---

## 2. Intraday backtests (`backtest/backtest.py`)

Data pulled from the broker feed (Yahoo/yfinance is blocked by network egress).
30-min bars (96 sessions, Jan 30–Jun 17) and 5-min bars (81 sessions, Feb 23–Jun
17). Intraday only (flat overnight), 4 bps round-trip cost, full-equity compounding.

**Results — none beat buy & hold:**

| Bars | Strategy | Trades | Win% | PF | Total ret | (Buy&hold) |
|---|---|---|---|---|---|---|
| 30-min | Opening Range Breakout | 96 | 49.0% | 1.08 | +1.33% | +7.15% |
| 30-min | VWAP Reversion | 182 | 39.6% | 0.59 | −10.53% | +7.15% |
| 5-min | Opening Range Breakout | 81 | 45.7% | 0.87 | **−2.33%** | +7.77% |
| 5-min | VWAP Reversion | 525 | 31.0% | 0.49 | **−23.00%** | +7.77% |
| 5-min | EMA Trend 9/21 (momentum) | 268 | 31.3% | 0.71 | **−9.18%** | +7.77% |

**Key lessons:**
- The ORB "edge" on 30-min bars **vanished on finer 5-min bars** → it was partly an
  artifact of coarse bars + optimistic fills, not a real edge.
- More trading = more bleed (VWAP reversion worse the more it traded).
- Momentum (EMA crossover) got whipsawed AND forfeited SPY's **overnight drift**,
  which is where most of the buy-&-hold gain accrued.
- Charts: `results/equity_curve_5min.png`.

---

## 3. Event-driven options backtest (`backtest/event_study.py`)

Tested "buy SPY options into FOMC/CPI." 8 real 2026 events (5 CPI, 3 FOMC).
**Live option IV was unavailable (broker token expired)** → implied move is
MODELED from realized vol × an IV-premium factor (swept 1.0–1.3). Re-auth broker
to swap in real ATM straddle prices.

**Results:**
- Realized daily vol 0.93%. Avg move on **event** days **0.60%** — *lower* than
  non-event days (0.74%). Only 3 of 8 events moved big (Mar-18 FOMC, Jun-10 CPI,
  Jun-17 FOMC); 4 of 5 CPIs were duds.
- Long ATM straddle: lost in EVERY scenario (−1.2% to −3.0% over 8 events), 37.5%
  win — including the "fair IV" case, because realized < priced-in move.
- Directional ATM call (always long): 12.5% win, −2.4% to −3.3%.

**Why:** scheduled events are *known* → the option already prices the expected
move (**IV crush** / variance risk premium). You need realized > implied, and on
average it's less. Direction is a second coin flip on top. Geopolitics excluded —
only *unscheduled* shocks aren't priced, and by the time you read the headline the
move + IV spike already happened. Chart: `results/event_options.png`.

---

## 4. Option bracket / OCO helper (`bracket/bracket.py`) — SIMULATION ONLY

Reproduces "drag take-profit + stop-loss onto the chart, walk away" — which
**Robinhood lacks natively for options** (use thinkorswim / tastytrade / IBKR /
TradingView-linked broker for real chart-drag brackets).

- **Bracket / OCO** = take-profit above + stop-loss below entry, linked so one
  filling cancels the other.
- This impl is a **monitoring bot**: `BracketEngine.on_price(quote)` watches the
  **option's price** (per user's choice) and fires one marketable exit when a
  level hits; OCO is automatic since only one ever fires. `on_session_end()`
  flattens if neither hit.
- **Safety:** `SimBroker` only PRINTS intended orders. No live order path exists.
  Going live = subclass `Broker.submit_exit()` to call `place_option_order` and
  feed quotes from `get_option_quotes` — only on explicit per-session go-ahead.
- Design notes: stop checked first (conservative); **gaps fill at observed price,
  not the stop level** (stops are triggers, not guarantees).
- Self-tests pass (TP-first, SL-first, gap-through-stop, neither-hit, validation):
  run `python3 bracket/bracket.py`.

**Open follow-ups for the bracket tool:**
1. Demo against a live SPY contract (still simulation — react to real quotes).
2. Add **underlying-based triggers** ("exit when SPY hits X", not option price).
3. Add **trailing stop** and partial scaling.

---

## 5. Repo-switch request (unresolved)

User asked to switch this chat to their GitHub repo named **`Claude`**. Could not
do it: the session repo-management tools (`list_repos` / `add_repo`) are not
connected in this session, and GitHub scope is locked to the nba repo. **Action
for next chat:** start a new Claude Code session pointed at the `Claude` repo
(exact owner/name to confirm — likely `harrisonhong21/Claude`), then move these
two folders over if you want the trading work there.

---

## Environment notes
- Network egress is allowlisted; **Yahoo Finance / yfinance is blocked** — pull
  market data via the broker MCP feed instead.
- Broker MCP **option-quote token expired** mid-session → re-auth needed for live
  option prices (equity quotes/historicals still worked).
- Large historicals responses exceed the token limit and auto-save to a file on
  disk; read/process them with Python rather than inline.

## One-line bottom line
Across intraday strategies, event-driven options, and three granularities, **none
beat simply holding SPY** — consistent with the research. The bracket tool is a
discipline/time-saver, not an edge.
