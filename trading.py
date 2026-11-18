import time, threading, logging, json, os
from config import TOP_PAIRS
logger = logging.getLogger("ND-Trading")
STATE_FILE = "state.json"

class MinimalistGridEngine:
    def __init__(self, exchange_manager, config):
        self.ex=exchange_manager; self.cfg=config
        self.reference_price=0.0
        self.orders_state=[]
        self.lock=threading.Lock()
        self._thread=None
        self.last_ref_touch=time.time()
        self.cycle_start_time=0
        self.paper_equity=0.0
        self.hist_long_pnl=0.0
        self.hist_short_pnl=0.0
        self.history=[]
        self.last_price=0.0
        self._load_state()

    # ---------- helpers PAPER ----------
    def _is_paper(self): return bool(getattr(self.cfg,"paper_trading",False))
    def _paper_place(self, symbol, side, qty, price, position_idx):
        """Simula uma ordem - NÃO toca na Bybit"""
        fake={"id":f"PAPER_{int(time.time()*1000)}","average":price,"price":price,"side":side,"amount":qty}
        logger.info(f"[PAPEL] Ordem simulada {side} {symbol} qty={qty} @ {price} idx={position_idx}")
        return fake
    def _place(self, symbol, side, qty, price, position_idx, reduce_only=False):
        if self._is_paper():
            return self._paper_place(symbol, side, qty, price, position_idx)
        return self.ex.place_market_order(symbol, side, qty, position_idx, reduce_only=reduce_only)
    def _close_all_paper(self):
        self.orders_state=[]
        return True
    def _paper_equity(self, current_price):
        """Equity simulado = Equity0 + Cofre + PnL flutuante das posições abertas"""
        if self.cfg.cycle_initial_equity<=0: return self.cfg.paper_initial_balance
        pnl=0.0
        for o in self.orders_state:
            if o["status"]!="ACTIVE": continue
            if o["side"]=="buy": pnl += (current_price - o["entry_price"])*o["qty"]
            else: pnl += (o["entry_price"] - current_price)*o["qty"]
        return self.cfg.cycle_initial_equity + self.cfg.cofre + pnl
    def _live_positions_pnl(self, symbol, current_price):
        if self._is_paper():
            pnl=0.0
            for o in self.orders_state:
                if o["status"]!="ACTIVE": continue
                if o["side"]=="buy": pnl += (current_price - o["entry_price"])*o["qty"]
                else: pnl += (o["entry_price"] - current_price)*o["qty"]
            return pnl
        live=self.ex.fetch_positions_live(symbol)
        return sum(p["unrealizedPnl"] for p in live)

    # ---------- persistencia ----------
    def _save_state(self):
        try:
            data={"ref":self.reference_price,"orders":self.orders_state,"active":self.cfg.active_symbol,
                  "equity0":self.cfg.cycle_initial_equity,"cofre":self.cfg.cofre,"cofre_global":self.cfg.cofre_global,
                  "last_touch":self.last_ref_touch,"cycle_start":self.cycle_start_time,"is_running":self.cfg.is_running,
                  "paper":self._is_paper(),"paper_equity":self.paper_equity,"history":self.history,"hist_long":self.hist_long_pnl,"hist_short":self.hist_short_pnl}
            with open(STATE_FILE,"w") as f: json.dump(data,f)
        except Exception as e: logger.error(f"save_state: {e}")
    def _load_state(self):
        if not os.path.exists(STATE_FILE): return
        try:
            with open(STATE_FILE) as f: d=json.load(f)
            # Se mudou de modo (papel <-> real), NÃO restaura estado antigo - evita confusão
            if bool(d.get("paper",False)) != self._is_paper():
                logger.info("Mudança de modo Papel/Real - estado antigo ignorado")
                return
            self.reference_price=d.get("ref",0.0); self.orders_state=d.get("orders",[])
            self.cfg.active_symbol=d.get("active"); self.cfg.cycle_initial_equity=d.get("equity0",0)
            self.cfg.cofre=d.get("cofre",0); self.cfg.cofre_global=d.get("cofre_global",0)
            self.last_ref_touch=d.get("last_touch",time.time()); self.cycle_start_time=d.get("cycle_start",time.time())
            self.paper_equity=d.get("paper_equity",0)
            self.history=d.get("history",[])
            self.hist_long_pnl=d.get("hist_long",0)
            self.hist_short_pnl=d.get("hist_short",0)
            logger.info(f"Estado restaurado Papel={self._is_paper()} {self.cfg.active_symbol} Ref={self.reference_price}")
        except Exception as e: logger.error(f"load_state: {e}")

    def start_background_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread=threading.Thread(target=self._run_loop,daemon=True); self._thread.start()
    def _run_loop(self):
        while True:
            try:
                if self.cfg.is_running: self.tick()
            except Exception as e: logger.error(f"tick err: {e}")
            time.sleep(0.5)  # FIX CIRURGICO: 0.5s para apanhar o recuo logo, nao deixar escapar dentro de 1s

    def start_bot(self):
        with self.lock:
            self.cfg.completed_operations=0; self.cfg.is_running=True
            pair=TOP_PAIRS[TOP_PAIRS.index(self.cfg.selected_pair) % len(TOP_PAIRS)] if self.cfg.auto_mode else self.cfg.selected_pair  # FIX Auto
            self.initialize_cycle(pair)

    def switch_pair(self, new_pair):
        with self.lock:
            if not self.cfg.is_running:
                self.cfg.selected_pair = new_pair
                return 'par_guardado_parado'
            if self.cfg.active_symbol == new_pair:
                return 'ja_esta_nesse_par'
            old = self.cfg.active_symbol
            try: self.cfg.cofre_global += self.cfg.cofre; self.cfg.cofre = 0.0
            except Exception: pass
            self.close_entire_cycle(old, reason='Troca')
            self.cfg.selected_pair = new_pair
            try: self.cfg.pair_index = TOP_PAIRS.index(new_pair)
            except ValueError: self.cfg.pair_index = 0
            self.initialize_cycle(new_pair)
            return 'trocado'
    def stop_bot(self, close_all=True):
        with self.lock:
            self.cfg.is_running=False
            if close_all and self.cfg.active_symbol:
                self.close_entire_cycle(self.cfg.active_symbol, reason="Paragem Manual")
            self.cfg.active_symbol=None; self.cfg.status_message="Parado pelo Utilizador"
            self._save_state()

    def initialize_cycle(self, symbol):
        # Equity inicial: papel usa saldo simulado, real usa Bybit
        if self._is_paper():
            equity=self.cfg.paper_initial_balance if self.cfg.cycle_initial_equity<=0 else self.cfg.cycle_initial_equity
            # Em papel, se já havia ciclo anterior, mantém o paper_equity acumulado
            if self.paper_equity>0: equity=self.paper_equity
            logger.info(f"[PAPEL] Ciclo simulado - Equity inicial simulado {equity}")
        else:
            equity=self.ex.get_total_equity()
            if equity<0:
                self.cfg.is_running=False; self.cfg.status_message="Erro a ler equity - nao iniciou"; return
        required=self.cfg.margin_per_order*2
        if equity < required*1.5:
            self.cfg.is_running=False; self.cfg.status_message=f"Saldo insuficiente ({equity:.2f})"; return
        self.cfg.active_symbol=symbol; self.cfg.cycle_initial_equity=equity; self.cfg.cofre=0.0
        if not self._is_paper():
            self.ex.set_hedge_mode_and_leverage(symbol, self.cfg.leverage)
        try: ticker=self.ex.fetch_ticker(symbol)
        except Exception as e:
            self.cfg.is_running=False; self.cfg.status_message=f"Erro ticker: {e}"; return
        self.reference_price=float(ticker["last"])
        self.last_price=self.reference_price
        self.orders_state=[]; self.last_ref_touch=time.time(); self.cycle_start_time=time.time()
        qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, self.reference_price)
        if qty<=0:
            self.cfg.is_running=False; self.cfg.status_message="Qty invalido"; return
        o_long=self._place(symbol,"buy",qty,self.reference_price,position_idx=1)
        if o_long:
            entry=float(o_long.get("average") or o_long.get("price") or self.reference_price)
            self.orders_state.append({"id":"LONG_BASE","side":"buy","position_idx":1,"entry_price":entry,"best_price":entry,"qty":qty,"status":"ACTIVE"})
        o_short=self._place(symbol,"sell",qty,self.reference_price,position_idx=2)
        if o_short:
            entry=float(o_short.get("average") or o_short.get("price") or self.reference_price)
            self.orders_state.append({"id":"SHORT_BASE","side":"sell","position_idx":2,"entry_price":entry,"best_price":entry,"qty":qty,"status":"ACTIVE"})
        mode="[PAPEL] " if self._is_paper() else "[REAL] "
        self.cfg.status_message=f"{mode}Operando {symbol} | Ref: {self.reference_price:.4f} | Cofre: 0"
        logger.info(f"{mode}Ciclo {symbol} Ref={self.reference_price} Equity0={equity}")
        self._save_state()

    def tick(self):
        with self.lock:
            if not self.cfg.is_running or not self.cfg.active_symbol: return
            symbol=self.cfg.active_symbol
            try: ticker=self.ex.fetch_ticker(symbol)
            except Exception: return
            current_price=float(ticker["last"])
            # Equity: papel = simulado, real = Bybit
            if self._is_paper():
                equity=self._paper_equity(current_price)
                self.paper_equity=equity
            else:
                equity=self.ex.get_total_equity()
                if equity<0: return
            if self.cfg.cycle_initial_equity>0:
                net=equity-self.cfg.cycle_initial_equity
                target=self.cfg.cycle_initial_equity*(self.cfg.target_profit_pct/100)
                maxloss=self.cfg.cycle_initial_equity*(self.cfg.max_loss_pct/100)
                if net>=target:
                    logger.info(f"META atingida +{net:.2f} {'[PAPEL]' if self._is_paper() else '[REAL]'}")
                    self.close_entire_cycle(symbol, reason="Meta Atingida"); self._handle_post_cycle_transition(); return
                if net<=-maxloss:
                    logger.info(f"STOP GLOBAL {net:.2f}")
                    self.close_entire_cycle(symbol, reason="Stop Global"); self.cfg.is_running=False; self.cfg.active_symbol=None; self._save_state(); return
            if self._should_reanchor(current_price):
                self._do_reanchor(symbol, current_price); return
            for slot in list(self.orders_state):
                if slot["status"]=="ACTIVE": self._monitor_position(symbol, slot, current_price)
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
        logger.info(f"REANCORAGEM {symbol} {self.reference_price} -> {current_price} {'[PAPEL]' if self._is_paper() else '[REAL]'}")
        pnl_conj=self._live_positions_pnl(symbol, current_price)
        if self._is_paper():
            self._close_all_paper()
        else:
            self.ex.close_all_positions(symbol)
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        resultado=self.cfg.cofre + pnl_conj - taxas_est
        self.cfg.cofre_global+=resultado
        logger.info(f"Reancoragem: cofre {self.cfg.cofre:.2f} + pnl {pnl_conj:.2f} - taxas {taxas_est:.2f} = {resultado:.2f} | Global {self.cfg.cofre_global:.2f}")
        self.reference_price=current_price; self.cfg.cofre=0.0
        self.last_ref_touch=time.time(); self.cycle_start_time=time.time()
        self.orders_state=[]
        qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
        if qty>0:
            o1=self._place(symbol,"buy",qty,current_price,position_idx=1)
            if o1:
                e=float(o1.get("average") or o1.get("price") or current_price)
                self.orders_state.append({"id":f"LONG_REANCH_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
            o2=self._place(symbol,"sell",qty,current_price,position_idx=2)
            if o2:
                e=float(o2.get("average") or o2.get("price") or current_price)
                self.orders_state.append({"id":f"SHORT_REANCH_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        self.cfg.status_message=f"{'[PAPEL] ' if self._is_paper() else ''}Reancorado {symbol} | Nova Ref: {current_price:.4f} | CofreGlobal: {self.cfg.cofre_global:.2f}"
        self._save_state()

    def _monitor_position(self, symbol, slot, current_price):
        # === TRAILING CIRURGICO - PROMPT INICIAL, CORRETO ===
        # Para que serve o Trailing nos Ajustes? Era o espaco de recuo permitido.
        # Bug: Trailing 0.1% em OP = 0.075 USDT de recuo permitido. LONG a +0.04 podia cair 0.075 antes de fechar -> lucro fugia.
        # Correcao: Trailing dos Ajustes passa a ser IGNORADO aqui. Recuo permitido = ZERO.
        # Regra exata:
        #  1. Trava ativa a 0.01 - a partir dai a perna esta ARMADA
        #  2. Segue o melhor preco - se subir 0.01 -> 0.02 -> 0.04, vai acompanhando, NAO fecha
        #  3. Recuou 1 tick a partir do melhor, fecha ALI MESMO - tocou 0.04 e recuou, fecha a ~0.04. Nao pode deixar escapar por nada.
        # Antes errava de 2 formas: Trailing 0.1% deixava recuar 0.075; Trava 0.01/0.02 fechava logo a 0.01 sem deixar subir a 0.04.
        side=slot["side"]; entry=slot["entry_price"]
        _p = (current_price-entry)*slot["qty"] if side=="buy" else (entry-current_price)*slot["qty"]
        # Atualiza melhor lucro / melhor preco ja vistos
        try: slot["best_profit"] = max(float(slot.get("best_profit", _p)), _p)
        except Exception: slot["best_profit"] = _p
        # 1. Armou? (atingiu 0.01 alguma vez)
        if slot["best_profit"] >= 0.01:
            slot["armed"] = True
        if not slot.get("armed", False):
            # Ainda nao atingiu 0.01 - nao faz nada, espera. Nao usa Trailing dos Ajustes.
            # Atualiza best_price para quando armar ja saber o ponto de partida
            if side=="buy":
                if current_price>slot["best_price"]: slot["best_price"]=current_price
            else:
                if current_price<slot["best_price"]: slot["best_price"]=current_price
            return
        # 2. Armada - segue o melhor preco
        if side=="buy":
            if current_price>slot["best_price"]:
                slot["best_price"]=current_price
                return  # subiu - segue, NAO fecha
            # 3. Recuou 1 tick a partir do melhor -> fecha ALI MESMO
            if current_price < slot["best_price"]:
                closed=self._place(symbol,"sell",slot["qty"],current_price,position_idx=1,reduce_only=True)
                if not closed: return
                _lock = _p if _p>0 else 0.0
                self.cfg.cofre+=_lock
                try:
                    self.hist_long_pnl+=_lock
                    self.history.append({"time":int(time.time()),"side":side,"profit":round(_lock,4),"reason":"Trailing Cirurgico 0.01","price":current_price,"best":round(slot["best_profit"],4)})
                except Exception: pass
                slot["status"]="CLOSED"
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self._place(symbol,"buy",qty,current_price,position_idx=1)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"LONG_TC_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE","best_profit":0.0,"armed":False})
                self.orders_state=[o for o in self.orders_state if o["status"]!="CLOSED"]
                return
        else:  # sell / SHORT
            if current_price<slot["best_price"]:
                slot["best_price"]=current_price
                return  # desceu - segue, NAO fecha
            if current_price > slot["best_price"]:
                closed=self._place(symbol,"buy",slot["qty"],current_price,position_idx=2,reduce_only=True)
                if not closed: return
                _lock = _p if _p>0 else 0.0
                self.cfg.cofre+=_lock
                try:
                    self.hist_short_pnl+=_lock
                    self.history.append({"time":int(time.time()),"side":side,"profit":round(_lock,4),"reason":"Trailing Cirurgico 0.01","price":current_price,"best":round(slot["best_profit"],4)})
                except Exception: pass
                slot["status"]="CLOSED"
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self._place(symbol,"sell",qty,current_price,position_idx=2)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_TC_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE","best_profit":0.0,"armed":False})
                self.orders_state=[o for o in self.orders_state if o["status"]!="CLOSED"]
                return

    def _check_convergence(self, symbol, current_price):
        act=[o for o in self.orders_state if o["status"]=="ACTIVE"]
        if len(act)<2: return
        pnl_conj=self._live_positions_pnl(symbol, current_price)
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        net_conj=pnl_conj-taxas_est
        logger.info(f"Toque Ref {current_price} PnLconj {pnl_conj:.4f} net {net_conj:.4f} Cofre {self.cfg.cofre:.4f}")
        if net_conj>0:
            if self._is_paper(): self._close_all_paper()
            else:
                ok=self.ex.close_all_positions(symbol)
                if not ok: return
            self.cfg.cofre+=net_conj
            logger.info(f"CONVERGENCIA fechou +{net_conj:.4f} | Cofre {self.cfg.cofre:.4f}")
            self.orders_state=[]
            qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
            if qty>0:
                o1=self._place(symbol,"buy",qty,current_price,position_idx=1)
                if o1:
                    e=float(o1.get("average") or o1.get("price") or current_price)
                    self.orders_state.append({"id":f"LONG_CONV_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
                o2=self._place(symbol,"sell",qty,current_price,position_idx=2)
                if o2:
                    e=float(o2.get("average") or o2.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_CONV_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
            self._save_state()

    def close_entire_cycle(self, symbol, reason=""):
        if self._is_paper(): self._close_all_paper()
        else: self.ex.close_all_positions(symbol)
        self.orders_state=[]
        logger.info(f"Ciclo encerrado {symbol} ({reason}) Cofre {self.cfg.cofre:.2f} {'[PAPEL]' if self._is_paper() else '[REAL]'}")

    def _handle_post_cycle_transition(self):
        _tot=self.hist_long_pnl+self.hist_short_pnl
        _win="LONG" if self.hist_long_pnl>self.hist_short_pnl else ("SHORT" if self.hist_short_pnl>self.hist_long_pnl else "EMPATE")
        self.history.append({"ciclo":len(self.history)+1,"par":self.cfg.active_symbol,"total":round(_tot,4),"long":round(self.hist_long_pnl,4),"short":round(self.hist_short_pnl,4),"vencedor":_win})
        self.hist_long_pnl=0.0; self.hist_short_pnl=0.0
        self.cfg.completed_operations+=1
        self.cfg.cofre_global+=self.cfg.cofre
        # Em papel, o equity simulado segue para o próximo ciclo
        if self._is_paper(): self.paper_equity=self.cfg.cycle_initial_equity + self.cfg.cofre_global
        self.cfg.cofre=0.0
        if self.cfg.auto_mode and self.cfg.completed_operations < self.cfg.max_auto_operations:
            self.cfg.pair_index=(self.cfg.pair_index+1)%len(TOP_PAIRS)
            nxt=TOP_PAIRS[self.cfg.pair_index]
            self.cfg.status_message=f"Auto ({self.cfg.completed_operations}): {nxt}"
            time.sleep(1); self.initialize_cycle(nxt)
        else:
            self.cfg.is_running=False; self.cfg.active_symbol=None
            self.cfg.status_message=f"Concluido. CofreGlobal: {self.cfg.cofre_global:.2f} Aguardando Start."
            self._save_state()
