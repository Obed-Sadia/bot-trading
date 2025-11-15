import asyncio
import websockets
import json
import logging
from .base import BaseConnector
from ..schemas import BinanceL2Data, Trade
from datetime import datetime
from src.monitoring import MESSAGES_PROCESSED

logger = logging.getLogger(__name__)

class BinanceConnector(BaseConnector):
    def __init__(self, symbols: list, queue: asyncio.Queue):
        super().__init__(symbols, None)
        self.queue = queue
        self.exchange_name = "binance"
    
    async def connect(self):
        stream_symbols = [s.lower().replace('/', '') for s in self.symbols]
        l2_streams = [f"{s}@depth20@1s" for s in stream_symbols]
        trade_streams = [f"{s}@trade" for s in stream_symbols]
        url = f"wss://stream.binance.com:9443/ws/{'/'.join(l2_streams + trade_streams)}"
        
        logger.info(f"[{self.exchange_name.upper()}] Connexion à {url}...")
        
        while True:
            try:
                async with websockets.connect(url) as websocket:
                    logger.info(f"[{self.exchange_name.upper()}] Connecté avec succès.")
                    async for message in websocket:
                        try:
                            payload = json.loads(message)
                            if 'stream' in payload and 'data' in payload:
                                stream_type = payload['stream']
                                data = payload['data']

                                if "@depth" in stream_type:
                                    data['symbol'] = data['s']
                                    validated_data = BinanceL2Data.model_validate(data)
                                    MESSAGES_PROCESSED.labels(exchange=self.exchange_name).inc()
                                    await self.queue.put(('binance_l2', validated_data))
                                
                                elif "@trade" in stream_type:
                                    validated_trade = Trade(
                                        exchange=self.exchange_name, symbol=data['s'],
                                        price=float(data['p']), quantity=float(data['q']),
                                        side='sell' if data['m'] else 'buy',
                                        trade_time=datetime.fromtimestamp(data['T'] / 1000),
                                        trade_id=str(data['t'])
                                    )
                                    MESSAGES_PROCESSED.labels(exchange=self.exchange_name).inc()
                                    await self.queue.put(('trade', validated_trade))
                        except Exception as e:
                            logger.error(f"[{self.exchange_name.upper()}] Erreur parsing: {e} | Message: {message[:300]}")
            except Exception as e:
                logger.error(f"[{self.exchange_name.upper()}] Erreur de connexion: {e}. Reconnexion...")
                await asyncio.sleep(5)