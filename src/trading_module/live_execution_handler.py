# src/trading_module/live_execution_handler.py

import ccxt.async_support as ccxt
import logging
import asyncio
from datetime import datetime, timezone
from src.common.objects import OrderEvent, FillEvent

logger = logging.getLogger(__name__)

class LiveExecutionHandler:
    """Gère l'exécution des ordres sur un exchange réel."""
    def __init__(self, event_bus: asyncio.Queue, portfolio, exchange_id: str, api_key: str, api_secret: str, is_testnet: bool = False):
        self.event_bus = event_bus
        self.portfolio = portfolio
        self.exchange_id = exchange_id
        self.api_key = api_key
        self.api_secret = api_secret
        self.is_testnet = is_testnet
        self.exchange = self._create_exchange_instance()

    @classmethod
    async def create(cls, event_bus: asyncio.Queue, portfolio, exchange_id: str, api_key: str, api_secret: str, is_testnet: bool = False):
        self = cls(event_bus, portfolio, exchange_id, api_key, api_secret, is_testnet)
        try:
            await self.exchange.load_markets()
            logger.info(f"Marchés chargés avec succès pour {self.exchange.id}.")
        except Exception as e:
            logger.error(f"Impossible de charger les marchés pour {exchange_id}: {e}")
            await self.exchange.close()
            raise
        return self

    def _create_exchange_instance(self):
        exchange_class = getattr(ccxt, self.exchange_id)
        instance = exchange_class({
            'apiKey': self.api_key,
            'secret': self.api_secret,
        })
        if self.is_testnet:
            if 'test' in instance.urls:
                instance.set_sandbox_mode(True)
                logger.warning(f"ATTENTION : MODE TESTNET/SANDBOX ACTIVÉ POUR {self.exchange_id.upper()}.")
            else:
                logger.error(f"L'exchange {self.exchange_id} ne supporte pas le mode testnet via ccxt.")
        return instance

    def _translate_symbol_to_execution(self, original_symbol: str) -> str:
        """
        Traduit un symbole d'une source de données (Kraken) vers le format
        attendu par la plateforme d'exécution (Binance).
        """
        # Exemple : 'BTC/USD' (Kraken) -> 'BTC/USDT' (Binance)
        if original_symbol.upper().endswith('/USD'):
            translated = original_symbol.upper().replace('/USD', '/USDT')
            logger.debug(f"Symbole traduit de '{original_symbol}' à '{translated}' pour l'exécution.")
            return translated
        return original_symbol


    async def on_order(self, order: OrderEvent):
        """Reçoit un OrderEvent, le place sur l'exchange et gère robustement la réponse."""
        logger.info(f"LIVE EXECUTION: Ordre reçu -> {order.direction} {order.quantity} {order.symbol}")
        
        try:
            execution_symbol = self._translate_symbol_to_execution(order.symbol)
            
            # Passe l'ordre de marché à l'exchange
            api_order = await self.exchange.create_market_order(
                symbol=execution_symbol,
                side=order.direction.lower(),
                amount=order.quantity
            )

            # --- BLOC DE VÉRIFICATION AMÉLIORÉ ---

            # Loggue la réponse brute de l'exchange pour le débogage
            logger.debug(f"Réponse de l'exchange pour l'ordre sur {execution_symbol}: {api_order}")

            # Vérification explicite si la réponse est vide (None) ou n'est pas un dictionnaire
            if not isinstance(api_order, dict):
                logger.error(f"Ordre non exécuté. Réponse invalide ou nulle de l'exchange pour {execution_symbol}.")
                return

            # Vérification que l'ordre a bien été rempli et que les données nécessaires sont présentes
            if api_order.get('filled', 0.0) > 0 and 'timestamp' in api_order and 'average' in api_order:
                fill_event = FillEvent(
                    timestamp=datetime.fromtimestamp(api_order['timestamp'] / 1000, tz=timezone.utc),
                    symbol=order.symbol, # Utilise le symbole original pour la cohérence interne
                    direction=order.direction,
                    quantity=float(api_order.get('filled')),
                    price=float(api_order.get('average')),
                    commission=float(api_order.get('fee', {}).get('cost', 0.0)),
                    exchange=self.exchange.id,
                    stop_loss_price=order.stop_loss_price,
                    take_profit_price=order.take_profit_price
                )
                logger.info(f"FillEvent généré : {fill_event}")
                await self.event_bus.put(fill_event)
            else:
                logger.error(f"Ordre non exécuté ou réponse incomplète de l'exchange: {api_order}")

        except ccxt.BadSymbol as e:
            logger.error(f"ERREUR D'EXÉCUTION : Symbole invalide. {e}")
        except ccxt.InsufficientFunds as e:
            logger.error(f"ERREUR D'EXÉCUTION : Fonds insuffisants sur le compte d'exécution. {e}")
        except Exception as e:
            logger.error(f"ERREUR D'EXÉCUTION : Erreur inattendue lors du passage d'ordre. {e}", exc_info=True)

