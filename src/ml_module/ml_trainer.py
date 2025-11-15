import pandas as pd
import numpy as np
import yaml
import joblib
import os
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from influxdb_client import InfluxDBClient
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler
from sklearn.metrics import classification_report, accuracy_score
from transformers import pipeline
from tqdm import tqdm
from .models import PricePredictorLSTM

class MLTrainer:
    def __init__(self, config: dict):
        self.config = config
        influx_config = config['data_acquisition']['influxdb']
        self.client = InfluxDBClient(url=influx_config['url'], token=influx_config['token'], org=influx_config['org'])
        self.query_api = self.client.query_api()
        # Initialise le pipeline de sentiment FinBERT
        print("Chargement du modèle de sentiment FinBERT...")
        self.sentiment_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert")
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Utilisation du device : {self.device}")

    def _get_data_from_influx(self, measurement: str, time_range: str = "-30d") -> pd.DataFrame:
        print(f"Lecture des données depuis '{measurement}'...")
        bucket = self.config['data_acquisition']['influxdb']['bucket']
        query = f'''from(bucket: "{bucket}") |> range(start: {time_range}) |> filter(fn: (r) => r._measurement == "{measurement}") |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")'''
        df = self.query_api.query_data_frame(query=query)
        if df is None or df.empty: return pd.DataFrame()
        df = df.drop(columns=['result', 'table'], errors='ignore').set_index('_time').sort_index()
        df.index = pd.to_datetime(df.index).tz_convert('UTC')
        return df

    def _analyze_sentiment(self, sentiment_df: pd.DataFrame) -> pd.DataFrame:
        print("Analyse du sentiment avec FinBERT...")
        if sentiment_df.empty or 'text' not in sentiment_df.columns: return pd.DataFrame()
        
        scores = []
        for text in tqdm(sentiment_df['text'], desc="Sentiment Analysis"):
            result = self.sentiment_pipeline(text)[0]
            score = result['score'] if result['label'] == 'positive' else -result['score']
            scores.append(score)
        
        sentiment_df['sentiment_score'] = scores
        # Agréger par heure
        return sentiment_df.resample('1H', on='timestamp')['sentiment_score'].mean().to_frame()

    def _create_sequences(self, data, seq_length):
        xs, ys = [], []
        for i in range(len(data) - seq_length):
            x = data[i:(i + seq_length), :-1] # Features
            y = data[i + seq_length, -1]    # Label
            xs.append(x)
            ys.append(y)
        return np.array(xs), np.array(ys)

    def train(self, symbol="BTC/USD"):
        # 1. Charger et préparer les données
        market_df = self._get_data_from_influx(self.config['feature_engine']['destination_measurement'], symbol=symbol)
        sentiment_df_raw = self._get_data_from_influx("raw_sentiment_data") # Pas de symbole spécifique ici
        
        # 2. Analyser le sentiment et fusionner
        sentiment_df = self._analyze_sentiment(sentiment_df_raw.rename(columns={'_start': 'timestamp'}))
        
        if not market_df.empty and not sentiment_df.empty:
            df = pd.merge_asof(market_df.sort_index(), sentiment_df.sort_index(), left_index=True, right_index=True, direction='backward', tolerance=pd.Timedelta('12h')).fillna(0)
        else:
            df = market_df
            df['sentiment_score'] = 0

        # 3. Créer les labels
        df['label'] = (df['wap'].shift(-6) > df['wap']).astype(int)
        df = df.dropna()

        # 4. Normaliser et créer les séquences
        features_to_scale = ['wap', 'spread', 'obi', 'sentiment_score']
        scaler = MinMaxScaler()
        df[features_to_scale] = scaler.fit_transform(df[features_to_scale])
        
        data_for_sequences = df[features_to_scale + ['label']].values
        X_seq, y_seq = self._create_sequences(data_for_sequences, seq_length=24) # Séquences de 24h

        # 5. Préparer pour PyTorch
        X_train, X_test, y_train, y_test = train_test_split(X_seq, y_seq, test_size=0.2, shuffle=False)
        train_data = TensorDataset(torch.from_numpy(X_train).float(), torch.from_numpy(y_train).float())
        test_data = TensorDataset(torch.from_numpy(X_test).float(), torch.from_numpy(y_test).float())
        train_loader = DataLoader(train_data, shuffle=False, batch_size=64)

        # 6. Entraîner le modèle LSTM
        model = PricePredictorLSTM(input_dim=len(features_to_scale), hidden_dim=64, n_layers=2, dropout=0.2).to(self.device)
        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

        print("Début de l'entraînement du LSTM...")
        for epoch in range(10): # 10 epochs pour l'exemple
            model.train()
            for inputs, labels in tqdm(train_loader, desc=f"Epoch {epoch+1}/10"):
                inputs, labels = inputs.to(self.device), labels.to(self.device)
                optimizer.zero_grad()
                output = model(inputs)
                loss = criterion(output.squeeze(), labels)
                loss.backward()
                optimizer.step()
            print(f"Epoch {epoch+1}, Loss: {loss.item()}")

        # 7. Évaluation et sauvegarde
        model.eval()
        with torch.no_grad():
            test_inputs = torch.from_numpy(X_test).float().to(self.device)
            test_labels = torch.from_numpy(y_test)
            outputs = torch.sigmoid(model(test_inputs).squeeze())
            preds = (outputs > 0.5).int().cpu()
            print(classification_report(test_labels, preds))

        model_filename = f"models/{symbol.replace('/', '_')}_lstm_model.pth"
        torch.save(model.state_dict(), model_filename)
        joblib.dump(scaler, f"models/{symbol.replace('/', '_')}_scaler.joblib")
        print(f"Modèle et scaler sauvegardés.")

if __name__ == '__main__':
    if not os.path.exists('models'): os.makedirs('models')
    with open('config.yml', 'r') as f: config = yaml.safe_load(f)
    trainer = MLTrainer(config)
    trainer.train(symbol="BTC/USD")