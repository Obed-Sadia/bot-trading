# src/trading_module/strategies/multi_model_strategy.py

import asyncio
import pandas as pd
import numpy as np
import logging
import json
import redis
from collections import deque
from datetime import datetime, timezone, timedelta

from .base import BaseStrategy
from src.common.objects import SignalEvent
from src.trading_module.ml_utils.ml_model_loader import load_ml_models
from src.trading_module.ml_utils.feature_engineering import add_technical_indicators


# Configuration du logger pour ce module spécifique
logger = logging.getLogger(__name__)

class MultiModelStrategy(BaseStrategy):
    """
    Stratégie qui combine 3 modèles ML pour prendre des décisions et qui reconstruit
    les bougies OHLCV à partir des données du carnet d'ordres en temps réel.
    """
    def __init__(self, event_bus, portfolio, params: dict, backfill_connector=None):
        super().__init__(event_bus, portfolio, params)
        
        self.models = load_ml_models(self.params['model_paths'])
        self.history_length = self.params.get('history_length', 250)
        self.rsi_params = self.params['rsi_trigger']
        self.primary_symbol = "BTC/USD"
        self.backfill_connector = backfill_connector

        # --- NOUVEAUTÉ : Paramètres pour le système de score ---
        self.scoring_params = self.params.get('scoring', {
            "buy_threshold": 5,
            "sell_threshold": 5,
            "weights": {
                "regime_bull": 3,
                "regime_neutral": 0,
                "regime_bear": -5,
                "momentum_bull": 3,
                "momentum_bear": -3,
                "volatility_low": 1,
                "volatility_high": -5,
                "rsi_oversold": 1,
                "rsi_overbought": 1
            }
        })
        
        self.is_ready = False
        self.market_data_history = deque(maxlen=self.history_length)
        self.current_candle = {}
        self.last_analysis_time = {}

        # --- BLOC 1 : INITIALISATION DE LA CONNEXION REDIS (CRUCIAL) ---
        self.redis_client = None
        try:
            self.redis_client = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
            self.redis_client.ping()
            logger.info("Connexion à Redis réussie depuis la stratégie.")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Échec de la connexion à Redis depuis la stratégie: {e}")
        # --- FIN BLOC 1 ---

        if self.backfill_connector:
            asyncio.create_task(self.backfill_from_connector())
        else:
            logger.warning("Aucun connecteur de backfill fourni.")
            self.is_ready = True

    async def backfill_from_connector(self):
        logger.info("Lancement du remplissage de l'historique via le backfill connector...")
        initial_candles = await self.backfill_connector.fetch_initial_candles(
            symbol=self.primary_symbol, timeframe='1h', limit=self.history_length
        )
        if initial_candles:
            self.market_data_history.extend(initial_candles)
            logger.info(f"Historique rempli avec {len(self.market_data_history)} bougies.")
        else:
            logger.error("Le remplissage de l'historique a échoué.")
        self.is_ready = True
        logger.info("✅ Stratégie prête à recevoir les données en direct.")

    def _update_candle(self, symbol: str, price: float, timestamp: datetime):
        """
        Met à jour la bougie en cours ou finalise la précédente et en crée une nouvelle.
        Inclut une vérification pour empêcher l'ajout de bougies en double.
        """
        current_hour = timestamp.replace(minute=0, second=0, microsecond=0)

        # Si c'est une nouvelle heure, on doit finaliser la bougie précédente
        if symbol not in self.current_candle or self.current_candle[symbol]['start_time'] != current_hour:
            
            # S'il y avait une bougie en cours de construction...
            if symbol in self.current_candle:
                candle = self.current_candle[symbol]
                completed_candle = [
                    candle['start_time'], 
                    candle['o'], 
                    candle['h'], 
                    candle['l'], 
                    candle['c'], 
                    candle.get('v', 0.0)
                ]
                
                # --- CORRECTION APPLIQUÉE ICI ---
                # On vérifie si une bougie avec ce timestamp n'existe pas DÉJÀ dans l'historique
                # pour éviter les doublons créés par le backfill initial.
                if not any(c[0] == completed_candle[0] for c in self.market_data_history):
                    self.market_data_history.append(completed_candle)
                    logger.info(
                        f"🕯️ Bougie complétée et ajoutée pour {symbol} @ {completed_candle[0].strftime('%Y-%m-%d %H:%M')}: "
                        f"O={completed_candle[1]:.2f}, H={completed_candle[2]:.2f}, L={completed_candle[3]:.2f}, C={completed_candle[4]:.2f}"
                    )
                else:
                    # Ce log est utile pour confirmer que la protection anti-doublon fonctionne
                    logger.warning(
                        f"Doublon de bougie détecté et ignoré pour le timestamp {completed_candle[0].strftime('%Y-%m-%d %H:%M')}"
                    )

            # On commence la nouvelle bougie pour l'heure actuelle
            self.current_candle[symbol] = {
                'start_time': current_hour, 
                'o': price, 'h': price, 
                'l': price, 'c': price, 
                'v': 0
            }
        
        # Si on est toujours dans la même heure, on met simplement à jour la bougie en cours
        else:
            candle = self.current_candle[symbol]
            candle['h'] = max(candle['h'], price)
            candle['l'] = min(candle['l'], price)
            candle['c'] = price

    def _prepare_features(self) -> pd.DataFrame:
        if len(self.market_data_history) < self.history_length: return None
        df = pd.DataFrame(list(self.market_data_history), columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df.set_index('timestamp', inplace=True)
        try:
            df_for_indicators = df.copy()
            df_for_indicators.reset_index(inplace=True)
            df_featured = add_technical_indicators(df_for_indicators)
            if 'timestamp' in df_featured.columns:
                df_featured.set_index('timestamp', inplace=True)
            df_featured.dropna(inplace=True)
            return df_featured
        except Exception as e:
            logger.error(f"Erreur dans add_technical_indicators: {e}", exc_info=True)
            return None
        
    # --- NOUVELLE FONCTION : Logique de score séparée ---
    def _calculate_scores(self, regime, momentum, volatility, rsi):
        """Calcule les scores d'achat et de vente basés sur les prédictions des modèles."""
        weights = self.scoring_params['weights']
        buy_score = 0
        sell_score = 0

        # Score du Régime (XGBoost)
        if regime in ['Bull_Market_2021', 'Recent_Data_2024']:
            buy_score += weights['regime_bull']
        elif regime == 'Bear_Market_2022':
            sell_score += weights['regime_bull'] # Un marché baissier est bon pour la vente
        else: # Marché neutre
            buy_score += weights['regime_neutral']
            sell_score += weights['regime_neutral']

        # Score du Momentum (LSTM)
        if momentum == 'Momentum Haussier':
            buy_score += weights['momentum_bull']
        else:
            sell_score += weights['momentum_bull'] # Un momentum baissier est bon pour la vente

        # Score de Volatilité (GRU) - Le même pour l'achat et la vente
        if volatility == 'Basse Volatilité':
            buy_score += weights['volatility_low']
            sell_score += weights['volatility_low']
        else:
            buy_score += weights['volatility_high']
            sell_score += weights['volatility_high']
            
        # Score du Déclencheur (RSI)
        if rsi < self.rsi_params['buy_threshold']:
            buy_score += weights['rsi_oversold']
        if rsi > self.rsi_params['sell_threshold']:
            sell_score += weights['rsi_overbought']
            
        return buy_score, sell_score
        
    async def on_market_data(self, event):
        
        if not self.is_ready:
            logger.debug("Stratégie en attente de la préparation de l'historique...")
            return

        if event.symbol != self.primary_symbol:
            return
        
        mid_price = (event.best_bid + event.best_ask) / 2
        self._update_candle(event.symbol, mid_price, event.timestamp)

        current_hour = event.timestamp.replace(minute=0, second=0, microsecond=0)
        if self.last_analysis_time.get(event.symbol) == current_hour:
            return
            
        features_df = self._prepare_features()
        if features_df is None or features_df.empty:
            return
            
        self.last_analysis_time[event.symbol] = current_hour
        latest_features = features_df.iloc[-1:]

        logger.info(f"--- Lancement de l'entonnoir de décision pour {event.symbol} ---")

        # Initialiser l'état et la fonction de publication
        analysis_state = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "symbol": event.symbol,
            "regime": {"value": "En cours...", "pass": False},
            "momentum": {"value": "En attente...", "pass": False},
            "volatility": {"value": "En attente...", "pass": False},
            "rsi": {"value": "En attente...", "pass": False},
            "final_decision": "ANALYSE EN COURS"
        }
        
        def publish_state():
            if self.redis_client:
                self.redis_client.set("bot:latest_analysis", json.dumps(analysis_state))

        publish_state()

        # Étape 1: XGBoost
        xgb_feature_names = self.models['xgboost'].get_booster().feature_names
        xgb_features = latest_features[xgb_feature_names]
        regime_encoded = await asyncio.to_thread(self.models['xgboost'].predict, xgb_features)
        regime = self.models['xgboost_encoder'].inverse_transform([regime_encoded[0]])[0]
        # Note: 'regime_pass' est spécifique à l'achat, on le calcule plus tard
        analysis_state["regime"] = {"value": regime, "pass": False} # Pass sera mis à jour plus tard
        publish_state()
        logger.info(f"-> XGBoost: {regime}")
            
        # Étape 2: LSTM
        analysis_state["momentum"]["value"] = "En cours..."
        publish_state()
        lstm_look_back = 120
        lstm_features_cols = self.models['lstm_scaler'].feature_names_in_
        
        logger.info(f"DataFrame shape for models: {features_df.shape}") # Voir la taille après dropna()
        lstm_sequence_data = features_df[lstm_features_cols].tail(lstm_look_back)
        logger.info(f"Sequence length for LSTM: {len(lstm_sequence_data)} (Required: {lstm_look_back})")

        if len(lstm_sequence_data) < lstm_look_back:
            logger.warning("Not enough data for LSTM sequence after feature calculation. Skipping this cycle.")
            return # Maintenant, vous savez pourquoi il s'arrête

        #lstm_sequence_data = features_df[lstm_features_cols].tail(lstm_look_back)
        #if len(lstm_sequence_data) < lstm_look_back: return
        lstm_sequence_scaled = self.models['lstm_scaler'].transform(lstm_sequence_data)
        lstm_input = np.expand_dims(lstm_sequence_scaled, axis=0)
        lstm_pred = await asyncio.to_thread(self.models['lstm'].predict, lstm_input, verbose=0)
        momentum = "Momentum Haussier" if lstm_pred[0][0] > 0.5 else "Momentum Baissier"
        analysis_state["momentum"] = {"value": momentum, "pass": False}
        publish_state()
        logger.info(f"-> LSTM: {momentum}")
            
        # Étape 3: GRU
        analysis_state["volatility"]["value"] = "En cours..."
        publish_state()
        gru_look_back = 48
        gru_features_cols = self.models['gru_scaler'].feature_names_in_
        gru_sequence_data = features_df[gru_features_cols].tail(gru_look_back)
        if len(gru_sequence_data) < gru_look_back: return
        gru_sequence_scaled = self.models['gru_scaler'].transform(gru_sequence_data)
        gru_input = np.expand_dims(gru_sequence_scaled, axis=0)
        gru_pred = await asyncio.to_thread(self.models['gru'].predict, gru_input, verbose=0)
        volatility = "Haute Volatilité" if gru_pred[0][0] > 0.5 else "Basse Volatilité"
        analysis_state["volatility"] = {"value": volatility, "pass": False}
        publish_state()
        logger.info(f"-> GRU: {volatility}")

        # Étape 4: RSI
        latest_rsi = latest_features['RSI_14'].iloc[0]
        analysis_state["rsi"] = {"value": f"{latest_rsi:.2f}", "pass": False}
        publish_state()
        logger.info(f"-> RSI: {latest_rsi:.2f}")

        # --- DÉCISION FINALE ET GÉNÉRATION DE SIGNAL ---

        final_decision = "AUCUN SIGNAL"
        buy_score, sell_score = self._calculate_scores(regime, momentum, volatility, latest_rsi)

        logger.info(f"SCORE ACHAT: {buy_score} (Seuil: {self.scoring_params['buy_threshold']})")
        logger.info(f"SCORE VENTE: {sell_score} (Seuil: {self.scoring_params['sell_threshold']})")

        # --- RÈGLE D'ACHAT ---
        buy_regime_pass = regime in ['Bull_Market_2021', 'Recent_Data_2024']
        buy_momentum_pass = momentum == 'Momentum Haussier'
        buy_volatility_pass = volatility == 'Basse Volatilité'
        buy_rsi_pass = latest_rsi < self.rsi_params['buy_threshold']

        if buy_score >= self.scoring_params['buy_threshold']:
            final_decision = "ACHAT"
            logger.warning(f"🚨 SIGNAL D'ACHAT ({event.symbol}) - Score: {buy_score}")
            signal = SignalEvent(timestamp=datetime.now(timezone.utc), symbol=event.symbol, direction='LONG')
            await self.event_bus.put(signal)
        
        elif sell_score >= self.scoring_params['sell_threshold']:
            final_decision = "VENTE"
            logger.warning(f"🚨 SIGNAL DE VENTE ({event.symbol}) - Score: {sell_score}")
            signal = SignalEvent(timestamp=datetime.now(timezone.utc), symbol=event.symbol, direction='SHORT')
            await self.event_bus.put(signal)

        # Publication de l'état final de l'analyse
        analysis_state["final_decision"] = final_decision
        publish_state()
