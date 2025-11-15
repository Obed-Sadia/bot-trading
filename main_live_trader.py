import asyncio
import yaml
import logging
import os
import shutil
from prometheus_client import start_http_server

# --- Imports des modules ---
from src.data_module.connectors.kraken_ws_trade import KrakenTradeConnector
from src.data_module.connectors.kraken_ws_bougie import KrakenCandleBackfillConnector 

# Note : Ajoutez l'import pour Binance si vous voulez pouvoir switcher
# from src.data_module.connectors.binance_ws import BinanceConnector 
from src.trading_module.portfolio import Portfolio
from src.trading_module.risk_manager import RiskManager
from src.trading_module.live_execution_handler import LiveExecutionHandler
from src.trading_module.strategy_loader import load_strategy
from src.monitoring import monitor_queue_size
from main_acquirer import setup_logging

async def watch_panic_file(portfolio: Portfolio):
    """Vérifie périodiquement l'existence du fichier panic.kill."""
    logging.info("Démarrage de la vérification du fichier panique (toutes les 5 secondes).")
    panic_file_path = '/app/panic.kill'
    while True:
        if os.path.exists(panic_file_path):
            logging.warning("FICHIER PANIQUE DÉTECTÉ ! Activation du mode panique.")
            await portfolio.activate_panic_mode()
            try:
                os.remove(panic_file_path)
                logging.info("Fichier panique supprimé.")
            except OSError as e:
                logging.error(f"Erreur lors de la suppression du fichier panique: {e}")
        await asyncio.sleep(5)

async def event_loop(queue: asyncio.Queue, strategy, risk_manager, executor, portfolio):
    """La boucle d'événements principale qui route les messages."""
    logging.info("Boucle d'événements démarrée. En attente d'événements...")
    while True:
        try:
            event = await queue.get()
            
            if event.type == "MARKET":
                logging.debug(f"EVENT: MARKET data received for {event.symbol}")
                await strategy.on_market_data(event)
                mid_price = (event.best_bid + event.best_ask) / 2
                portfolio.update_portfolio_value({event.symbol: mid_price})
                await risk_manager.check_exits({event.symbol: mid_price})

            elif event.type == "SIGNAL":
                logging.info(f"EVENT: SIGNAL received: {event.direction} on {event.symbol}")
                await risk_manager.on_signal(event)

            elif event.type == "ORDER":
                logging.info(f"EVENT: ORDER generated: {event.direction} {event.quantity} of {event.symbol}")
                await executor.on_order(event)

            elif event.type == "FILL":
                logging.info(f"EVENT: FILL confirmed for order on {event.symbol}")
                await portfolio.update_on_fill(event)
            
            else:
                logging.warning(f"EVENT: Unknown event type received: {event.type}")

        except Exception as e:
            logging.error(f"Erreur majeure dans la boucle d'événements: {e}", exc_info=True)

async def main():
    setup_logging()
    logging.info("Lancement du BOT DE TRADING LIVE (Architecture Hybride)...")
    start_http_server(8002)
    
    with open('config.yml', 'r') as f:
        config = yaml.safe_load(f)

    # --- Lecture de la configuration pour l'architecture hybride ---
    live_config = config['live_trading']
    acq_config = config['data_acquisition']

    # Source de données (ex: Kraken)
    data_source_id = live_config['data_source_id']
    data_source_symbols = acq_config['exchanges'][data_source_id]['symbols']
    
    # Plateforme d'exécution (ex: Binance)
    execution_id = live_config['execution_exchange_id']

    strategy_name = config['active_strategy']
    strategy_params = config['strategies'][strategy_name]
    
    event_queue = asyncio.Queue()
    portfolio = Portfolio(event_queue, initial_capital=10000.0)
    
    
    # --- Instanciation des composants ---
    logging.info(f"Source de données configurée sur : {data_source_id.upper()} (Symboles: {data_source_symbols})")
    
    # Ici, vous pourriez ajouter une logique pour choisir le connecteur dynamiquement
    if data_source_id == 'kraken':
        data_connector = KrakenTradeConnector(symbols=data_source_symbols, queue=event_queue)
    # elif data_source_id == 'binance':
    #     data_connector = BinanceConnector(symbols=data_source_symbols, queue=event_queue)
    else:
        raise ValueError(f"Data source '{data_source_id}' non supportée.")
    
    # 1. Créer le connecteur de remplissage dédié
    backfill_connector = KrakenCandleBackfillConnector()


    logging.info(f"Plateforme d'exécution configurée sur : {execution_id.upper()}")
    execution_keys = live_config['api_keys'][execution_id]
    live_executor = await LiveExecutionHandler.create(
        event_bus=event_queue, 
        portfolio=portfolio, 
        exchange_id=execution_id,
        api_key=execution_keys['apiKey'], 
        api_secret=execution_keys['secret'], 
        is_testnet=live_config.get('is_testnet', True)
    )
    
    risk_manager = RiskManager(event_queue, portfolio)
    strategy = load_strategy(strategy_name, event_queue, portfolio, strategy_params, backfill_connector=backfill_connector)
    
    tasks = [
        data_connector.connect(),
        event_loop(event_queue, strategy, risk_manager, live_executor, portfolio),
        monitor_queue_size(event_queue),
        watch_panic_file(portfolio)
    ]
    
    logging.info(f"Bot démarré. Stratégie: '{strategy_name}'. Données: {data_source_id.upper()}. Exécution: {execution_id.upper()}.")
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt du bot.")