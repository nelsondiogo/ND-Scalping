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
        self.testnet = os.getenv("BYBIT_TESTNET","True").lower()=="true"
        # Capital
        self.leverage = int(os.getenv("LEVERAGE","5"))
        self.margin_per_order = float(os.getenv("MARGIN_PER_ORDER","5.0"))
        # Trailing - MINIMO VIAVEL 0.25% por causa das taxas
        self.trailing_offset_pct = float(os.getenv("TRAILING_PCT","0.0025"))
        self.ref_tolerance_pct = float(os.getenv("REF_TOL_PCT","0.0005"))  # 0.05%
        # Meta / Stop Global sobre Equity0
        self.target_profit_pct = float(os.getenv("TARGET_PCT","1.0"))
        self.max_loss_pct = float(os.getenv("MAX_LOSS_PCT","2.0"))
        # Reancoragem - REGRA CLARA V2
        self.reanchor_distance_pct = float(os.getenv("REANCHOR_DIST_PCT","0.03"))  # 3%
        self.reanchor_time_sec = int(os.getenv("REANCHOR_TIME_SEC","3600"))  # 60 min
        self.reanchor_min_distance_pct = float(os.getenv("REANCHOR_MIN_DIST_PCT","0.015"))  # 1.5% p/ tempo
        self.fee_rate = 0.00055  # taker Bybit
        # Ciclo
        self.auto_mode = False
        self.max_auto_operations = 3
        self.completed_operations = 0
        # Estado
        self.selected_pair = TOP_PAIRS[0]
        self.is_running = False
        self.active_symbol = None
        self.cycle_initial_equity = 0.0
        self.status_message = "Aguardando Start Manual"
        self.pair_index = 0
        # GRID V3 - Espacamento entre ordens (define em Ajustes, com base na volatilidade)
        # OP 0.65% | SOL 0.40% | BTC 0.15% | ETH 0.25% - quanto maior a volatilidade, maior o espacamento
        self.grid_spacing_pct = float(os.getenv("GRID_SPACING_PCT","0.0065"))  # 0.65%
        self.grid_orders_per_side = 5
        self.grid_target_profit = float(os.getenv("GRID_TARGET_PROFIT","0.01"))  # lucro alvo por ordem fechada (so para exibicao, o real e passo*qty)
        # Cofre - lucro acumulado do ciclo
        self.cofre = 0.0
        self.cofre_global = 0.0
        # Auth UI
        self.admin_password = os.getenv("ADMIN_PASSWORD","admin123")
