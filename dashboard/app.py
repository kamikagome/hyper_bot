import asyncio
import asyncpg
import redis.asyncio as redis
from config import settings
from nicegui import ui

class DashboardApp:
    def __init__(self):
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.pool = None
        self.setup_ui()
    
    async def init_db(self):
        if not self.pool:
            self.pool = await asyncpg.create_pool(settings.POSTGRES_URL)

    def setup_ui(self):
        ui.label('Hyperliquid Market-Making Bot Dashboard').classes('text-3xl font-extrabold mb-6')
        
        with ui.row().classes('w-full gap-4'):
            with ui.card().classes('w-1/3 p-4 shadow-lg'):
                ui.label('Live Status').classes('text-xl font-bold border-b pb-2 mb-2 w-full')
                self.pnl_label = ui.label('Total P&L: $0.00').classes('text-lg')
                self.pos_label = ui.label('Current Position: 0.00').classes('text-lg')
                self.cb_status = ui.label('Circuit Breaker: OK').classes('text-green-500 font-bold text-lg mt-2')
                ui.button('Reset CB', on_click=self.reset_cb).classes('mt-4 bg-red-500 text-white w-full')
            
            with ui.card().classes('w-1/3 p-4 shadow-lg'):
                ui.label('Engine Controls').classes('text-xl font-bold border-b pb-2 mb-2 w-full')
                ui.label('Target Position Size (ETH)').classes('text-sm text-gray-500')
                self.tgt_input = ui.number(format='%.2f', on_change=self.update_target).classes('w-full mb-4')
                self.pause_btn = ui.button('Pause Engine', on_click=self.toggle_pause).classes('mt-2 w-full bg-yellow-500')
            
        with ui.row().classes('w-full gap-4 mt-6'):
            with ui.card().classes('w-1/2 p-4 shadow-lg'):
                ui.label('Latency (Tick-to-Trade)').classes('text-xl font-bold border-b pb-2 mb-2 w-full')
                ui.label('Rolling 1000 cancel paths').classes('text-sm text-gray-500')
                self.t2t_stats = ui.label('p50: -ms | p95: -ms | p99: -ms').classes('text-xl mt-4 font-mono')
                
            with ui.card().classes('w-1/2 p-4 shadow-lg'):
                ui.label('Markouts (Slippage)').classes('text-xl font-bold border-b pb-2 mb-2 w-full')
                ui.label('Rolling 500 fills Beta-adjusted').classes('text-sm text-gray-500')
                self.markout_stats = ui.label('5s: - | 30s: - | 5m: -').classes('text-xl mt-4 font-mono')

    async def update_target(self, e):
        if e.value is not None:
            await self.redis.set("bot:target_position", float(e.value))
            ui.notify(f"Target mathematically set to {e.value}")

    async def toggle_pause(self):
        is_paused = await self.redis.get("bot:paused") == "true"
        await self.redis.set("bot:paused", "false" if is_paused else "true")
        ui.notify("Engine Resumed" if is_paused else "Engine Paused", type='warning' if not is_paused else 'positive')

    async def reset_cb(self):
        await self.redis.set("bot:paused", "false")
        ui.notify("Circuit breaker boundaries manually bypassed!", type='negative')

    async def update_data(self):
        await self.init_db()
        
        # Sync simple toggle states
        is_paused = await self.redis.get("bot:paused") == "true"
        self.cb_status.text = 'Circuit Breaker: TRIPPED / PAUSED' if is_paused else 'Circuit Breaker: OK'
        self.cb_status.classes(replace='text-red-500 font-bold text-lg mt-2' if is_paused else 'text-green-500 font-bold text-lg mt-2')
        self.pause_btn.text = 'Resume Engine' if is_paused else 'Pause Engine'
        
        # Async fetch and update DOM bindings
        async with self.pool.acquire() as conn:
            snap = await conn.fetchrow("SELECT position_size, unrealized_pnl + realized_pnl as total_pnl FROM position_snapshots ORDER BY id DESC LIMIT 1")
            if snap:
                self.pos_label.text = f"Current Position: {snap['position_size']}"
                self.pnl_label.text = f"Total P&L: ${snap['total_pnl']:.2f}"
                
            ttt = await conn.fetch("SELECT tick_to_trade_ns FROM orders WHERE tick_to_trade_ns IS NOT NULL ORDER BY id DESC LIMIT 1000")
            if ttt:
                arr = sorted([row['tick_to_trade_ns'] for row in ttt])
                p50 = arr[int(len(arr)*0.5)] / 1_000_000 if arr else 0
                p95 = arr[int(len(arr)*0.95)] / 1_000_000 if len(arr) > 20 else 0
                p99 = arr[int(len(arr)*0.99)] / 1_000_000 if len(arr) > 100 else 0
                self.t2t_stats.text = f"p50: {p50:.2f}ms | p95: {p95:.2f}ms | p99: {p99:.2f}ms"
                
            m_out = await conn.fetch("SELECT AVG(markout_5s) as m5s, AVG(markout_30s) as m30s, AVG(markout_5m) as m5m FROM (SELECT * FROM fills ORDER BY id DESC LIMIT 500) sub")
            if m_out and m_out[0]['m5s'] is not None:
                o = m_out[0]
                self.markout_stats.text = f"5s: {o['m5s']:.4f} | 30s: {o['m30s']:.4f} | 5m: {o['m5m']:.4f}"
