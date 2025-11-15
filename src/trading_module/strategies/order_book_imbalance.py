# src/trading_module/strategies/order_book_imbalance.py

from datetime import datetime, timedelta
from collections import deque
import pandas as pd
from .base import BaseStrategy
from src.common.objects import MarketEvent, SignalEvent

class OrderBookImbalanceStrategy(BaseStrategy):
    """
    Stratégie de scalping qui génère UNIQUEMENT des signaux d'ENTRÉE
    basés sur le déséquilibre du carnet d'ordres et un filtre de tendance.
    La sortie de position est entièrement déléguée au RiskManager.
    """
    def __init__(self, event_bus, portfolio, params: dict):
        super().__init__(event_bus, portfolio, params)
        # Paramètres de la stratégie
        self.imbalance_threshold = self.params['imbalance_threshold']
        self.cooldown_period = timedelta(seconds=self.params['cooldown_period_seconds'])
        self.trend_filter_window = self.params.get('trend_filter_window', 200)
        
        # Outils pour le filtre de tendance
        self.prices = deque(maxlen=self.trend_filter_window)
        self.last_signal_time = {}

    def on_market_data(self, event: MarketEvent):
        symbol = event.symbol
        position = self.portfolio.positions.get(symbol)
        mid_price = (event.best_bid + event.best_ask) / 2
        
        self.prices.append(mid_price)
        if len(self.prices) < self.trend_filter_window:
            return # Attendre d'avoir assez de données pour le filtre

        # Si une position est déjà ouverte, la stratégie ne fait rien.
        if position:
            return

        # Calculer le filtre de tendance (EMA longue)
        long_term_ema = pd.Series(list(self.prices)).ewm(span=self.trend_filter_window, adjust=False).mean().iloc[-1]
        
        # Calculer le déséquilibre du carnet d'ordres
        total_bid_volume = event.bids['volume'].sum()
        total_ask_volume = event.asks['volume'].sum()

        if total_ask_volume <= 0 or total_bid_volume <= 0: return

        imbalance_ratio = total_bid_volume / total_ask_volume
        signal_direction = None

        if imbalance_ratio > self.imbalance_threshold:
            signal_direction = 'LONG'
        elif (1 / imbalance_ratio) > self.imbalance_threshold:
            signal_direction = 'SHORT'
        
        # Appliquer le filtre de tendance
        if signal_direction == 'LONG' and mid_price < long_term_ema:
            return
        if signal_direction == 'SHORT' and mid_price > long_term_ema:
            return
        
        # Envoyer le signal d'ouverture si toutes les conditions sont remplies
        if signal_direction:
            last_time = self.last_signal_time.get(symbol)
            if last_time and (event.timestamp - last_time) < self.cooldown_period:
                return
            
            print(f"STRATEGY [Imbalance]: Opening signal to go {signal_direction} on {symbol} (Ratio: {imbalance_ratio:.2f})")
            opening_signal = SignalEvent(event.timestamp, symbol, direction=signal_direction)
            self.event_bus.put(opening_signal)
            self.last_signal_time[symbol] = event.timestamp