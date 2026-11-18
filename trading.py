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
        self.closed_orders=[]  # V6: historico = ordens FECHADAS, cada uma com o seu lucro
        self.per_side=7  # V6: total 14 = 7 LONG + 7 SHORT (Ajustes)
        self.grid_step=20.0
        self.first_dist=10.0
        self._load_state()

    # ---------- helpers PAPER ----------
    def _is_paper(self): return bool(getattr(self.cfg,"paper_trading",False))
    def _fee_rate(self):
        # V6: papel simula taxa MAKER (0.01%) porque as PENDING sao ordens limite. Real usa a taxa da conta.
        return 0.0001 if self._is_paper() else float(getattr(self.cfg, "fee_rate", 0.00055))
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
            _op=float(o.get("open_price", o["entry_price"]))
            if o["side"]=="buy": pnl += (current_price - _op)*o["qty"]
            else: pnl += (_op - current_price)*o["qty"]
        return self.cfg.cycle_initial_equity + self.cfg.cofre + pnl
    def _live_positions_pnl(self, symbol, current_price):
        if self._is_paper():
            pnl=0.0
            for o in self.orders_state:
                if o["status"]!="ACTIVE": continue
                _op=float(o.get("open_price", o["entry_price"]))
                if o["side"]=="buy": pnl += (current_price - _op)*o["qty"]
                else: pnl += (_op - current_price)*o["qty"]
            return pnl
        live=self.ex.fetch_positions_live(symbol)
        return sum(p["unrealizedPnl"] for p in live)

    # ---------- persistencia ----------
    def _save_state(self):
        try:
            data={"ref":self.reference_price,"orders":self.orders_state,"active":self.cfg.active_symbol,
                  "equity0":self.cfg.cycle_initial_equity,"cofre":self.cfg.cofre,"cofre_global":self.cfg.cofre_global,
                  "last_touch":self.last_ref_touch,"cycle_start":self.cycle_start_time,"is_running":self.cfg.is_running,
                  "paper":self._is_paper(),"paper_equity":self.paper_equity,"history":list(getattr(self,"closed_orders",[])),"hist_long":self.hist_long_pnl,"hist_short":self.hist_short_pnl}
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
            _h=d.get("history",[])
            # estado antigo (resumos de ciclo) nao e lista de ordens -> ignora
            if isinstance(_h, list) and _h and isinstance(_h[0], dict) and "ciclo" in _h[0]:
                self.closed_orders=[]
            else:
                self.closed_orders=list(_h) if isinstance(_h, list) else []
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
            time.sleep(0.5)  # GRID V6: 0.5s

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
                self._fold_cofre_to_principal()
            self.cfg.active_symbol=None
            self.cfg.status_message=f"Parado. Saldo principal atualizado: {self.cfg.paper_initial_balance:.2f} USDT (Papel)" if self._is_paper() else "Parado pelo Utilizador. Cofre somado ao principal."
            self._save_state()

    def initialize_cycle(self, symbol):
        # === ND GRID V6 CORRETO - Ref no centro, LONG acima, SHORT abaixo ===
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
        # V5 - Passo ABSOLUTO em preco, livre, so nao pode ser 0. Ex BTC 20 | OP 0.0015.
        _step = float(getattr(self.cfg, "grid_step_price", 20.0))
        if _step==0: _step = 20.0
        if _step<0: _step = abs(_step)
        # V6 - Ref = preco no INICIAR. NADA abre na Ref. Tudo PENDING.
        # Primeira distancia = passo/2 (ex passo 40 -> 20). LONG 1 = Ref+20, alvo +40. SHORT 1 = Ref-20, alvo -40.
        # Total dos Ajustes: total 14 = 7 LONG + 7 SHORT. LONG i = Ref + primeira + passo*(i-1). SHORT i = Ref - primeira - passo*(i-1).
        _total=int(getattr(self.cfg, "total_orders", 14))
        if _total<2: _total=2
        _per=max(1, _total//2)
        self.per_side=_per; self.grid_step=_step; self.first_dist=_step/2.0
        qty_per = round(qty_total/(_per*2), 8)
        if qty_per<=0: qty_per = round(qty_total/(_per*2), 10)
        _profit_per = round(_step * qty_per, 6)
        for i in range(1, _per+1):
            entry_long = self.reference_price + self.first_dist + _step*(i-1)
            tgt_long = entry_long + _step
            self.orders_state.append({"id":f"GRID_LONG_{i}","side":"buy","position_idx":1,"entry_price":round(entry_long,8),"best_price":round(entry_long,8),"qty":qty_per,"status":"PENDING","target_price":round(tgt_long,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
            entry_short = self.reference_price - self.first_dist - _step*(i-1)
            tgt_short = entry_short - _step
            self.orders_state.append({"id":f"GRID_SHORT_{i}","side":"sell","position_idx":2,"entry_price":round(entry_short,8),"best_price":round(entry_short,8),"qty":qty_per,"status":"PENDING","target_price":round(tgt_short,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
        mode="[PAPEL] " if self._is_paper() else "[REAL] "
        self.cfg.status_message=f"{mode}GRID V6 {symbol} | Ref: {self.reference_price:.4f} | Passo: {_step:.4f} | 1a ordem a {_step/2:.4f} da Ref | {_per*2} ordens ({_per} LONG + {_per} SHORT) | Qty/ordem: {qty_per:.8f} | Tudo PENDING"
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
            # GRID V6: sem reanchor, sem convergencia. So GRID.
            for slot in list(self.orders_state):
                if slot["status"] in ("PENDING","ACTIVE"): self._monitor_position(symbol, slot, current_price)
            self._extend_grid(symbol, current_price)
            _rest=[o for o in self.orders_state if o["status"] in ("PENDING","ACTIVE")]
            if len(self.orders_state)>=2 and len(_rest)==0:
                try: self.cfg.cofre_global+=self.cfg.cofre
                except Exception: pass
                self.initialize_cycle(symbol); return
            self._save_state()

    def _should_reanchor(self, current_price):
        return False  # GRID V6: reancoragem DESLIGADA - Ref fixa
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
        # === GRID V6 MONITOR - PENDING -> ACTIVE -> CLOSED ===
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
                _gross = (current_price-_open)*slot["qty"]
                _fee = self._fee_rate()*(_open+current_price)*slot["qty"]
                _profit = _gross - _fee  # V6: lucro LIQUIDO de taxas maker
                self.cfg.cofre+=_profit
                try:
                    self.hist_long_pnl+=_profit
                    self.closed_orders.append({"time":int(time.time()),"side":"buy","entry":round(_open,8),"close":round(current_price,8),"profit":round(_profit,6),"gross":round(_gross,6),"fee":round(_fee,6),"reason":f"GRID V6 LONG {_lvl}"})
                except Exception: pass
                self._spawn_mirror(symbol, "sell", current_price)  # V6 espelho: SHORT 1 passo abaixo do fecho
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
                return
        else:
            if current_price <= _tgt:
                closed=self._place(symbol,"buy",slot["qty"],current_price,position_idx=2,reduce_only=True)
                if not closed: return
                _gross = (_open-current_price)*slot["qty"]
                _fee = self._fee_rate()*(_open+current_price)*slot["qty"]
                _profit = _gross - _fee  # V6: lucro LIQUIDO de taxas maker
                self.cfg.cofre+=_profit
                try:
                    self.hist_short_pnl+=_profit
                    self.closed_orders.append({"time":int(time.time()),"side":"sell","entry":round(_open,8),"close":round(current_price,8),"profit":round(_profit,6),"gross":round(_gross,6),"fee":round(_fee,6),"reason":f"GRID V6 SHORT {_lvl}"})
                except Exception: pass
                self._spawn_mirror(symbol, "buy", current_price)  # V6 espelho: LONG 1 passo acima do fecho
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
                return

    def _spawn_mirror(self, symbol, side, close_price):
        # V6 ESPELHO ping-pong: LONG fecha a C -> SHORT PENDING a C-passo, alvo C-2*passo.
        # SHORT fecha a C -> LONG PENDING a C+passo, alvo C+2*passo. Ao fechar, cria outro de volta.
        # Sem duplicados: se ja existe PENDING/ACTIVE do mesmo lado na mesma entrada, nao cria outro.
        try:
            _step=float(getattr(self, "grid_step", 0) or 0)
            if _step<=0: return
            if side=="sell":
                _entry=round(close_price-_step,8); _tgt=round(close_price-2*_step,8); _pos=2
            else:
                _entry=round(close_price+_step,8); _tgt=round(close_price+2*_step,8); _pos=1
            for o in self.orders_state:
                if o.get("side")==side and o.get("status") in ("PENDING","ACTIVE") and abs(float(o.get("entry_price",0))- _entry) < 1e-9:
                    return
            _qty=0.0
            for o in self.orders_state:
                if o.get("qty"): _qty=float(o["qty"]); break
            if _qty<=0: return
            self.orders_state.append({"id":f"ESP_{side}_{_entry}","side":side,"position_idx":_pos,"entry_price":_entry,"best_price":_entry,"qty":_qty,"status":"PENDING","target_price":_tgt,"target_profit":round(_step*_qty,6),"grid_level":0,"grid_step":round(_step,8),"mirror":True})
        except Exception as e: logger.error(f"mirror: {e}")
    def _extend_grid(self, symbol, current_price):
        # V6: se o preco foge para la da ponta do grid, o grid estende-se sozinho (1 nivel por tick, max 200 ordens).
        try:
            if len(self.orders_state)>=200: return
            _step=float(getattr(self, "grid_step", 0) or 0)
            if _step<=0: return
            _longs=[o for o in self.orders_state if o.get("side")=="buy" and not o.get("mirror")]
            _shorts=[o for o in self.orders_state if o.get("side")=="sell" and not o.get("mirror")]
            if _longs:
                _max=max(float(o["entry_price"]) for o in _longs)
                if current_price > _max:
                    _e=round(_max+_step,8)
                    _q=float(_longs[0].get("qty",0))
                    self.orders_state.append({"id":f"GRID_LONG_X_{_e}","side":"buy","position_idx":1,"entry_price":_e,"best_price":_e,"qty":_q,"status":"PENDING","target_price":round(_e+_step,8),"target_profit":round(_step*_q,6),"grid_level":99,"grid_step":round(_step,8)})
            if _shorts:
                _min=min(float(o["entry_price"]) for o in _shorts)
                if current_price < _min:
                    _e=round(_min-_step,8)
                    _q=float(_shorts[0].get("qty",0))
                    self.orders_state.append({"id":f"GRID_SHORT_X_{_e}","side":"sell","position_idx":2,"entry_price":_e,"best_price":_e,"qty":_q,"status":"PENDING","target_price":round(_e-_step,8),"target_profit":round(_step*_q,6),"grid_level":99,"grid_step":round(_step,8)})
        except Exception as e: logger.error(f"extend: {e}")
    @property
    def history(self):
        # V6: history = ordens fechadas (cada uma com lucro). O frontend soma o total no topo.
        return list(getattr(self, "closed_orders", []))
    @history.setter
    def history(self, v):
        self.closed_orders = list(v or [])
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

    def _fold_cofre_to_principal(self):
        # V6: sempre que o robo para, o Cofre entra no saldo principal. Papel: principal += cofre. Real: saldo na Bybit, cofre vai para global.
        try:
            _c=float(self.cfg.cofre)
            if self._is_paper():
                self.cfg.paper_initial_balance=float(self.cfg.paper_initial_balance)+_c
                self.cfg.cycle_initial_equity=float(self.cfg.paper_initial_balance)
                self.paper_equity=float(self.cfg.paper_initial_balance)
            self.cfg.cofre_global=float(getattr(self.cfg, "cofre_global", 0.0))+_c
            self.cfg.cofre=0.0
            logger.info(f"V6 FOLD Cofre {_c:.4f} -> principal")
        except Exception as e: logger.error(f"fold: {e}")
    def close_entire_cycle(self, symbol, reason=""):
        # V6: realiza as ACTIVE ao preco atual (lucro/prejuizo liquido de taxas), regista cada fecho, limpa o grid. NAO faz fold (quem chama decide).
        try:
            _t=self.ex.fetch_ticker(symbol); _px=float(_t["last"])
        except Exception: _px=float(getattr(self, "last_price", 0) or 0)
        _rate=self._fee_rate()
        for o in list(self.orders_state):
            if o.get("status")!="ACTIVE": continue
            _op=float(o.get("open_price", o["entry_price"]))
            _gross=(_px-_op)*o["qty"] if o["side"]=="buy" else (_op-_px)*o["qty"]
            _fee=_rate*(_op+_px)*o["qty"]
            _net=_gross-_fee
            self.cfg.cofre+=_net
            if o["side"]=="buy": self.hist_long_pnl+=_net
            else: self.hist_short_pnl+=_net
            self.closed_orders.append({"time":int(time.time()),"side":o["side"],"entry":round(_op,8),"close":round(_px,8),"profit":round(_net,6),"gross":round(_gross,6),"fee":round(_fee,6),"reason":reason or "Fecho ao Parar"})
        if self._is_paper(): self._close_all_paper()
        else:
            try: self.ex.close_all_positions(symbol)
            except Exception: pass
        self.orders_state=[]
        logger.info(f"Ciclo encerrado {symbol} ({reason}) Cofre {self.cfg.cofre:.4f} {'[PAPEL]' if self._is_paper() else '[REAL]'}")

    def _handle_post_cycle_transition(self):
        # V6: historico = ordens fechadas (nao resumos). O resumo do ciclo fica em last_cycle_summary.
        _tot=self.hist_long_pnl+self.hist_short_pnl
        _win="LONG" if self.hist_long_pnl>self.hist_short_pnl else ("SHORT" if self.hist_short_pnl>self.hist_long_pnl else "EMPATE")
        self.last_cycle_summary={"ciclo":len(getattr(self, "cycle_summaries", []))+1,"par":self.cfg.active_symbol,"total":round(_tot,4),"long":round(self.hist_long_pnl,4),"short":round(self.hist_short_pnl,4),"vencedor":_win}
        if not hasattr(self, "cycle_summaries"): self.cycle_summaries=[]
        self.cycle_summaries.append(self.last_cycle_summary)
        self.hist_long_pnl=0.0; self.hist_short_pnl=0.0
        self.cfg.completed_operations+=1
        self._fold_cofre_to_principal()
        if self.cfg.auto_mode and self.cfg.completed_operations < self.cfg.max_auto_operations:
            self.cfg.pair_index=(self.cfg.pair_index+1)%len(TOP_PAIRS)
            nxt=TOP_PAIRS[self.cfg.pair_index]
            self.cfg.status_message=f"Auto ({self.cfg.completed_operations}): {nxt}"
            time.sleep(1); self.initialize_cycle(nxt)
        else:
            self.cfg.is_running=False; self.cfg.active_symbol=None
            self.cfg.status_message=f"Concluido. Saldo principal atualizado. Aguardando Start."
            self._save_state()
