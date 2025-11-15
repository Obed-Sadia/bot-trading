import asyncio
import websockets
import json
import logging
from .base import BaseConnector
from ..schemas import KrakenL2Data, Trade
from datetime import datetime
from src.monitoring import MESSAGES_PROCESSED

logger = logging.getLogger(__name__)

class KrakenCollectionConnector(BaseConnector):
    def __init__(self, symbols: list, queue: asyncio.Queue):
        super().__init__(symbols, None)
        self.queue = queue
        self.exchange_name = "kraken"
    
    async def connect(self):
        url = "wss://ws.kraken.com/v2"
        book_subscription = {
            "method": "subscribe",
            "params": { "channel": "book", "symbol": self.symbols, "depth": 10 }
        }
        trade_subscription = {
            "method": "subscribe",
            "params": { "channel": "trade", "symbol": self.symbols }
        }
        
        logger.info(f"[{self.exchange_name.upper()}] Connexion à {url}...")

        while True:
            try:
                async with websockets.connect(url) as websocket:
                    await websocket.send(json.dumps(book_subscription))
                    await websocket.send(json.dumps(trade_subscription))
                    logger.info(f"[{self.exchange_name.upper()}] Connecté et abonné aux flux.")
                    
                    async for message in websocket:
                        try:
                            data = json.loads(message)
                            channel = data.get("channel")

                            if channel == "book":
                                book_data = data['data'][0]
                                validated_data = KrakenL2Data.model_validate({"symbol": book_data['symbol'], "bids": book_data['bids'], "asks": book_data['asks']})
                                MESSAGES_PROCESSED.labels(exchange=self.exchange_name).inc()
                                await self.queue.put(('kraken_l2', validated_data))
                            
                            elif channel == "trade":
                                for trade_info in data['data']:
                                    
                                    trade_timestamp = datetime.fromisoformat(trade_info['timestamp'].replace('Z', '+00:00'))
                                    
                                    
                                    # On crée un ID de transaction unique 
                                    synthetic_trade_id = f"{trade_info['symbol']}-{trade_info['timestamp']}-{trade_info['price']}"

                                    validated_trade = Trade(
                                        exchange=self.exchange_name,
                                        symbol=trade_info['symbol'],
                                        price=float(trade_info['price']),
                                        quantity=float(trade_info['qty']),
                                        side=trade_info['side'],
                                        trade_time=trade_timestamp,
                                        trade_id=synthetic_trade_id 
                                    )
                                    MESSAGES_PROCESSED.labels(exchange=self.exchange_name).inc()
                                    await self.queue.put(('trade', validated_trade))
                        except Exception as e:
                            logger.error(f"[{self.exchange_name.upper()}] Erreur parsing: {e}")
            except Exception as e:
                logger.error(f"[{self.exchange_name.upper()}] Erreur de connexion: {e}. Reconnexion dans 5s...")
                await asyncio.sleep(5)