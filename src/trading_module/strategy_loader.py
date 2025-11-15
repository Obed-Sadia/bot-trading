# src/trading_module/strategy_loader.py

import logging

from .strategies.sma_crossover import SmaCrossoverStrategy
from .strategies.order_book_imbalance import OrderBookImbalanceStrategy
from .strategies.triangular_arbitrage import TriangularArbitrageStrategy
from .strategies.multi_model_strategy import MultiModelStrategy

logger = logging.getLogger(__name__)

STRATEGIES = {
    "sma_crossover": SmaCrossoverStrategy,
    "order_book_imbalance": OrderBookImbalanceStrategy,
    "triangular_arbitrage": TriangularArbitrageStrategy,
    "multi_model_strategy": MultiModelStrategy
}

def load_strategy(strategy_name: str, event_bus, portfolio, params: dict, **kwargs):
    """
    Charge et instancie une stratégie par son nom.
    """
    if strategy_name in STRATEGIES:
        logger.info(f"Chargement de la stratégie: {strategy_name}")
        # On passe les arguments supplémentaires (comme exchange_client) à la stratégie
        return STRATEGIES[strategy_name](event_bus, portfolio, params, **kwargs)
    else:
        raise ValueError(f"Stratégie inconnue: {strategy_name}")
