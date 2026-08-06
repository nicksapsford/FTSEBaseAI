# FTSEBase A.I.

Part of the **Albion Benchmark Desk** — a parallel scientific baseline for the
original Albion Trading Desk. FTSEBase trades the FTSE 100 on **pure Lancelot
signals with no AI overlay**, so its P&L can be compared like-for-like against the
original FTSETrader.

- **Port:** 5032 · **Instrument:** FTSE 100 (UK100, Capital.com) · **Balance:** £1,000
- **Template:** FTSETrader v2.1.23 · **Paper trading only** · **Session:** 07:45–16:30 UTC weekdays

> Strategic note: Gaius Commission 001 found 63/63 FTSE phantom signals were SHORTs
> in an uptrend — the contrarian LONG would have returned +£272. FTSEBase in
> **AGAINST** mode is the direct test of that hypothesis.

## Decision engine (the whole thing)

Every 5-minute candle:

1. **Lancelot pre-checks** must all pass — identical to FTSETrader (`pre_checks_ftse`, copied verbatim, confirmed pure).
2. **3-timeframe SSL agreement** — Daily + 1h + 5m SSL must all point the same way. That is the direction signal.
3. **Direction switch** decides execution:
   - `WITH` — trade the SSL direction.
   - `AGAINST` — trade the opposite (contrarian). Lancelot always validates the *signal* direction; only the executed direction flips.

Exits are pure risk management: **10pt trailing stop / 25pt take profit / Profit Protection Ladder (Variant 2)** — via Stanley's `monitor_trade()`.

**Stripped vs FTSETrader:** no Arthur (AI), no Morgan (confidence), no Guinevere (news), no phantom logging, no confidence thresholds.

Parameters: £2.00/pt stake, 3pt spread, bidirectional, switch default **WITH**. FTSE is GBP-denominated (no USD conversion).

## The direction switch (WITH / AGAINST)
One switch, **live reload** — re-read from `logs/direction_switch.json` every tick; flip from the dashboard or BenchmarkRoundTable with **no restart**. Default WITH; persists; atomic write.

## Running
```
python dashboard_ftsebase.py     # port 5032 (switch + status)
python watchdog_ftsebase.py      # supervises main_ftsebase.py
```

Session phases: PRE_OPEN / MORNING_PRIME / AFTERNOON / CLOSED. Appears automatically on **BenchmarkRoundTable** (port 5030) once running.

All times UTC.
