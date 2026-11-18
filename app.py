import logging, os, time
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
*{box-sizing:border-box}body{font-family:-apple-system,Arial;background:#0b1220;color:#f8fafc;margin:0;padding:0;padding-bottom:70px;font-size:14px}
.top{position:sticky;top:0;background:#0b1220;padding:12px 14px 8px;border-bottom:1px solid #1e293b;z-index:10}
.top h1{margin:0;font-size:17px;letter-spacing:1px;color:#22c55e;display:inline}
.badge{font-size:11px;padding:5px 10px;border-radius:20px;font-weight:700}
.badge-paper{background:#f59e0b;color:#000}.badge-real{background:#ef4444;color:#fff}
.tabs{position:fixed;bottom:0;left:0;right:0;z-index:50;display:flex;gap:8px;padding:10px 14px;background:#0b1220;border-top:1px solid #1e293b;justify-content:center}
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
.grid-wrap{display:flex;gap:0;border:1px solid #1e293b;border-radius:10px;overflow:hidden;margin-top:10px}.grid-col{flex:1;padding:12px}.grid-col.short{background:#1a0f0f}.grid-col.long{background:#0f1a0f}.grid-divider{width:3px;background:#eab308;position:relative;flex-shrink:0}.grid-divider span{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%) rotate(-90deg);background:#eab308;color:#000;font-weight:700;font-size:11px;padding:4px 8px;border-radius:6px;white-space:nowrap}.ref-line{border-top:2px dashed #eab308;margin:12px 0;text-align:center}.ref-line span{background:#eab308;color:#000;font-weight:700;font-size:12px;padding:3px 10px;border-radius:12px;position:relative;top:-11px}.grid-row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1e293b;font-size:12px}</style></head><body>
<div class="top"><h1>ND-SCALPING</h1> <span id="modeBadge" class="badge badge-paper">PAPEL</span><div class="muted" id="sync" style="margin-top:4px">A ligar...</div></div>
<div class="tabs"><button class="active" onclick="showPage('dashboard',this)">Dashboard</button><button onclick="showPage('mercado',this)">Mercado</button><button onclick="showPage('historico',this)">Historico</button><button onclick="showPage('ajustes',this)">Ajustes</button></div>
<div class="wrap">
<div id="page-dashboard" class="page active">
<div class="card"><h3>Status</h3><div class="big" id="statusTxt">PARADO</div><div class="muted" id="statusMsg">A aguardar...</div><div class="muted">Par: <b id="activePair">BTC/USDT:USDT</b> | Preco atual: <b id="livePrice">--</b> | Ref: <b id="refP">--</b></div></div>
<div class="row"><div class="card"><h3>Inicial</h3><div class="big green" id="equity0">--</div></div><div class="card"><h3>Atual</h3><div class="big green" id="equity">--</div></div></div>
<div class="card"><h3>Posicao Atual - AO VIVO</h3><div class="muted">Preco agora: <b id="livePriceTop">--</b> <span id="priceArrow"></span> | Ref: <b id="refTop">--</b></div><div id="liveCards"></div><p><b>TOTAL AGORA:</b> <b id="pnlTxt">+0.0000</b> <span id="totalArrow"></span> | Cofre ciclo: <b class="green" id="cofre">0.0000</b> | Cofre global: <b class="green" id="cofreG">0.0000</b></p><p class="muted">LONG ganha quando o preco SOBE. SHORT ganha quando o preco DESCE.</p></div>
<div class="card"><h3>Grid — Ref no Centro</h3><p class="muted">Não importa a direção, o robô sempre ganha até ao lucro definido. Sobe → fecha LONG. Desce → fecha SHORT. Vai e volta → fecha dos dois lados.</p><div class="ref-line"><span id="refLine">Ref: --</span></div><div class="grid-wrap"><div class="grid-col short"><h3 style="color:#ef4444">▼ SHORT — Abaixo da Ref</h3><div id="shortCol"></div></div><div class="grid-divider"><span>REF</span></div><div class="grid-col long"><h3 style="color:#22c55e">▲ LONG — Acima da Ref</h3><div id="longCol"></div></div></div></div>
<button class="btn btn-start" id="powerBtn" onclick="toggleBot()">INICIAR ROBO</button>
<p class="muted">Em Papel o preco vem publico, sem precisar de API. Em Real, a API tem de estar valida no Render.</p>
</div>
<div id="page-mercado" class="page"><div class="card"><h3>Mercado - Posicoes Ativas</h3><div class="muted">Preco atual: <b id="livePrice2">--</b></div></div></div>
<div id="page-historico" class="page"><div id="histList"><p class="muted">Sem ciclos concluidos.</p></div></div>
<div id="page-ajustes" class="page"><div class="card"><h3>Ajustes - Todos os parametros aqui</h3>
<p class="muted">A API e o Secret NAO ficam aqui. Ficam no Render em Environment Variables. Aqui mudas o par, alavancagem e margem.</p>
<label>Par</label><select id="selected_pair">{% for p in pairs %}<option value="{{p}}" {% if p==cfg.selected_pair %}selected{% endif %}>{{p}}</option>{% endfor %}</select>
<label>Alavancagem (1 a 20)</label><input type="number" id="leverage" value="{{cfg.leverage}}">
<label>Margem por ordem USDT</label><input type="number" step="0.5" id="margin_per_order" value="{{cfg.margin_per_order}}">
<label>Espaçamento Grid (em preço) - LIVRE, só não pode ser 0</label><input type="number" step="any" id="grid_step_price" value="{{ cfg.grid_step_price if cfg.grid_step_price is defined else 20 }}"><p class="muted">Escreve o passo em preço: BTC 20 | ETH 1.5 | SOL 0.15 | OP 0.0015. Ex BTC: 64500.5 → 64520 → 64540. Ex OP: 0.7515 → 0.7530 → 0.7545.</p><label>Numero total de ordens (divide-se por 2: LONG + SHORT)</label><input type="number" step="2" min="2" max="100" id="total_orders" value="{{ cfg.total_orders if cfg.total_orders is defined else 14 }}"><p class="muted" id="splitHint">14 = 7 LONG + 7 SHORT</p><p class="muted" id="stepPctHint"></p>

<label>Meta % (lucro para fechar ciclo)</label><input type="number" step="0.1" id="target_profit_pct" value="{{cfg.target_profit_pct}}">
<label>Modo</label><select id="auto_mode"><option value="false" {% if not cfg.auto_mode %}selected{% endif %}>Manual</option><option value="true" {% if cfg.auto_mode %}selected{% endif %}>Automatico</option></select>
<label>N Operacoes Auto</label><input type="number" id="max_auto_operations" value="{{cfg.max_auto_operations}}" min="1" max="50">
<button class="btn btn-blue" onclick="saveSettings()">Guardar Definicoes</button>
<p class="muted">Saldo real: com Margem 5 precisas de 15 USDT minimo em Futuros (2 ordens x 5). Ideal: 50 USDT. Se so tens 5 USDT, usa Margem 1.0.</p>
</div></div>
</div>
<script>
function showPage(n,btn){document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+n).classList.add('active');document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));btn.classList.add('active')}
async function saveSettings(){const p={selected_pair:document.getElementById('selected_pair').value,leverage:parseInt(document.getElementById('leverage').value),margin_per_order:parseFloat(document.getElementById('margin_per_order').value),grid_step_price:parseFloat(document.getElementById('grid_step_price').value),total_orders:parseInt(document.getElementById('total_orders').value),target_profit_pct:parseFloat(document.getElementById('target_profit_pct').value),auto_mode:document.getElementById('auto_mode').value==='true',max_auto_operations:parseInt(document.getElementById('max_auto_operations').value)};const r=await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});alert(r.ok?'Guardado!':'Erro ao guardar');}
async function controlBot(a){const r=await fetch('/api/'+a,{method:'POST'});const d=await r.json();alert(a==='start'?'A iniciar... aguarda 5s e ve o Dashboard. Se ficar PARADO, le a mensagem de Status.':'Parado.');updateStatus()}
function fmtQ(q){if(q==null)return '--';var s=Number(q).toFixed(8);return s.replace(/\.?0+$/,'')||'0';}
function fmtP(p){if(!p&&p!==0)return '--';if(p<1)return p.toFixed(4);if(p<10)return p.toFixed(3);return p.toFixed(2);}
let _running=false;async function toggleBot(){await controlBot(_running?'stop':'start');}
async function updateStatus(){try{const r=await fetch('/api/status');const d=await r.json();document.getElementById('sync').innerText='Atualizado: '+new Date().toLocaleTimeString('pt-PT');document.getElementById('equity').innerText=(d.equity||0).toFixed(2)+' USDT';document.getElementById('equity0').innerText=(d.cycle_equity||d.equity||0).toFixed(2)+' USDT';document.getElementById('statusMsg').innerText=d.status_message;document.getElementById('statusTxt').innerText=d.is_running?'OPERANDO':'PARADO';document.getElementById('statusTxt').className='big '+(d.is_running?'green':'red');_running=!!d.is_running;var pb=document.getElementById('powerBtn');if(pb){pb.innerText=d.is_running?'PARAR ROBO':'INICIAR ROBO';pb.className='btn '+(d.is_running?'btn-stop':'btn-start');}document.getElementById('activePair').innerText=d.active_symbol||d.selected_pair||'BTC/USDT:USDT';document.getElementById('pnlTxt').innerText=(d.net_pnl>=0?'+':'')+(d.net_pnl||0).toFixed(4);document.getElementById('cofre').innerText=(d.cofre||0).toFixed(4)+' USDT';document.getElementById('cofreG').innerText=(d.cofre_global||0).toFixed(4)+' USDT';document.getElementById('refP').innerText=d.reference_price?d.reference_price.toFixed(2):'--';document.getElementById('livePrice').innerText=d.last_price?d.last_price.toFixed(2):(d.reference_price?d.reference_price.toFixed(2):'--');document.getElementById('livePrice2').innerText=d.last_price?d.last_price.toFixed(2):'--';const b=document.getElementById('modeBadge');if(d.paper_trading){b.innerText='PAPEL';b.className='badge badge-paper';}else{b.innerText='REAL';b.className='badge badge-real';}document.getElementById('livePriceTop').innerText=d.last_price?fmtP(d.last_price):'--';document.getElementById('refTop').innerText=d.reference_price?fmtP(d.reference_price):'--';document.getElementById('priceArrow').innerText=d.price_dir==='up'?'▲ A SUBIR':(d.price_dir==='down'?'▼ A DESCER':'— ESTAVEL');document.getElementById('priceArrow').style.color=d.price_dir==='up'?'#22c55e':(d.price_dir==='down'?'#ef4444':'#94a3b8');document.getElementById('pnlTxt').innerText=((d.live_total||0)>0?'+':'')+(d.live_total||0).toFixed(4)+' USDT';document.getElementById('pnlTxt').style.color=(d.live_total||0)>0?'#22c55e':((d.live_total||0)<0?'#ef4444':'#94a3b8');document.getElementById('liveCards').innerHTML=(d.live_orders||[]).map(o=>{const p=o.pnl_live||0;const col=p>0?'#22c55e':(p<0?'#ef4444':'#94a3b8');const nome=o.side==='buy'?'LONG':'SHORT';const verbo=o.side==='buy'?(d.price_dir==='up'?'a ganhar porque o preco SOBE':(d.price_dir==='down'?'a perder porque o preco DESCE':'estavel')):(d.price_dir==='down'?'a ganhar porque o preco DESCE':(d.price_dir==='up'?'a perder porque o preco SOBE':'estavel'));return `<div style="background:#0b1220;border:1px solid #1e293b;border-radius:12px;padding:10px;margin-top:8px"><b>${nome}</b> Entrada ${fmtP(o.entry_price)} Qty ${fmtQ(o.qty)}<br><b style="color:${col}">${p>0?'+':''}${p.toFixed(4)} USDT ${p>0?'▲ POSITIVO':(p<0?'▼ NEGATIVO':'— NEUTRO')}</b></div>`;}).join('')||'';
var _hlist=(d.history||[]);var _orders=_hlist.filter(function(h){return !h.ciclo;});var _lo=_orders.filter(function(h){return h.side==='buy';});var _sh=_orders.filter(function(h){return h.side==='sell';});var _tl=_lo.reduce(function(s,h){return s+Number(h.profit||0);},0);var _ts=_sh.reduce(function(s,h){return s+Number(h.profit||0);},0);var _tot=_tl+_ts;document.getElementById('histList').innerHTML='<div class=card><h3>Total fechado: '+(_tot>=0?'+':'')+_tot.toFixed(4)+' USDT | '+_orders.length+' ordens</h3><p>LONG: '+(_tl>=0?'+':'')+_tl.toFixed(4)+' USDT | '+_lo.length+' ordens</p><p>SHORT: '+(_ts>=0?'+':'')+_ts.toFixed(4)+' USDT | '+_sh.length+' ordens</p></div>';return '<div class=hist-item><b>'+(h.side==='buy'?'LONG':'SHORT')+'</b> '+fmtP(h.entry)+' → '+fmtP(h.close)+' | Lucro: <b style=color:'+(Number(h.profit)>=0?'#22c55e':'#ef4444')+'>'+(Number(h.profit)>=0?'+':'')+Number(h.profit).toFixed(4)+' USDT</b><br><span class=muted>'+_d+' | '+(h.reason||'')+'</span></div>';}).join(''):'<p class=muted>Sem ordens fechadas ainda.</p>');
try{var _to=document.getElementById('total_orders');if(_to){var _v=parseInt(_to.value)||14;var _h=document.getElementById('splitHint');if(_h)_h.innerText=_v+' = '+Math.floor(_v/2)+' LONG + '+Math.floor(_v/2)+' SHORT';}var _sp=document.getElementById('stepPctHint');var _si=document.getElementById('grid_step_price');if(_sp&&_si&&d.last_price){var _sv=parseFloat(_si.value)||0;_sp.innerText='Passo '+_sv+' = '+(_sv/Number(d.last_price)*100).toFixed(4)+'% do preco atual ('+fmtP(d.last_price)+') | 1a ordem a '+(_sv/2)+' da Ref';}}catch(e){}try{renderGrid(d)}catch(e){console.log('grid',e)}}catch(e){document.getElementById('sync').innerText='Sem ligacao ao servidor - verifica o Render.';}}
function renderGrid(d){try{var refEl=document.getElementById('refLine');if(refEl){refEl.innerText='— Ref: '+(d.reference_price?Number(d.reference_price).toFixed(4):'--')+' • Preço: '+(d.last_price?Number(d.last_price).toFixed(2):'--')+' —';}var orders=Array.isArray(d.orders)?d.orders:[];var longs=orders.filter(function(o){return o.side==='buy'}).sort(function(a,b){return a.entry_price-b.entry_price});var shorts=orders.filter(function(o){return o.side==='sell'}).sort(function(a,b){return b.entry_price-a.entry_price});function fmt(o){var tgt=(o.target_price!=null)?Number(o.target_price).toFixed(4):'--';var tp=(o.target_profit!=null)?Number(o.target_profit).toFixed(4):'0.0100';var cls=o.status==='PENDING'?'yellow':(o.status==='ACTIVE'?'green':'red');return '<div class="grid-row"><span>'+String(o.id).replace('GRID_','')+' • '+Number(o.entry_price).toFixed(4)+' → '+tgt+'</span><span class="'+cls+'">'+o.status+' • +'+tp+'</span></div>';}var lc=document.getElementById('longCol');if(lc){lc.innerHTML=longs.length?longs.map(fmt).join(''):'<p class="muted">Sem LONG</p>';}var sc=document.getElementById('shortCol');if(sc){sc.innerHTML=shorts.length?shorts.map(fmt).join(''):'<p class="muted">Sem SHORT</p>';}}catch(e){console.log('grid',e)}}
setInterval(updateStatus,2000);updateStatus();
</script></body></html>
"""
@app.route("/")
@requires_auth
def index(): return render_template_string(HTML, cfg=cfg, pairs=TOP_PAIRS)
@app.route("/api/settings", methods=["POST"])
@requires_auth
def update_settings():
    # V5 - Ajustes LIVRES para quem esta a operar. Sem barreiras. Unica regra: espacamento != 0.
    try:
        d=request.json or {}
        if "selected_pair" in d and d["selected_pair"] in TOP_PAIRS:
            _np=d["selected_pair"]; cfg.selected_pair=_np
            if cfg.is_running and cfg.active_symbol and cfg.active_symbol!=_np:
                try: engine.switch_pair(_np)
                except Exception as _e: print("switch err", _e)
        if "leverage" in d:
            try: cfg.leverage=int(d["leverage"])
            except Exception: pass
        if "margin_per_order" in d:
            try: cfg.margin_per_order=float(d["margin_per_order"])
            except Exception: pass
        if "grid_step_price" in d:
            v=float(d["grid_step_price"])
            if v==0: return jsonify({"status":"error","error":"Espacamento nao pode ser 0"}),400
            cfg.grid_step_price=abs(v)
        if "total_orders" in d:
            try:
                _t=int(d["total_orders"])
                if _t>=2: cfg.total_orders=_t
            except Exception: pass
        if "trailing_offset_pct" in d:
            try: cfg.trailing_offset_pct=float(d["trailing_offset_pct"])
            except Exception: pass
        if "target_profit_pct" in d:
            try: cfg.target_profit_pct=float(d["target_profit_pct"])
            except Exception: pass
        if "auto_mode" in d: cfg.auto_mode=bool(d["auto_mode"])
        if "max_auto_operations" in d:
            try: cfg.max_auto_operations=int(d["max_auto_operations"])
            except Exception: pass
        return jsonify({"status":"ok"})
    except Exception as e: return jsonify({"status":"error","error":str(e)}),400
def switch_pair():
    try:
        d=request.json or {}
        npair=d.get("selected_pair") or d.get("pair")
        if npair not in TOP_PAIRS: return jsonify({"status":"error","error":"par invalido"}),400
        res=engine.switch_pair(npair)
        return jsonify({"status":"ok","result":res,"active":cfg.active_symbol})
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
    # V5 WATCHDOG: se o motor esta a correr mas o loop de fundo esta parado ha +5s (Render Free dorme),
    # o proprio pedido do Dashboard (de 2 em 2s) da o tick. O preco a passar uma entrada REAGE na hora.
    try:
        if cfg.is_running and (time.time()-getattr(engine,"last_tick_time",0)>5):
            engine.tick()
    except Exception as _e: print("watchdog tick", _e)
    # FIX ESTATICO: busca preco FRESCO a cada pedido, nao usa last_price parado
    _sym = cfg.active_symbol or cfg.selected_pair
    last_price = 0
    ticker_err = ""
    try:
        _t = ex_manager.fetch_ticker(_sym)
        last_price = float(_t.get("last",0) or 0)
        if last_price>0:
            engine.prev_price = engine.last_price if getattr(engine,"last_price",0)>0 else last_price
            engine.last_price = last_price
    except Exception as e:
        ticker_err = str(e)
        last_price = getattr(engine,"last_price",0) or engine.reference_price or 0
    if False:
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
    # PNL vivo com preco fresco
    live_orders=[]; live_total=0.0
    for _o in (engine.orders_state or []):
        if _o.get("status")!="ACTIVE": continue
        _pnl = ((_o["entry_price"]-last_price) if _o.get("side")=="sell" else (last_price-_o["entry_price"]))*float(_o.get("qty",0))
        live_total+=_pnl
        _oo=dict(_o); _oo["pnl_live"]=round(_pnl,4); _oo["price_now"]=last_price; _oo["is_profit"]=_pnl>0
        live_orders.append(_oo)
    live_total=round(live_total,4)
    if getattr(cfg,'paper_trading',False):
        equity=(cfg.cycle_initial_equity or cfg.paper_initial_balance)+cfg.cofre+live_total
    # TOTAL AGORA = fechadas (Cofre) + flutuante
    net=(equity-cfg.cycle_initial_equity) if (cfg.is_running and cfg.cycle_initial_equity>0) else 0.0
    price_dir="flat"
    if getattr(engine,"last_price",0) and getattr(engine,"prev_price",0):
        price_dir="up" if engine.last_price>engine.prev_price else ("down" if engine.last_price<engine.prev_price else "flat")
    return jsonify({"is_running":cfg.is_running,"active_symbol":cfg.active_symbol,"selected_pair":cfg.selected_pair,"equity":equity,"cycle_equity":cfg.cycle_initial_equity,"live_orders":live_orders,"live_total":live_total,"price_dir":price_dir,"tick_age":round(time.time()-getattr(engine,"last_tick_time",0),1),
        "net_pnl":net,"completed_operations":cfg.completed_operations,"max_auto_operations":cfg.max_auto_operations,
        "auto_mode":cfg.auto_mode,"status_message":cfg.status_message,"orders":engine.orders_state,
        "cofre":cfg.cofre,"cofre_global":cfg.cofre_global,"reference_price":engine.reference_price,"last_price":last_price,
        "paper_trading":cfg.paper_trading,"paper_equity":engine.paper_equity,"history":getattr(engine,"history",[]),
        "leverage":cfg.leverage,"total_orders":cfg.total_orders,"per_side":getattr(engine,"per_side",7),"first_dist":getattr(engine,"first_dist",0),"grid_step":getattr(engine,"grid_step",cfg.grid_step_price),"margin_per_order":cfg.margin_per_order,"ticker_err":ticker_err})
@app.route("/health")
def health(): return jsonify({"status":"ok"})
if __name__=="__main__":
    port=int(os.getenv("PORT","5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
