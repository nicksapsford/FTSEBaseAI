"""
FTSETrader AI -- strategy_ftse.py
FTSE 100 spread betting strategy mechanics.
Points-based trailing stop (NOT percentage-based like BTC).
P&L = points_moved * stake_per_point.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger("FTSETrader.Strategy")

# ── Settings from backtest optimal configuration ──────────────────────────────

TRAILING_STOP_POINTS   = 10.0    # trailing stop in index points (System 1 Review 17 Jul: 40->10; whipsaw 41.9% at 10pt vs 64.9% at 5pt, above 7.9pt median adverse move)
TAKE_PROFIT_POINTS     = 25.0    # take-profit (System 1 Review: 200->25; evidence-based, ~90th pct move ~46pt phantom / ~23pt actual)
MAX_RISK_PER_TRADE_GBP = 20.0    # max GBP loss per trade (2% of £1000). stake = 20/10 = £2.00/pt
IG_SPREAD_POINTS       = 3.0     # total spread in points (Capital.com demo UK100, confirmed 17 Jul: Sell 10,573.2 / Buy 10,576.2)
IG_SPREAD_HALF         = IG_SPREAD_POINTS / 2   # half-spread applied to each fill (ask/bid)
FORCE_CLOSE_HOUR       = 16
FORCE_CLOSE_MIN        = 20

UK_TZ = "Europe/London"


# ── Trade record ──────────────────────────────────────────────────────────────

# Recalibrated for the 10pt stop / £2.00 per point stake (System 1 Review, 17 Jul).
# Step1 £8=4pt (above noise, trade developing); Step2 £20=10pt (1x stop); Step3 £35=17.5pt (toward the 25pt target).
PROFIT_LADDER = [
    {"trigger_gbp": 8.00,  "floor_gbp": 6.00},
    {"trigger_gbp": 20.00, "floor_gbp": 17.00},
    {"trigger_gbp": 35.00, "floor_gbp": 30.00},
]


@dataclass
class FTSETrade:
    """
    A single FTSE spread bet trade.
    Sizing: stake = MAX_RISK / stop_distance (e.g. £10/40pt = £0.25/pt)
    P&L: points_moved * stake_per_point
    """
    direction:     str
    entry_price:   float
    stop_pts:      float
    entry_time:    object = field(default=None)
    session_phase: str    = field(default="")

    def __post_init__(self):
        self.stake         = round(MAX_RISK_PER_TRADE_GBP / self.stop_pts, 4)
        self.trail_best    = self.entry_price
        if self.direction == "LONG":
            self.stop_loss   = self.entry_price - self.stop_pts
            self.take_profit = self.entry_price + TAKE_PROFIT_POINTS
        else:
            self.stop_loss   = self.entry_price + self.stop_pts
            self.take_profit = self.entry_price - TAKE_PROFIT_POINTS
        self.exit_price  = None
        self.exit_time   = None
        self.exit_reason = None
        self.pnl_pts     = None
        self.pnl_gbp     = None
        if self.entry_time is None:
            self.entry_time = datetime.now(timezone.utc)

    def apply_profit_ladder(self, price: float):
        """Profit Protection Ladder (Variant 2). Tighten the stop to guarantee a
        minimum GBP floor as floating profit builds -- additive to the trailing stop,
        only ever tightens, never triggers on a floating loss. The trailing stop and
        the force close are unaffected (whichever stop is tighter wins). Idempotent,
        so it re-applies correctly on restart. Returns a dict describing a NEWLY
        triggered rung (for logging), else None."""
        if not PROFIT_LADDER or self.stake <= 0:
            return None
        if not hasattr(self, "ladder_step"):     # lazy init (also survives reload)
            self.ladder_step, self.ladder_floor_gbp = 0, 0.0
        pts = (price - self.entry_price) if self.direction == "LONG" else (self.entry_price - price)
        float_gbp = pts * self.stake
        if float_gbp <= 0:                       # never engage on a floating loss
            return None
        idx, floor = 0, 0.0
        for i, s in enumerate(PROFIT_LADDER, start=1):
            if float_gbp >= s["trigger_gbp"]:
                idx, floor = i, s["floor_gbp"]
        if idx == 0:
            return None
        new_rung = idx > self.ladder_step
        if new_rung:
            self.ladder_step = idx
            self.ladder_floor_gbp = floor
        if self.ladder_floor_gbp <= 0:
            return None
        floor_pts = self.ladder_floor_gbp / self.stake
        stop_before = self.stop_loss
        if self.direction == "LONG":
            floor_stop = round(self.entry_price + floor_pts, 2)
            if floor_stop > self.stop_loss:      # tighten only
                self.stop_loss = floor_stop
        else:
            floor_stop = round(self.entry_price - floor_pts, 2)
            if floor_stop < self.stop_loss:      # tighten only
                self.stop_loss = floor_stop
        if new_rung:
            log.info("  PROFIT LADDER step %d: float GBP %.2f -> floor GBP %.2f | stop %.2f -> %.2f",
                     idx, float_gbp, self.ladder_floor_gbp, stop_before, self.stop_loss)
            return {"step": idx, "floor_gbp": self.ladder_floor_gbp,
                    "trigger_float_gbp": round(float_gbp, 2),
                    "stop_before": round(stop_before, 2), "stop_after": self.stop_loss}
        return None

    def update_trailing_stop(self, price: float) -> bool:
        """
        Move stop in favour of the trade as price moves our way.
        Returns True if stop was moved.
        """
        if self.direction == "LONG" and price > self.trail_best:
            self.trail_best = price
            new_sl = price - self.stop_pts
            if new_sl > self.stop_loss:
                self.stop_loss = new_sl
                log.info(
                    "  Trailing stop moved UP to %.1f (price=%.1f)",
                    self.stop_loss, price,
                )
                return True
        elif self.direction == "SHORT" and price < self.trail_best:
            self.trail_best = price
            new_sl = price + self.stop_pts
            if new_sl < self.stop_loss:
                self.stop_loss = new_sl
                log.info(
                    "  Trailing stop moved DOWN to %.1f (price=%.1f)",
                    self.stop_loss, price,
                )
                return True
        return False

    def check_exit(self, price: float) -> Optional[str]:
        """Check stop loss and take profit. Returns exit reason or None."""
        if self.direction == "LONG":
            if price <= self.stop_loss:  return "STOP_LOSS"
            if price >= self.take_profit: return "TAKE_PROFIT"
        else:
            if price >= self.stop_loss:  return "STOP_LOSS"
            if price <= self.take_profit: return "TAKE_PROFIT"
        return None

    def close(self, price: float, reason: str) -> None:
        """
        Record exit at the bid/ask fill, not the mid.
        LONG closes by SELLING at the bid  (mid - half-spread);
        SHORT closes by BUYING at the ask (mid + half-spread).
        The entry was already recorded at the opposite side (ask for LONG, bid
        for SHORT), so the full 1-point spread cost is captured across the two
        fills -- it is NOT deducted a second time here.
        """
        if self.direction == "LONG":
            self.exit_price = round(price - IG_SPREAD_HALF, 1)
        else:
            self.exit_price = round(price + IG_SPREAD_HALF, 1)
        self.exit_time   = datetime.now(timezone.utc)
        self.exit_reason = reason
        raw_pts          = (self.exit_price - self.entry_price) if self.direction == "LONG" else (self.entry_price - self.exit_price)
        self.pnl_pts     = raw_pts
        self.pnl_gbp     = round(self.pnl_pts * self.stake, 2)

    @property
    def is_open(self) -> bool:
        return self.exit_price is None

    @property
    def points_from_entry(self) -> Optional[float]:
        """Signed points moved from entry (positive = our favour)."""
        if not self.is_open:
            return self.pnl_pts
        return None

    def summary(self) -> str:
        if self.is_open:
            return (
                f"[OPEN {self.direction}] entry={self.entry_price:.1f} "
                f"stop={self.stop_loss:.1f} target={self.take_profit:.1f} "
                f"stake=£{self.stake:.2f}/pt"
            )
        sign = "WIN " if (self.pnl_gbp or 0) >= 0 else "LOSS"
        return (
            f"[{sign} {self.direction}] "
            f"entry={self.entry_price:.1f} exit={self.exit_price:.1f} "
            f"pts={self.pnl_pts:+.1f} P&L=£{self.pnl_gbp:+.2f} "
            f"reason={self.exit_reason}"
        )


# ── Strategy helpers ──────────────────────────────────────────────────────────

def calculate_stake(stop_distance: float = TRAILING_STOP_POINTS) -> float:
    """Return stake per point for the given stop distance."""
    return round(MAX_RISK_PER_TRADE_GBP / stop_distance, 4)


def calculate_stop_loss(entry_price: float, direction: str,
                        stop_pts: float = TRAILING_STOP_POINTS) -> float:
    if direction == "LONG":
        return entry_price - stop_pts
    return entry_price + stop_pts


def calculate_take_profit(entry_price: float, direction: str,
                          tp_pts: float = TAKE_PROFIT_POINTS) -> float:
    if direction == "LONG":
        return entry_price + tp_pts
    return entry_price - tp_pts


def should_force_close(ts_utc=None) -> bool:
    """Return True if it is 16:20 UK time or later -- force close all positions."""
    if ts_utc is None:
        ts_utc = datetime.now(timezone.utc)
    try:
        import pytz
        uk_tz = pytz.timezone(UK_TZ)
        ts_uk = ts_utc.astimezone(uk_tz)
    except ImportError:
        ts_uk = ts_utc.astimezone()
    return ts_uk.hour == FORCE_CLOSE_HOUR and ts_uk.minute >= FORCE_CLOSE_MIN or ts_uk.hour > FORCE_CLOSE_HOUR


def open_trade(direction: str, price: float, session_phase: str = "",
               stop_pts: float = TRAILING_STOP_POINTS) -> FTSETrade:
    """
    Create and log a new FTSETrade.
    The mid price is converted to the real fill: LONG BUYS at the ask
    (mid + half-spread), SHORT SELLS at the bid (mid - half-spread), so the
    recorded entry reflects the price actually paid -- this is how the 1-point
    spread cost enters the P&L.
    """
    fill_price = round(price + IG_SPREAD_HALF, 1) if direction == "LONG" else round(price - IG_SPREAD_HALF, 1)
    trade = FTSETrade(
        direction    = direction,
        entry_price  = fill_price,
        stop_pts     = stop_pts,
        entry_time   = datetime.now(timezone.utc),
        session_phase= session_phase,
    )
    log.info(
        ">>> TRADE OPENED | %s | entry=%.1f (mid=%.1f) | stake=£%.4f/pt | "
        "stop=%.1f | target=%.1f | session=%s",
        direction, trade.entry_price, price, trade.stake,
        trade.stop_loss, trade.take_profit, session_phase,
    )
    return trade


def close_trade(trade: FTSETrade, price: float, reason: str) -> FTSETrade:
    """Close a trade and log the result."""
    trade.close(price, reason)
    sign = "WIN " if trade.pnl_gbp >= 0 else "LOSS"
    log.info(
        "<<< TRADE CLOSED | [%s %s] | pts=%+.1f | P&L=£%+.2f | reason=%s",
        sign, trade.direction, trade.pnl_pts, trade.pnl_gbp, reason,
    )
    return trade


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log.info("Strategy self-test")
    t = open_trade("LONG", 8250.0, "MORNING_PRIME")
    log.info("%s", t.summary())
    log.info("Stake: £%.4f/pt | Max risk: £%.2f", t.stake, t.stake * t.stop_pts)
    t.update_trailing_stop(8290.0)
    log.info("After +40pt move: stop=%.1f", t.stop_loss)
    exit_reason = t.check_exit(8240.0)
    log.info("Check exit at 8240: %s", exit_reason)
    close_trade(t, 8240.0, "STOP_LOSS")
    log.info("%s", t.summary())
    log.info("Force close at 16:20: %s", should_force_close())
