import time, threading, logging, json, os
from config import TOP_PAIRS
logger = logging.getLogger("ND-Trading")
STATE_FILE = "state.json"
# TRAVA RIGIDA - codigo fonte, NUNCA em Ajustes. Sempre ligada.
# Arma quando o lucro BRUTO da ordem >= 0.002 USDT.
# Depois de armada, fecha no 1o tick contra (recuo ZERO).
# Nunca armou = nunca fecha por trava, espera pelo alvo.

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
        self.last_tick_time=0.0
        self.closed_orders=[]
        self.bloquear_novas=False
        self.per_side=7
        self.grid_step=20.0
        self.first_dist=10.0
        self._load_state()

    def _is_paper(self): return bool(getattr(self.cfg,"paper_trading",False))
    def _fee_rate(self):
        return 0.0001 if self._is_paper() else float(getattr(self.cfg, "fee_rate", 0.00055))
    def _paper_place(self, symbol, side, qty, price, position_idx):
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
        if self.cfg.cycle_initial_equity<=0: return self.cfg.paper_initial_balance
        pnl=0.0
        for o in self.orders_state:
            if o["status"]!="ACTIVE": continue
            _op=float(o["entry_price"])
            if o["side"]=="buy": pnl += (current_price - _op)*o["qty"]
            else: pnl += (_op - current_price)*o["qty"]
        return self.cfg.cycle_initial_equity + self.cfg.cofre + pnl
    def _live_positions_pnl(self, symbol, current_price):
        if self._is_paper():
            pnl=0.0
            for o in self.orders_state:
                if o["status"]!="ACTIVE": continue
                _op=float(o["entry_price"])
                if o["side"]=="buy": pnl += (current_price - _op)*o["qty"]
                else: pnl += (_op - current_price)*o["qty"]
            return pnl
        live=self.ex.fetch_positions_live(symbol)
        return sum(p["unrealizedPnl"] for p in live)

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
            if bool(d.get("paper",False)) != self._is_paper():
                logger.info("Mudança de modo Papel/Real - estado antigo ignorado")
                return
            self.reference_price=0.0; self.orders_state=[]
            self.cfg.active_symbol=None; self.cfg.cycle_initial_equity=0; self.cfg.cofre=0.0
            self.cfg.cofre_global=d.get("cofre_global",0)
            self.last_ref_touch=time.time(); self.cycle_start_time=0
            self.paper_equity=0.0
            _h=d.get("history",[])
            if isinstance(_h, list) and _h and isinstance(_h[0], dict) and "ciclo" in _h[0]:
                self.closed_orders=[]
            else:
                self.closed_orders=list(_h) if isinstance(_h, list) else []
            self.hist_long_pnl=d.get("hist_long",0)
            self.hist_short_pnl=d.get("hist_short",0)
            logger.info("V6 FINAL arranque limpo - historico mantido, ciclo descartado")
        except Exception as e: logger.error(f"load_state: {e}")

    def start_background_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread=threading.Thread(target=self._run_loop,daemon=True); self._thread.start()
    def _run_loop(self):
        while True:
            try:
                if self.cfg.is_running: self.tick()
            except Exception as e: logger.error(f"tick err: {e}")
            time.sleep(0.5)

    def start_bot(self):
        with self.lock:
            self.cfg.completed_operations=0; self.cfg.is_running=True
            pair=TOP_PAIRS[TOP_PAIRS.index(self.cfg.selected_pair) % len(TOP_PAIRS)] if self.cfg.auto_mode else self.cfg.selected_pair
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
            self.reference_price=0.0; self.cfg.cycle_initial_equity=0; self.cfg.cofre=0.0
            self.cfg.status_message=f"Parado. Saldo principal atualizado: {self.cfg.paper_initial_balance:.2f} USDT (Papel)" if self._is_paper() else "Parado pelo Utilizador. Cofre somado ao principal."
            self._save_state()

    def initialize_cycle(self, symbol):
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
        _step = float(getattr(self.cfg, "grid_step_price", 20.0))
        if _step==0: _step = 20.0
        if _step<0: _step = abs(_step)
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
            self.orders_state.append({"id":f"GRID_LONG_{i}","side":"buy","position_idx":1,"entry_price":round(entry_long,8),"best_price":round(entry_long,8),"best_net":0.0,"qty":qty_per,"status":"PENDING","target_price":round(tgt_long,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
            entry_short = self.reference_price - self.first_dist - _step*(i-1)
            tgt_short = entry_short - _step
            self.orders_state.append({"id":f"GRID_SHORT_{i}","side":"sell","position_idx":2,"entry_price":round(entry_short,8),"best_price":round(entry_short,8),"best_net":0.0,"qty":qty_per,"status":"PENDING","target_price":round(tgt_short,8),"target_profit":_profit_per,"grid_level":i,"grid_step":round(_step,8)})
        mode="[PAPEL] " if self._is_paper() else "[REAL] "
        self.cfg.status_message=f"{mode}GRID V6 {symbol} | Ref: {self.reference_price:.4f} | Passo: {_step:.4f} | 1a ordem a {_step/2:.4f} da Ref | {_per*2} ordens ({_per} LONG + {_per} SHORT) | Qty/ordem: {qty_per:.8f} | Tudo PENDING"
        self._save_state()

    def tick(self):
        with self.lock:
            self.last_tick_time=time.time()
            if not self.cfg.is_running or not self.cfg.active_symbol: return
            symbol=self.cfg.active_symbol
            try: ticker=self.ex.fetch_ticker(symbol)
            except Exception: return
            current_price=float(ticker["last"])
            if self._is_paper():
                equity=self._paper_equity(current_price)
                self.paper_equity=equity
            else:
                equity=self.ex.get_total_equity()
                if equity<0: return
            _lucro_cfg = float(getattr(self.cfg, "lucro_por_operacao", 0) or 0)
            self.bloquear_novas = (_lucro_cfg > 0 and self.cfg.cofre >= _lucro_cfg)
            if self.cfg.cycle_initial_equity>0:
                net=equity-self.cfg.cycle_initial_equity
                maxloss=self.cfg.cycle_initial_equity*(self.cfg.max_loss_pct/100)
                if net<=-maxloss:
                    logger.info(f"STOP GLOBAL {net:.2f}")
                    self.close_entire_cycle(symbol, reason="Stop Global"); self.cfg.is_running=False; self.cfg.active_symbol=None; self._save_state(); return
            for slot in list(self.orders_state):
                if slot["status"] in ("PENDING","ACTIVE"): self._monitor_position(symbol, slot, current_price)
            self._extend_grid(symbol, current_price)
            if _lucro_cfg > 0 and self._vantagem(symbol, current_price) >= _lucro_cfg:
                self._encerrar_operacao(symbol, reason="Lucro Operacao")
                return
            _rest=[o for o in self.orders_state if o["status"] in ("PENDING","ACTIVE")]
            if len(self.orders_state)>=2 and len(_rest)==0:
                try: self.cfg.cofre_global+=self.cfg.cofre
                except Exception: pass
                self.initialize_cycle(symbol); return
            self._save_state()

    def _should_reanchor(self, current_price):
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
                self.orders_state.append({"id":f"LONG_REANCH_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"best_net":0.0,"qty":qty,"status":"ACTIVE"})
            o2=self._place(symbol,"sell",qty,current_price,position_idx=2)
            if o2:
                e=float(o2.get("average") or o2.get("price") or current_price)
                self.orders_state.append({"id":f"SHORT_REANCH_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"best_net":0.0,"qty":qty,"status":"ACTIVE"})
        self.cfg.status_message=f"{'[PAPEL] ' if self._is_paper() else ''}Reancorado {symbol} | Nova Ref: {current_price:.4f} | CofreGlobal: {self.cfg.cofre_global:.2f}"
        self._save_state()

    def _monitor_position(self, symbol, slot, current_price):
        if slot["status"]=="PENDING":
            if slot["side"]=="buy" and current_price >= slot["entry_price"]:
                o=self._place(symbol,"buy",slot["qty"],current_price,position_idx=1)
                if not o: return
                slot["status"]="ACTIVE"
                slot["open_price"]=float(slot["entry_price"])
                slot["best_net"]=0.0
                _stp=float(slot.get("grid_step",0) or getattr(self,"grid_step",0) or self.cfg.grid_step_price)
                slot["target_price"]=round(float(slot["entry_price"])+_stp,8)
                return
            if slot["side"]=="sell" and current_price <= slot["entry_price"]:
                o=self._place(symbol,"sell",slot["qty"],current_price,position_idx=2)
                if not o: return
                slot["status"]="ACTIVE"
                slot["open_price"]=float(slot["entry_price"])
                slot["best_net"]=0.0
                _stp=float(slot.get("grid_step",0) or getattr(self,"grid_step",0) or self.cfg.grid_step_price)
                slot["target_price"]=round(float(slot["entry_price"])-_stp,8)
                return
            return
        if slot["status"]!="ACTIVE":
            return
        _tgt = float(slot["target_price"])
        _lvl = slot.get("grid_level", "?")
        _open = float(slot["entry_price"])
        slot["open_price"] = _open
        _qty = float(slot.get("qty", 0) or 0)
        # TRAVA RIGIDA: usa entry_price = o que o ecra mostra. open_price antigo era o preco do tick e nunca armava.: arma a 0.002 BRUTO, recuo ZERO, 1 tick contra fecha
        _rate = self._fee_rate()
        if slot["side"]=="buy":
            if current_price > float(slot.get("best_price", _open)): slot["best_price"]=current_price
            _gross_now = (current_price - _open)*_qty
        else:
            if current_price < float(slot.get("best_price", _open)): slot["best_price"]=current_price
            _gross_now = (_open - current_price)*_qty
        if _gross_now > float(slot.get("best_gross", 0.0)):
            slot["best_gross"] = _gross_now
        _best_gross = float(slot.get("best_gross", 0.0))
        _armed = _best_gross >= 0.002
        _hit_trava = _armed and (_gross_now < _best_gross)
        if slot["side"]=="buy":
            _hit_alvo = current_price >= _tgt
            if _hit_alvo or _hit_trava:
                closed=self._place(symbol,"sell",slot["qty"],current_price,position_idx=1,reduce_only=True)
                if not closed: return
                _gross = (current_price-_open)*slot["qty"]
                _fee = self._fee_rate()*(_open+current_price)*slot["qty"]
                _profit = _gross - _fee
                self.cfg.cofre+=_profit
                try:
                    self.hist_long_pnl+=_profit
                    _rsn = (f"TRAVA LONG {_lvl}" if (_hit_trava and not _hit_alvo) else f"GRID V6 LONG {_lvl}")
                    self.closed_orders.append({"time":int(time.time()),"side":"buy","entry":round(_open,8),"close":round(current_price,8),"profit":round(_profit,6),"gross":round(_gross,6),"fee":round(_fee,6),"reason":_rsn})
                except Exception: pass
                self._spawn_mirror(symbol, "sell", current_price)
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
                return
        else:
            _hit_alvo = current_price <= _tgt
            if _hit_alvo or _hit_trava:
                closed=self._place(symbol,"buy",slot["qty"],current_price,position_idx=2,reduce_only=True)
                if not closed: return
                _gross = (_open-current_price)*slot["qty"]
                _fee = self._fee_rate()*(_open+current_price)*slot["qty"]
                _profit = _gross - _fee
                self.cfg.cofre+=_profit
                try:
                    self.hist_short_pnl+=_profit
                    _rsn = (f"TRAVA SHORT {_lvl}" if (_hit_trava and not _hit_alvo) else f"GRID V6 SHORT {_lvl}")
                    self.closed_orders.append({"time":int(time.time()),"side":"sell","entry":round(_open,8),"close":round(current_price,8),"profit":round(_profit,6),"gross":round(_gross,6),"fee":round(_fee,6),"reason":_rsn})
                except Exception: pass
                self._spawn_mirror(symbol, "buy", current_price)
                slot["status"]="CLOSED"
                self.orders_state=[o for o in self.orders_state if not (o.get("id")==slot.get("id") and o.get("status")=="CLOSED")]
                return

    def _spawn_mirror(self, symbol, side, close_price):
        try:
            if getattr(self, "bloquear_novas", False): return
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
            self.orders_state.append({"id":f"ESP_{side}_{_entry}","side":side,"position_idx":_pos,"entry_price":_entry,"best_price":_entry,"best_net":0.0,"qty":_qty,"status":"PENDING","target_price":_tgt,"target_profit":round(_step*_qty,6),"grid_level":0,"grid_step":round(_step,8),"mirror":True})
        except Exception as e: logger.error(f"mirror: {e}")
    def _extend_grid(self, symbol, current_price):
        try:
            if getattr(self, "bloquear_novas", False): return
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
                    self.orders_state.append({"id":f"GRID_LONG_X_{_e}","side":"buy","position_idx":1,"entry_price":_e,"best_price":_e,"best_net":0.0,"qty":_q,"status":"PENDING","target_price":round(_e+_step,8),"target_profit":round(_step*_q,6),"grid_level":99,"grid_step":round(_step,8)})
            if _shorts:
                _min=min(float(o["entry_price"]) for o in _shorts)
                if current_price < _min:
                    _e=round(_min-_step,8)
                    _q=float(_shorts[0].get("qty",0))
                    self.orders_state.append({"id":f"GRID_SHORT_X_{_e}","side":"sell","position_idx":2,"entry_price":_e,"best_price":_e,"best_net":0.0,"qty":_q,"status":"PENDING","target_price":round(_e-_step,8),"target_profit":round(_step*_q,6),"grid_level":99,"grid_step":round(_step,8)})
        except Exception as e: logger.error(f"extend: {e}")
    @property
    def history(self):
        return list(getattr(self, "closed_orders", []))
    @history.setter
    def history(self, v):
        self.closed_orders = list(v or [])
    def _vantagem(self, symbol, current_price):
        _f = 0.0
        _rate = self._fee_rate()
        for o in self.orders_state:
            if o.get("status") != "ACTIVE": continue
            _op = float(o["entry_price"])
            _gross = (current_price - _op)*o["qty"] if o["side"]=="buy" else (_op - current_price)*o["qty"]
            _f += _gross - _rate*(_op + current_price)*o["qty"]
        return self.cfg.cofre + _f

    def _encerrar_operacao(self, symbol, reason="Lucro Operacao"):
        self.close_entire_cycle(symbol, reason=reason)
        self._fold_cofre_to_principal()
        self.cfg.completed_operations += 1
        _modo = getattr(self.cfg, "modo_operacao", "manual")
        _limite = int(getattr(self.cfg, "operacoes_por_dia", 0) or 0)
        if _modo == "auto" and (_limite <= 0 or self.cfg.completed_operations < _limite):
            self.cfg.status_message = f"Auto ({self.cfg.completed_operations}): nova operacao {symbol}"
            self.bloquear_novas = False
            self.initialize_cycle(symbol)
        else:
            self.cfg.is_running = False
            self.cfg.active_symbol = None
            self.reference_price = 0.0
            self.cfg.status_message = "Operacao encerrada. Aguardando Start."
        self._save_state()

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
                    self.orders_state.append({"id":f"LONG_CONV_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"best_net":0.0,"qty":qty,"status":"ACTIVE"})
                o2=self._place(symbol,"sell",qty,current_price,position_idx=2)
                if o2:
                    e=float(o2.get("average") or o2.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_CONV_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"best_net":0.0,"qty":qty,"status":"ACTIVE"})
            self._save_state()

    def _fold_cofre_to_principal(self):
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
        try:
            _t=self.ex.fetch_ticker(symbol); _px=float(_t["last"])
        except Exception: _px=float(getattr(self, "last_price", 0) or 0)
        _rate=self._fee_rate()
        for o in list(self.orders_state):
            if o.get("status")!="ACTIVE": continue
            _op=float(o["entry_price"])
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
