# main_acquirer.py

import asyncio
import yaml
import logging
import logging.handlers
import os
from prometheus_client import start_http_server

from src.monitoring import BUFFER_QUEUE_SIZE, monitor_queue_size
from src.data_module.database_worker import DatabaseWorker
from src.data_module.connectors.binance_ws import BinanceConnector
from src.data_module.connectors.kraken_ws_collection import KrakenCollectionConnector
from src.data_module.connectors.coinbase_ws import CoinbaseConnector

CONNECTORS = {
    #"binance": BinanceConnector,
    "kraken": KrakenCollectionConnector,
    #"coinbase": CoinbaseConnector,
}

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    if logger.hasHandlers():
        logger.handlers.clear()

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    if not os.path.exists('logs'):
        os.makedirs('logs')
    fh = logging.handlers.RotatingFileHandler('logs/data_acquirer.log', maxBytes=10*1024*1024, backupCount=5)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

async def main():
    setup_logging()
    logging.info("Lancement du module d'acquisition de données (Qualité Production)...")

    start_http_server(8000)
    logging.info("Serveur de métriques démarré sur le port 8000.")

    with open('config.yml', 'r') as f:
        config = yaml.safe_load(f)

    data_config = config['data_acquisition']
    api_keys = config.get('api_keys', {})

    buffer_queue = asyncio.Queue(maxsize=10000)
    db_worker = DatabaseWorker(buffer_queue, data_config['influxdb'])

    tasks = [
        asyncio.create_task(db_worker.run()),
        asyncio.create_task(monitor_queue_size(buffer_queue))
    ]

    active_connector_count = 0
    for exchange_name in data_config.get('active_exchanges', []):
        if exchange_name in CONNECTORS:
            symbols = data_config['exchanges'][exchange_name]['symbols']
            connector_class = CONNECTORS[exchange_name]

            logging.info(f"Initialisation du connecteur pour {exchange_name.upper()}...")
            connector = connector_class(symbols, buffer_queue)
            

            tasks.append(asyncio.create_task(connector.connect()))
            active_connector_count += 1
        else:
            logging.warning(f"Connecteur pour '{exchange_name}' non trouvé.")

    if active_connector_count == 0:
        logging.warning("Aucun exchange actif. Arrêt du programme.")
        for task in tasks: 
            task.cancel()
        return

    try:
        await asyncio.gather(*tasks)
    finally:
        # Cette section sera atteinte en cas d'erreur dans une des tâches ou lors de l'arrêt.
        await db_worker.close()
        logging.info("Programme terminé.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé par l'utilisateur.")