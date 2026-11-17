import time
import json
import os


class TradingEngine:
    def __init__(self, config, exchange):
        self.cfg = config
        self.exchange = exchange
        self.position = None
        self.direction = None
        self.entry_price = 0.0
        self.ref_price = 0.0
        self.ref_time = 0.0
        self.cycle = 1
        self.hist_long_pnl = 0.0
        self.hist_short_pnl = 0.0
        self.history = []
        self._load_state()

    def _monitor_position(self, price):
        if not self.position:
            return
        profit = 0.0
        if self.direction == "LONG":
            profit = (price - self.entry_price) * self.position["qty"]
            profit -= self.position["qty"] * price * self.cfg.fee_rate
            if profit >= self.position["target"]:
                self.cfg.cofre += profit
                self.hist_long_pnl += profit
                self._close_cycle(price, profit)
        if self.direction == "SHORT":
            profit = (self.entry_price - price) * self.position["qty"]
            profit -= self.position["qty"] * price * self.cfg.fee_rate
            if profit >= self.position["target"]:
                self.cfg.cofre += profit
                self.hist_short_pnl += profit
                self._close_cycle(price, profit)

    def _close_cycle(self, price, profit):
        self.position = None
        self.direction = None
        self._handle_post_cycle_transition(price)
        self._save_state()

    def _handle_post_cycle_transition(self, price):
        total = self.hist_long_pnl + self.hist_short_pnl
        if self.hist_long_pnl >= self.hist_short_pnl:
            winner = "LONG"
        else:
            winner = "SHORT"
        self.history.append({
            "ciclo": self.cycle,
            "par": self.cfg.selected_pair,
            "total": round(total, 2),
            "long": round(self.hist_long_pnl, 2),
            "short": round(self.hist_short_pnl, 2),
            "vencedor": winner
        })
        self.hist_long_pnl = 0.0
        self.hist_short_pnl = 0.0
        self.cycle += 1
        self.cfg.cycle_initial_equity = self.exchange.get_total_equity()
        self.ref_price = price
        self.ref_time = time.time()
        if self.cfg.auto_mode:
            self.cfg.completed_operations += 1
            if self.cfg.completed_operations >= self.cfg.max_auto_operations:
                self.cfg.is_running = False
                self.cfg.status_message = "Auto concluido"
        self._save_state()

    def _save_state(self, path="state.json"):
        data = {
            "cycle": self.cycle,
            "cofre": self.cfg.cofre,
            "cofre_global": self.cfg.cofre_global,
            "pair_index": self.cfg.pair_index,
            "selected_pair": self.cfg.selected_pair,
            "history": self.history,
            "hist_long": self.hist_long_pnl,
            "hist_short": self.hist_short_pnl
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def _load_state(self, path="state.json"):
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cycle = int(data.get("cycle", 1))
            self.cfg.cofre = float(data.get("cofre", 0.0))
            self.cfg.cofre_global = float(data.get("cofre_global", 0.0))
            self.cfg.pair_index = int(data.get("pair_index", 0))
            self.cfg.selected_pair = data.get("selected_pair", self.cfg.selected_pair)
            self.history = data.get("history", [])
            self.hist_long_pnl = float(data.get("hist_long", 0.0))
            self.hist_short_pnl = float(data.get("hist_short", 0.0))
        except Exception:
            self.history = []
            self.hist_long_pnl = 0.0
            self.hist_short_pnl = 0.0
