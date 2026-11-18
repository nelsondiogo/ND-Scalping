import logging, os
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, Response
from config import BotConfig, TOP_PAIRS
from exchange_management import BybitExchangeManager
from trading import MinimalistGridEngine
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
app=Flask(__name__)
cfg=BotConfig()
ex_manager=BybitExchangeManager(cfg)
engine=MinimalistGridEngine(ex_manager, cfg)
engine.start_background_loop()
def check_auth(u,p): return u=="admin" and p==cfg.admin_password
def requires_auth(f):
    @wraps(f)
    def d(*a,**k):
        auth=request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response("Login necessario",401,{"WWW-Authenticate":'Basic realm="ND-Scalping"'})
        return f(*a,**k)
    return d
HTML="""
<!DOCTYPE html><html lang="pt"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ND-Scalping</title><style>
*{box-sizing:border-box}body{font-family:-apple-system,Arial;background:#0b1220;color:#f8fafc;margin:0;padding:0;padding-bottom:20px;font-size:14px}
.top{position:sticky;top:0;background:#0b1220;padding:12px 14px 8px;border-bottom:1px solid #1e293b;z-index:10}
.top h1{margin:0;font-size:17px;letter-spacing:1px;color:#22c55e;display:inline}
.badge{font-size:11px;padding:5px 10px;border-radius:20px;font-weight:700}
.badge-paper{background:#f59e0b;color:#000}.badge-real{background:#ef4444;color:#fff}
.tabs{display:flex;gap:8px;padding:10px 14px}
.tabs button{border:none;background:#162033;color:#94a3b8;padding:9px 13px;border-radius:20px;font-size:13px;font-weight:700;cursor:pointer}
.tabs button.active{background:#22c55e;color:#000}
.wrap{padding:0 14px}.card{background:#162033;border:1px solid #1e293b;border-radius:14px;padding:14px;margin-bottom:12px}
.card h3{margin:0 0 8px;color:#38bdf8;font-size:12px;letter-spacing:1px;text-transform:uppercase}
.big{font-size:16px;font-weight:800}.green{color:#22c55e}.red{color:#ef4444}.muted{color:#94a3b8;font-size:12px;line-height:1.5}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
label{display:block;font-size:11px;color:#38bdf8;font-weight:700;margin:12px 0 5px;text-transform:uppercase}
input,select{width:100%;padding:11px;border-radius:10px;border:1px solid #1e293b;background:#0b1220;color:#fff;font-size:14px}
.btn{width:100%;padding:13px;border:none;border-radius:12px;font-weight:800;font-size:14px;cursor:pointer;margin-top:10px}
.btn-start{background:#22c55e;color:#000}.btn-stop{background:#ef4444;color:#fff}.btn-blue{background:#0284c7;color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:8px;border-bottom:1px solid #1e293b;text-align:center}
.page{display:none}.page.active{display:block}
.hist-item{background:#0b1220;border:1px solid #1e293b;border-radius:12px;padding:12px;margin-bottom:8px;font-size:13px}
</style></head><body>
<div class="top"><h1>ND-SCALPING</h1> <span id="modeBadge" class="badge badge-paper">PAPEL</span><div class="muted" id="sync" style="margin-top:4px">A ligar...</div></div>
<div class="tabs"><button class="active" onclick="showPage('dashboard',this)">Dashboard</button><button onclick="showPage('mercado',this)">Mercado</button><button onclick="showPage('historico',this)">Historico</button><button onclick="showPage('ajustes',this)">Ajustes</button></div>
<div class="wrap">
<div id="page-dashboard" class="page active">
<div class="card"><h3>Status</h3><div class="big" id="statusTxt">PARADO</div><div class="muted" id="statusMsg">A aguardar...</div><div class="muted">Par: <b id="activePair">BTC/USDT:USDT</b> | Preco atual: <b id="livePrice">--</b> | Ref: <b id="refP">--</b></div></div>
<div class="row"><div class="card"><h3>Inicial</h3><div class="big green" id="equity0">--</div></div><div class="card"><h3>Atual</h3><div class="big green" id="equity">--</div></div></div>
<div class="card"><h3>Posicao Atual - AO VIVO</h3><div class="muted">Preco agora: <b id="livePriceTop">--</b> <span id="priceArrow"></span> | Ref: <b id="refTop">--</b></div><div id="liveCards"></div><div id="posBox"><p class="muted">Nenhuma posicao ativa.</p></div><p><b>TOTAL AGORA:</b> <b id="pnlTxt">+0.0000</b> <span id="totalArrow"></span> | Cofre ciclo: <b class="green" id="cofre">0.0000</b> | Cofre global: <b class="green" id="cofreG">0.0000</b></p><p class="muted">LONG ganha quando o preco SOBE. SHORT ganha quando o preco DESCE. Quando um esta verde, o outro esta vermelho - e normal, e o hedge.</p></div>
<button class="btn btn-start" onclick="controlBot('start')">INICIAR ROBO</button><button class="btn btn-stop" onclick="controlBot('stop')">PARAR ROBO</button>
<p class="muted">Em Papel o preco vem publico, sem precisar de API. Em Real, a API tem de estar valida no Render.</p>
</div>
<div id="page-mercado" class="page"><div class="card"><h3>Mercado - Posicoes Ativas</h3><div class="muted">Preco atual: <b id="livePrice2">--</b></div><table><thead><tr><th>ID</th><th>Lado</th><th>Entrada</th><th>Best</th><th>Qty</th></tr></thead><tbody id="ordersTable"></tbody></table></div></div>
<div id="page-historico" class="page"><div class="card"><h3>Historico por ciclo</h3><p class="muted">Cada ciclo mostra o que ganhou/perdeu no total, quanto veio do LONG, quanto veio do SHORT, e qual lado teve mais performance.</p></div><div id="histList"><p class="muted">Sem ciclos concluidos.</p></div></div>
<div id="page-ajustes" class="page"><div class="card"><h3>Ajustes - Todos os parametros aqui</h3>
<p class="muted">A API e o Secret NAO ficam aqui. Ficam no Render em Environment Variables. Aqui mudas o par, alavancagem e margem.</p>
<label>Par</label><select id="selected_pair">{% for p in pairs %}<option value="{{p}}" {% if p==cfg.selected_pair %}selected{% endif %}>{{p}}</option>{% endfor %}</select>
<label>Alavancagem (1 a 20)</label><input type="number" id="leverage" value="{{cfg.leverage}}" min="1" max="20">
<label>Margem por ordem USDT</label><input type="number" step="0.5" id="margin_per_order" value="{{cfg.margin_per_order}}">
<label>Trailing %</label><input type="number" step="0.01" id="trailing_offset_pct" value="{{cfg.trailing_offset_pct*100}}">
<label>Meta % (lucro para fechar ciclo)</label><input type="number" step="0.1" id="target_profit_pct" value="{{cfg.target_profit_pct}}">
<label>Modo</label><select id="auto_mode"><option value="false" {% if not cfg.auto_mode %}selected{% endif %}>Manual</option><option value="true" {% if cfg.auto_mode %}selected{% endif %}>Automatico</option></select>
<label>N Operacoes Auto</label><input type="number" id="max_auto_operations" value="{{cfg.max_auto_operations}}" min="1" max="50">
<button class="btn btn-blue" onclick="saveSettings()">Guardar Definicoes</button>
<p class="muted">Saldo real: com Margem 5 precisas de 15 USDT minimo em Futuros (2 ordens x 5). Ideal: 50 USDT. Se so tens 5 USDT, usa Margem 1.0.</p>
</div></div>
</div>
<script>
function showPage(n,btn){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+n).classList.add('active');document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}
async function saveSettings(){const p={selected_pair:document.getElementById('selected_pair').value,leverage:parseInt(document.getElementById('leverage').value),margin_per_order:parseFloat(document.getElementById('margin_per_order').value),trailing_offset_pct:parseFloat(document.getElementById('trailing_offset_pct').value)/100,target_profit_pct:parseFloat(document.getElementById('target_profit_pct').value),auto_mode:document.getElementById('auto_mode').value==='true',max_auto_operations:parseInt(document.getElementById('max_auto_operations').value)};const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});alert(r.ok?'Guardado!':'Erro ao guardar');}
async function controlBot(a){const r=await fetch('/api/'+a,{method:'POST'});const d=await r.json();alert(a==='start'?'A iniciar... aguarda 5s e ve o Dashboard. Se ficar PARADO, le a mensagem de Status.':'Parado.');updateStatus()}
async function updateStatus(){try{const r=await fetch('/api/status');const d=await r.json();document.getElementById('sync').innerText='Atualizado: '+new Date().toLocaleTimeString('pt-PT')+' | '+d.status_message;document.getElementById('equity').innerText=(d.equity||0).toFixed(2)+' USDT';document.getElementById('equity0').innerText=(d.cycle_equity||d.equity||0).toFixed(2)+' USDT';document.getElementById('statusMsg').innerText=d.status_message;document.getElementById('statusTxt').innerText=d.is_running?'OPERANDO':'PARADO';document.getElementById('statusTxt').className='big '+(d.is_running?'green':'red');document.getElementById('activePair').innerText=d.active_symbol||d.selected_pair||'BTC/USDT:USDT';document.getElementById('pnlTxt').innerText=(d.net_pnl>=0?'+':'')+(d.net_pnl||0).toFixed(4);document.getElementById('cofre').innerText=(d.cofre||0).toFixed(4)+' USDT';document.getElementById('cofreG').innerText=(d.cofre_global||0).toFixed(4)+' USDT';document.getElementById('refP').innerText=d.reference_price?d.reference_price.toFixed(2):'--';document.getElementById('livePrice').innerText=d.last_price?d.last_price.toFixed(2):(d.reference_price?d.reference_price.toFixed(2):'--');document.getElementById('livePrice2').innerText=d.last_price?d.last_price.toFixed(2):'--';const b=document.getElementById('modeBadge');if(d.paper_trading){b.innerText='PAPEL';b.className='badge badge-paper';}else{b.innerText='REAL';b.className='badge badge-real';}document.getElementById('ordersTable').innerHTML=(d.orders||[]).map(o=>`<tr><td>${o.id}</td><td>${o.side==='buy'?'LONG':'SHORT'}</td><td>${o.entry_price.toFixed(2)}</td><td>${o.best_price.toFixed(2)}</td><td>${o.qty}</td></tr>`).join('')||'<tr><td colspan=5>Sem posicoes. Carrega INICIAR.</td></tr>';document.getElementById('livePriceTop').innerText=d.last_price?d.last_price.toFixed(2):'--';document.getElementById('refTop').innerText=d.reference_price?d.reference_price.toFixed(2):'--';document.getElementById('priceArrow').innerText=d.price_dir==='up'?'▲ A SUBIR':(d.price_dir==='down'?'▼ A DESCER':'— ESTAVEL');document.getElementById('priceArrow').style.color=d.price_dir==='up'?'#22c55e':(d.price_dir==='down'?'#ef4444':'#94a3b8');document.getElementById('totalArrow').innerText=(d.live_total||0)>=0?'▲ POSITIVO':'▼ NEGATIVO';document.getElementById('totalArrow').style.color=(d.live_total||0)>=0?'#22c55e':'#ef4444';document.getElementById('pnlTxt').innerText=((d.live_total||0)>=0?'+':'')+(d.live_total||0).toFixed(4)+' USDT';document.getElementById('pnlTxt').style.color=(d.live_total||0)>=0?'#22c55e':'#ef4444';document.getElementById('liveCards').innerHTML=(d.live_orders||[]).map(o=>{const p=o.pnl_live||0;const col=p>=0?'#22c55e':'#ef4444';const nome=o.side==='buy'?'LONG':'SHORT';const verbo=o.side==='buy'?(d.price_dir==='up'?'a ganhar porque o preco SOBE':(d.price_dir==='down'?'a perder porque o preco DESCE':'estavel')):(d.price_dir==='down'?'a ganhar porque o preco DESCE':(d.price_dir==='up'?'a perder porque o preco SOBE':'estavel'));return `<div style="background:#0b1220;border:1px solid #1e293b;border-radius:12px;padding:10px;margin-top:8px"><b>${nome}</b> Entrada ${o.entry_price.toFixed(2)} Qty ${o.qty}<br><b style="color:${col}">${p>=0?'+':''}${p.toFixed(4)} USDT ${p>=0?'▲ POSITIVO':'▼ NEGATIVO'}</b> - ${verbo}</div>`;}).join('')||'';
document.getElementById('posBox').innerHTML=(d.orders||[]).length?(d.orders||[]).map(o=>`<p><b>${o.side==='buy'?'LONG':'SHORT'}</b> Entrada ${o.entry_price.toFixed(2)} Qty ${o.qty}</p>`).join(''):'<p class=muted>Nenhuma posicao ativa.</p>';document.getElementById('histList').innerHTML=(d.history||[]).length?(d.history||[]).map(h=>`<div class=hist-item><b>Ciclo ${h.ciclo} - ${h.par}</b><br>Total: <b>${h.total>=0?'+':''}${h.total} USDT</b> | LONG ${h.long} | SHORT ${h.short}<br>Vencedor: <b>${h.vencedor}</b></div>`).join(''):'<p class=muted>Sem ciclos concluidos.</p>';}catch(e){document.getElementById('sync').innerText='Sem ligacao ao servidor - verifica o Render.';}}
setInterval(updateStatus,2000);updateStatus();
</script></body></html>
"""
@app.route("/")
@requires_auth
def index(): return render_template_string(HTML, cfg=cfg, pairs=TOP_PAIRS)
@app.route("/api/settings", methods=["POST"])
@requires_auth
def update_settings():
    try:
        d=request.json or {}
        if "selected_pair" in d and d["selected_pair"] in TOP_PAIRS: cfg.selected_pair=d["selected_pair"]
        if "leverage" in d:
            v=int(d["leverage"]); assert 1<=v<=20; cfg.leverage=v
        if "margin_per_order" in d:
            v=float(d["margin_per_order"]); assert 0.5<=v<=1000; cfg.margin_per_order=v
        if "trailing_offset_pct" in d:
            v=float(d["trailing_offset_pct"]); assert 0.001<=v<=0.05; cfg.trailing_offset_pct=v
        if "target_profit_pct" in d:
            v=float(d["target_profit_pct"]); assert 0.1<=v<=20; cfg.target_profit_pct=v
        if "auto_mode" in d: cfg.auto_mode=bool(d["auto_mode"])
        if "max_auto_operations" in d:
            v=int(d["max_auto_operations"]); assert 1<=v<=50; cfg.max_auto_operations=v
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"status":"error","error":str(e)}),400
@app.route("/api/start", methods=["POST"])
@requires_auth
def start(): engine.start_bot(); return jsonify({"status":"started","message":cfg.status_message})
@app.route("/api/stop", methods=["POST"])
@requires_auth
def stop(): engine.stop_bot(close_all=True); return jsonify({"status":"stopped"})
@app.route("/api/status")
@requires_auth
def status():
    # Em Papel, mostra equity simulado e tenta preco publico mesmo parado, para nunca ficar "sem dados"
    last_price=getattr(engine,"last_price",0) or engine.reference_price or 0
    if not last_price:
        try:
            t=ex_manager.fetch_ticker(cfg.selected_pair)
            last_price=float(t.get("last",0) or 0)
            engine.last_price=last_price
        except Exception: last_price=0
    if getattr(cfg,'paper_trading',False):
        equity=engine.paper_equity if engine.paper_equity>0 else cfg.paper_initial_balance
    else:
        equity=ex_manager.get_total_equity()
        if equity<0: equity=0
    net=(equity-cfg.cycle_initial_equity) if (cfg.is_running and cfg.cycle_initial_equity>0) else 0.0
    live_orders = engine.get_live_positions() if hasattr(engine,"get_live_positions") else engine.orders_state
    live_total = engine.get_live_total() if hasattr(engine,"get_live_total") else 0.0
    if getattr(cfg,'paper_trading',False):
        equity = (cfg.cycle_initial_equity or cfg.paper_initial_balance) + cfg.cofre + live_total
    price_dir = "flat"
    if getattr(engine,"last_price",0) and getattr(engine,"prev_price",0):
        price_dir = "up" if engine.last_price>engine.prev_price else ("down" if engine.last_price<engine.prev_price else "flat")
    return jsonify({"is_running":cfg.is_running,"active_symbol":cfg.active_symbol,"selected_pair":cfg.selected_pair,"equity":equity,"cycle_equity":cfg.cycle_initial_equity,"live_orders":live_orders,"live_total":live_total,"price_dir":price_dir,
        "net_pnl":net,"completed_operations":cfg.completed_operations,"max_auto_operations":cfg.max_auto_operations,
        "auto_mode":cfg.auto_mode,"status_message":cfg.status_message,"orders":engine.orders_state,
        "cofre":cfg.cofre,"cofre_global":cfg.cofre_global,"reference_price":engine.reference_price,"last_price":last_price,
        "paper_trading":cfg.paper_trading,"paper_equity":engine.paper_equity,"history":getattr(engine,"history",[]),
        "leverage":cfg.leverage,"margin_per_order":cfg.margin_per_order})
@app.route("/health")
def health(): return jsonify({"status":"ok"})
if __name__=="__main__":
    port=int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
