# src/trading_module/ml_utils/feature_engineering.py

import pandas as pd
import pandas_ta as ta
import logging

logger = logging.getLogger(__name__)

# Définir les constantes pour être cohérent avec l'entraînement
ATR_PERIOD = 14
MOMENTUM_EMA_PERIOD = 120

def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ajoute une suite complète d'indicateurs, synchronisée avec
    ceux requis par les modèles pré-entraînés.
    """
    logger.info("Ajout des indicateurs techniques (features)...")
    
    # S'assurer que l'index est bien un DatetimeIndex pour les calculs
    if not isinstance(df.index, pd.DatetimeIndex):
        df.set_index('timestamp', inplace=True)

    # Stratégie d'indicateurs explicite utilisant pandas_ta
    explicit_strategy = ta.Strategy(
        name="Stratégie de Prédiction Live",
        description="Indicateurs requis par les modèles XGBoost, LSTM et GRU.",
        ta=[
            # Momentum
            {"kind": "rsi", "length": 14},
            {"kind": "macd", "fast": 12, "slow": 26, "signal": 9},
            {"kind": "stoch", "k": 14, "d": 3, "smooth_k": 3},
            
            # Tendance
            {"kind": "adx", "length": 14},
            {"kind": "ema", "length": 20},
            {"kind": "ema", "length": 50},
            {"kind": "ema", "length": MOMENTUM_EMA_PERIOD},

            # Volatilité
            {"kind": "bbands", "length": 20, "std": 2},
            {"kind": "atr", "length": ATR_PERIOD},
            
            # Volume
            {"kind": "obv"},
            
            # Retours (pour LOGRET_1 et PCTRET_1)
            {"kind": "log_return", "length": 1, "col_names": "LOGRET_1"},
            {"kind": "percent_return", "length": 1, "col_names": "PCTRET_1"},
        ]
    )
    df.ta.strategy(explicit_strategy)
    
    # Création des features "intelligentes"
    logger.info("Ajout de features avancées...")

    df['atr_sma'] = df['ATRr_14'].rolling(window=50).mean()
    df['atr_ratio'] = df['ATRr_14'] / df['atr_sma']

    ema_long_term_col = f"EMA_{MOMENTUM_EMA_PERIOD}"
    df.rename(columns={ema_long_term_col: "ema_long_term"}, inplace=True, errors='ignore')
    df['price_vs_ema_long'] = (df['close'] - df['ema_long_term']) / df['ema_long_term']

    df['rsi_change'] = df['RSI_14'].diff()

    # Création des features temporelles
    df['hour'] = df.index.hour
    df['day_of_week'] = df.index.dayofweek
    
    logger.info(f"{len(df.columns)} colonnes après ajout des indicateurs.")
    return df