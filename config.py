import os
from dotenv import load_dotenv
load_dotenv()

TOP_PAIRS = [
    "BTC/USDT:USDT","ETH/USDT:USDT","SOL/USDT:USDT","BNB/USDT:USDT",
    "XRP/USDT:USDT","ADA/USDT:USDT","AVAX/USDT:USDT","LINK/USDT:USDT",
    "SUI/USDT:USDT","NEAR/USDT:USDT","DOT/USDT:USDT","LTC/USDT:USDT",
    "UNI/USDT:USDT","APT/USDT:USDT","ARB/USDT:USDT","OP/USDT:USDT",
    "ATOM/USDT:USDT","FIL/USDT:USDT","ICP/USDT:USDT","RENDER/USDT:USDT"
]

class BotConfig:
    def __init__(self):
        self.api_key = os.getenv("BYBIT_API_KEY","")
        self.api_secret = os.getenv("BYBIT_API_SECRET","")
        self.testnet = os.getenv("BYBIT_TESTNET","False").lower()=="true"
        # === MODO PAPEL - NOVO V3 ===
        # True = SIMULA com preço real, NÃO envia ordens reais, NÃO mexe no saldo real
        # False = OPERA A SÉRIO com dinheiro real
        self.paper_trading = os.getenv("PAPER_TRADING","True").lower()=="true"
        self.paper_initial_balance = float(os.getenv("PAPER_INITIAL_BALANCE","1000.0"))
        # Capital
        self.leverage = int(os.getenv("LEVERAGE","3"))
        self.margin_per_order = float(os.getenv("MARGIN_PER_ORDER","5.0"))
        self.trailing_offset_pct = float(os.getenv("TRAILING_PCT","0.0025"))  # 0.25%
        self.ref_tolerance_pct = float(os.getenv("REF_TOL_PCT","0.0005"))
        self.target_profit_pct = float(os.getenv("TARGET_PCT","1.0"))
        self.max_loss_pct = float(os.getenv("MAX_LOSS_PCT","2.0"))
        # Reancoragem
        self.reanchor_distance_pct = float(os.getenv("REANCHOR_DIST_PCT","0.03"))
        self.reanchor_time_sec = int(os.getenv("REANCHOR_TIME_SEC","3600"))
        self.reanchor_min_distance_pct = float(os.getenv("REANCHOR_MIN_DIST_PCT","0.015"))
        self.fee_rate = 0.00055
        # Ciclo
        self.auto_mode = False
        self.max_auto_operations = 3
        self.completed_operations = 0
        self.selected_pair = TOP_PAIRS[0]
        self.is_running = False
        self.active_symbol = None
        self.cycle_initial_equity = 0.0
        self.status_message = "Aguardando Start Manual"
        self.pair_index = 0
        self.cofre = 0.0
        self.cofre_global = 0.0
        # GRID - Espacamento entre ordens (Ajustes, volatilidade) | OP 0.65% | SOL 0.40% | BTC 0.15% | ETH 0.25%
        # GRID V5 - Espacamento em PRECO, LIVRE. Unica regra: nao pode ser 0. Ex BTC 20 | ETH 1.5 | SOL 0.15 | OP 0.0015
        self.grid_step_price = float(os.getenv("GRID_STEP_PRICE","40.0"))  # V6: passo 40 para BTC (primeira ordem a 20 da Ref)
        self.total_orders = int(float(os.getenv("TOTAL_ORDERS","14")))  # V6: total = 14 -> 7 LONG + 7 SHORT
        self.paper_fee_rate = 0.0001  # V6: taxa maker simulada no papel
        self.grid_spacing_pct = float(os.getenv("GRID_SPACING_PCT","0.0065"))  # mantido por compatibilidade, ja nao e usado
        self.grid_orders_per_side = 5
        self.admin_password = os.getenv("ADMIN_PASSWORD","admin123")
