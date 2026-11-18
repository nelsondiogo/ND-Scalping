import ccxt, logging, math
logger = logging.getLogger("ND-Exchange")

class BybitExchangeManager:
    def __init__(self, config):
        self.cfg = config
        self.exchange = self._init_exchange()

    def _init_exchange(self):
        ex = ccxt.bybit({
            "apiKey": self.cfg.api_key,
            "secret": self.cfg.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType":"swap","adjustForTimeDifference":True},
        })
        if self.cfg.testnet:
            ex.set_sandbox_mode(True)
        try: ex.load_markets()
        except Exception as e: logger.warning(f"load_markets: {e}")
        return ex

    def reload_credentials(self, k,s,testnet):
        self.cfg.api_key=k; self.cfg.api_secret=s; self.cfg.testnet=testnet
        self.exchange=self._init_exchange()

    def get_total_equity(self):
        try:
            b=self.exchange.fetch_balance(params={"type":"UNIFIED"})
            info=b.get("info",{}); lst=info.get("result",{}).get("list",[])
            if lst and "totalEquity" in lst[0]:
                return float(lst[0]["totalEquity"])
            return float(b.get("USDT",{}).get("total",0.0))
        except Exception as e:
            logger.error(f"get_total_equity: {e}")
            return -1.0  # -1 = erro, NUNCA 0.0 para nao confundir com saldo zero

    def set_hedge_mode_and_leverage(self, symbol, leverage):
        try: self.exchange.set_position_mode(hedged=True, symbol=symbol)
        except Exception as e: logger.debug(f"position_mode: {e}")
        try: self.exchange.set_leverage(leverage, symbol)
        except Exception as e: logger.debug(f"leverage: {e}")

    def fetch_ticker(self, symbol):
        return self.exchange.fetch_ticker(symbol)

    def fetch_positions_live(self, symbol):
        """Fonte da verdade - vem da Bybit"""
        try:
            pos=self.exchange.fetch_positions([symbol])
            out=[]
            for p in pos:
                contracts=float(p.get("contracts") or 0)
                if contracts>0:
                    out.append({
                        "side": p.get("side"), # long/short
                        "contracts": contracts,
                        "entryPrice": float(p.get("entryPrice") or 0),
                        "markPrice": float(p.get("markPrice") or 0),
                        "unrealizedPnl": float(p.get("unrealizedPnl") or 0),
                        "positionIdx": p.get("info",{}).get("positionIdx"),
                    })
            return out
        except Exception as e:
            logger.error(f"fetch_positions: {e}")
            return []

    def calculate_qty(self, symbol, margin_usdt, leverage, price):
        try:
            market=self.exchange.market(symbol)
            notional=margin_usdt*leverage
            raw=notional/price
            # step / min
            prec=market.get("precision",{}).get("amount")
            limits=market.get("limits",{})
            min_amt=float(limits.get("amount",{}).get("min",0.001) or 0.001)
            min_cost=float(limits.get("cost",{}).get("min",5.0) or 5.0)
            qty=float(self.exchange.amount_to_precision(symbol, raw))
            qty=max(qty, min_amt)
            # garante minNotional
            if qty*price < min_cost:
                qty=float(self.exchange.amount_to_precision(symbol, (min_cost*1.05)/price))
            return qty
        except Exception as e:
            logger.error(f"calc_qty: {e}")
            return 0.0

    def place_market_order(self, symbol, side, qty, position_idx, reduce_only=False):
        if qty<=0: return None
        try:
            o=self.exchange.create_order(symbol=symbol,type="market",side=side,amount=qty,
                params={"positionIdx":position_idx,"reduceOnly":reduce_only})
            return o
        except Exception as e:
            logger.error(f"place_order {side} {symbol} qty={qty} idx={position_idx} ro={reduce_only}: {e}")
            return None

    def close_all_positions(self, symbol):
        try:
            positions=self.fetch_positions_live(symbol)
            for pos in positions:
                contracts=pos["contracts"]
                if pos["side"]=="long":
                    self.place_market_order(symbol,"sell",contracts,position_idx=1,reduce_only=True)
                elif pos["side"]=="short":
                    self.place_market_order(symbol,"buy",contracts,position_idx=2,reduce_only=True)
            return True
        except Exception as e:
            logger.error(f"close_all: {e}")
            return False
