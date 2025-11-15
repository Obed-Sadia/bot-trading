# src/trading_module/strategies/sma_crossover.py
"""
from collections import deque
from datetime import datetime
import pandas as pd
from .base import BaseStrategy
from src.common.objects import SignalEvent, MarketEvent

class SmaCrossoverStrategy(BaseStrategy):
    
    Stratégie basée sur le croisement de deux moyennes mobiles, avec une
    gestion d'état robuste pour détecter les croisements.
    
    
    def __init__(self, event_bus, portfolio, params: dict):
        super().__init__(event_bus, portfolio, params)
        self.short_window = self.params['short_window']
        self.long_window = self.params['long_window']
        
        self.prices = deque(maxlen=self.long_window)
        
        # --- CORRECTION : Variable pour mémoriser l'état précédent ---
        self.last_signal_state = None # Peut être 'LONG' ou 'SHORT'

    def on_market_data(self, event: MarketEvent):
        symbol = event.symbol
        position = self.portfolio.positions.get(symbol)

        if position:
            return

        mid_price = (event.best_bid + event.best_ask) / 2
        self.prices.append(mid_price)

        if len(self.prices) < self.long_window:
            return

        prices_series = pd.Series(list(self.prices))
        short_sma = prices_series.rolling(window=self.short_window).mean().iloc[-1]
        long_sma = prices_series.rolling(window=self.long_window).mean().iloc[-1]
        
        # --- CORRECTION : Logique de détection de croisement simplifiée et robuste ---
        
        # 1. Déterminer l'état actuel
        current_signal_state = None
        if short_sma > long_sma:
            current_signal_state = 'LONG'
        elif short_sma < long_sma:
            current_signal_state = 'SHORT'

        # 2. Vérifier si l'état a changé (un croisement a eu lieu)
        if current_signal_state and current_signal_state != self.last_signal_state:
            print(f"STRATEGY [SMA Crossover]: Crossover detected. Signal to go {current_signal_state} on {symbol}.")
            opening_signal = SignalEvent(
                timestamp=datetime.utcnow(), 
                symbol=symbol, 
                direction=current_signal_state
            )
            self.event_bus.put(opening_signal)
            
            # 3. Mettre à jour le dernier état connu
            self.last_signal_state = current_signal_state"""
            
            
            

# src/trading_module/strategies/sma_crossover.py

import logging
from collections import deque
from datetime import datetime, timezone
import pandas as pd
from .base import BaseStrategy
from src.common.objects import SignalEvent, MarketEvent

logger = logging.getLogger(__name__)

class SmaCrossoverStrategy(BaseStrategy):
    """Stratégie de croisement de moyennes mobiles avec une communication asynchrone correcte."""
    def __init__(self, event_bus, portfolio, params: dict):
        super().__init__(event_bus, portfolio, params)
        self.short_window = self.params.get('short_window', 3)
        self.long_window = self.params.get('long_window', 7)
        self.prices = deque(maxlen=self.long_window)
        self.last_signal_state = None

    # --- CORRECTION : La méthode doit être asynchrone ---
    async def on_market_data(self, event: MarketEvent):
        symbol = event.symbol
        if self.portfolio.positions.get(symbol):
            return

        mid_price = (event.best_bid + event.best_ask) / 2
        self.prices.append(mid_price)

        if len(self.prices) < self.long_window:
            logger.debug(f"[{symbol}] Collecte de données SMA: {len(self.prices)}/{self.long_window}")
            return

        prices_series = pd.Series(list(self.prices))
        short_sma = prices_series.rolling(window=self.short_window).mean().iloc[-1]
        long_sma = prices_series.rolling(window=self.long_window).mean().iloc[-1]
        
        logger.debug(f"[{symbol}] SMA Courte({self.short_window}): {short_sma:.2f} | SMA Longue({self.long_window}): {long_sma:.2f}")

        current_signal_state = 'LONG' if short_sma > long_sma else 'SHORT'

        if current_signal_state != self.last_signal_state:
            logger.info(f"STRATEGY [SMA Crossover]: CROISEMENT DÉTECTÉ! Signal pour aller {current_signal_state} sur {symbol}.")
            
            opening_signal = SignalEvent(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol, 
                direction=current_signal_state
            )
            
            # --- CORRECTION : 'await' est ajouté pour envoyer correctement le signal ---
            await self.event_bus.put(opening_signal)
            
            self.last_signal_state = current_signal_state
