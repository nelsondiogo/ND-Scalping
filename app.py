import logging, os, time
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, Response
from config import BotConfig, TOP_PAIRS
from exchange_management import 【entity-BybitExchangeManager¦canonical_name=Bybit】
from trading import MinimalistGridEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
app=Flask(__name__)
cfg=BotConfig()
ex_manager=【entity-BybitExchangeManager¦canonical_name=Bybit】(cfg)
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
*{box-sizing:border-box}body{font-family:-apple-system,Arial;background:#0b1220;color:#f8fafc;margin:0;padding:0;padding-bottom:80px}
.top{position:sticky;top:0;background:#0b1220;padding:14px 16px 6px;text-align:center;border-bottom:1px solid #1e293b;z-index:10}
.top h1{margin:0;color:#22c55e;font-size:22px;letter-spacing:2px}
.top small{color:#38bdf8;font-weight:bold}
.badge{display:inline-block;margin-top:8px;padding:6px 12px;border-radius:20px;font-size:12px;font-weight:bold}
.badge-paper{background:#22c55e;color:#000}.badge-real{background:#ef4444;color:#fff}
.wrap{padding:14px}.row{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
.card{background:#162033;border:1px solid #1e293b;border-radius:14px;padding:16px}
.card h3{margin:0 0 10px;color:#38bdf8;font-size:13px;letter-spacing:1px;text-transform:uppercase}
.big{font-size:22px;font-weight:900}.green{color:#22c55e}.red{color:#ef4444}.yellow{color:#eab308}.muted{color:#94a3b8;font-size:12px;line-height:1.5}
label{display:block;font-size:12px;color:#38bdf8;font-weight:bold;margin:14px 0 6px;text-transform:uppercase}
input,select{width:100%;padding:13px;border-radius:10px;border:1px solid #1e293b;background:#0b1220;color:#fff;font-size:15px}
.btn{width:100%;padding:16px;border:none;border-radius:12px;font-weight:900;font-size:16px;cursor:pointer;margin-top:12px}
.btn-start{background:#22c55e;color:#000}.btn-stop{background:#ef4444;color:#fff}.btn-blue{background:#0284c7;color:#fff}
table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px;border-bottom:1px solid #1e293b;text-align:center}
.log{border-left:4px solid #22c55e;background:#0b1220;padding:12px;border-radius:8px;font-size:13px}
.nav{position:fixed;bottom:0;left:0;right:0;background:#0f172a;border-top:1px solid #1e293b;display:grid;grid-template-columns:repeat(4,1fr);padding:8px 0 18px}
.nav button{background:none;border:none;color:#94a3b8;font-weight:bold;font-size:12px;cursor:pointer}.nav button.active{color:#22c55e}
.page{display:none}.page.active{display:block}
.hist-item{background:#0b1220;border:1px solid #1e293b;border-radius:12px;padding:14px;margin-bottom:10px}
</style></head><body>
<div class="top"><h1>ND-SCALPING</h1><small id="sync">Sincronizado: --:--:--</small><br><span id="modeBadge" class="badge">A CARREGAR...</span></div>
<div class="wrap">

<!-- DASHBOARD -->
<div id="page-dashboard" class="page active">
<div class="row"><div class="card"><h3>Inicial (USDT)</h3><div class="big green" id="equity0">--</div></div><div class="card"><h3>Atual (USDT)</h3><div class="big green" id="equity">--</div></div></div>
<div class="card"><h3>Ligacao a Bybit</h3><span class="badge badge-paper" id="connBadge">PAPEL - SIMULACAO</span> <span class="badge" style="background:#334155" id="runBadge">PARADO</span><p class="muted" id="statusMsg">Carregando...</p></div>
<div class="card" style="margin-top:12px"><h3>Posicao Atual</h3><div id="posBox"><p class="muted">Nenhuma posicao ativa no momento.</p></div><div class="row" style="margin-top:12px"><div><span class="muted">STATUS</span><div class="big green" id="statusTxt">PARADO</div></div><div><span class="muted">PNL REALIZADO</span><div class="big green" id="pnlTxt">+0.0000</div></div></div></div>
<div class="card" style="margin-top:12px"><h3>Alavancagem & Capital</h3><p>Alavancagem: <b id="levTxt">3x</b></p><p>Cofre Ciclo: <b class="green" id="cofre">0.0000 USDT</b></p><p>Cofre Global: <b class="green" id="cofreG">0.0000 USDT</b></p><p>Ref: <b id="refP">--</b></p><p class="muted">Regras: Trailing 0.25% | Meta 1% | Stop Global 2% | Reancoragem 3% / 1h</p></div>
<button class="btn btn-start" onclick="controlBot('start')">▶ INICIAR ROBO</button><button class="btn btn-stop" onclick="controlBot('stop')">⏹ PARAR ROBO</button>
</div>

<!-- MERCADO -->
<div id="page-mercado" class="page"><div class="card"><h3>Mercado - Posicoes Ativas</h3><table><thead><tr><th>ID</th><th>Direcao</th><th>Entrada</th><th>Best</th></tr></thead><tbody id="ordersTable"></tbody></table></div></div>

<!-- HISTORICO -->
<div id="page-historico" class="page"><div class="card"><h3>Resumo Geral do Historico</h3><p>Total de Operacoes: <b id="histTotal">--</b></p><p>Cofre Global: <b class="green" id="histCofre">--</b></p><p class="muted">O historico detalhado de cada trade fica no log do Render. Aqui vês o resumo do ciclo atual.</p></div><div id="histList"></div></div>

<!-- AJUSTES -->
<div id="page-ajustes" class="page"><div class="card"><h3>Configuracao & Alavancagem</h3>
<p class="muted">A API e o Secret NAO se colocam aqui. Colocam-se no Render em Environment Variables.</p>
<label>Ambiente da chave</label><input value="Conta REAL (so leitura de preco em Modo Papel)" disabled>
<label>Par (Manual)</label><select id="selected_pair">{% for p in pairs %}<option value="{{p}}" {% if p==cfg.selected_pair %}selected{% endif %}>{{p}}</option>{% endfor %}</select>
<label>Alavancagem Manual</label><input type="number" id="leverage" value="{{cfg.leverage}}" min="1" max="20">
<label>Margem por operacao (USDT)</label><input type="number" step="0.5" id="margin_per_order" value="{{cfg.margin_per_order}}">
<p class="muted">E a <b>margem</b>: o valor do teu saldo que entra em cada operacao. A posicao e margem x alavancagem. Ex.: 5 USDT x 3x = 15 USDT.</p>
<label>Trailing %</label><input type="number" step="0.01" id="trailing_offset_pct" value="{{cfg.trailing_offset_pct*100}}">
<label>Meta %</label><input type="number" step="0.1" id="target_profit_pct" value="{{cfg.target_profit_pct}}">
<label>Modo</label><select id="auto_mode"><option value="false" {% if not cfg.auto_mode %}selected{% endif %}>Manual</option><option value="true" {% if cfg.auto_mode %}selected{% endif %}>Automatico</option></select>
<label>N Operacoes Auto</label><input type="number" id="max_auto_operations" value="{{cfg.max_auto_operations}}" min="1" max="50">
<button class="btn btn-blue" onclick="saveSettings()">Guardar Definicoes</button></div></div>

</div>
<div class="nav"><button class="active" onclick="showPage('dashboard',this)">📊<br>Dashboard</button><button onclick="showPage('mercado',this)">📈<br>Mercado</button><button onclick="showPage('historico',this)">📋<br>Historico</button><button onclick="showPage('ajustes',this)">⚙️<br>Ajustes</button></div>
<script>
function showPage(n,btn){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+n).classList.add('active');document.querySelectorAll('.nav button').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}
async function saveSettings(){const p={selected_pair:document.getElementById('selected_pair').value,leverage:parseInt(document.getElementById('leverage').value),margin_per_order:parseFloat(document.getElementById('margin_per_order').value),trailing_offset_pct:parseFloat(document.getElementById('trailing_offset_pct').value)/100,target_profit_pct:parseFloat(document.getElementById('target_profit_pct').value),auto_mode:document.getElementById('auto_mode').value==='true',max_auto_operations:parseInt(document.getElementById('max_auto_operations').value)};await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});alert('Guardado!')}
async function controlBot(a){await fetch('/api/'+a,{method:'POST'});updateStatus()}
async function updateStatus(){const r=await fetch('/api/status');const d=await r.json();const now=new Date();document.getElementById('sync').innerText='Sincronizado: '+now.toLocaleTimeString('pt-PT');document.getElementById('equity').innerText=d.equity.toFixed(4);document.getElementById('equity0').innerText=d.cycle_equity?d.cycle_equity.toFixed(4):d.equity.toFixed(4);document.getElementById('statusMsg').innerText=d.status_message;document.getElementById('statusTxt').innerText=d.is_running?'OPERANDO':'PARADO';document.getElementById('statusTxt').className='big '+(d.is_running?'green':'red');document.getElementById('runBadge').innerText=d.is_running?'OPERANDO':'PARADO';document.getElementById('pnlTxt').innerText=(d.net_pnl>=0?'+':'')+d.net_pnl.toFixed(4);document.getElementById('pnlTxt').className='big '+(d.net_pnl>=0?'green':'red');document.getElementById('cofre').innerText=d.cofre.toFixed(4)+' USDT';document.getElementById('cofreG').innerText=d.cofre_global.toFixed(4)+' USDT';document.getElementById('histCofre').innerText=d.cofre_global.toFixed(4)+' USDT';document.getElementById('histTotal').innerText=d.completed_operations;document.getElementById('refP').innerText=d.reference_price?d.reference_price.toFixed(4):'--';document.getElementById('levTxt').innerText=document.getElementById('leverage').value+'x';const b=document.getElementById('modeBadge');if(d.paper_trading){b.innerText='MODO PAPEL - SIMULACAO, SEM DINHEIRO REAL';b.className='badge badge-paper';document.getElementById('connBadge').innerText='PAPEL - SIMULACAO';}else{b.innerText='MODO REAL - DINHEIRO REAL';b.className='badge badge-real';document.getElementById('connBadge').innerText='CONTA REAL';}document.getElementById('ordersTable').innerHTML=d.orders.map(o=>`<tr><td>${o.id}</td><td class="${o.side==='buy'?'green':'red'}">${o.side==='buy'?'LONG':'SHORT'}</td><td>${o.entry_price.toFixed(4)}</td><td>${o.best_price.toFixed(4)}</td></tr>`).join('')||'<tr><td colspan=4 class=muted>Nenhuma posicao</td></tr>';document.getElementById('posBox').innerHTML=d.orders.length?d.orders.map(o=>`<p><b>${o.side==='buy'?'LONG':'SHORT'}</b> | Entrada ${o.entry_price.toFixed(4)} | Best ${o.best_price.toFixed(4)}</p>`).join(''):'<p class=muted>Nenhuma posicao ativa no momento.</p>';document.getElementById('histList').innerHTML=d.orders.map(o=>`<div class=hist-item><b>${o.side==='buy'?'LONG':'SHORT'} ${d.active_symbol||''}</b><br><span class=muted>Entrada ${o.entry_price.toFixed(4)} | ID ${o.id}</span></div>`).join('')||'<p class=muted>Nenhum registo de historico recente.</p>'}
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
def start(): engine.start_bot(); return jsonify({"status":"started"})
@app.route("/api/stop", methods=["POST"])
@requires_auth
def stop(): engine.stop_bot(close_all=True); return jsonify({"status":"stopped"})
@app.route("/api/status")
@requires_auth
def status():
    if getattr(cfg,'paper_trading',False):
        equity=engine.paper_equity if engine.paper_equity>0 else cfg.paper_initial_balance
    else:
        equity=ex_manager.get_total_equity()
        if equity<0: equity=0
    net=(equity-cfg.cycle_initial_equity) if (cfg.is_running and cfg.cycle_initial_equity>0) else 0.0
    return jsonify({"is_running":cfg.is_running,"active_symbol":cfg.active_symbol,"equity":equity,"cycle_equity":cfg.cycle_initial_equity,
        "net_pnl":net,"completed_operations":cfg.completed_operations,"max_auto_operations":cfg.max_auto_operations,
        "auto_mode":cfg.auto_mode,"status_message":cfg.status_message,"orders":engine.orders_state,
        "cofre":cfg.cofre,"cofre_global":cfg.cofre_global,"reference_price":engine.reference_price,"paper_trading":cfg.paper_trading,"paper_equity":engine.paper_equity})
@app.route("/health")
def health(): return jsonify({"status":"ok"})
if __name__=="__main__":
    port=int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
