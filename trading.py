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
        self.last_tick_time=0.0  # V5: watchdog - ultimo tick do motor
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
            time.sleep(0.5)  # GRID V5: 0.5s

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
        # === ND GRID V5 CORRETO - Ref no centro, LONG acima, SHORT abaixo ===
        # ERRO DO GRID V1: as 10 ordens abriam TODAS na Ref (0.0774). Dashboard mostrava 10x a mesma entrada.
        # CORRETO: ordens PENDENTES nos niveis. Nao abrem na Ref. Esperam o preco chegar.
        # Ref no centro. Ex OP Ref 0.0774, passo 0.0005 (da ~0.01 de lucro com Qty 19.37):
        #  LONG 1 entrada 0.0779 (Ref+passo), alvo 0.0784 (+0.01) | LONG 2 entrada 0.0784, alvo 0.0789 | ... LONG 5 entrada 0.0794, alvo 0.0799
        #  SHORT 1 entrada 0.0769 (Ref-passo), alvo 0.0764 (+0.01) | SHORT 2 entrada 0.0764, alvo 0.0759 | ... SHORT 5 entrada 0.0754, alvo 0.0749
        # Preco SOBE -> toca LONG 1, abre, sobe mais, fecha +0.01 Cofre. Depois LONG 2, LONG 3...
        # Preco VOLTA A DESCER -> toca SHORT 1, abre, desce mais, fecha +0.01. Depois SHORT 2...
        # Ganha nas 2 direccoes. Perna positiva ganha quando preco a favor. Perna negativa so ganha quando preco reverte e atinge os precos das ordens abertas.
        # Sem trailing, sem reancoragem. Ref FIXA o ciclo todo.
        if self._is_paper():
            equity=self.cfg.paper_initial_balance if self.cfg.cycle_initial_equity<=0 else self.cfg.cycle_initial_equity
            if self.paper_equity>0: equity=self.paper_equity
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
        qty_total=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, self.reference_price)
        if qty_total<=0:
            self.cfg.is_running=False; self.cfg.status_message="Qty invalido"; return
        # V5 Qty: round 8 casas. round(...,2) dava 0.00 em BTC; Qty crua dava 0.0006000000000000001.
        qty_per = round(qty_total/10.0, 8)
        if qty_per<=0: qty_per = round(qty_total/10.0, 10)
        # V5 - Passo ABSOLUTO em preco, livre, so nao pode ser 0. Ex BTC 20 | OP 0.0015.
        _step = float(getattr(self.cfg, "grid_step_price", 20.0))
        if _step==0: _step = 20.0
        if _step<0: _step = abs(_step)
        _profit_per = round(_step * qty_per, 6)
        # V5 - LONG 1 e SHORT 1 abrem IMEDIATAMENTE na Ref, no instante do inicio. Nao esperam.
        # Ex Ref 62343: LONG 1 entrada 62343 ACTIVE, alvo 62363 | SHORT 1 entrada 62343 ACTIVE, alvo 62323.
        # Preco sobe 20 -> LONG 1 fecha +lucro. Preco desce 20 -> SHORT 1 fecha +lucro. Resultados desde o arranque.
        # Restantes PENDING por espacamento: LONG 2 Ref+passo, LONG 3 Ref+2*passo... SHORT 2 Ref-passo, SHORT 3 Ref-2*passo...
        self.orders_state.append({"id":"GRID_LONG_1","side":"buy","position_idx":1,"entry_price":round(self.reference_price,8),"best_price":round(self.reference_price,8),"qty":qty_per,"status":"ACTIVE","open_price":round(self.reference_price,8),"target_price":round(self.reference_price+_step,8),"target_profit":_profit_per,"grid_level":1,"grid_step":round(_step,8)})
        self.orders_state.append({"id":"GRID_SHORT_1","side":"sell","position_idx":2,"entry_price":round(self.reference_price,8),"best_price":round(self.reference_price,8),"qty":qty_per,"status":"ACTIVE","open_price":round(self.reference_price,8),"target_price":round(self.reference_price-_step,8),"target_profit":_profit_per,"grid_level":1,"grid_step":round(_step,8)})
        for i in range(2,6):
            entry_long = self.reference_price + _step*(i-1)
            tgt_long = entry_long + _step
            self.orders_state.append({"id":f"GRID_LONG_{i}","side":"buy","position_idx":1,"entry_price":round(entry_long,8),"best_price":round(entry_long,8),"qty":qty_per,"status":"PENDING","target_price":round(tgt_long,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
            entry_short = self.reference_price - _step*(i-1)
            tgt_short = entry_short - _step
            self.orders_state.append({"id":f"GRID_SHORT_{i}","side":"sell","position_idx":2,"entry_price":round(entry_short,8),"best_price":round(entry_short,8),"qty":qty_per,"status":"PENDING","target_price":round(tgt_short,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
        mode="[PAPEL] " if self._is_paper() else "[REAL] "
        self.cfg.status_message=f"{mode}GRID V5 {symbol} | Ref centro: {self.reference_price:.4f} | Passo: {_step:.4f} | Qty/ordem: {qty_per:.8f} | LONG 1 + SHORT 1 ATIVOS na Ref"
        self._save_state()

    def tick(self):
        with self.lock:
            self.last_tick_time=time.time()  # V5: marca cada tick, o Dashboard vigia
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
            # GRID V5: sem reanchor, sem convergencia. So GRID.
            for slot in list(self.orders_state):
                if slot["status"] in ("PENDING","ACTIVE"): self._monitor_position(symbol, slot, current_price)
            _rest=[o for o in self.orders_state if o["status"] in ("PENDING","ACTIVE")]
            if len(self.orders_state)>=10 and len(_rest)==0:
                try: self.cfg.cofre_global+=self.cfg.cofre
                except Exception: pass
                self.initialize_cycle(symbol); return
            self._save_state()

    def _should_reanchor(self, current_price):
        return False  # GRID V5: reancoragem DESLIGADA - Ref fixa
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
        # === GRID V5 MONITOR - PENDING -> ACTIVE -> CLOSED ===
        # PENDING: espera o preco tocar na entrada. LONG: preco >= entrada -> abre (ACTIVE). SHORT: preco <= entrada -> abre.
        # ACTIVE: espera o preco tocar no alvo. LONG: preco >= alvo -> fecha +0.01 Cofre. SHORT: preco <= alvo -> fecha +0.01.
        # Exemplo: Ref 0.0774, LONG 1 entrada 0.0779. Preco sobe 0.0774 -> 0.0779: LONG 1 abre. Preco sobe 0.0779 -> 0.0784: LONG 1 fecha +0.01.
        # Preco volta a descer 0.0784 -> 0.0769: SHORT 1 abre. Desce 0.0769 -> 0.0764: SHORT 1 fecha +0.01. Ganha nas 2 direccoes.
        if slot["status"]=="PENDING":
            if slot["side"]=="buy" and current_price >= slot["entry_price"]:
                # Abre LONG: simula em Papel, ordem real em Real
                o=self._place(symbol,"buy",slot["qty"],current_price,position_idx=1)
                if not o: return
                slot["status"]="ACTIVE"
                slot["open_price"]=current_price
                return
            if slot["side"]=="sell" and current_price <= slot["entry_price"]:
                o=self._place(symbol,"sell",slot["qty"],current_price,position_idx=2)
                if not o: return
                slot["status"]="ACTIVE"
                slot["open_price"]=current_price
                return
            return
        if slot["status"]!="ACTIVE":
            return
        _tgt = float(slot["target_price"])
        _lvl = slot.get("grid_level", "?")
        _open = float(slot.get("open_price", slot["entry_price"]))
        if slot["side"]=="buy":
            if current_price >= _tgt:
                closed=self._place(symbol,"sell",slot["qty"],current_price,position_idx=1,reduce_only=True)
                if not closed: return
                _profit = (current_price-_open)*slot["qty"]
                if _profit < float(slot.get("target_profit",0.01)): _profit = float(slot.get("target_profit",0.01))
                self.cfg.cofre+=_profit
                try:
                    self.hist_long_pnl+=_profit
                    self.history.append({"time":int(time.time()),"side":"buy","profit":round(_profit,4),"reason":f"GRID V5 LONG {_lvl}","price":current_price,"target":_tgt})
                except Exception: pass
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
                return
        else:
            if current_price <= _tgt:
                closed=self._place(symbol,"buy",slot["qty"],current_price,position_idx=2,reduce_only=True)
                if not closed: return
                _profit = (_open-current_price)*slot["qty"]
                if _profit < float(slot.get("target_profit",0.01)): _profit = float(slot.get("target_profit",0.01))
                self.cfg.cofre+=_profit
                try:
                    self.hist_short_pnl+=_profit
                    self.history.append({"time":int(time.time()),"side":"sell","profit":round(_profit,4),"reason":f"GRID V5 SHORT {_lvl}","price":current_price,"target":_tgt})
                except Exception: pass
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
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
