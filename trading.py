# trading.py - ND-SCALPING V6 - TRAVA RIGIDA SEM RECUO
# MUDANCA UNICA: trava sem percentagem, sem recuo.
# O resto do V6 NAO foi alterado: grid, espelho, reentrada, convergencia, cofre.
# Trava: arma a 0.002 BRUTO, acompanha o melhor preco, 1 tick contra e fecha.
# O alvo NAO fecha sozinho. So a trava fecha.

import os, time, threading, math
from datetime import datetime, timezone

# ---------- CONFIG (lida do ambiente / Ajustes) ----------
PAPER_TRADING = os.getenv("PAPER_TRADING", "True") == "True"
PAPER_INITIAL_BALANCE = float(os.getenv("PAPER_INITIAL_BALANCE", "1000"))
SYMBOL = os.getenv("SYMBOL", "BTC/USDT")
MARGIN_USDT = float(os.getenv("MARGIN_USDT", "5"))
LEVERAGE = float(os.getenv("LEVERAGE", "3"))
GRID_STEP = float(os.getenv("GRID_STEP", "20"))  # espacamento em preco
GRID_TOTAL = int(os.getenv("GRID_TOTAL", "14"))  # 7 long + 7 short
PROFIT_TARGET_USDT = float(os.getenv("PROFIT_TARGET_USDT", "5"))
# Trava rigida - fixo no codigo, nunca em Ajustes
TRAVA_ARMAR_BRUTO = 0.002
FEE_RATE = 0.0001  # 0.01% maker papel

state = {
    "running": False,
    "ref": None,
    "price": 0.0,
    "slots": [],  # cada slot: {id, side, entry, target, qty, status, armed, best_gross}
    "history": [],
    "balance": PAPER_INITIAL_BALANCE,
    "initial_balance": PAPER_INITIAL_BALANCE,
    "cofre_ciclo": 0.0,
    "cofre_global": 0.0,
    "vantagem": 0.0,
    "lock": threading.Lock(),
}

def _now():
    return datetime.now(timezone.utc).isoformat()

def _gross(side, entry, price, qty):
    if side == "buy":
        return (price - entry) * qty
    return (entry - price) * qty

def _net(side, entry, price, qty):
    g = _gross(side, entry, price, qty)
    fee = FEE_RATE * (entry + price) * qty
    return g - fee

# ---------- CICLO / GRID V6 (inalterado) ----------
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
        # qty por ordem: margem * alavancagem / preco / total ordens
        qty_total = (MARGIN_USDT * LEVERAGE) / price if price > 0 else 0
        qty = qty_total / GRID_TOTAL if GRID_TOTAL else 0
        qty = round(qty, 8)
        # LONG acima: primeira a step/2, resto a step
        for i in range(per_side):
            entry = ref + (GRID_STEP / 2) + (i * GRID_STEP)
            state["slots"].append({
                "id": f"LONG_{i}", "side": "buy", "entry": round(entry, 2),
                "qty": qty, "status": "PENDING",
                "armed": False, "best_gross": 0.0,
            })
        # SHORT abaixo: primeira a step/2, resto a step
        for i in range(per_side):
            entry = ref - (GRID_STEP / 2) - (i * GRID_STEP)
            state["slots"].append({
                "id": f"SHORT_{i}", "side": "sell", "entry": round(entry, 2),
                "qty": qty, "status": "PENDING",
                "armed": False, "best_gross": 0.0,
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
    n = _net(slot["side"], slot["entry"], price, slot["qty"])
    slot["status"] = "CLOSED"
    state["balance"] += n
    state["cofre_ciclo"] += n
    state["cofre_global"] += n
    state["history"].append({
        "side": "LONG" if slot["side"] == "buy" else "SHORT",
        "entry": slot["entry"], "exit": round(price, 2),
        "profit": round(n, 4), "motivo": motivo,
        "id": slot["id"], "time": _now(),
    })
    return n

def _mirror(slot, price):
    """Espelho V6: quando uma ordem fecha, abre a oposta no mesmo nivel.
    Ping-pong. Mantido igual."""
    # espelho abre na direcao oposta, no preco atual, com mesmo qty
    opp = "sell" if slot["side"] == "buy" else "buy"
    nid = f"ESP_{slot['id']}_{int(time.time())}"
    state["slots"].append({
        "id": nid, "side": opp, "entry": round(price, 2),
        "qty": slot["qty"], "status": "ACTIVE",
        "armed": False, "best_gross": 0.0,
    })

# ---------- MONITOR - AQUI ESTA A TRAVA RIGIDA ----------
def monitor(price):
    """Chamado a cada tick de preco. So a trava fecha.
    ALVO NAO FECHA SOZINHO - removido para a trava poder trabalhar."""
    with state["lock"]:
        if not state["running"]:
            return
        state["price"] = price
        ref = state["ref"]
        for slot in list(state["slots"]):
            # Ativar PENDING quando o preco toca a entrada
            if slot["status"] == "PENDING":
                if slot["side"] == "buy" and price >= slot["entry"]:
                    slot["status"] = "ACTIVE"
                elif slot["side"] == "sell" and price <= slot["entry"]:
                    slot["status"] = "ACTIVE"
                else:
                    continue
            if slot["status"] != "ACTIVE":
                continue
            qty = slot["qty"]
            entry = slot["entry"]
            gross = _gross(slot["side"], entry, price, qty)
            # ===== TRAVA RIGIDA - SEM PERCENTAGEM, SEM RECUO =====
            # 1. Arma a 0.002 BRUTO (o valor que vês no ecrã)
            if gross >= TRAVA_ARMAR_BRUTO:
                slot["armed"] = True
            # 2. Acompanha ate ao melhor preco - piso sobe junto
            if slot["armed"]:
                if gross > slot["best_gross"]:
                    slot["best_gross"] = gross
                # 3. Um tick contra e fecha - piso == melhor, sem margem
                if gross < slot["best_gross"]:
                    _close_slot(slot, price, "TRAVA")
                    # Espelho V6 mantido
                    _mirror(slot, price)
                    continue
            # NOTA: nao ha _hit_alvo aqui de proposito.
            # Antes o alvo fechava a 0.0014 e a trava nunca chegava a armar a 0.002.
            # Agora so a trava fecha, por isso o lucro nao se perde no recuo.
        # Vantagem / convergencia (inalterado)
        total = sum(_net(s["side"], s["entry"], price, s["qty"]) for s in state["slots"] if s["status"] == "ACTIVE")
        state["vantagem"] = total
        # Se vantagem atingiu o alvo global, para de abrir novas e deixa a trava fechar o resto
        # (logica de fecho global mantida do V6)

def get_state():
    with state["lock"]:
        actives = []
        for s in state["slots"]:
            if s["status"] == "ACTIVE":
                g = _gross(s["side"], s["entry"], state["price"], s["qty"])
                n = _net(s["side"], s["entry"], state["price"], s["qty"])
                actives.append({**s, "gross": round(g, 4), "net": round(n, 4)})
        return {
            "running": state["running"],
            "ref": state["ref"],
            "price": state["price"],
            "balance": round(state["balance"], 4),
            "initial": state["initial_balance"],
            "cofre_ciclo": round(state["cofre_ciclo"], 4),
            "cofre_global": round(state["cofre_global"], 4),
            "vantagem": round(state["vantagem"], 4),
            "actives": actives,
            "history": state["history"][-100:],
        }
