# Option Bracket / OCO Helper — Simulation Only

Reproduces the "drag a take-profit and a stop-loss onto the chart and walk
away" behaviour that Robinhood lacks natively for options. Triggers are on the
**option's own price**.

> ⚠️ **Simulation only.** This code never contacts a broker. It uses a
> `SimBroker` that only *prints* what it would do. Going live is a separate,
> deliberate step (see below) and is intentionally not wired up.

## What a bracket / OCO is

When you buy an option you have one open position. A **bracket** attaches two
exit orders to it:

- a **take-profit** *above* your entry (sell for a gain), and
- a **stop-loss** *below* your entry (sell to cap the loss).

They're linked as **OCO — "one-cancels-other":** whichever fills first, the
other is cancelled automatically. That's the "set it and forget it" part — you
don't have to babysit the screen and click through exits.

## How this implementation works

A real broker rests two live orders. This helper instead **watches the quote
and fires one marketable exit** when a level is hit (what a bot does) — simpler
and easier to reason about. The flow:

```
Bracket  (entry, qty, take-profit, stop-loss)
   │
   ▼
BracketEngine.on_price(quote)   ← called on every new option quote
   │   price ≤ stop  → exit (stop_loss)
   │   price ≥ target→ exit (take_profit)
   │   else          → keep watching
   ▼
Broker.submit_exit(...)         ← SimBroker just prints; a LiveBroker would trade
```

Only one exit can ever fire, so the OCO cancel is automatic. If neither level
is hit by the close, `on_session_end()` flattens so nothing is held overnight.

### Design choices worth knowing

- **Stop-loss is checked first.** Conservative tie-breaker if a single quote
  ever straddles both levels.
- **Gaps fill at the observed price, not the level.** If the option gaps from
  $2.00 to $1.05 through a $1.20 stop, the exit is modeled at **1.05** — stops
  are triggers, not guarantees. (See the "gap through stop" self-test.)
- **Levels can be percentages or absolute prices** (`take_profit_pct=0.50`, or
  `take_profit_price=3.00`).

## Self-tests

`python3 bracket/bracket.py` runs scripted scenarios and asserts correct
behaviour: take-profit first, stop first, gap-through-stop, neither-hit, and
input validation. All must print `PASSED ✓` (exactly one exit per bracket).

## Going live later (not done yet)

The `Broker` interface is the single seam. To trade for real you'd:

1. Subclass `Broker` with a `submit_exit()` that calls the real
   `place_option_order` (sell-to-close).
2. Feed `engine.on_price()` from a live option-quote loop (`get_option_quotes`).

In this Claude session that live loop can be driven through the brokerage MCP
tools — but only on your explicit, per-session go-ahead. Nothing here sends an
order on its own.

## Roadmap / easy extensions

- **Trailing stop** (ratchet the stop up as the option gains).
- **Underlying-based triggers** (exit when SPY hits X, not the option price) —
  you said option-price first; this is the natural next mode.
- **Partial scaling** (take half at target 1, rest at target 2).
