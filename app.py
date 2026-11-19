# ND-SCALPING V6 Final - Visual original + Trava Rigida
# UNICA MUDANCA: a trava. Todo o resto (visual, grid, espelho, cofre,
# vantagem, historico) fica como estava.
# Trava (fixa no codigo, nunca em Ajustes):
#  - Arma SOMENTE quando lucro LIQUIDO >= 0.001 USDT
#  - Recuo = 1.5% do melhor lucro liquido atingido
#  - Nunca armada = nunca fecha por trava

import os, time, threading, json
from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
import ccxt

app = Flask(__name__)

SYMBOL = os.environ.get("SYMBOL", "BTC/USDT:USDT")
PAPER_TRADING = os.environ.get("PAPER_TRADING", "True") == "True"
PAPER_INITIAL_BALANCE = float(os.environ.get("PAPER_INITIAL_BALANCE", "1000.0"))
MARGIN_PER_ORDER = float(os.environ.get("MARGIN_PER_ORDER", "5.0"))
LEVERAGE = int(os.environ.get("LEVERAGE", "3"))
STEP = float(os.environ.get("STEP", "40.0"))
TOTAL_ORDERS = int(os.environ.get("TOTAL_ORDERS", "14"))
PROFIT_PER_OPERATION = float(os.environ.get("PROFIT_PER_OPERATION", "0.05"))
MODE = os.environ.get("MODE", "MANUAL")
OPS_PER_DAY = int(os.environ.get("OPS_PER_DAY", "0"))

# Trava rigida - NAO MEXER, NAO POR EM AJUSTES
TRAVA_ARM_NET = 0.001
TRAVA_RECUO_FRAC = 0.015
FEE_RATE = 0.0001

state = {
    "balance": PAPER_INITIAL_BALANCE,
    "initial": PAPER_INITIAL_BALANCE,
    "ref": None, "price": None, "direction": "ESTAVEL",
    "orders": [], "history": [],
    "cofre_ciclo": 0.0, "cofre_global": 0.0,
    "operation_profit": 0.0, "operation_active": True,
    "ops_today": 0, "updated": "",
    "profit_per_operation": PROFIT_PER_OPERATION,
    "mode": MODE, "ops_per_day": OPS_PER_DAY,
    "margin": MARGIN_PER_ORDER, "leverage": LEVERAGE,
    "step": STEP, "total_orders": TOTAL_ORDERS,
    "symbol": SYMBOL, "paper": PAPER_TRADING,
}
lock = threading.Lock()

if PAPER_TRADING:
    exchange = ccxt.bybit({"options": {"defaultType": "linear"}})
else:
    exchange = ccxt.bybit({
        "apiKey": os.environ.get("BYBIT_API_KEY", ""),
        "secret": os.environ.get("BYBIT_API_SECRET", ""),
        "options": {"defaultType": "linear"},
    })
    try:
        exchange.set_leverage(LEVERAGE, SYMBOL)
    except Exception as e:
        print("leverage erro:", e)

def fee_roundtrip(open_price, close_price, qty):
    return FEE_RATE * (open_price + close_price) * qty

def net_profit(o, price):
    if o["side"] == "LONG":
        gross = (price - o["open_price"]) * o["qty"]
    else:
        gross = (o["open_price"] - price) * o["qty"]
    return gross - fee_roundtrip(o["open_price"], price, o["qty"])

def gross_profit(o, price):
    if o["side"] == "LONG":
        return (price - o["open_price"]) * o["qty"]
    return (o["open_price"] - price) * o["qty"]

def get_price():
    try:
        t = exchange.fetch_ticker(SYMBOL)
        return float(t["last"])
    except Exception:
        return state["price"]

def build_grid(ref):
    orders = []
    half = TOTAL_ORDERS // 2
    for i in range(1, half + 1):
        entry_long = ref + STEP / 2 + (i - 1) * STEP
        entry_short = ref - STEP / 2 - (i - 1) * STEP
        orders.append({"id": "LONG_%d" % i, "side": "LONG", "entry": entry_long,
                       "target": entry_long + STEP, "qty": MARGIN_PER_ORDER * LEVERAGE / entry_long,
                       "status": "PENDING", "open_price": None, "best_net": None, "armed": False})
        orders.append({"id": "SHORT_%d" % i, "side": "SHORT", "entry": entry_short,
                       "target": entry_short - STEP, "qty": MARGIN_PER_ORDER * LEVERAGE / entry_short,
                       "status": "PENDING", "open_price": None, "best_net": None, "armed": False})
    return orders

def close_order(o, price, reason):
    gross = gross_profit(o, price)
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
    mirror_side = "SHORT" if o["side"] == "LONG" else "LONG"
    mirror_entry = price - STEP if mirror_side == "SHORT" else price + STEP
    mirror_target = mirror_entry - STEP if mirror_side == "SHORT" else mirror_entry + STEP
    qty = MARGIN_PER_ORDER * LEVERAGE / mirror_entry
    with lock:
        state["orders"].append({
            "id": "ESP_%s_%d" % (mirror_side, int(price)),
            "side": mirror_side, "entry": mirror_entry,
            "target": mirror_target, "qty": qty,
            "status": "PENDING", "open_price": None,
            "best_net": None, "armed": False,
        })

def loop():
    while True:
        try:
            price = get_price()
            if price is None:
                time.sleep(2)
                continue
            with lock:
                prev = state["price"]
                state["price"] = price
                if prev and price > prev:
                    state["direction"] = "A SUBIR"
                elif prev and price < prev:
                    state["direction"] = "A DESCER"
                else:
                    state["direction"] = "ESTAVEL"
                state["updated"] = datetime.now().strftime("%H:%M:%S")
                if state["ref"] is None:
                    state["ref"] = price
                    state["orders"] = build_grid(price)
            for o in list(state["orders"]):
                if o["status"] == "PENDING":
                    hit = (price >= o["entry"]) if o["side"] == "LONG" else (price <= o["entry"])
                    if hit:
                        with lock:
                            o["status"] = "ACTIVE"
                            o["open_price"] = price
                            o["best_net"] = None
                            o["armed"] = False
            for o in list(state["orders"]):
                if o["status"] != "ACTIVE":
                    continue
                np = net_profit(o, price)
                # TRAVA RIGIDA - unica mudanca
                if not o["armed"] and np >= TRAVA_ARM_NET:
                    o["armed"] = True
                    o["best_net"] = np
                if o["armed"]:
                    if np > o["best_net"]:
                        o["best_net"] = np
                    if np <= o["best_net"] * (1 - TRAVA_RECUO_FRAC):
                        close_order(o, price, "TRAVA")
                        continue
                hit_target = (price >= o["target"]) if o["side"] == "LONG" else (price <= o["target"])
                if hit_target:
                    close_order(o, price, "ALVO")
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
            print("loop erro:", e)
            time.sleep(3)

threading.Thread(target=loop, daemon=True).start()

TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ND-SCALPING</title>
<style>
*{box-sizing:border-box} body{margin:0;background:#0a1120;color:#e5e7eb;font-family:-apple-system,system-ui,sans-serif;padding-bottom:90px}
.top{padding:14px 16px 8px} .top h1{margin:0;font-size:22px;color:#22c55e;display:inline}
.badge{display:inline-block;background:#f59e0b;color:#000;font-size:12px;font-weight:800;padding:4px 12px;border-radius:14px;margin-left:8px;vertical-align:middle}
.small{color:#94a3b8;font-size:13px;margin-top:4px}
.cards{display:flex;gap:10px;padding:10px 16px} .card{flex:1;background:#111c33;border-radius:14px;padding:14px}
.card .lbl{color:#38bdf8;font-size:12px;letter-spacing:1px;font-weight:700} .card .val{color:#22c55e;font-size:20px;font-weight:800;margin-top:6px}
.box{margin:10px 16px;background:#111c33;border-radius:14px;padding:16px}
.box h2{margin:0 0 8px;color:#38bdf8;font-size:14px;letter-spacing:1px}
.mut{color:#94a3b8;font-size:13px;line-height:1.5}
.big{font-size:16px;font-weight:800} .red{color:#ef4444} .grn{color:#22c55e}
.refbar{background:#eab308;color:#000;text-align:center;font-weight:800;border-radius:20px;padding:8px;margin:12px 0;font-size:13px}
.grid{display:flex;border-radius:12px;overflow:hidden;border:1px solid #1f2937}
.col{flex:1;padding:12px} .col.short{background:#2a0f0f} .col.long{background:#0f240f}
.col h3{margin:0 0 10px;font-size:13px} .col.short h3{color:#f87171} .col.long h3{color:#4ade80}
.ord{border-bottom:1px solid rgba(255,255,255,.08);padding:8px 0;font-size:12px;line-height:1.5}
.ord b{font-size:12px}
table{width:100%;border-collapse:collapse;font-size:13px} td{padding:8px 4px;border-bottom:1px solid #1f2937}
.menu{position:fixed;bottom:0;left:0;right:0;background:#0a1120;padding:10px 12px 18px;display:flex;gap:8px;border-top:1px solid #1f2937}
.menu button{flex:1;border:0;border-radius:20px;padding:12px 4px;font-weight:700;background:#1a2942;color:#94a3b8;font-size:13px}
.menu button.on{background:#22c55e;color:#000}
input,select{width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0a1120;color:#fff;margin:6px 0}
label{font-size:12px;color:#94a3b8}
.hist-line{font-size:13px;padding:8px 0;border-bottom:1px solid #1f2937}
</style></head><body>
<div class="top"><h1>ND-SCALPING</h1><span class="badge" id="badge">PAPEL</span>
<div class="small">Atualizado: <span id="updated">--</span></div></div>
<div class="cards"><div class="card"><div class="lbl">INICIAL</div><div class="val" id="initial">--</div></div>
<div class="card"><div class="lbl">ATUAL</div><div class="val" id="atual">--</div></div></div>

<div id="tab-dashboard">
<div class="box"><h2>POSICAO ATUAL - AO VIVO</h2>
<div class="mut">Preco agora: <b id="price" style="color:#fff">--</b> <span id="dir"></span> | Ref: <b id="ref" style="color:#fff">--</b></div>
<div id="activeBox" style="margin-top:10px"></div>
<div class="big" style="margin-top:10px">TOTAL AGORA: <span id="totalAgora">--</span> | Cofre ciclo: <span id="cofreCiclo">--</span> USDT | Cofre global: <span id="cofreGlobal">--</span> USDT</div>
<p class="mut">LONG ganha quando o preco SOBE. SHORT ganha quando o preco DESCE.</p></div>
<div class="box"><h2>GRID — REF NO CENTRO</h2>
<p class="mut">Nao importa a direcao, o robo sempre ganha ate ao lucro definido. Sobe &rarr; fecha LONG. Desce &rarr; fecha SHORT. Vai e volta &rarr; fecha dos dois lados.</p>
<div class="refbar" id="refbar">--</div>
<div class="grid"><div class="col short"><h3>&#9660; SHORT — ABAIXO DA REF</h3><div id="shortCol"></div></div>
<div class="col long"><h3>&#9650; LONG — ACIMA DA REF</h3><div id="longCol"></div></div></div></div>
</div>

<div id="tab-mercado" style="display:none"><div class="box"><h2>MERCADO</h2>
<p class="mut">Preco atual e Ref. O grafico de ordens esta no Dashboard.</p>
<div class="big">Preco: <span id="mPrice">--</span> | Ref: <span id="mRef">--</span></div>
<canvas id="chart" width="330" height="140" style="width:100%;margin-top:10px;background:#0a1120;border-radius:8px"></canvas>
</div></div>

<div id="tab-historico" style="display:none"><div class="box"><h2>HISTORICO</h2>
<div class="big" id="histTotal">--</div>
<div class="mut" id="histSplit"></div><div id="histList"></div></div></div>

<div id="tab-ajustes" style="display:none"><div class="box"><h2>AJUSTES</h2>
<label>Lucro por operacao (USDT)</label><input id="cfgProfit" type="number" step="0.01">
<label>Modo</label><select id="cfgMode"><option>MANUAL</option><option>AUTO</option></select>
<label>Operacoes por dia (0 = sem limite)</label><input id="cfgOps" type="number">
<p class="mut">A trava e fixa no codigo e nao aparece aqui: arma a 0.001 liquido, recuo 1.5%.</p>
<button onclick="saveCfg()" style="width:100%;padding:12px;border:0;border-radius:10px;background:#22c55e;font-weight:800">Guardar</button>
</div></div>

<div class="menu">
<button id="b-dashboard" class="on" onclick="show('dashboard')">Dashboard</button>
<button id="b-mercado" onclick="show('mercado')">Mercado</button>
<button id="b-historico" onclick="show('historico')">Historico</button>
<button id="b-ajustes" onclick="show('ajustes')">Ajustes</button>
</div>
<script>
let hist=[];
function show(t){['dashboard','mercado','historico','ajustes'].forEach(function(x){
document.getElementById('tab-'+x).style.display=(x===t?'block':'none');
document.getElementById('b-'+x).className=(x===t?'on':'');});}
function fmt(n){return (n>=0?'+':'')+Number(n).toFixed(4);}
function drawChart(){
let c=document.getElementById('chart');let ctx=c.getContext('2d');ctx.clearRect(0,0,c.width,c.height);
if(hist.length<2)return;let mn=Math.min.apply(null,hist),mx=Math.max.apply(null,hist);
ctx.strokeStyle='#22c55e';ctx.beginPath();
hist.forEach(function(v,i){let x=i/(hist.length-1)*c.width;let y=130-(v-mn)/((mx-mn)||1)*120;if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});
ctx.stroke();}
async function tick(){try{let r=await fetch('/api/state');let s=await r.json();
document.getElementById('updated').textContent=s.updated||'--';
document.getElementById('initial').textContent=Number(s.initial).toFixed(2)+' USDT';
document.getElementById('atual').textContent=Number(s.balance).toFixed(2)+' USDT';
document.getElementById('badge').textContent=s.paper?'PAPEL':'REAL';
document.getElementById('price').textContent=s.price==null?'--':Number(s.price).toFixed(2);
document.getElementById('ref').textContent=s.ref==null?'--':Number(s.ref).toFixed(2);
document.getElementById('mPrice').textContent=s.price==null?'--':Number(s.price).toFixed(2);
document.getElementById('mRef').textContent=s.ref==null?'--':Number(s.ref).toFixed(2);
document.getElementById('dir').textContent=s.direction||'';
document.getElementById('refbar').textContent='— Ref: '+Number(s.ref||0).toFixed(4)+' • Preço: '+Number(s.price||0).toFixed(2)+' —';
let act=s.orders.filter(function(o){return o.status==='ACTIVE';});
let tot=0;let ab=document.getElementById('activeBox');ab.innerHTML='';
act.forEach(function(o){let gp=0;if(o.open_price!=null){gp=(o.side==='LONG'?(s.price-o.open_price):(o.open_price-s.price))*o.qty;}tot+=gp;
ab.innerHTML+='<div style="background:#0a1120;border-radius:10px;padding:10px"><b>'+o.side+'</b> Entrada '+Number(o.open_price).toFixed(2)+' Qty '+Number(o.qty).toFixed(8)+'<br><span class="'+(gp>=0?'grn':'red')+'">'+fmt(gp)+' USDT '+(gp>=0?'▲ POSITIVO':'▼ NEGATIVO')+(o.armed?' • TRAVA ARMADA':'')+'</span></div>';});
if(!act.length){ab.innerHTML='<div class="mut">Sem posicao ativa no momento.</div>';}
document.getElementById('totalAgora').innerHTML='<span class="'+(tot>=0?'grn':'red')+'">'+fmt(tot)+'</span>';
document.getElementById('cofreCiclo').innerHTML='<span class="grn">'+Number(s.cofre_ciclo).toFixed(4)+'</span>';
document.getElementById('cofreGlobal').innerHTML='<span class="grn">'+Number(s.cofre_global).toFixed(4)+'</span>';
let sh=s.orders.filter(function(o){return o.side==='SHORT';});
let lg=s.orders.filter(function(o){return o.side==='LONG';});
function col(list){return list.map(function(o){let tgt=o.target!=null?Number(o.target).toFixed(4):'--';
return '<div class="ord">'+o.id+' • '+o.status+'<br>'+Number(o.entry).toFixed(4)+' &rarr; '+tgt+' &nbsp; '+fmt(0.0029)+'</div>';}).join('')||'<div class="mut">--</div>';}
document.getElementById('shortCol').innerHTML=col(sh);
document.getElementById('longCol').innerHTML=col(lg);
let h=s.history||[];let totH=h.reduce(function(a,x){return a+x.profit;},0);
let totL=h.filter(function(x){return x.side==='LONG';}).reduce(function(a,x){return a+x.profit;},0);
let totS=h.filter(function(x){return x.side==='SHORT';}).reduce(function(a,x){return a+x.profit;},0);
document.getElementById('histTotal').innerHTML='TOTAL FECHADO: <span class="'+(totH>=0?'grn':'red')+'">'+fmt(totH)+' USDT | '+h.length+' ordens</span>';
document.getElementById('histSplit').innerHTML='LONG: '+fmt(totL)+' USDT | '+h.filter(function(x){return x.side==='LONG';}).length+' ordens<br>SHORT: '+fmt(totS)+' USDT | '+h.filter(function(x){return x.side==='SHORT';}).length+' ordens';
document.getElementById('histList').innerHTML=h.map(function(x){return '<div class="hist-line"><b>'+x.side+'</b> '+Number(x.open).toFixed(2)+' &rarr; '+Number(x.close).toFixed(2)+' <span class="'+(x.profit>=0?'grn':'red')+'">'+fmt(x.profit)+' USDT</span> '+x.reason+'<br><span class="mut">'+x.id+'</span></div>';}).join('')||'<div class="mut">Sem ordens fechadas ainda.</div>';
if(s.price!=null){hist.push(s.price);if(hist.length>60)hist.shift();drawChart();}
}catch(e){} }
async function saveCfg(){let b={profit_per_operation:parseFloat(document.getElementById('cfgProfit').value),mode:document.getElementById('cfgMode').value,ops_per_day:parseInt(document.getElementById('cfgOps').value||'0')};
await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});alert('Guardado');}
setInterval(tick,3000);tick();
</script></body></html>"""

@app.route("/health")
def health():
    return jsonify({"ok": True})

@app.route("/")
def index():
    return render_template_string(TEMPLATE)

@app.route("/api/state")
def api_state():
    with lock:
        return jsonify(state)

@app.route("/api/config", methods=["POST"])
def api_config():
    d = request.get_json(force=True, silent=True) or {}
    with lock:
        if "profit_per_operation" in d:
            state["profit_per_operation"] = float(d["profit_per_operation"])
        if "mode" in d:
            state["mode"] = str(d["mode"]).upper()
        if "ops_per_day" in d:
            state["ops_per_day"] = int(d["ops_per_day"])
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
