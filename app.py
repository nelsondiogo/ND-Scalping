# app.py - ND-SCALPING V6 - Frontend + API compativel com trading.py
# Resolve "Sem ligacao ao servidor": expoe /api/status, /status, /health que o frontend usa.
from flask import Flask, jsonify, request, render_template_string
from trading import MinimalistGridEngine, fetch_price
import threading

app = Flask(__name__)
engine = MinimalistGridEngine()
try:
    engine.start_background_loop()
except Exception:
    pass

HTML = r"""<!doctype html><html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ND-SCALPING</title><style>
body{background:#0b1220;color:#e8eef5;font-family:system-ui,Arial,sans-serif;margin:0;padding:0}
.top{padding:14px 16px;background:#0a0f1a;border-bottom:1px solid #1e2a3a}
.top b{color:#22c55e;font-size:22px}.badge{background:#f59e0b;color:#000;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:800}
.sub{color:#9fb0c3;font-size:13px;margin-top:4px}.sub.ok{color:#22c55e}.sub.err{color:#f87171}
.card{background:#132033;border:1px solid #1e2a3a;border-radius:14px;margin:12px;padding:14px}
.card h3{color:#38bdf8;margin:0 0 8px;font-size:14px;letter-spacing:1px}
.big{font-size:26px;font-weight:800}.mut{color:#9fb0c3;font-size:13px}
.row{display:flex;gap:10px}.col{flex:1;background:#132033;border:1px solid #1e2a3a;border-radius:14px;margin:0 0 0 12px;padding:12px}.col:last-child{margin-right:12px}
button{padding:12px 16px;border:0;border-radius:10px;font-weight:800;cursor:pointer;font-size:14px}
.btn-start{background:#22c55e;color:#000}.btn-stop{background:#ef4444;color:#fff}
.tabs{position:fixed;bottom:0;left:0;right:0;background:#0a0f1a;display:flex;gap:8px;padding:10px;justify-content:center;border-top:1px solid #1e2a3a}
.tabs button{background:#1e2a3a;color:#cbd5e1}.tabs button.on{background:#22c55e;color:#000}
section{display:none}section.on{display:block}.pad{padding-bottom:80px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#fff;margin:4px 0 10px}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{padding:6px;border-bottom:1px solid #1e2a3a;text-align:left}
.pos{color:#22c55e}.neg{color:#ef4444}
</style></head><body><div class="pad">
<div class="top"><b>ND-SCALPING</b> <span class="badge">PAPEL</span><div class="sub" id="conn">A ligar ao servidor...</div></div>

<section id="tab-dashboard" class="on">
<div class="card"><h3>STATUS</h3><div class="big" id="status">PARADO</div><div class="mut" id="statusline">A aguardar...</div><div style="margin-top:10px"><button class="btn-start" onclick="startBot()">▶ INICIAR</button> <button class="btn-stop" onclick="stopBot()">■ PARAR</button></div></div>
<div class="row"><div class="col"><h3>INICIAL</h3><div class="big" id="inicial">--</div></div><div class="col"><h3>ATUAL</h3><div class="big" id="atual">--</div></div></div>
<div class="card"><h3>POSICAO ATUAL - AO VIVO</h3><div class="mut" id="posline">Preco agora: -- | Ref: --</div><div style="margin-top:8px"><b id="total">TOTAL AGORA: +0.0000</b> | Cofre ciclo: <span id="cofre_ciclo">0.0000</span> | Cofre global: <span id="cofre_global">0.0000</span></div><div class="mut" style="margin-top:8px">LONG ganha quando o preco SOBE. SHORT ganha quando o preco DESCE.</div></div>
<div class="card"><h3>GRID — REF NO CENTRO</h3><div class="mut">Nao importa a direcao, o robo sempre ganha ate ao lucro definido. Sobe → fecha LONG. Desce → fecha SHORT. Vai e volta → fecha dos dois lados.</div><div style="text-align:center;margin:12px 0;color:#facc15">--- Ref: <span id="ref">--</span> ---</div><div style="display:flex;gap:10px"><div style="flex:1;background:#3a1414;padding:10px;border-radius:10px;color:#f87171">▼ SHORT — ABAIXO DA REF</div><div style="flex:1;background:#12331f;padding:10px;border-radius:10px;color:#22c55e">▲ LONG — ACIMA DA REF</div></div></div>
</section>

<section id="tab-mercado">
<div class="card"><h3>MERCADO - GRAFICO EM TEMPO REAL</h3><div class="mut">Preco atual: <span id="m_preco">--</span> | Ref (entrada): <span id="m_ref">--</span></div><canvas id="chart" width="340" height="180" style="width:100%;background:#0a0f1a;border-radius:10px;margin-top:10px"></canvas><div class="mut" style="margin-top:8px">Linha amarela no meio = Ref. Linha azul = preco. Ultimos ~4 minutos.</div></div>
<div class="card"><h3>MERCADO - POSICOES ATIVAS</h3><div id="ativas">Preco atual: --</div></div>
</section>

<section id="tab-historico">
<div class="card"><h3>HISTORICO</h3><div id="hist">Sem ciclos concluidos.</div></div>
</section>

<section id="tab-ajustes">
<div class="card"><h3>AJUSTES</h3><div class="mut">Trava: 0.002 bruto, sem % , 1 tick contra fecha. Trava esta no codigo, nao nos Ajustes.</div>
<label>Par (ex: BTC/USDT)</label><input id="par" value="BTC/USDT">
<label>Margem USDT</label><input id="margem" value="5">
<label>Alavancagem</label><input id="lev" value="3">
<label>Passo (GRID_STEP)</label><input id="step" value="20">
<div class="mut">Os Ajustes sao informativos nesta versao. Para mudar, altera as variaveis no Render.</div></div>
</section>
</div>
<div class="tabs"><button class="on" onclick="show('dashboard',this)">Dashboard</button><button onclick="show('mercado',this)">Mercado</button><button onclick="show('historico',this)">Historico</button><button onclick="show('ajustes',this)">Ajustes</button></div>
<script>
let hist=[];let prices=[];
function show(t,btn){document.querySelectorAll('section').forEach(s=>s.classList.remove('on'));document.getElementById('tab-'+t).classList.add('on');document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));btn.classList.add('on');}
function fmt(v){return (v==null||v===undefined)?'--':Number(v).toFixed(2)}
function fmt4(v){return (v==null)?'0.0000':Number(v).toFixed(4)}
async function refresh(){
  try{
    const r=await fetch('/api/status'); if(!r.ok) throw new Error('HTTP '+r.status);
    const d=await r.json();
    document.getElementById('conn').textContent='Ligado ao servidor ✓'; document.getElementById('conn').className='sub ok';
    const price=d.price ?? d.current_price ?? 0;
    const ref=d.ref ?? null;
    document.getElementById('status').textContent=d.running?'A CORRER':'PARADO';
    document.getElementById('statusline').textContent='Par: BTC/USDT:USDT | Preco atual: '+fmt(price)+' | Ref: '+fmt(ref)+' | Modo: PAPEL';
    document.getElementById('inicial').textContent=fmt(d.initial ?? d.balance);
    document.getElementById('atual').textContent=fmt(d.balance);
    document.getElementById('posline').textContent='Preco agora: '+fmt(price)+' | Ref: '+fmt(ref);
    document.getElementById('total').textContent='TOTAL AGORA: '+fmt4(d.vantagem);
    document.getElementById('cofre_ciclo').textContent=fmt4(d.cofre_ciclo);
    document.getElementById('cofre_global').textContent=fmt4(d.cofre_global);
    document.getElementById('ref').textContent=fmt(ref);
    document.getElementById('m_preco').textContent=fmt(price);
    document.getElementById('m_ref').textContent=fmt(ref);
    const act=d.actives||[];
    document.getElementById('ativas').innerHTML = act.length? ('Preco atual: '+fmt(price)+'<br>'+act.map(a=>'<div>'+(a.side=='buy'?'LONG':'SHORT')+' '+fmt(a.entry)+' → '+fmt(price)+' | Bruto '+fmt4(a.gross)+' | Liquido '+fmt4(a.net)+' '+(a.armed?'🔒 TRAVA ARMADA':'')+'</div>').join('')) : ('Preco atual: '+fmt(price)+'<br>Sem posicoes ativas.');
    const h=d.history||[];
    document.getElementById('hist').innerHTML = h.length? ('<table><tr><th>Lado</th><th>Entrada</th><th>Saida</th><th>Lucro</th><th>Motivo</th></tr>'+h.slice(-20).reverse().map(x=>'<tr><td>'+x.side+'</td><td>'+fmt(x.entry)+'</td><td>'+fmt(x.exit)+'</td><td class="'+(x.profit>=0?'pos':'neg')+'">'+fmt4(x.profit)+'</td><td>'+x.motivo+'</td></tr>').join('')+'</table>') : 'Sem ciclos concluidos.';
    if(price>0){prices.push(price); if(prices.length>120) prices.shift(); draw();}
  }catch(e){ document.getElementById('conn').textContent='Sem ligacao ao servidor - verifica o Render. ('+e.message+')'; document.getElementById('conn').className='sub err'; }
}
function draw(){
  const c=document.getElementById('chart'); const ctx=c.getContext('2d'); ctx.clearRect(0,0,c.width,c.height);
  if(prices.length<2) return; const mn=Math.min(...prices), mx=Math.max(...prices), rng=(mx-mn)||1;
  ctx.strokeStyle='#38bdf8'; ctx.beginPath();
  prices.forEach((p,i)=>{const x=i/(prices.length-1)*c.width; const y=c.height-((p-mn)/rng)*(c.height-20)-10; i?ctx.lineTo(x,y):ctx.moveTo(x,y);}); ctx.stroke();
}
async function startBot(){ await fetch('/api/start',{method:'POST'}); refresh(); }
async function stopBot(){ await fetch('/api/stop',{method:'POST'}); refresh(); }
setInterval(refresh,2000); refresh();
</script></body></html>"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/health")
def health():
    return jsonify({"ok": True, "connected": True})

@app.route("/status")
def status_alias():
    try:
        return jsonify(engine.get_state())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/status")
def api_status():
    try:
        s = engine.get_state()
        s["ok"] = True
        s["connected"] = True
        return jsonify(s)
    except Exception as e:
        return jsonify({"ok": False, "connected": False, "error": str(e)}), 500

@app.route("/api/start", methods=["POST"])
def api_start():
    try:
        p = None
        try:
            p = fetch_price()
        except Exception:
            pass
        if not p:
            p = engine.get_state().get("price") or 64000
        engine.start_cycle(float(p), ref=float(p))
        return jsonify({"ok": True, "price": p})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/stop", methods=["POST"])
def api_stop():
    try:
        p = engine.get_state().get("price") or 0
        engine.stop_cycle(float(p))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=False)
