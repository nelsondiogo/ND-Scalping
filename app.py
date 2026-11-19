# ND-SCALPING V6 Final — Trava corrigida
# Regra da trava (so no codigo-fonte, nunca em Ajustes):
#   - Arma SOMENTE quando o lucro LIQUIDO (bruto - taxas ida e volta) >= 0.001 USDT
#   - Recuo = 1.5% do melhor lucro liquido atingido (best_net)
#   - Nunca armada = nunca fecha por trava
#   - Apos armada, fecha quando lucro liquido cair 1.5% abaixo do best_net
# Isto acaba com "armou positiva, fechou negativa": a trava so tranca lucro real.

import os, time, threading, json
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string
import ccxt

app = Flask(__name__)

# ---------------- CONFIG ----------------
SYMBOL = os.environ.get("SYMBOL", "BTC/USDT:USDT")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "True") == "True"
PAPER_INITIAL_BALANCE = float(os.environ.get("PAPER_INITIAL_BALANCE", "1000.0"))
MARGIN_PER_ORDER = float(os.environ.get("MARGIN_PER_ORDER", "5.0"))
LEVERAGE = int(os.environ.get("LEVERAGE", "3"))
STEP = float(os.environ.get("STEP", "40.0"))          # passo em preco (BTC 40)
TOTAL_ORDERS = int(os.environ.get("TOTAL_ORDERS", "14"))  # 7 LONG + 7 SHORT
PROFIT_PER_OPERATION = float(os.environ.get("PROFIT_PER_OPERATION", "0.05"))  # USDT
MODE = os.environ.get("MODE", "MANUAL")  # MANUAL | AUTO
OPS_PER_DAY = int(os.environ.get("OPS_PER_DAY", "0"))  # 0 = sem limite

# Trava de seguranca — FIXA no codigo
TRAVA_ARM_NET = 0.001      # arma quando lucro liquido >= 0.001 USDT
TRAVA_RECUO_FRAC = 0.015   # recuo de 1.5% do melhor lucro liquido
FEE_RATE = 0.0001          # maker Bybit (papel)

# ---------------- ESTADO ----------------
state = {
    "balance": PAPER_INITIAL_BALANCE,
    "initial": PAPER_INITIAL_BALANCE,
    "ref": None,
    "price": None,
    "direction": "ESTAVEL",
    "orders": [],       # grid + espelhos
    "history": [],      # ordens fechadas
    "cofre_ciclo": 0.0,
    "cofre_global": 0.0,
    "operation_profit": 0.0,
    "operation_active": True,
    "ops_today": 0,
    "updated": "",
}
lock = threading.Lock()

exchange = None
if not PAPER_TRADING:
    exchange = ccxt.bybit({
        "apiKey": os.environ.get("BYBIT_API_KEY", ""),
        "secret": os.environ.get("BYBIT_API_SECRET", ""),
        "options": {"defaultType": "linear"},
    })
    exchange.set_leverage(LEVERAGE, SYMBOL)
else:
    exchange = ccxt.bybit({"options": {"defaultType": "linear"}})

# ---------------- HELPERS ----------------
def fee_roundtrip(open_price, close_price, qty):
    return FEE_RATE * (open_price + close_price) * qty

def net_profit(o, price):
    """Lucro liquido da ordem aberta o ao preco atual."""
    if o["side"] == "LONG":
        gross = (price - o["open_price"]) * o["qty"]
    else:
        gross = (o["open_price"] - price) * o["qty"]
    return gross - fee_roundtrip(o["open_price"], price, o["qty"])

def get_price():
    try:
        t = exchange.fetch_ticker(SYMBOL)
        return float(t["last"])
    except Exception:
        return state["price"]

def build_grid(ref):
    """Grid: Ref no centro. LONG acima, SHORT abaixo. 1a ordem a step/2."""
    orders = []
    half = TOTAL_ORDERS // 2
    for i in range(1, half + 1):
        entry_long = ref + STEP / 2 + (i - 1) * STEP
        entry_short = ref - STEP / 2 - (i - 1) * STEP
        qty = MARGIN_PER_ORDER * LEVERAGE / entry_long
        orders.append({"id": f"LONG_{i}", "side": "LONG", "entry": entry_long,
                       "target": entry_long + STEP, "qty": qty,
                       "status": "PENDING", "open_price": None,
                       "best_net": None, "armed": False})
        qty_s = MARGIN_PER_ORDER * LEVERAGE / entry_short
        orders.append({"id": f"SHORT_{i}", "side": "SHORT", "entry": entry_short,
                       "target": entry_short - STEP, "qty": qty_s,
                       "status": "PENDING", "open_price": None,
                       "best_net": None, "armed": False})
    return orders

def close_order(o, price, reason):
    """Fecha ordem, regista lucro LIQUIDO no historico e cria espelho."""
    gross = (price - o["open_price"]) * o["qty"] if o["side"] == "LONG" else (o["open_price"] - price) * o["qty"]
    fee = fee_roundtrip(o["open_price"], price, o["qty"])
    net = gross - fee
    with lock:
        state["balance"] += net
        state["cofre_ciclo"] += net
        state["operation_profit"] += net
        state["history"].insert(0, {
            "id": o["id"], "side": o["side"],
            "open": o["open_price"], "close": price,
            "profit": round(net, 6), "reason": reason,
            "time": datetime.now().strftime("%H:%M:%S"),
        })
        o["status"] = "CLOSED"
    # Espelho: fechar cria ordem oposta a um passo de distancia
    mirror_side = "SHORT" if o["side"] == "LONG" else "LONG"
    mirror_entry = price - STEP if mirror_side == "SHORT" else price + STEP
    mirror_target = mirror_entry - STEP if mirror_side == "SHORT" else mirror_entry + STEP
    qty = MARGIN_PER_ORDER * LEVERAGE / mirror_entry
    with lock:
        state["orders"].append({
            "id": f"ESP_{mirror_side}_{int(price)}", "side": mirror_side,
            "entry": mirror_entry, "target": mirror_target, "qty": qty,
            "status": "PENDING", "open_price": None,
            "best_net": None, "armed": False,
        })

# ---------------- LOOP PRINCIPAL ----------------
def loop():
    while True:
        try:
            price = get_price()
            if price is None:
                time.sleep(2); continue
            with lock:
                prev = state["price"]
                state["price"] = price
                state["direction"] = "A SUBIR" if prev and price > prev else ("A DESCER" if prev and price < prev else "ESTAVEL")
                state["updated"] = datetime.now().strftime("%H:%M:%S")
                if state["ref"] is None:
                    state["ref"] = price
                    state["orders"] = build_grid(price)
            # Ativar PENDING -> ACTIVE
            for o in list(state["orders"]):
                if o["status"] == "PENDING":
                    hit = (price >= o["entry"]) if o["side"] == "LONG" else (price <= o["entry"])
                    if hit:
                        with lock:
                            o["status"] = "ACTIVE"; o["open_price"] = price; o["best_net"] = None; o["armed"] = False
            # Monitorizar ACTIVE: alvo ou trava
            for o in list(state["orders"]):
                if o["status"] != "ACTIVE":
                    continue
                np = net_profit(o, price)
                # --- TRAVA CORRIGIDA ---
                # 1) Arma SOMENTE com lucro liquido >= 0.001 (nunca no bruto!)
                if not o["armed"] and np >= TRAVA_ARM_NET:
                    o["armed"] = True
                    o["best_net"] = np
                # 2) Depois de armada, segue o melhor lucro liquido
                if o["armed"]:
                    if np > o["best_net"]:
                        o["best_net"] = np
                    # 3) Fecha quando cair 1.5% abaixo do melhor lucro
                    if np <= o["best_net"] * (1 - TRAVA_RECUO_FRAC):
                        close_order(o, price, "TRAVA")
                        continue
                # Alvo do grid
                hit_target = (price >= o["target"]) if o["side"] == "LONG" else (price <= o["target"])
                if hit_target:
                    close_order(o, price, "ALVO")
            # Vantagem: fechar tudo e terminar operacao
            with lock:
                if state["operation_active"] and state["operation_profit"] >= PROFIT_PER_OPERATION:
                    for o in list(state["orders"]):
                        if o["status"] == "ACTIVE":
                            close_order(o, price, "VANTAGEM")
                    state["operation_profit"] = 0.0
                    state["cofre_global"] += state["cofre_ciclo"]
                    state["cofre_ciclo"] = 0.0
                    state["ops_today"] += 1
                    if MODE == "AUTO" and (OPS_PER_DAY == 0 or state["ops_today"] < OPS_PER_DAY):
                        state["ref"] = price
                        state["orders"] = build_grid(price)
                        state["operation_active"] = True
                    else:
                        state["operation_active"] = False
            time.sleep(2)
        except Exception as e:
            print("loop erro:", e); time.sleep(3)

threading.Thread(target=loop, daemon=True).start()

# ---------------- ROTAS ----------------
@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/")
def index():
    with lock:
        s = json.loads(json.dumps(state))
    return render_template_string("""
    <h1>ND-SCALPING {{ 'PAPEL' if True else 'REAL' }}</h1>
    <p>Preco: {{ s.price }} | Ref: {{ s.ref }} | Saldo: {{ s.balance }}</p>
    <p>Lucro operacao: {{ s.operation_profit }} | Cofre ciclo: {{ s.cofre_ciclo }}</p>
    <h2>Ordens</h2>
    {% for o in s.orders %}<p>{{ o.id }} {{ o.side }} {{ o.status }} entrada {{ o.entry }} alvo {{ o.target }}{% if o.armed %} TRAVA ARMADA best_net {{ o.best_net }}{% endif %}</p>{% endfor %}
    <h2>Historico</h2>
    {% for h in s.history %}<p>{{ h.id }} {{ h.side }} {{ h.open }} -> {{ h.close }} {{ h.profit }} {{ h.reason }}</p>{% endfor %}
    """, s=s)

@app.route("/api/state")
def api_state():
    with lock:
        return jsonify(state)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
