from pydantic import BaseModel, Field
from typing import List, Dict
from datetime import datetime

class BinanceL2Data(BaseModel):
    last_update_id: int = Field(..., alias='lastUpdateId')
    bids: List[List[str]]
    asks: List[List[str]]
    symbol: str

class KrakenBookLevel(BaseModel):
    price: float
    qty: float

class KrakenL2Data(BaseModel):
    symbol: str
    bids: List[KrakenBookLevel]
    asks: List[KrakenBookLevel]

class CoinbaseL2Update(BaseModel):
    product_id: str
    changes: List[List[str]]

class CoinbaseL2Snapshot(BaseModel):
    product_id: str
    bids: List[List[str]]
    asks: List[List[str]]

class Trade(BaseModel):
    """
    Modèle standardisé pour une transaction unique, peu importe l'exchange.
    """
    exchange: str
    symbol: str
    price: float
    quantity: float
    side: str  # 'buy' ou 'sell'
    trade_time: datetime
    trade_id: str
    
class RawSentimentPost(BaseModel):
    """
    Valide les données brutes de sentiment (titre de nouvelle, post Reddit)
    avant de les enregistrer dans la base de données.
    """
    # La source de la donnée (ex: 'cryptopanic', 'reddit')
    source: str
    
    # Le symbole de la cryptomonnaie concernée (ex: 'BTC', 'ETH', 'GENERAL')
    symbol: str
    
    # Le texte brut du titre ou du post qui sera analysé plus tard
    text: str