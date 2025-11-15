import asyncio
import logging
from datetime import datetime
from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
from .schemas import BinanceL2Data, KrakenL2Data, CoinbaseL2Snapshot, CoinbaseL2Update, Trade

logger = logging.getLogger(__name__)

class DatabaseWorker:
    def __init__(self, queue: asyncio.Queue, influx_config: dict):
        self.queue = queue
        self.bucket = influx_config['bucket']
        self.client = InfluxDBClientAsync(
            url=influx_config['url'], token=influx_config['token'], org=influx_config['org']
        )
        self.write_api = self.client.write_api()
        self.coinbase_books = {}

    async def run(self):
        logger.info("Le worker de base de données est démarré.")
        coinbase_snapshot_task = asyncio.create_task(self._send_coinbase_snapshots())
        while True:
            try:
                data_type, data_obj = await self.queue.get()
                points = []
                source_exchange = "unknown"

                if data_type == 'binance_l2':
                    source_exchange = "binance"
                    points = self._format_l2_points(source_exchange, data_obj.symbol, data_obj.bids, data_obj.asks)
                elif data_type == 'kraken_l2':
                    source_exchange = "kraken"
                    bids_list = [[item.price, item.qty] for item in data_obj.bids]
                    asks_list = [[item.price, item.qty] for item in data_obj.asks]
                    points = self._format_l2_points(source_exchange, data_obj.symbol, bids_list, asks_list)
                elif data_type in ['coinbase_l2_snapshot', 'coinbase_l2_update']:
                    self._update_coinbase_book(data_obj)
                elif data_type == 'trade':
                    source_exchange = data_obj.exchange
                    points = self._format_trade_points(data_obj)
                
                # On passe la source directement à la méthode d'écriture
                await self._write_points(points, source_exchange)
            except Exception as e:
                logger.error(f"Erreur dans la boucle du worker: {e}", exc_info=True)
            finally:
                self.queue.task_done()

    async def _write_points(self, points: list, source_exchange: str):
        """Tente d'écrire des points dans InfluxDB avec une logique de retry."""
        if not points: return
        try:
            await self.write_api.write(bucket=self.bucket, record=points)
            logger.info(f"DB Worker: {len(points)} points écrits avec succès pour {source_exchange.upper()}.")
        except Exception as e:
            logger.error(f"DB Worker: Erreur d'écriture dans InfluxDB: {e}. Attente de 10s...")
            await asyncio.sleep(10)

    def _format_trade_points(self, trade: Trade) -> list:
        point = Point("market_trades").tag("exchange", trade.exchange).tag("symbol", trade.symbol).tag("side", trade.side).field("price", trade.price).field("quantity", trade.quantity).field("trade_id", trade.trade_id).time(trade.trade_time)
        return [point]
    
    def _update_coinbase_book(self, data):
        symbol = data.product_id
        if isinstance(data, CoinbaseL2Snapshot):
            self.coinbase_books[symbol] = {'bids': {float(p): float(s) for p, s in data.bids}, 'asks': {float(p): float(s) for p, s in data.asks}}
        elif isinstance(data, CoinbaseL2Update):
            if symbol not in self.coinbase_books: return
            for side, price_str, size_str in data.changes:
                book_side = 'bids' if side == 'buy' else 'asks'
                price, size = float(price_str), float(size_str)
                if size == 0.0:
                    self.coinbase_books[symbol][book_side].pop(price, None)
                else:
                    self.coinbase_books[symbol][book_side][price] = size
    
    async def _send_coinbase_snapshots(self):
        """Tâche périodique pour envoyer des snapshots du carnet d'ordres Coinbase."""
        while True:
            await asyncio.sleep(1)
            points_to_write = []
            source_exchange = "coinbase"
            for symbol, book in self.coinbase_books.items():
                if book.get('bids') and book.get('asks'):
                    points_to_write.extend(self._format_l2_points(source_exchange, symbol, book['bids'], book['asks']))
            await self._write_points(points_to_write, source_exchange)

    def _format_l2_points(self, exchange, symbol, bids, asks):
        timestamp = datetime.utcnow()
        points = []
        bids_items = bids if isinstance(bids, list) else sorted(bids.items(), key=lambda x: x[0], reverse=True)
        asks_items = asks if isinstance(asks, list) else sorted(asks.items(), key=lambda x: x[0])
        for level, (price, qty) in enumerate(bids_items[:20]):
            points.append(Point("order_book_l2").tag("exchange", exchange).tag("symbol", symbol).tag("side", "bid").tag("level", level).field("price", float(price)).field("quantity", float(qty)).time(timestamp))
        for level, (price, qty) in enumerate(asks_items[:20]):
            points.append(Point("order_book_l2").tag("exchange", exchange).tag("symbol", symbol).tag("side", "ask").tag("level", level).field("price", float(price)).field("quantity", float(qty)).time(timestamp))
        return points

    async def close(self):
        await self.client.close()
        logger.info("DB Worker: Connexion InfluxDB fermée.")