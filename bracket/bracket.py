"""
Option bracket / OCO helper -- SIMULATION ONLY.

Reproduces the "drag a take-profit and a stop-loss onto the chart and walk away"
behaviour that Robinhood lacks natively for options. You define a long option
position plus a take-profit and a stop-loss; the engine watches the option's
price and fires the matching exit when either level is hit. Because only one
exit can ever fire, the other is implicitly cancelled -- that's the OCO
("one-cancels-other") behaviour.

SAFETY: this module never talks to a broker. It uses a SimBroker that only
PRINTS what it would do. Wiring a real broker is a separate, explicit step
(implement the Broker interface) and is intentionally not included here.

Triggers are on the OPTION's own price (per your choice). Run:

    python3 bracket/bracket.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

CONTRACT_MULTIPLIER = 100  # 1 option contract = 100 shares


class State(str, Enum):
    ACTIVE = "active"            # watching, no exit yet
    TP_FILLED = "take_profit"    # take-profit hit -> position closed
    SL_FILLED = "stop_loss"      # stop-loss hit -> position closed
    CLOSED_EOD = "closed_eod"    # neither hit; flattened at session end


# ---------------------------------------------------------------------------
# The bracket definition
# ---------------------------------------------------------------------------
@dataclass
class Bracket:
    """A long-option position with a take-profit ABOVE and a stop-loss BELOW
    the entry price. Levels are on the option's own price (e.g. a $2.00 premium
    going to $3.00)."""
    symbol: str
    entry_price: float
    qty: int = 1
    tp_price: float | None = None
    sl_price: float | None = None

    @classmethod
    def from_targets(cls, symbol, entry_price, qty=1,
                     take_profit_pct=None, stop_loss_pct=None,
                     take_profit_price=None, stop_loss_price=None):
        """Build from either percentages (e.g. +50% / -40%) or absolute prices."""
        tp = (take_profit_price if take_profit_price is not None
              else entry_price * (1 + take_profit_pct) if take_profit_pct is not None
              else None)
        sl = (stop_loss_price if stop_loss_price is not None
              else entry_price * (1 - stop_loss_pct) if stop_loss_pct is not None
              else None)
        b = cls(symbol, entry_price, qty, tp, sl)
        b.validate()
        return b

    def validate(self):
        if self.tp_price is not None and self.tp_price <= self.entry_price:
            raise ValueError("take-profit must be ABOVE entry for a long option")
        if self.sl_price is not None and self.sl_price >= self.entry_price:
            raise ValueError("stop-loss must be BELOW entry for a long option")
        if self.tp_price is None and self.sl_price is None:
            raise ValueError("set at least one of take-profit / stop-loss")


# ---------------------------------------------------------------------------
# Broker interface + a safe simulation implementation
# ---------------------------------------------------------------------------
class Broker:
    """Interface a real broker adapter would implement. To go live later, make
    a subclass whose submit_exit() actually calls place_option_order."""
    def submit_exit(self, reason: str, price: float, qty: int, ts) -> int:
        raise NotImplementedError


@dataclass
class SimBroker(Broker):
    """Logs intended orders. Sends nothing. This is the whole safety guarantee."""
    orders: list = field(default_factory=list)

    def submit_exit(self, reason, price, qty, ts):
        oid = len(self.orders) + 1
        self.orders.append({"id": oid, "reason": reason, "price": price,
                            "qty": qty, "ts": ts})
        print(f"   [SIM] would SELL TO CLOSE {qty}x @ ~{price:.2f}  ({reason})  "
              f"-- no live order sent")
        return oid


@dataclass
class Action:
    kind: str            # "none" or "exit"
    reason: str = ""
    price: float | None = None


# ---------------------------------------------------------------------------
# The engine: feed it prices, it decides
# ---------------------------------------------------------------------------
class BracketEngine:
    def __init__(self, bracket: Bracket, broker: Broker):
        self.b = bracket
        self.broker = broker
        self.state = State.ACTIVE
        self.exit_order_id: int | None = None
        self.exit_price: float | None = None

    @property
    def done(self) -> bool:
        return self.state is not State.ACTIVE

    def on_price(self, price: float, ts=None) -> Action:
        """Call once per new option quote. Stop-loss is checked first (the
        conservative choice if a single quote somehow straddles both levels)."""
        if self.done:
            return Action("none")
        # Stop-loss: price at or below the stop -> exit. A gap can fill WORSE
        # than the stop, so we fire at the observed price, not the stop level.
        if self.b.sl_price is not None and price <= self.b.sl_price:
            return self._fire(State.SL_FILLED, "stop_loss", price, ts)
        # Take-profit: price at or above the target -> exit.
        if self.b.tp_price is not None and price >= self.b.tp_price:
            return self._fire(State.TP_FILLED, "take_profit", price, ts)
        return Action("none")

    def on_session_end(self, last_price: float, ts=None) -> Action:
        """No level hit by the close -> flatten so nothing is held overnight."""
        if self.done:
            return Action("none")
        return self._fire(State.CLOSED_EOD, "eod_flatten", last_price, ts)

    def _fire(self, new_state: State, reason: str, price: float, ts) -> Action:
        self.state = new_state
        self.exit_price = price
        self.exit_order_id = self.broker.submit_exit(reason, price, self.b.qty, ts)
        # OCO: only one exit ever fires; the "sibling" never gets submitted.
        return Action("exit", reason, price)

    def pnl(self) -> float | None:
        if self.exit_price is None:
            return None
        return (self.exit_price - self.b.entry_price) * self.b.qty * CONTRACT_MULTIPLIER


# ---------------------------------------------------------------------------
# Driving the engine over a price series
# ---------------------------------------------------------------------------
def run_path(bracket: Bracket, prices: list[float], label: str = "") -> BracketEngine:
    eng = BracketEngine(bracket, SimBroker())
    print(f"\n--- {label} ---")
    print(f"   entry {bracket.entry_price:.2f}  |  TP {bracket.tp_price}  "
          f"|  SL {bracket.sl_price}  |  qty {bracket.qty}")
    for i, px in enumerate(prices):
        act = eng.on_price(px, ts=i)
        flag = "" if act.kind == "none" else f"  <== {act.reason.upper()}"
        print(f"   tick {i:>2}: {px:6.2f}{flag}")
        if eng.done:
            break
    else:
        eng.on_session_end(prices[-1], ts=len(prices) - 1)
    pnl = eng.pnl()
    print(f"   result: {eng.state.value}   exit {eng.exit_price:.2f}   "
          f"P&L ${pnl:+.0f}")
    return eng


# ---------------------------------------------------------------------------
# Self-tests: prove the logic is sound before anyone trusts it
# ---------------------------------------------------------------------------
def _self_test():
    print("\n" + "=" * 66)
    print("SELF-TESTS (proving OCO behaviour before any live wiring)")
    print("=" * 66)

    # 1. Take-profit hit first.
    b = Bracket.from_targets("SPY 746C", 2.00, qty=1,
                             take_profit_pct=0.50, stop_loss_pct=0.40)
    e = run_path(b, [2.00, 2.30, 2.80, 3.05, 2.50], "TP hit first")
    assert e.state is State.TP_FILLED
    assert len(e.broker.orders) == 1            # OCO: exactly one exit

    # 2. Stop-loss hit first.
    e = run_path(b, [2.00, 1.80, 1.30, 1.15], "SL hit first")
    assert e.state is State.SL_FILLED
    assert len(e.broker.orders) == 1

    # 3. Gap straight through the stop -> fills WORSE than the stop level.
    e = run_path(b, [2.00, 1.05], "Gap through stop (realistic slippage)")
    assert e.state is State.SL_FILLED
    assert e.exit_price == 1.05                  # not the 1.20 stop level

    # 4. Neither level hit -> flattened at the close.
    e = run_path(b, [2.00, 2.10, 2.40, 2.55, 2.30], "Neither hit -> EOD flatten")
    assert e.state is State.CLOSED_EOD
    assert len(e.broker.orders) == 1

    # 5. Validation guards.
    for bad in [dict(take_profit_price=1.50), dict(stop_loss_price=2.50)]:
        try:
            Bracket.from_targets("X", 2.00, **bad); assert False
        except ValueError:
            pass

    print("\nAll self-tests PASSED ✓  (one and only one exit per bracket)")


if __name__ == "__main__":
    _self_test()
    print("\n" + "=" * 66)
    print("SIMULATION ONLY -- no orders were sent. Not financial advice.")
    print("=" * 66)
