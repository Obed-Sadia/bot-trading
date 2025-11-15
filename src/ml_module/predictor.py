import torch
import joblib
import numpy as np
from transformers import pipeline
from .models import PricePredictorLSTM

class Predictor:
    def __init__(self, model_path: str, scaler_path: str, device: str = "cpu"):
        print("Chargement des modèles pour la prédiction...")
        self.device = device
        
        # Charger le scaler
        self.scaler = joblib.load(scaler_path)
        
        # Charger le modèle LSTM
        # Note: les hyperparamètres doivent correspondre à ceux de l'entraînement
        self.lstm_model = PricePredictorLSTM(input_dim=4, hidden_dim=64, n_layers=2, dropout=0.2).to(self.device)
        self.lstm_model.load_state_dict(torch.load(model_path, map_location=device))
        self.lstm_model.eval()
        
        # Charger le modèle de sentiment
        self.sentiment_pipeline = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1 if device=="cpu" else 0)
        print("Modèles prêts.")

    def predict_sentiment(self, texts: list) -> list:
        """Prédit le score de sentiment pour une liste de textes."""
        results = []
        for text in texts:
            result = self.sentiment_pipeline(text)[0]
            score = result['score'] if result['label'] == 'positive' else -result['score']
            results.append(score)
        return results

    def predict_direction(self, feature_sequence: np.ndarray) -> float:
        """
        Prédit la probabilité de hausse pour une séquence de features.
        :param feature_sequence: Un array numpy de shape (sequence_length, num_features).
        """
        # Normaliser les données avec le même scaler que l'entraînement
        scaled_features = self.scaler.transform(feature_sequence)
        
        # Convertir en tenseur et ajouter une dimension de batch
        tensor = torch.from_numpy(scaled_features).float().unsqueeze(0).to(self.device)
        
        with torch.no_grad():
            output = torch.sigmoid(self.lstm_model(tensor).squeeze())
        
        return output.item()