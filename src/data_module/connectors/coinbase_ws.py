import asyncio
import websockets
import json
import logging
from datetime import datetime
from .base import BaseConnector
from ..schemas import CoinbaseL2Snapshot, CoinbaseL2Update, Trade
from src.monitoring import MESSAGES_PROCESSED

logger = logging.getLogger(__name__)

class CoinbaseConnector(BaseConnector):
    """
    Connecteur pour les flux de données publics de Coinbase (Level 2 et Trades).
    N'utilise PAS d'authentification car les canaux ('level2', 'matches') sont publics.
    """
    def __init__(self, symbols: list, queue: asyncio.Queue):
        super().__init__(symbols, None)
        self.queue = queue
        self.exchange_name = "coinbase"

    async def connect(self):
        url = "wss://ws-feed.exchange.coinbase.com"
        logger.info(f"[{self.exchange_name.upper()}] Connexion à {url}...")

        subscribe_message = {
            "type": "subscribe",
            "product_ids": sorted(self.symbols),
            "channels": ["level2", "matches"]
        }

        while True:
            try:
                # Utilisation des pings/pongs gérés par la bibliothèque pour maintenir la connexion active.
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as websocket:

                    await websocket.send(json.dumps(subscribe_message))
                    logger.info(f"[{self.exchange_name.upper()}] Souscription publique envoyée pour les canaux {subscribe_message['channels']} sur les paires {self.symbols}.")

                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            msg_type = data.get('type')

                            if msg_type == 'subscriptions':
                                # Une réponse de souscription réussie a un champ 'channels'.
                                if 'channels' in data:
                                    logger.info(f"[{self.exchange_name.upper()}] Abonnement réussi: {data['channels']}")
                                else:
                                    # Gère les messages d'erreur à la souscription.
                                    logger.error(f"[{self.exchange_name.upper()}] Échec de l'abonnement, réponse: {data}")

                            elif msg_type in ['snapshot', 'l2update']:
                                if msg_type == 'snapshot':
                                    validated_data = CoinbaseL2Snapshot.model_validate(data)
                                    await self.queue.put(('coinbase_l2_snapshot', validated_data))
                                elif msg_type == 'l2update':
                                    validated_data = CoinbaseL2Update.model_validate(data)
                                    await self.queue.put(('coinbase_l2_update', validated_data))
                                MESSAGES_PROCESSED.labels(exchange=self.exchange_name, type=msg_type).inc()

                            elif msg_type == 'match':
                                validated_trade = Trade(
                                    exchange=self.exchange_name,
                                    symbol=data['product_id'],
                                    price=float(data['price']),
                                    quantity=float(data['size']),
                                    side=data['side'],
                                    trade_time=datetime.fromisoformat(data['time'].replace("Z", "+00:00")),
                                    trade_id=str(data['trade_id'])
                                )
                                await self.queue.put(('trade', validated_trade))
                                MESSAGES_PROCESSED.labels(exchange=self.exchange_name, type=msg_type).inc()

                            elif msg_type == 'error':
                                logger.error(f"[{self.exchange_name.upper()}] Erreur reçue du serveur: {json.dumps(data)}")

                        except json.JSONDecodeError:
                            logger.warning(f"[{self.exchange_name.upper()}] Message non-JSON reçu: {message}")
                        except Exception as e:
                            logger.error(f"[{self.exchange_name.upper()}] Erreur de traitement du message: {e}", exc_info=True)

            except websockets.exceptions.ConnectionClosed as e:
                logger.error(f"[{self.exchange_name.upper()}] Connexion fermée: {e}. Reconnexion dans 5s...")
            except Exception as e:
                logger.error(f"[{self.exchange_name.upper()}] Erreur de connexion générale: {e}. Reconnexion dans 5s...")
            
            await asyncio.sleep(5)