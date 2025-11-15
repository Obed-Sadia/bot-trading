import asyncio
import json
import logging
import pandas as pd
import websockets
from datetime import datetime, timezone
from src.common.objects import MarketEvent

logger = logging.getLogger(__name__)

class KrakenTradeConnector:
    """
    Connecteur WebSocket pour Kraken, optimisé pour le TRADING EN DIRECT.
    Gère les messages 'snapshot' et 'update' de manière robuste.
    """
    _WS_URL = "wss://ws.kraken.com/v2"

    def __init__(self, symbols: list[str], queue: asyncio.Queue):
        if not symbols:
            raise ValueError("La liste des symboles ne peut pas être vide.")
        self.symbols = symbols
        self.queue = queue
        self.running = False

    async def connect(self):
        logger.info(f"[KRAKEN_TRADE] Connexion à {self._WS_URL}...")
        subscription_msg = {
            "method": "subscribe",
            "params": {"channel": "book", "symbol": self.symbols, "depth": 10}
        }
        self.running = True
        while self.running:
            try:
                async with websockets.connect(self._WS_URL) as websocket:
                    await websocket.send(json.dumps(subscription_msg))
                    logger.info(f"[KRAKEN_TRADE] Souscription au carnet d'ordres réussie pour: {self.symbols}")
                    await self.listen(websocket)
            except Exception as e:
                logger.warning(f"[KRAKEN_TRADE] Connexion WebSocket perdue: {e}. Reconnexion...")
                await asyncio.sleep(5)

    async def listen(self, websocket):
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("channel") == "book":
                    await self._process_book_message(data)
            except Exception as e:
                logger.error(f"[KRAKEN_TRADE] Erreur dans la boucle d'écoute: {e}", exc_info=True)

    async def _process_book_message(self, data: dict):
        """Analyse un message du carnet d'ordres et le route."""
        
        
        # On vérifie le type de message. Si c'est un 'snapshot', on l'ignore.
        message_type = data.get('type')
        if message_type == 'snapshot':
            logger.debug("[KRAKEN_TRADE] Snapshot initial reçu et ignoré. En attente des mises à jour.")
            return
        
        # Si ce n'est pas un snapshot, on essaie de le traiter comme une mise à jour.
        try:
            book_data = data['data'][0]
            symbol = book_data['symbol']
            
            # Les mises à jour doivent avoir un timestamp.
            timestamp_str = book_data['timestamp']

            bids_raw = book_data.get('bids', [])
            asks_raw = book_data.get('asks', [])

            if not bids_raw or not asks_raw:
                return

            bids_df = pd.DataFrame(bids_raw, columns=['price', 'volume'], dtype=float)
            asks_df = pd.DataFrame(asks_raw, columns=['price', 'volume'], dtype=float)

            event = MarketEvent(
                symbol=symbol,
                timestamp=datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')),
                best_bid=bids_df['price'].iloc[0],
                best_ask=asks_df['price'].iloc[0],
                bids=bids_df,
                asks=asks_df
            )
            
            await self.queue.put(event)
            logger.debug(f"[KRAKEN_TRADE] MarketEvent pour {symbol} envoyé à la stratégie.")

        except (KeyError, IndexError) as e:
            logger.warning(f"[KRAKEN_TRADE] Erreur de formatage du message de mise à jour: {data}. Erreur: {e}")

