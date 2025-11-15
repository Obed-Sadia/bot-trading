# src/monitoring.py

import asyncio
from prometheus_client import Counter, Gauge

# --- Définitions des Métriques ---

MESSAGES_PROCESSED = Counter(
    'data_acquirer_messages_processed_total',
    'Total number of messages processed by the data acquirer',
    ['exchange']
)

DB_WRITES_SUCCESS = Counter(
    'data_acquirer_db_writes_success_total',
    'Total number of successful writes to the database'
)

DB_WRITES_FAILURE = Counter(
    'data_acquirer_db_writes_failure_total',
    'Total number of failed writes to the database'
)

BUFFER_QUEUE_SIZE = Gauge(
    'data_acquirer_buffer_queue_size',
    'Current number of items in the buffer queue'
)

# --- Fonctions de Monitoring ---

async def monitor_queue_size(queue: asyncio.Queue):
    """
    Tâche asynchrone qui met à jour la métrique Prometheus 
    pour la taille de la file d'attente toutes les 5 secondes.
    """
    while True:
        BUFFER_QUEUE_SIZE.set(queue.qsize())
        await asyncio.sleep(5)
        
PORTFOLIO_VALUE = Gauge(
    'trading_bot_portfolio_value_usd',
    'Valeur totale actuelle du portefeuille de trading'
)

OPEN_POSITIONS = Gauge(
    'trading_bot_open_positions_total',
    'Nombre actuel de positions ouvertes'
)

TRADES_EXECUTED = Counter(
    'trading_bot_trades_executed_total',
    'Nombre total de trades exécutés par le bot',
    ['exchange', 'symbol', 'side']
)