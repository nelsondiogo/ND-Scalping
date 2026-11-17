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
        self._load_state()

    def _is_paper(self): return bool(getattr(self.cfg,"paper_trading",False))
    def _paper_place(self, symbol, side, qty, price, position_idx):
        fake={"id":f"PAPER_{int(time.time()*1000)}","average":price,"price":price,"side":side,"amount":qty}
        logger.info(f"[PAPEL] Ordem simulada {side} {symbol} qty={qty} @ {price}")
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

    def _save_state(self):
        try:
            data={"ref":self.reference_price,"orders":self.orders_state,"active":self.cfg.active_symbol,
                  "equity0":self.cfg.cycle_initial_equity,"cofre":self.cfg.cofre,"cofre_global":self.cfg.cofre_global,
                  "last_touch":self.last_ref_touch,"cycle_start":self.cycle_start_time,"is_running":self.cfg.is_running,
                  "paper":self._is_paper(),"paper_equity":self.paper_equity}
            with open(STATE_FILE,"w") as f: json.dump(data,f)
        except Exception as e: logger.error(f"save_state: {e}")
    def _load_state(self):
        if not os.path.exists(STATE_FILE): return
        try:
            with open(STATE_FILE) as f: d=json.load(f)
            if bool(d.get("paper",False)) != self._is_paper():
                logger.info("Mudanca de modo Papel/Real - estado antigo ignorado")
                return
            self.reference_price=d.get("ref",0.0); self.orders_state=d.get("orders",[])
            self.cfg.active_symbol=d.get("active"); self.cfg.cycle_initial_equity=d.get("equity0",0)
            self.cfg.cofre=d.get("cofre",0); self.cfg.cofre_global=d.get("cofre_global",0)
            self.last_ref_touch=d.get("last_touch",time.time()); self.cycle_start_time=d.get("cycle_start",time.time())
            self.paper_equity=d.get("paper_equity",0)
        except Exception as e: logger.error(f"load_state: {e}")

    def start_background_loop(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread=threading.Thread(target=self._run_loop,daemon=True); self._thread.start()
    def _run_loop(self):
        while True:
            try:
                if self.cfg.is_running: self.tick()
            except Exception as e: logger.error(f"tick err: {e}")
            time.sleep(1.0)

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
        if self._is_paper():
            equity=self.cfg.paper_initial_balance if self.cfg.cycle_initial_equity<=0 else self.cfg.cycle_initial_equity
            if self.paper_equity>0: equity=self.paper_equity
        else:
            equity=self.ex.get_total_equity()
            if equity<0:
                self.cfg.is_running=False; self.cfg.status_message="Erro a ler equity"; return
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
        self.cfg.status_message=f"{mode}Operando {symbol} | Ref: {self.reference_price:.4f}"
        self._save_state()

    def tick(self):
        with self.lock:
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
            if self.cfg.cycle_initial_equity>0:
                net=equity-self.cfg.cycle_initial_equity
                target=self.cfg.cycle_initial_equity*(self.cfg.target_profit_pct/100)
                maxloss=self.cfg.cycle_initial_equity*(self.cfg.max_loss_pct/100)
                if net>=target:
                    self.close_entire_cycle(symbol, reason="Meta Atingida"); self._handle_post_cycle_transition(); return
                if net<=-maxloss:
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
        pnl_conj=self._live_positions_pnl(symbol, current_price)
        if self._is_paper(): self._close_all_paper()
        else: self.ex.close_all_positions(symbol)
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        resultado=self.cfg.cofre + pnl_conj - taxas_est
        self.cfg.cofre_global+=resultado
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
        self.cfg.status_message=f"Reancorado {symbol} | Nova Ref: {current_price:.4f}"
        self._save_state()

    def _monitor_position(self, symbol, slot, current_price):
        side=slot["side"]; entry=slot["entry_price"]
        if side=="buy":
            if current_price>slot["best_price"]: slot["best_price"]=current_price
            in_profit=current_price>entry
            drawdown=(slot["best_price"]-current_price)/slot["best_price"] if slot["best_price"]>0 else 0
            if in_profit and drawdown>=self.cfg.trailing_offset_pct:
                closed=self._place(symbol,"sell",slot["qty"],current_price,position_idx=1,reduce_only=True)
                if not closed: return
                profit=(current_price-entry)*slot["qty"]
                self.cfg.cofre+=profit
                slot["status"]="CLOSED"
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self._place(symbol,"buy",qty,current_price,position_idx=1)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"LONG_REV_{int(time.time())}","side":"buy","position_idx":1,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        elif side=="sell":
            if current_price<slot["best_price"]: slot["best_price"]=current_price
            in_profit=current_price<entry
            bounce=(current_price-slot["best_price"])/slot["best_price"] if slot["best_price"]>0 else 0
            if in_profit and bounce>=self.cfg.trailing_offset_pct:
                closed=self._place(symbol,"buy",slot["qty"],current_price,position_idx=2,reduce_only=True)
                if not closed: return
                profit=(entry-current_price)*slot["qty"]
                self.cfg.cofre+=profit
                slot["status"]="CLOSED"
                qty=self.ex.calculate_qty(symbol, self.cfg.margin_per_order, self.cfg.leverage, current_price)
                new_o=self._place(symbol,"sell",qty,current_price,position_idx=2)
                if new_o:
                    e=float(new_o.get("average") or new_o.get("price") or current_price)
                    self.orders_state.append({"id":f"SHORT_REV_{int(time.time())}","side":"sell","position_idx":2,"entry_price":e,"best_price":e,"qty":qty,"status":"ACTIVE"})
        self.orders_state=[o for o in self.orders_state if o["status"]!="CLOSED"]

    def _check_convergence(self, symbol, current_price):
        act=[o for o in self.orders_state if o["status"]=="ACTIVE"]
        if len(act)<2: return
        pnl_conj=self._live_positions_pnl(symbol, current_price)
        notional=self.cfg.margin_per_order*self.cfg.leverage*2
        taxas_est=notional*self.cfg.fee_rate*2
        net_conj=pnl_conj-taxas_est
        if net_conj>0:
            if self._is_paper(): self._close_all_paper()
            else:
                ok=self.ex.close_all_positions(symbol)
                if not ok: return
            self.cfg.cofre+=net_conj
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

    def _handle_post_cycle_transition(self):
        self.cfg.completed_operations+=1
        self.cfg.cofre_global+=self.cfg.cofre
        if self._is_paper(): self.paper_equity=self.cfg.cycle_initial_equity + self.cfg.cofre_global
        self.cfg.cofre=0.0
        if self.cfg.auto_mode and self.cfg.completed_operations < self.cfg.max_auto_operations:
            self.cfg.pair_index=(self.cfg.pair_index+1)%len(TOP_PAIRS)
            nxt=TOP_PAIRS[self.cfg.pair_index]
            time.sleep(1); self.initialize_cycle(nxt)
        else:
            self.cfg.is_running=False; self.cfg.active_symbol=None
            self.cfg.status_message=f"Concluido. CofreGlobal: {self.cfg.cofre_global:.2f}"
            self._save_state()
