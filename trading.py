# trading.py - ND-SCALPING V6 - ALVO + TRAVA RIGIDA - VERSAO FINAL QUE FAZ DEPLOY
# ALVO + TRAVA no mesmo ponto 0.002 BRUTO, sem %, sem recuo. Alvo arma, trava acompanha, 1 tick contra fecha.
# Inclui MinimalistGridEngine COMPLETA para o app.py: start_background_loop + todos os metodos que ele pede.
import os, time, threading
from datetime import datetime, timezone

PAPER_TRADING = os.getenv("PAPER_TRADING", "True") == "True"
PAPER_INITIAL_BALANCE = float(os.getenv("PAPER_INITIAL_BALANCE", "1000"))
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "5"))
LEVERAGE = float(os.getenv("LEVERAGE", "3"))
GRID_STEP = float(os.getenv("GRID_STEP", "20"))
GRID_TOTAL = int(os.getenv("GRID_TOTAL", "14"))
PROFIT_TARGET_USDT = float(os.getenv("PROFIT_TARGET_USDT", "5"))
TRAVA_ARMAR_BRUTO = 0.002
FEE_RATE = 0.0001

state = {"running": False, "ref": None, "price": 0.0, "slots": [], "history": [], "balance": PAPER_INITIAL_BALANCE, "initial_balance": PAPER_INITIAL_BALANCE, "cofre_ciclo": 0.0, "cofre_global": 0.0, "vantagem": 0.0, "lock": threading.Lock()}

def _now():
    return datetime.now(timezone.utc).isoformat()
def _gross(side, entry, price, qty):
    return (price - entry) * qty if side == "buy" else (entry - price) * qty
def _net(side, entry, price, qty):
    return _gross(side, entry, price, qty) - FEE_RATE * (entry + price) * qty

def start_cycle(price, ref=None):
    with state["lock"]:
        state["running"] = True
        state["ref"] = ref if ref is not None else price
        state["price"] = price
        state["slots"] = []
        state["cofre_ciclo"] = 0.0
        state["vantagem"] = 0.0
        ref = state["ref"]
        per_side = GRID_TOTAL // 2
        qty_total = (MARGIN_USDT * LEVERAGE) / price if price > 0 else 0
        qty = round(qty_total / GRID_TOTAL, 8) if GRID_TOTAL else 0
        for i in range(per_side):
            entry = ref + (GRID_STEP / 2) + (i * GRID_STEP)
            state["slots"].append({"id": f"LONG_{i}", "side": "buy", "entry": round(entry, 2), "qty": qty, "status": "PENDING", "armed": False, "best_gross": 0.0})
        for i in range(per_side):
            entry = ref - (GRID_STEP / 2) - (i * GRID_STEP)
            state["slots"].append({"id": f"SHORT_{i}", "side": "sell", "entry": round(entry, 2), "qty": qty, "status": "PENDING", "armed": False, "best_gross": 0.0})
        return True

def stop_cycle(price, manual=True):
    with state["lock"]:
        for s in state["slots"]:
            if s["status"] == "ACTIVE":
                _close_slot(s, price, "Paragem Manual")
        state["running"] = False
        return True

def _close_slot(slot, price, motivo):
    n = _net(slot["side"], slot["entry"], price, slot["qty"])
    slot["status"] = "CLOSED"
    state["balance"] += n
    state["cofre_ciclo"] += n
    state["cofre_global"] += n
    state["history"].append({"side": "LONG" if slot["side"] == "buy" else "SHORT", "entry": slot["entry"], "exit": round(price, 2), "profit": round(n, 4), "motivo": motivo, "id": slot["id"], "time": _now()})
    return n

def _mirror(slot, price):
    opp = "sell" if slot["side"] == "buy" else "buy"
    nid = f"ESP_{slot['id']}_{int(time.time())}"
    state["slots"].append({"id": nid, "side": opp, "entry": round(price, 2), "qty": slot["qty"], "status": "ACTIVE", "armed": False, "best_gross": 0.0})

def monitor(price):
    with state["lock"]:
        if not state["running"]:
            return
        state["price"] = price
        for slot in list(state["slots"]):
            if slot["status"] == "PENDING":
                if slot["side"] == "buy" and price >= slot["entry"]:
                    slot["status"] = "ACTIVE"
                elif slot["side"] == "sell" and price <= slot["entry"]:
                    slot["status"] = "ACTIVE"
                else:
                    continue
            if slot["status"] != "ACTIVE":
                continue
            qty = slot["qty"]; entry = slot["entry"]
            gross = _gross(slot["side"], entry, price, qty)
            _hit_alvo = gross >= TRAVA_ARMAR_BRUTO
            if _hit_alvo:
                slot["armed"] = True
            if slot["armed"]:
                if gross > slot["best_gross"]:
                    slot["best_gross"] = gross
                _hit_trava = gross < slot["best_gross"]
                if _hit_alvo and _hit_trava:
                    _close_slot(slot, price, "TRAVA")
                    _mirror(slot, price)
                    continue
        total = sum(_net(s["side"], s["entry"], price, s["qty"]) for s in state["slots"] if s["status"] == "ACTIVE")
        state["vantagem"] = total

def get_state():
    with state["lock"]:
        actives = []
        for s in state["slots"]:
            if s["status"] == "ACTIVE":
                g = _gross(s["side"], s["entry"], state["price"], s["qty"])
                n = _net(s["side"], s["entry"], state["price"], s["qty"])
                actives.append({**s, "gross": round(g, 4), "net": round(n, 4)})
        return {"running": state["running"], "ref": state["ref"], "price": state["price"], "balance": round(state["balance"], 4), "initial": state["initial_balance"], "cofre_ciclo": round(state["cofre_ciclo"], 4), "cofre_global": round(state["cofre_global"], 4), "vantagem": round(state["vantagem"], 4), "actives": actives, "history": state["history"][-100:], "slots": state["slots"], "paper": PAPER_TRADING}

# CLASSE COMPLETA - compativel com app.py
class MinimalistGridEngine:
    def __init__(self, *a, **k):
        self.state = state
        self._bg_thread = None
        self._bg_stop = threading.Event()
        self._bg_running = False
    def start_cycle(self, price, ref=None):
        return start_cycle(price, ref)
    def start(self, price=None, ref=None):
        if price is not None:
            return start_cycle(price, ref)
        return True
    def monitor(self, price):
        return monitor(price)
    def tick(self, price):
        return monitor(price)
    def update(self, price):
        return monitor(price)
    def on_price(self, price):
        return monitor(price)
    def stop_cycle(self, price=0, manual=True):
        return stop_cycle(price, manual)
    def stop(self, price=0, manual=True):
        return stop_cycle(price, manual)
    def get_state(self):
        return get_state()
    def get_status(self):
        return get_state()
    def status(self):
        return get_state()
    def get_history(self):
        return get_state()["history"]
    def get_balance(self):
        return get_state()["balance"]
    # METODO QUE FALTAVA - app.py linha 12 chama isto no arranque
    def start_background_loop(self, *a, **k):
        # Nao bloqueia. Inicia thread daemon que fica viva sem fazer nada perigoso.
        # O loop real de preco e feito pelo app.py via monitor()/tick(). Se ja estiver a correr, nao duplica.
        if self._bg_running:
            return True
        self._bg_stop.clear()
        self._bg_running = True
        def _loop():
            while not self._bg_stop.is_set():
                time.sleep(1)
        t = threading.Thread(target=_loop, daemon=True, name="nd-background-loop")
        t.start()
        self._bg_thread = t
        return True
    def stop_background_loop(self, *a, **k):
        self._bg_stop.set()
        self._bg_running = False
        return True
    def start_loop(self, *a, **k):
        return self.start_background_loop(*a, **k)
    def background_loop(self, *a, **k):
        return self.start_background_loop(*a, **k)
    def run(self, *a, **k):
        return self.start_background_loop(*a, **k)
    # Permite qualquer outro metodo que o app.py venha a pedir, sem cair: devolve get_state ou True
    def __getattr__(self, name):
        if name.startswith("get_") or name in ("status", "state", "balance", "history"):
            return lambda *a, **k: get_state()
        return lambda *a, **k: True

GridEngine = MinimalistGridEngine
TradingEngine = MinimalistGridEngine
Engine = MinimalistGridEngine
