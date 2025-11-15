import pandas as pd
import yaml
from datetime import datetime
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

class SentimentAnalyzer:
    """
    Lit le texte brut des nouvelles depuis InfluxDB, calcule un score de sentiment agrégé,
    et le sauvegarde dans une nouvelle 'measurement' (table).
    """
    def __init__(self, config: dict):
        self.config = config.get('feature_engine', {}) # On réutilise la config du feature_engine
        influx_config = config.get('data_acquisition', {}).get('influxdb', {})
        
        if not self.config or not influx_config:
            raise ValueError("Configuration pour feature_engine ou influxdb manquante dans config.yml")
            
        # Initialise le client InfluxDB en mode synchrone
        self.client = InfluxDBClient(
            url=influx_config['url'],
            token=influx_config['token'],
            org=influx_config['org']
        )
        self.query_api = self.client.query_api()
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        
        # Initialise le modèle d'analyse de sentiment VADER
        self.analyzer = SentimentIntensityAnalyzer()

    def _read_raw_text_data(self, time_range: str = "-1h") -> pd.DataFrame:
        """Récupère les données textuelles brutes depuis InfluxDB."""
        print(f"Lecture des données de sentiment brutes sur la dernière heure...")
        
        flux_query = f'''
        from(bucket: "{self.config['source_bucket']}")
            |> range(start: {time_range})
            |> filter(fn: (r) => r._measurement == "raw_sentiment_data")
            |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
            |> keep(columns: ["_time", "symbol", "source", "text"])
        '''
        df = self.query_api.query_data_frame(query=flux_query, org=self.client.org)
        if df is None or df.empty:
            return pd.DataFrame()
            
        print(f"{len(df)} titres de nouvelles lus.")
        return df

    def run(self):
        """Orchestre le processus d'analyse."""
        raw_df = self._read_raw_text_data()
        if raw_df.empty:
            print("Aucune nouvelle donnée de sentiment à analyser.")
            return

        print("Analyse du sentiment en cours...")
        # Appliquer le modèle VADER pour obtenir un score 'compound' (-1 à +1)
        # La colonne 'text' doit exister dans les données lues
        if 'text' not in raw_df.columns:
             print("Erreur: La colonne 'text' est introuvable dans les données brutes.")
             return

        raw_df['sentiment_score'] = raw_df['text'].apply(
            lambda text: self.analyzer.polarity_scores(str(text))['compound']
        )
        
        # Agréger les scores par symbole (ex: BTC, ETH) pour obtenir un indicateur global
        agg_sentiment = raw_df.groupby('symbol')['sentiment_score'].mean().reset_index()
        
        print("Sauvegarde des scores de sentiment agrégés...")
        points = []
        timestamp = datetime.utcnow()
        for _, row in agg_sentiment.iterrows():
            point = Point("market_regime") \
                .tag("symbol", row['symbol']) \
                .field("sentiment_score_hourly", row['sentiment_score']) \
                .time(timestamp)
            points.append(point)
        
        if points:
            self.write_api.write(bucket=self.config['destination_bucket'], record=points)
            print(f"{len(points)} scores de 'régime de marché' enregistrés dans InfluxDB.")
        
    def close(self):
        """Ferme la connexion à InfluxDB."""
        self.client.close()

if __name__ == '__main__':
    try:
        with open('config.yml', 'r') as f:
            config = yaml.safe_load(f)
        
        analyzer = SentimentAnalyzer(config)
        analyzer.run()
        analyzer.close()
    except FileNotFoundError:
        print("ERREUR: Le fichier 'config.yml' est introuvable.")
    except Exception as e:
        print(f"Une erreur est survenue: {e}")