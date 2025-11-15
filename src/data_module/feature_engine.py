import pandas as pd
import yaml
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

class FeatureEngine:
    def __init__(self, config: dict):
        self.config = config['feature_engine']
        influx_config = config['data_acquisition']['influxdb']
        self.client = InfluxDBClient(
            url=influx_config['url'], token=influx_config['token'], org=influx_config['org']
        )
        self.query_api = self.client.query_api()
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def _read_data(self, measurement: str, symbol: str, time_range: str = "-1h") -> pd.DataFrame:
        """Récupère des données d'une 'measurement' InfluxDB."""
        print(f"Lecture des données depuis '{measurement}' pour {symbol}...")
        
        flux_query = f'''
        from(bucket: "{self.config['source_bucket']}")
            |> range(start: {time_range})
            |> filter(fn: (r) => r._measurement == "{measurement}")
            |> filter(fn: (r) => r.symbol == "{symbol}")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
        '''
        df = self.query_api.query_data_frame(query=flux_query, org=self.client.org)
        if df is None or df.empty: return pd.DataFrame()
        
        # S'assurer que l'index est bien un datetime et fuseau-horaire-naïf pour la fusion
        df['_time'] = pd.to_datetime(df['_time']).dt.tz_localize(None)
        df = df.set_index('_time')
        return df

    def _calculate_book_features(self, book_df: pd.DataFrame) -> pd.DataFrame:
        """Calcule les features basées sur le carnet d'ordres."""
        print("Calcul des features du carnet d'ordres...")
        features = []
        for timestamp, group in book_df.groupby(level=0):
            bids = group[group['side'] == 'bid'].sort_values('price', ascending=False)
            asks = group[group['side'] == 'ask'].sort_values('price', ascending=True)
            if bids.empty or asks.empty: continue

            best_bid_price = bids.iloc[0]['price']
            best_ask_price = asks.iloc[0]['price']
            best_bid_qty = bids.iloc[0]['quantity']
            best_ask_qty = asks.iloc[0]['quantity']

            wap = (best_bid_price * best_ask_qty + best_ask_price * best_bid_qty) / (best_bid_qty + best_ask_qty)
            spread = best_ask_price - best_bid_price
            obi = bids.head(5)['quantity'].sum() / asks.head(5)['quantity'].sum() if asks.head(5)['quantity'].sum() > 0 else 1.0

            features.append({'timestamp': timestamp, 'wap': wap, 'spread': spread, 'obi': obi})
        
        return pd.DataFrame(features).set_index('timestamp')

    def _calculate_trade_features(self, trades_df: pd.DataFrame) -> pd.DataFrame:
        """Calcule les features basées sur les transactions."""
        if trades_df.empty: return pd.DataFrame()
        print("Calcul des features des transactions...")
        
        trades_df['volume'] = trades_df['price'] * trades_df['quantity']
        # Calculer le VWAP (Volume-Weighted Average Price) sur une fenêtre de 1 minute
        vwap = trades_df.resample('1min').apply(lambda x: (x['price'] * x['quantity']).sum() / x['quantity'].sum() if x['quantity'].sum() > 0 else None).rename('vwap')
        
        return vwap.ffill() # Propager la dernière valeur connue

    def run(self, symbol: str):
        """Orchestre le processus complet."""
        book_measurement = self.config['source_measurements']['order_book']
        trades_measurement = self.config['source_measurements']['trades']

        # 1. Lire les deux sources de données
        book_df_raw = self._read_data(book_measurement, symbol)
        trades_df = self._read_data(trades_measurement, symbol)
        if book_df_raw.empty:
            print("Aucune donnée de carnet d'ordres à traiter.")
            return

        # 2. Calculer les features pour chaque source
        book_features_df = self._calculate_book_features(book_df_raw)
        trade_features_df = self._calculate_trade_features(trades_df)

        # 3. Aligner et fusionner les features
        print("Fusion des jeux de features...")
        
        if not trade_features_df.empty:
            final_features_df = pd.merge_asof(
                left=book_features_df.sort_index(),
                right=trade_features_df.sort_index(),
                left_index=True,
                right_index=True,
                direction='backward' # Pour chaque snapshot de carnet, prend la dernière valeur de VWAP connue
            )
        else:
            final_features_df = book_features_df
            final_features_df['vwap'] = float('nan')
        
        final_features_df.dropna(inplace=True)

        # 4. Écrire les features unifiées dans InfluxDB
        points_to_write = []
        for timestamp, row in final_features_df.iterrows():
            point = Point(self.config['destination_measurement']).tag("symbol", symbol).time(timestamp)
            for feature_name, value in row.items():
                point.field(feature_name, value)
            points_to_write.append(point)
        
        if not points_to_write:
            print("Aucune feature finale à écrire.")
            return
            
        print(f"Écriture de {len(points_to_write)} points de features unifiées...")
        self.write_api.write(bucket=self.config['destination_bucket'], record=points_to_write)
        print("Processus terminé.")

    def close(self):
        self.client.close()

if __name__ == '__main__':
    try:
        with open('config.yml', 'r') as f: config = yaml.safe_load(f)
        engine = FeatureEngine(config)
        engine.run(symbol="BTC/USDT")
        engine.close()
    except Exception as e:
        print(f"Une erreur est survenue: {e}")