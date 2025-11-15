import ccxt.async_support as ccxt
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class KrakenCandleBackfillConnector:
    """
    Un connecteur spécialisé dont l'unique rôle est de télécharger un 
    historique de bougies depuis Kraken au démarrage.
    """
    def __init__(self):
        # Initialise un client ccxt 
        # pour télécharger les données publiques de marché (OHLCV).
        self.exchange = ccxt.kraken()
        logger.info("KrakenCandleBackfillConnector initialisé.")

    async def fetch_initial_candles(self, symbol: str, timeframe: str, limit: int) -> list:
        """
        Télécharge les N dernières bougies pour un symbole donné.
        """
        try:
            logger.info(f"Téléchargement de {limit} bougies '{timeframe}' pour {symbol} via ccxt...")
            
            # Utilise ccxt pour récupérer les données OHLCV
            # timeframe: '1h' pour 1 heure, '1m' pour 1 minute, etc.
            ohlcv = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            
            if not ohlcv:
                logger.warning("Aucune donnée OHLCV retournée par l'exchange.")
                return []

            # Formater les données pour la stratégie : [datetime, o, h, l, c, v]
            # On ignore la dernière bougie car elle est en cours de formation.
            formatted_candles = [
                [datetime.fromtimestamp(candle[0] / 1000, tz=timezone.utc), candle[1], candle[2], candle[3], candle[4], candle[5]]
                for candle in ohlcv
            ]
            
            logger.info(f"✅ {len(formatted_candles)} bougies historiques téléchargées avec succès.")
            return formatted_candles

        except Exception as e:
            logger.error(f"Échec du téléchargement des bougies historiques : {e}", exc_info=True)
            return []
        finally:
            # Ferme la session du client après l'opération
            await self.exchange.close()