from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd

@dataclass
class MarketEvent:
    type: str = field(default="MARKET", init=False, repr=False) 
    timestamp: datetime
    symbol: str
    best_bid: float
    best_ask: float
    bids: pd.DataFrame
    asks: pd.DataFrame

@dataclass
class SignalEvent:
    type: str = field(default="SIGNAL", init=False, repr=False) 
    timestamp: datetime
    symbol: str
    direction: str  # 'LONG' ou 'SHORT'
    strength: float = 1.0

@dataclass
class OrderEvent:
    type: str = field(default="ORDER", init=False, repr=False) 
    timestamp: datetime
    symbol: str
    order_type: str  # 'MARKET' ou 'LIMIT'
    direction: str  # 'BUY' ou 'SELL'
    quantity: float
    price: float = 0.0
    stop_loss_price: float = 0.0 
    take_profit_price: float = 0.0 

@dataclass
class FillEvent:
    type: str = field(default="FILL", init=False, repr=False) 
    timestamp: datetime
    symbol: str
    direction: str
    quantity: float
    price: float
    commission: float
    exchange: str
    stop_loss_price: float = 0.0 
    take_profit_price: float = 0.0 