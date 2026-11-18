import time, threading, logging, json, os
from config import TOP_PAIRS
logger = logging.getLogger("ND-Trading")
STATE_FILE = "state.json"

class MinimalistGridEngine:
    def __init__(self, exchange_manager, config):
        self.ex=exchange_manager; self.cfg=config
        self.reference_price=0.0
        self.orders_state=[]  # [{id,side,position_idx,entry_price,best_price,qty,status}]
        self.lock=threading.Lock()
        self._thread=None
        self.last_ref_touch=time.time()
        self.cycle_start_time=0
        self._load_state()

    # ---------- persistencia ----------
    def _save_state(self):
        try:
            data={"ref":self.reference_price,"orders":self.orders_state,
                  "active":self.cfg.active_symbol,"equity0":self.cfg.cycle_initial_equity,
                  "cofre":self.cfg.cofre,"cofre_global":self.cfg.cofre_global,
                  "last_touch":self.last_ref_touch,"cycle_start":self.cycle_start_time,
                  "is_running":self.cfg.is_running}
            with open(STATE_FILE,"w") as f: json.dump(data,f)
        except Exception as e: logger.error(f"save_state: {e}")
    def _load_state(self):
        if not os.path.exists(STATE_FILE): return
        try:
            with open(STATE_FILE) as f: d=json.load(f)
            self.reference_price=d.get("ref",0.0); self.orders_state=d.get("orders",[])
            self.cfg.active_symbol=d.get("active"); self.cfg.cycle_initial_equity=d.get("equity0",0)
            self.cfg.cofre=d.get("cofre",0); self.cfg.cofre_global=d.get("cofre_global",0)
            self.last_ref_touch=d.get("last_touch",time.time()); self.cycle_start_time=d.get("cycle_start",time.time())
            logger.info(f"Estado restaurado: {self.cfg.active_symbol} Ref={self.reference_price}")
        except Exception as e: logger.error(f"load_state: {e}")

    def start_background_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread=threading.Thread(target=self._run_loop,daemon=True); self._thread.start()
    def _run_loop(self):
        while True:
            try:
                if self.cfg.is_running: self.tick()
            except Exception as e: logger.error(f"tick err: {e}")
            time.sleep(1.0)  # 1s, nao 0.5s - evita rate limit

    def start_bot(self):
        with self.lock:
            self.cfg.completed_operations=0; self.cfg.is_running=True
            pair=TOP_PAIRS[self.cfg.pair_index % len(TOP_PAIRS)] if self.cfg.auto_mode else self.cfg.selected_pair
            self.initialize_cycle(pair)

    def stop_bot(self, close_all=True):
        with self.lock:
            self.cfg.is_running=False
            if close_all and self.cfg.active_symbol:
                self.close_entire_cycle(self.cfg.active_symbol, reason="Paragem Manual")
            self.cfg.active_symbol=None; self.cfg.status_message="Parado pelo Utilizador"
            self._save_state()

    def initialize_cycle(self, symbol):
        equity=self.ex.get_total_equity()
        if equity<0:
            self.cfg.is_running=False; self.cfg.status_message="Erro a ler equity - nao iniciou"; return
        required=self.cfg.margin_per_order*2
        if equity < required*1.5:
            self.cfg.is_running=False; self.cfg.status_message=f"Saldo insuficiente ({equity:.2f})"; return
        self.cfg.active_symbol=symbol; self.cfg.cycle_initial_equity=equity
        self.cfg.cofre=0.0
        self.ex.set_hedge_mode_and_leverage(symbol, self.cfg.leverage)
        try: ticker=self.ex.fetch_ticker(symbol)
        except Exception as e:
            self.cfg.is_running=False; self.cfg.status_message=f"Erro ticker: {e}"; return
        self.reference_price=float(ticker["last"])
        self.orders_state=[]; self.last_ref_touch=time.time(); self.cycle_start_time=time.time()
        qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, self.reference_price)
        if qty<=0:
            self.cfg.is_running=False; self.cfg.status_message="Qty invalido"; return
        # LONG
        o_long=self.ex.place_market_order(symbol,"buy",qty,position_idx=1)
        if o_long:
            entry=float(o_long.get("average") or o_long.get("price") or self.reference_price)
            self.orders_state.append({"id":"LONG_BASE","side":"buy","position_idx":1,"entry_price":entry,"best_price":entry,"qty":qty,"status":"ACTIVE"})
        # SHORT
        o_short=self.ex.place_market_order(symbol,"sell",qty,position_idx=2)
        if o_short:
            entry=float(o_short.get("average") or o_short.get("price") or self.reference_price)
            self.orders_state.append({"id":"SHORT_BASE","side":"sell","position_idx":2,"entry_price":entry,"best_price":entry,"qty":qty,"status":"ACTIVE"})
        self.cfg.status_message=f"Operando {symbol} | Ref: {self.reference_price:.4f} | Cofre: 0"
        logger.info(f"Ciclo {symbol} Ref={self.reference_price} Equity0={equity}")
        self._save_state()

    def tick(self):
        with self.lock:
            if not self.cfg.is_running or not self.cfg.active_symbol: return
            symbol=self.cfg.active_symbol
            try: ticker=self.ex.fetch_ticker(symbol)
            except Exception: return
            current_price=float(ticker["last"])
            # 2A META / STOP GLOBAL
            equity=self.ex.get_total_equity()
            if equity<0: return  # erro de rede, nao decide nada
            if self.cfg.cycle_initial_equity>0:
                net=equity-self.cfg.cycle_initial_equity
                target=self.cfg.cycle_initial_equity*(self.cfg.target_profit_pct/100)
                maxloss=self.cfg.cycle_initial_equity*(self.cfg.max_loss_pct/100)
                if net>=target:
                    logger.info(f"META atingida +{net:.2f}")
                    self.close_entire_cycle(symbol, reason="Meta Atingida"); self._handle_post_cycle_transition(); return
                if net<=-maxloss:
                    logger.info(f"STOP GLOBAL -{net:.2f}")
                    self.close_entire_cycle(symbol, reason="Stop Global"); self.cfg.is_running=False; self.cfg.active_symbol=None; self._save_state(); return
            # 2C VERIFICA REANCORAGEM ANTES DO TRAILING (prioridade)
            if self._should_reanchor(current_price):
                self._do_reanchor(symbol, current_price); return
            # 2B TRAILING + 2C TOQUE REF
            for slot in list(self.orders_state):
                if slot["status"]=="ACTIVE": self._monitor_position(symbol, slot, current_price)
            # Toque na Ref -> Convergencia
            if abs(current_price-self.reference_price)/self.reference_price <= self.cfg.ref_tolerance_pct:
                self.last_ref_touch=time.time()
                self._check_convergence(symbol, current_price)
            self._save_state()

    def _should_reanchor(self, current_price):
        if self.reference_price<=0: return False
        dist=abs(current_price-self.reference_price)/self.reference_price
        if dist>=self.cfg.reanchor_distance_pct: return True
        elapsed=time.time()-self.last_ref_touch
        if elapsed>=self.cfg.reanchor_time_sec and dist>=self.cfg.reanchor_min_distance_pct: return True
        return False

    def _do_reanchor(self, symbol, current_price):
        logger.info(f"REANCORAGEM {symbol} Ref antiga {self.reference_price} -> nova {current_price}")
        # 1. Calcula PnL conjunto antes de fechar (via Bybit)
        live=self.ex.fetch_positions_live(symbol)
        pnl_conj=sum(p["unrealizedPnl"] for p in live)
        # 2. Fecha tudo
        self.ex.close_all_positions(symbol)
        # 3. Atualiza cofre global: cofre ciclo + pnl conjunto - taxas estimadas
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        resultado=self.cfg.cofre + pnl_conj - taxas_est
        self.cfg.cofre_global+=resultado
        logger.info(f"Reancoragem resultado: cofre {self.cfg.cofre:.2f} + pnl {pnl_conj:.2f} - taxas {taxas_est:.2f} = {resultado:.2f} | CofreGlobal {self.cfg.cofre_global:.2f}")
        # 4. Nova Ref
        self.reference_price=current_price
        self.cfg.cofre=0.0
        self.last_ref_touch=time.time(); self.cycle_start_time=time.time()
        self.orders_state=[]
        # 5. Abre novo par na nova Ref
        qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
        if qty>0:
            o1=self.ex.place_market_order(symbol,"buy",qty,position_idx=1)
            if o1:
                e=float(o1.get("average") or o1.get("price") or current_price)
                self.orders_state.append({"id":f"LONG_REANCH_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
            o2=self.ex.place_market_order(symbol,"sell",qty,position_idx=2)
            if o2:
                e=float(o2.get("average") or o2.get("price") or current_price)
                self.orders_state.append({"id":f"SHORT_REANCH_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        self.cfg.status_message=f"Reancorado {symbol} | Nova Ref: {current_price:.4f} | CofreGlobal: {self.cfg.cofre_global:.2f}"
        self._save_state()

    def _monitor_position(self, symbol, slot, current_price):
        side=slot["side"]; entry=slot["entry_price"]
        if side=="buy":
            if current_price>slot["best_price"]: slot["best_price"]=current_price
            in_profit=current_price>entry
            drawdown=(slot["best_price"]-current_price)/slot["best_price"] if slot["best_price"]>0 else 0
            if in_profit and drawdown>=self.cfg.trailing_offset_pct:
                # Fecha LONG
                closed=self.ex.place_market_order(symbol,"sell",slot["qty"],position_idx=1,reduce_only=True)
                if not closed: return  # Bybit rejeitou, nao marca como fechado
                profit=(current_price-entry)*slot["qty"]
                self.cfg.cofre+=profit
                logger.info(f"LONG fechou +{profit:.4f} | Cofre {self.cfg.cofre:.2f}")
                slot["status"]="CLOSED"
                # Repoem LONG novo (mesma direcao, para manter 1+1)
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self.ex.place_market_order(symbol,"buy",qty,position_idx=1)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"LONG_REV_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        elif side=="sell":
            if current_price<slot["best_price"]: slot["best_price"]=current_price
            in_profit=current_price<entry
            bounce=(current_price-slot["best_price"])/slot["best_price"] if slot["best_price"]>0 else 0
            if in_profit and bounce>=self.cfg.trailing_offset_pct:
                closed=self.ex.place_market_order(symbol,"buy",slot["qty"],position_idx=2,reduce_only=True)
                if not closed: return
                profit=(entry-current_price)*slot["qty"]
                self.cfg.cofre+=profit
                logger.info(f"SHORT fechou +{profit:.4f} | Cofre {self.cfg.cofre:.2f}")
                slot["status"]="CLOSED"
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self.ex.place_market_order(symbol,"sell",qty,position_idx=2)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_REV_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        self.orders_state=[o for o in self.orders_state if o["status"]!="CLOSED"]

    def _check_convergence(self, symbol, current_price):
        # So fecha se houver 1 LONG + 1 SHORT ativos
        act=[o for o in self.orders_state if o["status"]=="ACTIVE"]
        if len(act)<2: return
        live=self.ex.fetch_positions_live(symbol)
        pnl_conj=sum(p["unrealizedPnl"] for p in live)
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        net_conj=pnl_conj-taxas_est
        logger.info(f"Toque Ref {current_price} PnLconj {pnl_conj:.4f} net {net_conj:.4f} Cofre {self.cfg.cofre:.4f}")
        # REGRA DO COFRE: so fecha se conjunto > 0
        if net_conj>0:
            # Fecha ambas
            ok=self.ex.close_all_positions(symbol)
            if not ok: return
            self.cfg.cofre+=net_conj
            logger.info(f"CONVERGENCIA fechou +{net_conj:.4f} | Cofre {self.cfg.cofre:.4f}")
            self.orders_state=[]
            # Reposicao: abre nova ordem no sentido do ultimo movimento
            # Se preço veio de baixo (ultimo best LONG maior), abre SHORT; senao LONG
            # Simplificacao segura: abre par completo novo na Ref para manter invariante
            qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
            if qty>0:
                o1=self.ex.place_market_order(symbol,"buy",qty,position_idx=1)
                if o1:
                    e=float(o1.get("average") or o1.get("price") or current_price)
                    self.orders_state.append({"id":f"LONG_CONV_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
                o2=self.ex.place_market_order(symbol,"sell",qty,position_idx=2)
                if o2:
                    e=float(o2.get("average") or o2.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_CONV_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
            self._save_state()

    def close_entire_cycle(self, symbol, reason=""):
        self.ex.close_all_positions(symbol); self.orders_state=[]
        logger.info(f"Ciclo encerrado {symbol} ({reason}) Cofre ciclo {self.cfg.cofre:.2f}")

    def _handle_post_cycle_transition(self):
        self.cfg.completed_operations+=1
        self.cfg.cofre_global+=self.cfg.cofre; self.cfg.cofre=0.0
        if self.cfg.auto_mode and self.cfg.completed_operations < self.cfg.max_auto_operations:
            self.cfg.pair_index=(self.cfg.pair_index+1)%len(TOP_PAIRS)
            nxt=TOP_PAIRS[self.cfg.pair_index]
            self.cfg.status_message=f"Auto ({self.cfg.completed_operations}): {nxt}"
            time.sleep(1); self.initialize_cycle(nxt)
        else:
            self.cfg.is_running=False; self.cfg.active_symbol=None
            self.cfg.status_message=f"Concluido. CofreGlobal: {self.cfg.cofre_global:.2f} Aguardando Start."
            self._save_state()
