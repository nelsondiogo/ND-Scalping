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
<title>ND-Scalping V2</title><style>
body{font-family:Arial;background:#0f172a;color:#f8fafc;margin:0;padding:20px}
.container{max-width:960px;margin:auto}.card{background:#1e293b;border-radius:10px;padding:20px;margin-bottom:20px}
h1,h2{color:#38bdf8}.grid-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:15px}
.stat-box{background:#0f172a;padding:15px;border-radius:8px;text-align:center}.stat-val{font-size:1.4em;font-weight:bold}
.green{color:#22c55e}.red{color:#ef4444}.yellow{color:#eab308}
.form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
label{display:block;font-size:.85em;color:#94a3b8}input,select{width:100%;padding:8px;border-radius:6px;border:1px solid #334155;background:#0f172a;color:#fff;box-sizing:border-box}
.btn-group{display:flex;gap:10px;margin-top:15px}button{padding:12px 20px;border:none;border-radius:6px;font-weight:bold;cursor:pointer;flex:1}
.btn-start{background:#22c55e}.btn-stop{background:#ef4444;color:#fff}.btn-save{background:#38bdf8}
table{width:100%;border-collapse:collapse}th,td{padding:8px;border-bottom:1px solid #334155;text-align:center}
.badge{background:#0f172a;padding:6px 10px;border-radius:6px;display:inline-block;margin:2px}
.grid-wrap{display:flex;gap:0;border:1px solid #334155;border-radius:10px;overflow:hidden;margin-top:10px}
.grid-col{flex:1;padding:14px}.grid-col.short{background:#1a0f0f}.grid-col.long{background:#0f1a0f}
.grid-divider{width:3px;background:#eab308;position:relative;flex-shrink:0}
.grid-divider span{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-90deg);background:#eab308;color:#000;font-weight:bold;font-size:11px;padding:4px 8px;border-radius:6px;white-space:nowrap}
.ref-line{border-top:2px dashed #eab308;margin:12px 0;position:relative;text-align:center}
.ref-line span{background:#eab308;color:#000;font-weight:bold;font-size:12px;padding:3px 10px;border-radius:12px;position:relative;top:-11px}
.grid-row{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #334155;font-size:13px}

</style></head><body><div class="container">
<h1>ND-Scalping GRID | Ref Centro + LONG Acima / SHORT Abaixo</h1>
<div class="card"><div class="grid-stats">
<div class="stat-box"><div>Equity</div><div class="stat-val" id="equity">--</div></div>
<div class="stat-box"><div>Lucro Ciclo</div><div class="stat-val" id="pnl">--</div></div>
<div class="stat-box"><div>Par Ativo</div><div class="stat-val yellow" id="activePair">--</div></div>
<div class="stat-box"><div>Cofre Ciclo</div><div class="stat-val green" id="cofre">--</div></div>
<div class="stat-box"><div>Cofre Global</div><div class="stat-val green" id="cofreG">--</div></div>
<div class="stat-box"><div>Ref</div><div class="stat-val" id="refP">--</div></div>
</div><p style="text-align:center" id="statusMsg">Carregando...</p>
<div class="btn-group"><button class="btn-start" onclick="controlBot('start')">▶ INICIAR</button>
<button class="btn-stop" onclick="controlBot('stop')">⏹ PARAR E FECHAR TUDO</button></div></div>
<div class="card"><h2>Ajustes</h2><div class="form-grid">
<div><label>Par (Manual)</label><select id="selected_pair">{% for p in pairs %}<option value="{{p}}" {% if p==cfg.selected_pair %}selected{% endif %}>{{p}}</option>{% endfor %}</select></div>
<div><label>Alavancagem</label><input type="number" id="leverage" value="{{cfg.leverage}}" min="1" max="20"></div>
<div><label>Margem / Ordem</label><input type="number" step="0.5" id="margin_per_order" value="{{cfg.margin_per_order}}"></div>
<div><label>Espaçamento Grid % (volatilidade)</label><input type="number" step="0.05" id="grid_spacing_pct" value="{{ (cfg.grid_spacing_pct*100) if cfg.grid_spacing_pct is defined else 0.65 }}"><small style="color:#94a3b8">OP 0,65% | SOL 0,40% | BTC 0,15% | ETH 0,25%</small></div>
<div><label>Trailing %</label><input type="number" step="0.01" id="trailing_offset_pct" value="{{cfg.trailing_offset_pct*100}}"></div>
<div><label>Meta %</label><input type="number" step="0.1" id="target_profit_pct" value="{{cfg.target_profit_pct}}"></div>
<div><label>Modo</label><select id="auto_mode"><option value="false" {% if not cfg.auto_mode %}selected{% endif %}>Manual</option><option value="true" {% if cfg.auto_mode %}selected{% endif %}>Automático</option></select></div>
<div><label>Nº Ops Auto</label><input type="number" id="max_auto_operations" value="{{cfg.max_auto_operations}}" min="1" max="50"></div>
</div><div class="btn-group"><button class="btn-save" onclick="saveSettings()">💾 GUARDAR</button></div></div>
<div class="card"><h2>Posições</h2><table><thead><tr><th>ID</th><th>Direção</th><th>Entrada</th><th>Best</th></tr></thead><tbody id="ordersTable"></tbody></table></div><div class="card"><h2>Grid — Ref no Centro</h2><p style="color:#94a3b8;font-size:13px">Não importa a direção, o robô sempre ganha até ao lucro definido. Sobe → fecha LONG. Desce → fecha SHORT. Vai e volta → fecha dos dois lados.</p><div class="ref-line"><span id="refLine">Ref: --</span></div><div class="grid-wrap"><div class="grid-col short"><h3 style="color:#ef4444;margin:0 0 8px">▼ SHORT — Abaixo da Ref</h3><div id="shortCol"></div></div><div class="grid-divider"><span>REF</span></div><div class="grid-col long"><h3 style="color:#22c55e;margin:0 0 8px">▲ LONG — Acima da Ref</h3><div id="longCol"></div></div></div><p style="color:#94a3b8;font-size:12px">Linha amarela vertical = Ref. SHORT à esquerda, LONG à direita. Entrada → Alvo (+lucro) • PENDING espera o preço • ACTIVE já abriu.</p></div>
</div><script>
async function saveSettings(){const p={selected_pair:document.getElementById('selected_pair').value,leverage:parseInt(document.getElementById('leverage').value),margin_per_order:parseFloat(document.getElementById('margin_per_order').value),grid_spacing_pct:parseFloat(document.getElementById('grid_spacing_pct').value)/100,trailing_offset_pct:parseFloat(document.getElementById('trailing_offset_pct').value)/100,target_profit_pct:parseFloat(document.getElementById('target_profit_pct').value),auto_mode:document.getElementById('auto_mode').value==='true',max_auto_operations:parseInt(document.getElementById('max_auto_operations').value)};await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});alert('Guardado!')}
async function controlBot(a){await fetch('/api/'+a,{method:'POST'});updateStatus()}
async function updateStatus(){const r=await fetch('/api/status');const d=await r.json();document.getElementById('equity').innerText=d.equity.toFixed(2)+' USDT';const pnl=document.getElementById('pnl');pnl.innerText=(d.net_pnl>=0?'+':'')+d.net_pnl.toFixed(4);pnl.className='stat-val '+(d.net_pnl>=0?'green':'red');document.getElementById('activePair').innerText=d.active_symbol||'NENHUM';document.getElementById('cofre').innerText=d.cofre.toFixed(4)+' USDT';document.getElementById('cofreG').innerText=d.cofre_global.toFixed(4)+' USDT';document.getElementById('refP').innerText=d.reference_price?d.reference_price.toFixed(4):'--';document.getElementById('statusMsg').innerText=d.status_message;document.getElementById('ordersTable').innerHTML=d.orders.map(o=>`<tr><td>${o.id}</td><td class="${o.side==='buy'?'green':'red'}">${o.side==='buy'?'LONG':'SHORT'}</td><td>${o.entry_price.toFixed(4)}</td><td>${o.best_price.toFixed(4)}</td></tr>`).join('')}
try{renderGrid(d)}catch(e){console.log('grid',e)}
function renderGrid(d){try{var refEl=document.getElementById('refLine');if(refEl){refEl.innerText='— Ref: '+(d.reference_price?Number(d.reference_price).toFixed(4):'--')+' —';}var orders=Array.isArray(d.orders)?d.orders:[];var longs=orders.filter(function(o){return o.side==='buy'}).sort(function(a,b){return a.entry_price-b.entry_price});var shorts=orders.filter(function(o){return o.side==='sell'}).sort(function(a,b){return b.entry_price-a.entry_price});function fmt(o){var tgt=(o.target_price!=null)?Number(o.target_price).toFixed(4):'--';var tp=(o.target_profit!=null)?Number(o.target_profit).toFixed(4):'0.0100';var cls=o.status==='PENDING'?'yellow':(o.status==='ACTIVE'?'green':'red');return '<div class="grid-row"><span>'+String(o.id).replace('GRID_','')+' • '+Number(o.entry_price).toFixed(4)+' → '+tgt+'</span><span class="'+cls+'">'+o.status+' • +'+tp+'</span></div>';}var lc=document.getElementById('longCol');if(lc){lc.innerHTML=longs.length?longs.map(fmt).join(''):'<p style="color:#94a3b8">Sem LONG — já fecharam, Cofre subiu.</p>';}var sc=document.getElementById('shortCol');if(sc){sc.innerHTML=shorts.length?shorts.map(fmt).join(''):'<p style="color:#94a3b8">Sem SHORT — já fecharam, Cofre subiu.</p>';}}catch(e){console.log('grid',e)}}
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
        if "grid_spacing_pct" in d:
            v=float(d["grid_spacing_pct"]); assert 0.0005<=v<=0.05, "Espacamento deve ser 0.05% a 5%"; cfg.grid_spacing_pct=v
        if "trailing_offset_pct" in d:
            v=float(d["trailing_offset_pct"]); assert 0.001<=v<=0.05, "Trailing deve ser 0.10% a 5%"; cfg.trailing_offset_pct=v
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
    equity=ex_manager.get_total_equity()
    if equity<0: equity=0
    net=(equity-cfg.cycle_initial_equity) if (cfg.is_running and cfg.cycle_initial_equity>0) else 0.0
    return jsonify({"is_running":cfg.is_running,"active_symbol":cfg.active_symbol,"equity":equity,
        "net_pnl":net,"completed_operations":cfg.completed_operations,"max_auto_operations":cfg.max_auto_operations,
        "auto_mode":cfg.auto_mode,"status_message":cfg.status_message,"orders":engine.orders_state,
        "cofre":cfg.cofre,"cofre_global":cfg.cofre_global,"reference_price":engine.reference_price})
@app.route("/health")
def health(): return jsonify({"status":"ok"})

if __name__=="__main__":
    port=int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
