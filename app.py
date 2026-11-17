from flask import Flask, jsonify, request, render_template_string
from config import BotConfig
from exchange_management import BybitExchangeManager
from trading import TradingEngine

app = Flask(__name__)
cfg = BotConfig()
exchange = BybitExchangeManager(cfg)
engine = TradingEngine(cfg, exchange)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ND-SCALPING</title>
<style>
body { background: #0b1220; color: #eef2f7; font-family: sans-serif; margin: 0; padding: 16px; }
h1 { font-size: 17px; margin: 0 0 12px 0; }
.big { font-size: 16px; font-weight: 700; }
.card { background: #111a2e; border: 1px solid #24344f; border-radius: 12px; padding: 14px; margin-bottom: 12px; }
button { font-size: 14px; padding: 10px 14px; border: 0; border-radius: 9px; background: #22c55e; color: #06110a; font-weight: 700; }
button.secondary { background: #24344f; color: #eef2f7; }
.tabs { display: flex; gap: 8px; margin-bottom: 12px; }
.tab { font-size: 14px; padding: 9px 12px; border-radius: 999px; background: #16213a; cursor: pointer; }
.tab.active { background: #22c55e; color: #06110a; font-weight: 700; }
.badge { display: inline-block; font-size: 12px; padding: 4px 9px; border-radius: 999px; background: #f59e0b; color: #1a1000; font-weight: 700; }
.history-row { display: flex; flex-wrap: wrap; gap: 8px; padding: 10px 0; border-top: 1px solid #24344f; font-size: 14px; }
</style>
</head>
<body>
<h1>ND-SCALPING <span class="badge" id="modeBadge">PAPEL</span></h1>
<div class="tabs">
<div class="tab active" data-tab="dashboard">Dashboard</div>
<div class="tab" data-tab="mercado">Mercado</div>
<div class="tab" data-tab="historico">Historico</div>
<div class="tab" data-tab="ajustes">Ajustes</div>
</div>
<div id="dashboard" class="panel">
<div class="card"><div class="big" id="status">Aguardando Start Manual</div><div id="pair">BTC/USDT:USDT</div></div>
<div class="card"><button onclick="startBot()">Start</button> <button class="secondary" onclick="stopBot()">Stop</button></div>
</div>
<div id="mercado" class="panel" style="display:none"><div class="card"><div class="big">Mercado</div><div id="marketInfo">A aguardar dados.</div></div></div>
<div id="historico" class="panel" style="display:none"><div class="card"><div class="big">Historico por ciclo</div><div id="historyList"></div></div></div>
<div id="ajustes" class="panel" style="display:none"><div class="card"><div class="big">Ajustes</div><div>Modo papel / real e parametros no servidor.</div></div></div>
<script>
var tabs = document.querySelectorAll('.tab');
tabs.forEach(function(tab) {
  tab.addEventListener('click', function() {
    tabs.forEach(function(t) { t.classList.remove('active'); });
    tab.classList.add('active');
    document.querySelectorAll('.panel').forEach(function(p) { p.style.display = 'none'; });
    document.getElementById(tab.dataset.tab).style.display = 'block';
  });
});
function renderHistory(history) {
  var list = document.getElementById('historyList');
  if (!history || !history.length) { list.innerHTML = '<p>Sem ciclos concluidos.</p>'; return; }
  list.innerHTML = '';
  history.forEach(function(item) {
    var row = document.createElement('div');
    row.className = 'history-row';
    row.textContent = 'Ciclo ' + item.ciclo + ' - ' + item.par + ' - Total ' + item.total + ' - LONG ' + item.long + ' - SHORT ' + item.short + ' - Vencedor ' + item.vencedor;
    list.appendChild(row);
  });
}
function loadStatus() {
  fetch('/api/status').then(function(r) { return r.json(); }).then(function(data) {
    document.getElementById('status').textContent = data.status_message || '';
    document.getElementById('pair').textContent = data.selected_pair || '';
    document.getElementById('modeBadge').textContent = data.paper_trading ? 'PAPEL' : 'REAL';
    renderHistory(data.history || []);
  });
}
function startBot() { fetch('/api/start', {method: 'POST'}).then(loadStatus); }
function stopBot() { fetch('/api/stop', {method: 'POST'}).then(loadStatus); }
loadStatus();
setInterval(loadStatus, 5000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        if "selected_pair" in data:
            cfg.selected_pair = str(data["selected_pair"])
        if "margin_per_order" in data:
            cfg.margin_per_order = float(data["margin_per_order"])
        return jsonify({"ok": True, "selected_pair": cfg.selected_pair})
    return jsonify({
        "selected_pair": cfg.selected_pair,
        "leverage": cfg.leverage,
        "margin_per_order": cfg.margin_per_order,
        "paper_trading": cfg.paper_trading,
    })

@app.route("/api/start", methods=["POST"])
def start():
    cfg.is_running = True
    cfg.status_message = "A correr"
    return jsonify({"ok": True, "is_running": True})

@app.route("/api/stop", methods=["POST"])
def stop():
    cfg.is_running = False
    cfg.status_message = "Parado"
    return jsonify({"ok": True, "is_running": False})

@app.route("/api/status")
def status():
    return jsonify({
        "is_running": cfg.is_running,
        "status_message": cfg.status_message,
        "selected_pair": cfg.selected_pair,
        "paper_trading": cfg.paper_trading,
        "cofre": cfg.cofre,
        "cofre_global": cfg.cofre_global,
        "cycle": engine.cycle,
        "history": engine.history,
        "hist_long": engine.hist_long_pnl,
        "hist_short": engine.hist_short_pnl,
    })

@app.route("/health")
def health():
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
