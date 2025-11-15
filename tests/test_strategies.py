# tests/test_strategies.py

import unittest
from queue import Queue
from collections import deque
from src.trading_module.strategies.sma_crossover import SmaCrossoverStrategy
from src.common.objects import MarketEvent

class TestSmaCrossover(unittest.TestCase):
    def test_long_signal_on_golden_cross(self):
        """
        Vérifie qu'un signal LONG est bien envoyé lors d'un croisement doré.
        """
        # 1. Configuration (Arrange)
        event_bus = Queue()
        mock_portfolio = None # La stratégie n'utilise pas le portfolio pour cette décision
        params = {'short_window': 3, 'long_window': 5}
        
        strategy = SmaCrossoverStrategy(event_bus, mock_portfolio, params)

        # Simuler une série de prix où un croisement se produit
        prices = [10, 11, 10, 9, 8] # long_sma > short_sma
        for p in prices:
            strategy.on_market_data(MarketEvent(None, "BTC/USDT", p, None, None, None))
        
        self.assertTrue(event_bus.empty()) # Pas encore de signal

        # 2. Action (Act)
        # Le prix qui cause le croisement
        final_price_event = MarketEvent(None, "BTC/USDT", 12, None, None, None)
        strategy.on_market_data(final_price_event)

        # 3. Vérification (Assert)
        self.assertFalse(event_bus.empty(), "Le bus d'événements ne devrait pas être vide.")
        signal = event_bus.get()
        self.assertEqual(signal.direction, 'LONG')

if __name__ == '__main__':
    unittest.main()