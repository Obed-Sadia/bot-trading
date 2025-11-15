# src/trading_module/strategies/base.py

from abc import ABC, abstractmethod

class BaseStrategy(ABC):
    """
    Classe de base abstraite pour toutes les stratégies de trading.
    Toute nouvelle stratégie doit hériter de cette classe.
    """
    def __init__(self, event_bus, portfolio, params: dict):
        """
        Initialise la stratégie.
        
        :param event_bus: Le bus d'événements pour envoyer des signaux.
        :param portfolio: L'instance du portefeuille pour connaître l'état actuel.
        :param params: Un dictionnaire de paramètres provenant du fichier de configuration.
        """
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.params = params

    @abstractmethod
    def on_market_data(self, event):
        """
        Méthode principale appelée à chaque nouvel événement de marché.
        C'est ici que la logique de la stratégie réside.
        """
        raise NotImplementedError("La méthode on_market_data() doit être implémentée.")