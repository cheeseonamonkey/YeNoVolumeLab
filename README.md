# YeNo — AProbe paper-trading bot

Standalone deterministic Python submission for the Builderr YeNo BTC five-minute volume challenge. No third-party Python packages, credentials, exchange access, or real-money trading.

## Architecture and design choices

The submission deliberately favors **a small, auditable deterministic policy** over a learned model. Research variants (Ridge A1/A2, neural predictors, and risk gates) have not demonstrated better *completed trading volume with survivable cash* in independent execution tests. They are not included in this submission.

- **Contract adapter (`bot.py`):** standard-library HTTP server accepts `POST /decide`, serializes calls to one stateful policy instance, checks the action shape and fee-inclusive cash cap, and returns `HOLD` on invalid or unsupported actions. The evaluator, not the bot, executes paper orders.
- **Strategy (`yeno_evaluator/a_probe.py`):** per-market state tracks entry/exit and completed cycles. It uses the observed BTC midpoint minus the opening target to choose YES/NO, subject to timestamp freshness, non-provisional target, time-to-close, spread, price and depth filters. It never substitutes future reference data.
- **Execution estimates (`yeno_evaluator/execution.py`):** order-book levels are sorted and walked to estimate executable shares, gross notional, and protocol-plus-overlay fees. A prospective buy must fit the cash cap **including fees** and pass an immediate liquidation-loss check; these are estimates, not guaranteed fills after latency.
- **Exit priority:** while holding inventory, the bot considers estimated net proceeds and loss limits, then forces liquidation attempts near expiry. SELL decisions remain possible even when new entries are disallowed. Partial fills and final accounting belong to the evaluator.
- **Operational constraints:** one worker, ordered observations, in-memory per-market state, no network dependencies. The loopback HTTP server is a development interface, not a hardened public deployment.

The overall research harness uses causal incremental L2 replay with 250 ms simulated execution latency and 5-second local decision sampling. **That replay harness is not part of this minimal submission**, and its Binance BTC reference is only a proxy for the hidden evaluation inputs.

## Run

```sh
python3 bot.py
```

Binds to `127.0.0.1:8765` by default. `POST /decide` accepts the Builderr observation and returns `HOLD`, `BUY` or `SELL`. `GET /health` returns a health response. Use one worker and an ordered observation stream: the policy keeps per-market state in memory. Do not expose this development HTTP server publicly; use an authenticated HTTPS reverse proxy if deploying as an endpoint.

## Verify

```sh
python3 bot.py & BOT_PID=$!
python3 yeno-smoke-test.py --url http://127.0.0.1:8765/decide --observation yeno-sample-observation.json
kill "$BOT_PID"
```

## Measured AProbe scores (local paper replay)

These are **our own AProbe bot** results, not other entrants, and are not official Builderr scores. All runs used original PMData incremental L2 with a causal **Binance BTCUSDT reference proxy**, 250 ms simulated fill latency, 5-second local decision sampling, $10 starting paper cash, and a $5 fee-inclusive buy cap. Markets are **spaced samples**, not complete 288-market days.

| Date (2026) | Markets | Completed volume | Closed cycles | Ending cash | Fees | Maximum cash drawdown | Terminal flat |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| May 14 | 12 | $217.66 | 27 | $3.64 | $5.00 | 99.06% | Yes |
| May 25 | 12 | $174.21 | 22 | $3.78 | $4.05 | 99.93% | Yes |
| May 14 | 36 | $270.60 | 34 | $2.50 | $6.34 | 99.64% | Yes |

The 36-market May 14 result is **not an independent additional day**: it overlaps the 12-market May 14 sample. The 36-market Ridge *shadow* run did not change AProbe's trades or scores. The severe cash drawdowns are an important weakness; none of these partial-day simulations proves reaching the $1,000 qualification threshold or surviving a full official 24-hour evaluation.

## Evidence and limitations

The official starter-kit smoke test passed. A local 100-request loopback test measured median 1.49 ms and p99 2.50 ms (not a production load test). The heuristic was evaluated using PMData incremental L2 with a **proxy** Binance BTC reference, not Builderr's hidden official replay. Some simulations showed severe cash drawdowns. No $1,000 qualification or superior learned-policy performance is claimed. Paper trading only.

The implementation uses the local AProbe policy and its fee/depth-aware execution helpers. No external model is loaded.

## Submission verification and robustness

The repository root is the **standalone submission**. It needs only Python 3.11+
and the standard library; the much larger offline YeNoVolumeLab training/replay
worktree is not required.

Run the API and safety regressions before freezing a commit:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q bot.py yeno_evaluator tests
python3 bot.py &
pid=$!
python3 yeno-smoke-test.py --url http://127.0.0.1:8765/decide --observation yeno-sample-observation.json
kill "$pid"
git rev-parse HEAD
```

The server binds to loopback by default. Do not expose it directly to the
internet. Official assessment uses the immutable commit you provide to Builderr,
**not** subsequent changes to the default branch. Send Builderr a fresh commit
hash if submitting a revised build.

October 28 verification: original depth-walk had quadratic repeated summation
and exceeded the 200 ms response budget in synthetic deep-book estimates. The
optimized walk retains the exact fee formula and policy thresholds; it matched
the previous implementation to within 1e-10 on 1,400 randomized fills (fees
identical), and 840 synthetic sequential AProbe decisions agreed. At 1,000
synthetic order-book levels the single BUY-estimate runtime dropped from
approximately 1,648 ms to 22 ms on the test host. Malformed depth observations
now produce a valid fail-closed decision instead of raising an IndexError.

These are **interface and runtime improvements, not a demonstrated strategy
edge**. Historical local full-day AProbe replays have not qualified for $1,000
completed volume; the hidden Builderr evaluator has not been replicated.
