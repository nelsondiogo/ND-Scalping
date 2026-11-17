import ccxt


class BybitExchangeManager:
    def __init__(self, config):
        self.cfg = config
        self.exchange = None
        self._init_exchange()

    def _init_exchange(self):
        self.exchange = ccxt.bybit({
            "apiKey": self.cfg.api_key,
            "secret": self.cfg.api_secret,
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        })
        self.exchange.set_sandbox_mode(self.cfg.testnet)

    def get_total_equity(self):
        try:
            balance = self.exchange.fetch_balance()
            total = balance.get("total", {})
            return float(total.get("USDT", 0.0))
        except Exception:
            return 0.0

    def set_hedge_mode_and_leverage(self, symbol):
        try:
            self.exchange.set_position_mode(True, symbol)
        except Exception:
            pass
        try:
            self.exchange.set_leverage(self.cfg.leverage, symbol)
        except Exception:
            pass

    def fetch_ticker(self, symbol):
        return self.exchange.fetch_ticker(symbol)

    def fetch_positions_live(self):
        try:
            return self.exchange.fetch_positions()
        except Exception:
            return []

    def calculate_qty(self, symbol, price, margin=None, leverage=None):
        if margin is None:
            margin = self.cfg.margin_per_order
        if leverage is None:
            leverage = self.cfg.leverage
        try:
            if not price or price <= 0:
                return 0.001
            raw = (margin * leverage) / price
            qty = round(raw, 6)
            if qty <= 0:
                qty = round(raw, 6)
            if qty <= 0:
                qty = 0.001
            market = self.exchange.market(symbol)
            min_cost = 0.0
            limits = market.get("limits", {}) if market else {}
            cost_limits = limits.get("cost", {}) if limits else {}
            if cost_limits.get("min") is not None:
                min_cost = float(cost_limits.get("min"))
            if min_cost > 0 and qty * price < min_cost:
                qty = round((min_cost / price) + 0.001, 6)
            if qty <= 0:
                qty = round((margin * leverage) / price, 6)
            return qty
        except Exception:
            return round((margin * leverage) / price, 6)

    def place_market_order(self, symbol, side, qty, position_side):
        params = {"positionIdx": 1 if position_side == "Buy" else 2}
        return self.exchange.create_market_order(symbol, side, qty, None, params)

    def close_all_positions(self):
        positions = self.fetch_positions_live()
        closed = []
        for pos in positions:
            contracts = float(pos.get("contracts", 0) or 0)
            if contracts == 0:
                continue
            symbol = pos.get("symbol")
            side = "sell" if pos.get("side") == "long" else "buy"
            position_side = "Buy" if pos.get("side") == "long" else "Sell"
            closed.append(self.place_market_order(symbol, side, contracts, position_side))
        return closed
