# src/trading_module/ml_utils/ml_model_loader.py

import xgboost as xgb
import joblib
from tensorflow.keras.models import load_model # type: ignore
import logging

def load_ml_models(paths: dict) -> dict:
    """
    Charge tous les modèles ML, scalers et encodeurs depuis les chemins spécifiés.
    """
    logging.info("Chargement des modèles ML...")
    try:
        models = {
            "xgboost": xgb.XGBClassifier(),
            "gru": load_model(paths['gru']),
            "lstm": load_model(paths['lstm']),
            "xgboost_encoder": joblib.load(paths['xgboost_encoder']),
            "gru_scaler": joblib.load(paths['gru_scaler']),
            "lstm_scaler": joblib.load(paths['lstm_scaler'])
        }
        models["xgboost"].load_model(paths['xgboost'])
        logging.info("✅ Tous les modèles ML ont été chargés avec succès.")
        return models
    except Exception as e:
        logging.error(f"Erreur critique lors du chargement des modèles ML: {e}", exc_info=True)
        raise