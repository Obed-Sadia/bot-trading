# src/trading_module/strategies/triangular_arbitrage.py

from .base import BaseStrategy
from src.common.objects import MarketEvent, SignalEvent
# NOTE: En pratique, on pourrait vouloir un événement spécial pour ce type de signal complexe.

class TriangularArbitrageStrategy(BaseStrategy):
    """
    Recherche des opportunités d'arbitrage entre trois paires de devises
    sur le même exchange.
    Exemple de cycle : USDT -> BTC -> ETH -> USDT
    """
    def __init__(self, event_bus, portfolio, params: dict):
        super().__init__(event_bus, portfolio, params)
        # Les trois paires (jambes) de l'arbitrage
        self.leg1, self.leg2, self.leg3 = params['legs']
        self.min_profit_pct = params['min_profit_pct']
        
        # Dictionnaire pour stocker l'état le plus récent de chaque paire
        self.market_data = {self.leg1: None, self.leg2: None, self.leg3: None}

    def on_market_data(self, event: MarketEvent):
        """
        Met à jour l'état du marché et vérifie une opportunité d'arbitrage.
        """
        symbol = event.symbol
        if symbol not in self.market_data:
            return # Ignore les événements qui ne concernent pas nos paires

        # Met à jour la dernière donnée connue pour la paire
        self.market_data[symbol] = event

        # Vérifie si nous avons des données fraîches pour les trois jambes
        if not all(self.market_data.values()):
            return

        # Récupère les meilleurs prix d'achat (bid) et de vente (ask)
        p1_ask = self.market_data[self.leg1].best_ask
        p2_ask = self.market_data[self.leg2].best_ask
        p3_bid = self.market_data[self.leg3].best_bid
        
        # Suppose un capital de départ de 1 unité de la devise de base (ex: 1 USDT)
        # et calcule le résultat du cycle d'échange.
        # Le calcul dépend de l'ordre des paires. Cet exemple est pour A->B, B->C, A->C
        # Ex: USDT -> BTC (achat de BTC), BTC -> ETH (achat de ETH), ETH -> USDT (vente de ETH)
        # La formule est : (1 / p1_ask) * (1 / p2_ask) * p3_bid
        # Une formule plus générale est nécessaire pour s'adapter à l'ordre des 'legs'.
        # Pour notre exemple BTC/USDT, ETH/BTC, ETH/USDT:
        # USDT -> BTC (Acheter BTC) => 1 / p_btc_usdt_ask
        # BTC -> ETH (Vendre BTC pour ETH) => (1/p_btc_usdt_ask) * p_eth_btc_bid
        # ETH -> USDT (Vendre ETH) => ((1/p_btc_usdt_ask) * p_eth_btc_bid) * p_eth_usdt_bid
        
        # Pour simplifier, nous vérifions juste un déséquilibre de taux
        # Taux A->B->C->A : (1/ask1) * (1/ask2) * bid3
        # Ce calcul est très spécifique au chemin. Une implémentation réelle
        # nécessite une gestion plus générique des chemins de conversion.
        
        # Exemple de calcul simplifié (ne pas utiliser en production sans validation)
        profit_ratio = (1 / p1_ask) * self.market_data[self.leg2].best_bid * p3_bid
        
        # Vérifie si le profit potentiel dépasse le seuil minimum requis (incluant les frais)
        # Une simulation de 3 transactions => ~0.3% de frais
        required_profit = 1 + self.min_profit_pct / 100 + 0.003 

        if profit_ratio > required_profit:
            print(f"STRATEGY [Arbitrage]: Opportunité détectée! Ratio: {profit_ratio:.6f}")
            # La génération de signaux pour l'arbitrage est complexe.
            # Idéalement, on enverrait un événement unique qui déclencherait 3 ordres.
            # Pour l'instant, nous émettons un signal sur la première jambe.
            signal = SignalEvent(event.timestamp, self.leg1, 'ARBITRAGE_BUY')
            self.event_bus.put(signal)
            # On vide les données pour attendre un nouveau cycle complet de ticks
            self.market_data = {leg: None for leg in self.market_data}