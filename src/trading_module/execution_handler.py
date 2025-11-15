# src/trading_module/execution_handler.py

from datetime import datetime
from src.common.objects import OrderEvent, FillEvent
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .portfolio import Portfolio

class SimulatedExecutionHandler:
    """
    Simule l'exécution d'ordres, en propageant toutes les informations
    pertinentes (y compris stop-loss et take-profit) à l'événement de confirmation.
    """
    def __init__(self, event_bus, portfolio: 'Portfolio'):
        self.event_bus = event_bus
        self.portfolio = portfolio

    def on_order(self, order: OrderEvent):
        """
        "Exécute" l'ordre en simulant slippage et frais.
        """
        last_price = self.portfolio.get_last_price(order.symbol)
        if last_price <= 0:
            print(f"EXECUTION ERROR: Pas de prix de marché pour {order.symbol}, ordre annulé.")
            return

        slippage = last_price * 0.0005
        if order.direction == 'BUY':
            fill_price = last_price + slippage
        else:
            fill_price = last_price - slippage
            
        commission = order.quantity * fill_price * 0.001

        fill_event = FillEvent(
            timestamp=datetime.utcnow(),
            symbol=order.symbol,
            direction=order.direction,
            quantity=order.quantity,
            price=fill_price,
            commission=commission,
            exchange='SIMULATED',
            stop_loss_price=order.stop_loss_price,
            take_profit_price=order.take_profit_price # <-- CORRECTION : Ajout du take-profit
        )
        
        print(f"EXECUTION: {order.direction} {order.quantity} {order.symbol} at ~{fill_price:.2f}")
        self.event_bus.put(fill_event)