# src/backtesting_module/engine.py

import queue
import pandas as pd
from .data_loader import HistoricCSVDataLoader
from .report_generator import ReportGenerator
from src.trading_module.portfolio import Portfolio
#from src.trading_module.portfolio import Portfolio

from src.trading_module.risk_manager import RiskManager
from src.trading_module.execution_handler import SimulatedExecutionHandler

class BacktestEngine:
    def __init__(self, csv_path, symbol, initial_capital, strategy_loader, strategy_name, strategy_params):
        self.event_queue = queue.Queue()
        self.csv_path = csv_path
        self.symbol = symbol
        self.initial_capital = initial_capital
        
        self.equity_history = []
        self.trade_history = []

        self.portfolio = Portfolio(self.event_queue, self.initial_capital)
        self.risk_manager = RiskManager(self.event_queue, self.portfolio)
        self.execution_handler = SimulatedExecutionHandler(self.event_queue, self.portfolio)
        self.data_loader = HistoricCSVDataLoader(self.event_queue, self.csv_path, self.symbol)
        
        self.strategy = strategy_loader.load_strategy(
            name=strategy_name,
            event_bus=self.event_queue,
            portfolio=self.portfolio,
            params=strategy_params
        )

        self.event_handlers = {
            "MARKET": self.handle_market_event,
            "SIGNAL": self.risk_manager.on_signal,
            "ORDER": self.execution_handler.on_order,
            "FILL": self.handle_fill_event,
        }

    def handle_market_event(self, event):
        """Met à jour l'état du système puis délègue aux autres composants."""
        mid_price = (event.best_bid + event.best_ask) / 2
    
        # 1. Mettre à jour le portefeuille avec le dernier prix connu
        self.portfolio.update_portfolio_value({event.symbol: mid_price})
        
        # 2. Laisser la stratégie et le risk manager agir sur la base de cet état à jour
        self.strategy.on_market_data(event)
        #self.risk_manager.check_stops({event.symbol: mid_price})
        self.risk_manager.check_exits({event.symbol: mid_price})
        
        # 3. Enregistrer l'historique
        self.equity_history.append((event.timestamp, self.portfolio.total_value))

    def handle_fill_event(self, event):
        """Gère les FillEvents pour mettre à jour le portefeuille et enregistrer le trade."""
        self.portfolio.update_on_fill(event)
        self.trade_history.append(event)

    def run(self):
        """Lance la boucle principale d'événements."""
        print("🚀 Lancement du backtest...")
        
        while self.data_loader.stream_next():
            while not self.event_queue.empty():
                try:
                    event = self.event_queue.get(False)
                except queue.Empty:
                    break
                else:
                    if hasattr(event, 'type') and event.type in self.event_handlers:
                        self.event_handlers[event.type](event)
        
        self.generate_report()

    def generate_report(self):
        """Génère et affiche le rapport de performance final."""
        if not self.equity_history:
            print("\n--- Backtest Terminé : Aucune donnée de marché traitée. ---")
            return
            
        print("\n--- Backtest Terminé ---")
        equity_df = pd.DataFrame(self.equity_history, columns=['timestamp', 'value']).set_index('timestamp')
        
        report_generator = ReportGenerator(equity_df['value'], self.trade_history)
        report_generator.generate_summary()
        report_generator.plot_equity_curve()