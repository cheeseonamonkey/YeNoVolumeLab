# YeNo — AProbe paper-trading bot

Standalone deterministic Python submission for the Builderr YeNo BTC five-minute volume challenge. No third-party Python packages, credentials, exchange access, or real-money trading.

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

## Evidence and limitations

The official starter-kit smoke test passed. A local 100-request loopback test measured median 1.49 ms and p99 2.50 ms (not a production load test). The heuristic was evaluated using PMData incremental L2 with a **proxy** Binance BTC reference, not Builderr's hidden official replay. Some simulations showed severe cash drawdowns. No $1,000 qualification or superior learned-policy performance is claimed. Paper trading only.

The implementation uses the local AProbe policy and its fee/depth-aware execution helpers. No external model is loaded.
