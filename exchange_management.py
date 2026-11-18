import ccxt, logging
logger = logging.getLogger("ND-Exchange")
class BybitExchangeManager:
    def __init__(self, config):
        self.cfg = config
        self.exchange = self._init_exchange()
        self.public = self._init_public()
    def _init_exchange(self):
        ex = ccxt.bybit({"apiKey": self.cfg.api_key, "secret": self.cfg.api_secret, "enableRateLimit": True, "options": {"defaultType":"swap","adjustForTimeDifference":True}})
        if self.cfg.testnet:
            ex.set_sandbox_mode(True)
        try: ex.load_markets()
        except Exception as e: logger.warning(f"load_markets auth: {e}")
        return ex
    def _init_public(self):
        # Publico, SEM API - serve para Papel mesmo que a API esteja bloqueada
        try:
            ex = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType":"swap"}})
            ex.load_markets()
            return ex
        except Exception as e:
            logger.warning(f"public init: {e}")
            return self.exchange
    def get_total_equity(self):
        try:
            b=self.exchange.fetch_balance(params={"type":"UNIFIED"})
            info=b.get("info",{}); lst=info.get("result",{}).get("list",[])
            if lst and "totalEquity" in lst[0]:
                return float(lst[0]["totalEquity"])
            return float(b.get("USDT",{}).get("total",0.0))
        except Exception as e:
            logger.error(f"get_total_equity: {e}")
            return -1.0
    def set_hedge_mode_and_leverage(self, symbol, leverage):
        try: self.exchange.set_position_mode(hedged=True, symbol=symbol)
        except Exception as e: logger.debug(f"position_mode: {e}")
        try: self.exchange.set_leverage(leverage, symbol)
        except Exception as e: logger.debug(f"leverage: {e}")
    def fetch_ticker(self, symbol):
        # Em Papel: tenta publico primeiro, sem API. Se falhar, tenta autenticado.
        if getattr(self.cfg,"paper_trading",False):
            try: return self.public.fetch_ticker(symbol)
            except Exception as e: logger.warning(f"ticker publico falhou, tenta auth: {e}")
        return self.exchange.fetch_ticker(symbol)
    def fetch_positions_live(self, symbol):
        try:
            pos=self.exchange.fetch_positions([symbol])
            out=[]
            for p in pos:
                contracts=float(p.get("contracts") or 0)
                if contracts>0:
                    out.append({"side": p.get("side"),"contracts": contracts,"entryPrice": float(p.get("entryPrice") or 0),"markPrice": float(p.get("markPrice") or 0),"unrealizedPnl": float(p.get("unrealizedPnl") or 0),"positionIdx": p.get("info",{}).get("positionIdx")})
            return out
        except Exception as e:
            logger.error(f"fetch_positions: {e}")
            return []
    def calculate_qty(self, symbol, margin_usdt, leverage, price):
        # V5: nunca devolve 0. Fallback matematico se mercado falhar.
        try:
            market=self.exchange.market(symbol)
            notional=margin_usdt*leverage
            raw=notional/price if price>0 else 0
            limits=market.get("limits",{})
            min_amt=float(limits.get("amount",{}).get("min",0.001) or 0.001)
            min_cost=float(limits.get("cost",{}).get("min",5.0) or 5.0)
            try: qty=float(self.exchange.amount_to_precision(symbol, raw))
            except Exception: qty=round(raw,6)
            if qty<=0: qty=round(raw,6)
            if qty<=0: qty=min_amt
            qty=max(qty, min_amt)
            if qty*price < min_cost:
                need=(min_cost*1.05)/price
                try: qty=float(self.exchange.amount_to_precision(symbol, need))
                except Exception: qty=round(need,6)
                if qty<=0: qty=round(need,6)
                qty=max(qty, min_amt)
            return qty
        except Exception as e:
            logger.error(f"calc_qty fallback: {e}")
            raw=(margin_usdt*leverage)/price if price>0 else 0.001
            return round(raw,6) if raw>0 else 0.001
    def place_market_order(self, symbol, side, qty, position_idx, reduce_only=False):
        if qty<=0: return None
        try:
            o=self.exchange.create_order(symbol=symbol,type="market",side=side,amount=qty, params={"positionIdx":position_idx,"reduceOnly":reduce_only})
            return o
        except Exception as e:
            logger.error(f"place_order {side} {symbol} qty={qty}: {e}")
            return None
    def close_all_positions(self, symbol):
        try:
            positions=self.fetch_positions_live(symbol)
            for pos in positions:
                contracts=pos["contracts"]
                if pos["side"]=="long": self.place_market_order(symbol,"sell",contracts,position_idx=1,reduce_only=True)
                elif pos["side"]=="short": self.place_market_order(symbol,"buy",contracts,position_idx=2,reduce_only=True)
            return True
        except Exception as e:
            logger.error(f"close_all: {e}")
            return False
