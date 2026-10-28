"""Independent YeNo A-prototype: explicit heuristic policy while A1 is researched.

This is NOT trained, optimized, or official. Its purpose is to exercise the
full-L2 execution harness with nontrivial BUY/SELL and preserve capital rules.
No network, wallets, state mutation outside the bot, or copied competitor code.
"""
from __future__ import annotations
import math
from yeno_evaluator.execution import buy, sell


class AProbeBot:
    def __init__(self, *, gap_floor_usd:float=22., spread_max:float=.05,
                 immediate_loss_max_usd:float=.32, entry_earliest:float=240.,
                 entry_latest:float=40., force_exit:float=30.):
        self.gap_floor=gap_floor_usd
        self.spread_max=spread_max
        self.immediate_loss_max=immediate_loss_max_usd
        self.entry_earliest=entry_earliest
        self.entry_latest=entry_latest
        self.force_exit=force_exit
        self.market=None
        self.was_holding=False
        self.exiting=False
        self.cycles=0
        self.last_flat=-math.inf

    def __call__(self, obs:dict) -> dict:
        try:
            return self._decide(obs)
        except (KeyError, ValueError, TypeError, IndexError, AttributeError, ArithmeticError):
            if obs.get("account",{}).get("position") is not None:
                return {"action":"SELL"}
            return {"action":"HOLD"}

    def _decide(self, obs:dict) ->dict:
        ts=float(obs["timestamp"])
        sec=float(obs["market"]["secondsToClose"])
        market=str(obs["market"]["id"])
        if market!=self.market:
            self.market=market;self.was_holding=False;self.exiting=False
            self.cycles=0;self.last_flat=-math.inf
        pos=obs["account"]["position"]
        if pos is None and self.was_holding:
            self.cycles+=1
            self.last_flat=ts
            self.exiting=False
        self.was_holding=pos is not None
        if pos is not None:
            if self.exiting or sec<=self.force_exit:
                self.exiting=True
                return {"action":"SELL"}
            bid=obs["books"][pos["outcome"]]["bids"]
            execution=sell(bid,float(pos["shares"]))
            if execution.shares<=0:
                return {"action":"HOLD"}
            # Partial liquidations stay in the original cycle; conservative
            # net mark-to-market for only the currently executable shares.
            received=float(pos["sell_gross_usd"])-float(pos["sell_fees_usd"])
            paid=float(pos["buy_gross_usd"])+float(pos["buy_fees_usd"])
            available=execution.gross-execution.fees
            net=received+available-paid
            if (net>=0.025 or net<=-0.12*float(pos["shares"])
                    or (sec<=65 and net>=-0.02*float(pos["shares"]))):
                self.exiting=True
                return {"action":"SELL"}
            return {"action":"HOLD"}

        if (self.cycles>=3 or ts-self.last_flat<3
                or not(self.entry_latest<sec<=self.entry_earliest)):
            return {"action":"HOLD"}
        ref=obs.get("reference")
        if (not ref or ref.get("targetProvisional",True)
                or ref.get("retrospectiveOracle", False)
                or ts-float(ref["observedAt"])>1.5
                or float(ref["targetObservedAt"])>ts):
            return {"action":"HOLD"}
        gap=float(ref["btcMidUsd"])-float(ref["openingTargetUsd"])
        if abs(gap)<self.gap_floor:
            return {"action":"HOLD"}
        side="YES" if gap>0 else "NO"
        b=obs["books"].get(side)
        if not b:return {"action":"HOLD"}
        bids,asks=b["bids"],b["asks"]
        if not bids or not asks:return {"action":"HOLD"}
        best_bid=float(bids[0][0]);best_ask=float(asks[0][0])
        if (best_ask>0.93 or best_ask<0.45 or
                best_ask-best_bid>self.spread_max):
            return {"action":"HOLD"}
        cap=min(4.85,float(obs["account"]["cashUsd"]),float(obs["rules"]["maximumBuyCashUsd"]))
        required=float(b.get("minOrderSize",5.) or 5.)
        if not math.isfinite(required) or required<=0:return {"action":"HOLD"}
        purchase=buy(asks,cap,max_shares=required)
        if purchase.shares + 1e-9 < required:return {"action":"HOLD"}
        # Local immediate-loss budget; actual later price +250ms may be worse.
        liquidation=sell(bids,purchase.shares)
        if liquidation.shares + 1e-9 < purchase.shares:return {"action":"HOLD"}
        cost=purchase.gross+purchase.fees-liquidation.gross+liquidation.fees
        if cost>self.immediate_loss_max:return {"action":"HOLD"}
        budget=min(cap,purchase.gross+purchase.fees+0.025)
        return {"action":"BUY","outcome":side,"maxCashUsd":round(budget,4)}
