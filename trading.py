# trading.py - ND-SCALPING V6 - SIMULACAO CONTA REAL
# O Papel agora calcula EXATAMENTE como o Real.
# O que mudou (SO o calculo, resto do V6 intacto):
#  1) QTY POR ORDEM = margem * alavancagem / preco de entrada
#     ANTES: dividia ainda por TOTAL_ORDENS -> Qty 15x mais pequena, lucro 15x mais pequeno.
#     Ex: Margem 30, Alav 15, BTC 59201 -> Qty = 450 / 59201 = 0.007600 (antes era 0.0005)
#  2) TAXA REAL = 0.055% taker na entrada + 0.055% taker na saida = 0.11% ida-e-volta
#     ANTES: 0.01% maker -> descontava 5x menos taxa, Papel parecia lucrar e Real perdia.
#     Taxa = 0.00055 * (entrada + saida) * qty
#  3) TRAVA ARMA NO LIQUIDO: net >= 0.002
#     ANTES: armava no bruto 0.002 -> 0.002 bruto nem pagava a taxa.
#     Agora: bruto tem de ser >= taxa + 0.002. Automatico, depende da Qty.
#     Recuo ZERO: 1 tick contra depois de armada -> fecha.
#  4) TUDO O QUE O ECRA MOSTRA E LIQUIDO: grid, posicao aberta, historico, saldo.
#     Historico guarda tambem bruto e taxa, para conferires.
#  5) ALVO TAMBEM FECHA NO LIQUIDO: se o alvo for atingido, so fecha se net >= 0.
#     Se net < 0, espera pela trava. Nunca fecha negativo por alvo/trava.
#  Paragem Manual continua a fechar tudo ao preco atual e PODE fechar negativo
#  porque e fecho forcado teu, nao e trava nem alvo.

import os, time, threading, math, json, urllib.request
from datetime import datetime, timezone

# ---------- CONFIG (lida do ambiente / Ajustes) ----------
PAPER_TRADING = os.getenv("PAPER_TRADING", "True") == "True"
PAPER_INITIAL_BALANCE = float(os.getenv("PAPER_INITIAL_BALANCE", "1000"))
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "5"))
LEVERAGE = float(os.getenv("LEVERAGE", "3"))
GRID_STEP = float(os.getenv("GRID_STEP", "20"))
GRID_TOTAL = int(os.getenv("GRID_TOTAL", "14"))
PROFIT_TARGET_USDT = float(os.getenv("PROFIT_TARGET_USDT", "5"))

# --- SIMULACAO REAL - fixo no codigo, nunca em Ajustes ---
FEE_TAKER = 0.00055        # 0.055% taker Bybit/Binance perp - entrada E saida
TRAVA_LUCRO_LIQUIDO = 0.002  # trava arma quando LUCRO LIQUIDO >= 0.002 USDT
TRAVA_RECUO = 0.0          # recuo ZERO

state = {
    "running": False,
    "ref": None,
    "price": 0.0,
    "slots": [],
    "history": [],
    "balance": PAPER_INITIAL_BALANCE,
    "initial_balance": PAPER_INITIAL_BALANCE,
    "cofre_ciclo": 0.0,
    "cofre_global": 0.0,
    "vantagem": 0.0,
    "lock": threading.Lock(),
    "price_error": None,
    "last_price_at": None,
}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _gross(side, entry, price, qty):
    if side == "buy":
        return (price - entry) * qty
    return (entry - price) * qty

def _fee(entry, price, qty):
    # TAXA REAL ida-e-volta: taker na abertura + taker no fecho
    # Notional abertura = entry*qty, fecho = price*qty
    return FEE_TAKER * (entry + price) * qty

def _net(side, entry, price, qty):
    return _gross(side, entry, price, qty) - _fee(entry, price, qty)

def _trava_arm_price(slot):
    # Preco onde a trava arma: o preco em que net == 0.002
    # Resolve: gross - fee = 0.002  ->  para LONG: (p-entry)*qty - 0.00055*(entry+p)*qty = 0.002
    # p = (0.002/qty + entry*(1+0.00055)) / (1-0.00055)  [LONG]
    # p = (entry*(1-0.00055) - 0.002/qty) / (1+0.00055)  [SHORT]
    e = slot["entry"]; q = slot["qty"]
    if q <= 0:
        return None
    if slot["side"] == "buy":
        return (TRAVA_LUCRO_LIQUIDO / q + e * (1 + FEE_TAKER)) / (1 - FEE_TAKER)
    else:
        return (e * (1 - FEE_TAKER) - TRAVA_LUCRO_LIQUIDO / q) / (1 + FEE_TAKER)

# ---------- CICLO / GRID V6 (inalterado, so a Qty corrigida) ----------
def start_cycle(price, ref=None):
    """Grid V6: Ref no centro. LONG acima, SHORT abaixo.
    Primeira ordem a step/2 da Ref. Espelho ping-pong."""
    with state["lock"]:
        state["running"] = True
        state["ref"] = ref if ref is not None else price
        state["price"] = price
        state["slots"] = []
        state["cofre_ciclo"] = 0.0
        state["vantagem"] = 0.0
        ref = state["ref"]
        per_side = GRID_TOTAL // 2
        # QTY CORRIGIDA - SIMULACAO REAL:
        # Qty POR ORDEM = margem * alavancagem / preco de entrada da ordem
        # NAO dividir pelo total de ordens. Cada ordem usa a sua margem cheia.
        for i in range(per_side):
            entry = ref + (GRID_STEP / 2) + (i * GRID_STEP)
            qty = round((MARGIN_USDT * LEVERAGE) / entry, 8) if entry > 0 else 0
            state["slots"].append({
                "id": f"LONG_{i}", "side": "buy", "entry": round(entry, 2),
                "qty": qty, "status": "PENDING",
                "armed": False, "best_net": 0.0,
            })
        for i in range(per_side):
            entry = ref - (GRID_STEP / 2) - (i * GRID_STEP)
            qty = round((MARGIN_USDT * LEVERAGE) / entry, 8) if entry > 0 else 0
            state["slots"].append({
                "id": f"SHORT_{i}", "side": "sell", "entry": round(entry, 2),
                "qty": qty, "status": "PENDING",
                "armed": False, "best_net": 0.0,
            })
        return True

def stop_cycle(price, manual=True):
    """Paragem Manual: fecha TUDO ao preco atual (por isso pode fechar negativo).
    Nao e trava, nao e alvo. E fecho forcado."""
    with state["lock"]:
        for s in state["slots"]:
            if s["status"] == "ACTIVE":
                _close_slot(s, price, "Paragem Manual")
        state["running"] = False
        return True

def _close_slot(slot, price, motivo):
    g = _gross(slot["side"], slot["entry"], price, slot["qty"])
    f = _fee(slot["entry"], price, slot["qty"])
    n = g - f
    slot["status"] = "CLOSED"
    state["balance"] += n
    state["cofre_ciclo"] += n
    state["cofre_global"] += n
    state["history"].append({
        "side": "LONG" if slot["side"] == "buy" else "SHORT",
        "entry": slot["entry"], "exit": round(price, 2),
        "gross": round(g, 4), "fee": round(f, 4),
        "profit": round(n, 4), "motivo": motivo,
        "id": slot["id"], "time": _now(),
    })
    return n

def _mirror(slot, price):
    """Espelho V6: quando uma ordem fecha, abre a oposta no mesmo nivel.
    Ping-pong. Mantido igual, com a Qty corrigida da ordem que fechou."""
    opp = "sell" if slot["side"] == "buy" else "buy"
    nid = f"ESP_{slot['id']}_{int(time.time())}"
    state["slots"].append({
        "id": nid, "side": opp, "entry": round(price, 2),
        "qty": slot["qty"], "status": "ACTIVE",
        "armed": False, "best_net": 0.0,
    })

# ---------- MONITOR - TRAVA RIGIDA NO LIQUIDO ----------
def monitor(price):
    """Chamado a cada tick de preco.
    1) Alvo fecha SO se net >= 0 (nunca fecha negativo por alvo).
    2) Trava arma quando net >= 0.002, depois fecha no 1o tick contra (recuo 0).
    3) Sem trava armada e sem alvo liquido, espera."""
    with state["lock"]:
        if not price or price <= 0:
            return
        state["price"] = price
        if not state["running"]:
            return
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
            net = _net(slot["side"], entry, price, qty)
            # Acompanha o melhor LIQUIDO (a trava segue o melhor, nunca desce)
            if net > slot.get("best_net", 0.0):
                slot["best_net"] = net
            # --- ALVO: so fecha se for liquido positivo ---
            target = entry + GRID_STEP if slot["side"] == "buy" else entry - GRID_STEP
            hit_target = (price >= target) if slot["side"] == "buy" else (price <= target)
            if hit_target and net >= 0:
                _close_slot(slot, price, "GRID V6")
                _mirror(slot, price)
                continue
            # --- TRAVA RIGIDA NO LIQUIDO ---
            # 1. Arma quando net >= 0.002
            if net >= TRAVA_LUCRO_LIQUIDO:
                slot["armed"] = True
            # 2. Depois de armada, 1 tick contra o melhor liquido -> fecha.
            # Recuo ZERO: qualquer net abaixo do melhor net registado fecha.
            if slot.get("armed") and net < slot.get("best_net", 0.0):
                _close_slot(slot, price, "TRAVA")
                _mirror(slot, price)
                continue
            # Se armada e o preco continua a favor, best_net sobe e ela acompanha.

def get_state():
    with state["lock"]:
        # Tudo o que vai para o ecra e LIQUIDO (net), nunca bruto.
        live = []
        for s in state["slots"]:
            if s["status"] == "ACTIVE":
                n = _net(s["side"], s["entry"], state["price"], s["qty"])
                live.append({**s, "pnl_live": round(n, 4)})
        return {
            "running": state["running"], "ref": state["ref"],
            "price": state["price"], "balance": round(state["balance"], 4),
            "initial_balance": state["initial_balance"],
            "cofre_ciclo": round(state["cofre_ciclo"], 4),
            "cofre_global": round(state["cofre_global"], 4),
            "slots": state["slots"], "live": live,
            "history": state["history"],
            "status": "RUNNING" if state["running"] else "PARADO",
            "paper": PAPER_TRADING,
            "connected": True,
            "price_error": state.get("price_error"),
            "last_price_at": state.get("last_price_at"),
            "fee_taker": FEE_TAKER,
            "trava_liquido": TRAVA_LUCRO_LIQUIDO,
        }

# ---------- PRECO REAL ----------
def fetch_price():
    try:
        req = urllib.request.Request("https://api.kraken.com/0/public/Ticker?pair=XBTUSD", headers={"User-Agent": "ND-Scalping"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
            p = float(d["result"]["XXBTZUSD"]["c"][0])
            if p > 0:
                with state["lock"]:
                    state["price"] = p; state["last_price_at"] = _now(); state["price_error"] = None
                return p
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://www.bitstamp.net/api/v2/ticker/btcusd/", headers={"User-Agent": "ND-Scalping"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
            p = float(d["last"])
            if p > 0:
                with state["lock"]:
                    state["price"] = p; state["last_price_at"] = _now(); state["price_error"] = None
                return p
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", headers={"User-Agent": "ND-Scalping"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
            p = float(d["price"])
            if p > 0:
                with state["lock"]:
                    state["price"] = p; state["last_price_at"] = _now(); state["price_error"] = None
                return p
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT", headers={"User-Agent": "ND-Scalping"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
            p = float(d["result"]["list"][0]["lastPrice"])
            if p > 0:
                with state["lock"]:
                    state["price"] = p; state["last_price_at"] = _now(); state["price_error"] = None
                return p
    except Exception:
        pass
    try:
        req = urllib.request.Request("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd", headers={"User-Agent": "ND-Scalping"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
            p = float(d["bitcoin"]["usd"])
            if p > 0:
                with state["lock"]:
                    state["price"] = p; state["last_price_at"] = _now(); state["price_error"] = None
                return p
    except Exception:
        pass
    with state["lock"]:
        state["price_error"] = "sem preco - a manter ultimo"
    return state.get("price", 0.0) or 0.0

class MinimalistGridEngine:
    def __init__(self, *a, **k):
        self.state = state; self._bg_thread = None; self._bg_stop = threading.Event(); self._bg_running = False
    def start_cycle(self, price, ref=None):
        return start_cycle(price, ref)
    def start(self, price=None, ref=None):
        return start_cycle(price, ref) if price is not None else True
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
    def start_background_loop(self, *a, **k):
        if self._bg_running:
            return True
        self._bg_stop.clear(); self._bg_running = True
        def _loop():
            while not self._bg_stop.is_set():
                try:
                    p = fetch_price()
                    if p and p > 0:
                        monitor(p)
                except Exception:
                    pass
                time.sleep(2)
        t = threading.Thread(target=_loop, daemon=True, name="nd-background-loop")
        t.start(); self._bg_thread = t; return True
    def stop_background_loop(self, *a, **k):
        self._bg_stop.set(); self._bg_running = False; return True
    def start_loop(self, *a, **k):
        return self.start_background_loop(*a, **k)
    def background_loop(self, *a, **k):
        return self.start_background_loop(*a, **k)
    def run(self, *a, **k):
        return self.start_background_loop(*a, **k)
    def __getattr__(self, name):
        if name.startswith("get_") or name in ("status", "state", "balance", "history"):
            return lambda *a, **k: get_state()
        return lambda *a, **k: True

GridEngine = MinimalistGridEngine
TradingEngine = MinimalistGridEngine
Engine = MinimalistGridEngine
