# src/trading_module/risk_manager.py

from datetime import datetime
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .portfolio import Portfolio
from src.common.objects import SignalEvent, OrderEvent

class RiskManager:
    def __init__(self, event_bus, portfolio: 'Portfolio', risk_per_trade_pct=0.01):
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.risk_per_trade_pct = risk_per_trade_pct

    def get_atr(self, symbol: str) -> float:
        last_price = self.portfolio.get_last_price(symbol)
        return last_price * 0.03 if last_price else 0.0

    async def on_signal(self, signal: SignalEvent): # <-- CHANGEMENT: async def
        if self.portfolio.is_panic_mode: return

        last_price = self.portfolio.get_last_price(signal.symbol)
        if last_price <= 0: return

        atr = self.get_atr(signal.symbol)
        if atr <= 0: return
        
        risk_per_trade_abs = self.portfolio.total_value * self.risk_per_trade_pct
        stop_multiplier = 2.0
        risk_reward_ratio = 1.5
        
        stop_distance = stop_multiplier * atr
        if stop_distance == 0: return
        
        quantity = risk_per_trade_abs / stop_distance
        if quantity <= 0: return

        stop_loss_price, take_profit_price = 0.0, 0.0
        if signal.direction == 'LONG':
            stop_loss_price = last_price - stop_distance
            take_profit_price = last_price + (stop_distance * risk_reward_ratio)
        else:
            stop_loss_price = last_price + stop_distance
            take_profit_price = last_price - (stop_distance * risk_reward_ratio)

        order = OrderEvent(
            timestamp=datetime.utcnow(),
            symbol=signal.symbol,
            order_type='MARKET',
            direction='BUY' if signal.direction == 'LONG' else 'SELL',
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            take_profit_price=take_profit_price
        )
        print(f"RISK MANAGER [SUCCESS]: Creating OrderEvent -> {order}")
        await self.event_bus.put(order) # <-- CHANGEMENT: await

    async def check_exits(self, market_data: dict): # <-- CHANGEMENT: async def
        for symbol, position in list(self.portfolio.positions.items()):
            current_price = market_data.get(symbol)
            if not current_price: continue

            exit_triggered = False
            exit_reason = ""

            if position.direction == 'BUY' and current_price <= position.stop_loss_price:
                exit_triggered = True
                exit_reason = "Stop-Loss"
            elif position.direction == 'SELL' and current_price >= position.stop_loss_price:
                exit_triggered = True
                exit_reason = "Stop-Loss"
            
            if not exit_triggered and position.take_profit_price > 0:
                if position.direction == 'BUY' and current_price >= position.take_profit_price:
                    exit_triggered = True
                    exit_reason = "Take-Profit"
                elif position.direction == 'SELL' and current_price <= position.take_profit_price:
                    exit_triggered = True
                    exit_reason = "Take-Profit"

            if exit_triggered:
                print(f"RISK MANAGER [EXIT]: {exit_reason} triggered for {position.direction} {symbol} at {current_price}")
                closing_direction = 'SELL' if position.direction == 'BUY' else 'BUY'
                close_order = OrderEvent(
                    timestamp=datetime.utcnow(),
                    symbol=symbol, order_type='MARKET',
                    direction=closing_direction, quantity=abs(position.quantity)
                )
                await self.event_bus.put(close_order) # <-- CHANGEMENT: await