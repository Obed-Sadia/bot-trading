# src/backtesting_module/data_loader.py

import random
import pandas as pd
#from common.objects import MarketEvent
from src.common.objects import MarketEvent


class HistoricCSVDataLoader:
    """
    Charge les données d'un fichier CSV et les transforme en MarketEvents.
    """
    def __init__(self, event_queue, csv_filepath, symbol):
        self.event_queue = event_queue
        self.csv_filepath = csv_filepath
        self.symbol = symbol
        self.data_stream = self._stream_csv_data()

    def _stream_csv_data(self):
        """Générateur qui lit le CSV ligne par ligne."""
        try:
            data = pd.read_csv(
                self.csv_filepath, 
                parse_dates=['timestamp'],
                index_col='timestamp'
            )
            # Pour chaque ligne du dataframe, crée un tuple (timestamp, row_data)
            for timestamp, row in data.iterrows():
                yield timestamp, row
        except FileNotFoundError:
            print(f"ERROR: Le fichier {self.csv_filepath} n'a pas été trouvé.")
            return

    # Dans la classe HistoricCSVDataLoader

    def stream_next(self):
        """Place le prochain MarketEvent avec un carnet d'ordres simulé et aléatoire."""
        try:
            timestamp, row = next(self.data_stream)

            best_ask = row['close'] * 1.0001
            best_bid = row['close'] * 0.9999
            
            # --- Simulation améliorée avec de l'aléatoire ---
            # Crée des volumes qui varient à chaque pas de temps
            bid_vol_1 = row['volume'] * random.uniform(0.2, 0.8)
            bid_vol_2 = row['volume'] * random.uniform(0.1, 0.5)
            ask_vol_1 = row['volume'] * random.uniform(0.2, 0.8)
            ask_vol_2 = row['volume'] * random.uniform(0.1, 0.5)

            bids_data = {'price': [best_bid, best_bid * 0.9998], 'volume': [bid_vol_1, bid_vol_2]}
            asks_data = {'price': [best_ask, best_ask * 1.0002], 'volume': [ask_vol_1, ask_vol_2]}
            
            bids_df = pd.DataFrame(bids_data)
            asks_df = pd.DataFrame(asks_data)

            market_event = MarketEvent(
                timestamp=timestamp,
                symbol=self.symbol,
                best_bid=best_bid,
                best_ask=best_ask,
                bids=bids_df,
                asks=asks_df
            )
            self.event_queue.put(market_event)
            return True
        except StopIteration:
            return False
