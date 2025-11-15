from datetime import datetime
from influxdb_client import Point, InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
from .schemas import RawSentimentPost
from typing import List

class Recorder:
    """
    Gère la connexion et l'écriture de données dans InfluxDB en utilisant
    le client SYNCHRONE pour une meilleure stabilité.
    """
    def __init__(self, influx_config: dict):
        self.bucket = influx_config['bucket']
        self.client = InfluxDBClient(
            url=influx_config['url'],
            token=influx_config['token'],
            org=influx_config['org']
        )
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)

    def save_sentiment_posts(self, posts: List[RawSentimentPost]):
        """Formate et écrit une liste de posts de sentiment (méthode synchrone)."""
        if not posts:
            return
            
        timestamp = datetime.utcnow()
        points = []
        for post in posts:
            points.append(Point("raw_sentiment_data")
                .tag("source", post.source)
                .tag("symbol", post.symbol)
                .field("text", post.text)
                .time(timestamp))
            
        self.write_api.write(bucket=self.bucket, record=points)

    def close(self):
        """Ferme proprement le client InfluxDB."""
        self.client.close()