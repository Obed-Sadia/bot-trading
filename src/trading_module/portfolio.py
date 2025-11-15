# src/trading_module/portfolio.py
import logging
import json
import redis
from datetime import datetime, timezone
from src.common.objects import FillEvent, OrderEvent
from src.monitoring import PORTFOLIO_VALUE, OPEN_POSITIONS, TRADES_EXECUTED

logger = logging.getLogger(__name__)

class Position:
    def __init__(self, symbol: str, direction: str, quantity: float, entry_price: float, stop_loss_price: float, take_profit_price: float):
        self.symbol = symbol
        self.direction = direction
        self.quantity = quantity
        self.entry_price = entry_price
        self.stop_loss_price = stop_loss_price
        self.take_profit_price = take_profit_price
        self.entry_timestamp = datetime.now(timezone.utc)

class Portfolio:
    def __init__(self, event_bus, initial_capital: float = 10000.0):
        self.event_bus = event_bus
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions = {}
        self.trade_history = [] 
        self.total_value = initial_capital
        self.last_known_prices = {}
        self.is_panic_mode = False
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0.0
        self.total_loss = 0.0
        self.holding_times_hours = []
        self.history = {"labels": [], "total_value": [], "cash": []}
        
        try:
            self.redis_client = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
            self.redis_client.ping()
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Impossible de se connecter à Redis: {e}")
            self.redis_client = None

    async def update_on_fill(self, fill: FillEvent):
        """Met à jour le portefeuille après une transaction (FillEvent)."""
        TRADES_EXECUTED.labels(exchange=fill.exchange, symbol=fill.symbol, side=fill.direction).inc()
        
        position = self.positions.get(fill.symbol)
        trade_value = fill.price * fill.quantity
        self.cash -= fill.commission

        if position and ((position.direction == 'BUY' and fill.direction == 'SELL') or (position.direction == 'SELL' and fill.direction == 'BUY')):
            # --- CORRECTION : Logique de clôture de position ---
            self.total_trades += 1
            pnl = (fill.price - position.entry_price) * position.quantity if position.direction == 'BUY' else (position.entry_price - fill.price) * position.quantity
            
            if pnl >= 0:
                self.winning_trades += 1
                self.total_profit += pnl
            else:
                self.total_loss += abs(pnl)
            
            # Mettre à jour le cash avec la valeur de la vente/rachat ET le PnL
            self.cash += (position.entry_price * position.quantity) + pnl
            
            holding_time = (datetime.now(timezone.utc) - position.entry_timestamp).total_seconds() / 3600
            self.holding_times_hours.append(holding_time)
            
            #  --- AJOUT: Historique des trades ---
            closed_trade = {
                "symbol": position.symbol,
                "direction": position.direction,
                "entry_price": position.entry_price,
                "exit_price": fill.price,
                "quantity": position.quantity,
                "pnl": pnl,
                "entry_time": position.entry_timestamp.isoformat(),
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "status": "Fermé"
            }
            self.trade_history.append(closed_trade)
            # --- FIN AJOUT ---
            
            logger.info(f"Position fermée pour {fill.symbol}. PnL Réalisé: ${pnl:.2f}")
            del self.positions[fill.symbol]
        else:
            # Note: Cette logique suppose qu'on n'augmente pas une position existante
            # On assume qu'un fill dans la même direction est une nouvelle position (après clôture)
            #self.cash -= trade_value
            #self.positions[fill.symbol] = Position(
            #    symbol=fill.symbol, direction=fill.direction, quantity=fill.quantity,
            #    entry_price=fill.price, 
            #    stop_loss_price=getattr(fill, 'stop_loss_price', 0.0),
            #    take_profit_price=getattr(fill, 'take_profit_price', 0.0)
            #)
            #logger.info(f"🆕 Position ouverte pour {fill.symbol}: {fill.direction} {fill.quantity} @ ${fill.price:.2f}")

        # Mettre à jour toutes les valeurs et les publier
        #self.update_portfolio_value()
        #self.update_portfolio_stats()
        

            # Logique d'ouverture de position
            self.cash -= trade_value if fill.direction == 'BUY' else -trade_value
            self.positions[fill.symbol] = Position(
                symbol=fill.symbol, direction=fill.direction, quantity=fill.quantity,
                entry_price=fill.price, stop_loss_price=getattr(fill, 'stop_loss_price', 0.0),
                take_profit_price=getattr(fill, 'take_profit_price', 0.0)
            )

        self.update_portfolio_value()
        self.update_portfolio_stats()

    def update_portfolio_value(self, market_data: dict = {}):
        """Recalcule la valeur totale et met à jour Redis ET Prometheus."""
        self.last_known_prices.update(market_data)
        holdings_value = sum(pos.quantity * self.last_known_prices.get(symbol, pos.entry_price) for symbol, pos in self.positions.items())
        self.total_value = self.cash + holdings_value

        PORTFOLIO_VALUE.set(self.total_value)
        OPEN_POSITIONS.set(len(self.positions))

        now = datetime.now(timezone.utc)
        if not self.history["labels"] or (now - datetime.fromisoformat(self.history["labels"][-1])).total_seconds() > 5:
            self.history["labels"].append(now.isoformat())
            self.history["total_value"].append(self.total_value)
            self.history["cash"].append(self.cash)
            
            max_points = 300
            if len(self.history["labels"]) > max_points:
                self.history["labels"] = self.history["labels"][-max_points:]
                self.history["total_value"] = self.history["total_value"][-max_points:]
                self.history["cash"] = self.history["cash"][-max_points:]

        if self.redis_client:
            try:
                # Publier l'état principal
                self.redis_client.set("bot:portfolio:state", json.dumps(self.to_dict(), default=str))
                # Publier l'historique pour le graphique
                self.redis_client.set("bot:portfolio:history", json.dumps(self.history))
                # --- AJOUT: Publier l'historique des trades ---
                self.redis_client.set("bot:trade_history", json.dumps(self.trade_history))
            except redis.exceptions.RedisError as e:
                logger.error(f"Erreur Redis lors de la sauvegarde de l'état: {e}")

    def update_portfolio_stats(self):
        """Met à jour les statistiques de trading dans Redis."""
        if not self.redis_client: return
        stats = {
            "total_trades": self.total_trades,
            "win_rate": (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0,
            "profit_factor": (self.total_profit / abs(self.total_loss)) if self.total_loss > 0 else 999, # Éviter la division par zéro
            "avg_holding_time_hours": sum(self.holding_times_hours) / len(self.holding_times_hours) if self.holding_times_hours else 0
        }
        logger.info(f"📊 Mise à jour des stats: {stats}")
        try:
            self.redis_client.set("bot:stats", json.dumps(stats))
        except redis.exceptions.RedisError as e:
            logger.error(f"Erreur Redis lors de la sauvegarde des stats: {e}")
            
    def to_dict(self) -> dict:
        """Sérialise l'état actuel du portefeuille pour l'API."""
        pnl_value = self.total_value - self.initial_capital
        pnl_pct = (pnl_value / self.initial_capital * 100) if self.initial_capital > 0 else 0
        return {
            "total_value": self.total_value, "pnl_value": pnl_value, "pnl_pct": pnl_pct, "cash": self.cash,
            "positions": [pos.__dict__ for pos in self.positions.values()]
        }

    def get_last_price(self, symbol: str) -> float:
        return self.last_known_prices.get(symbol, 0.0)

    async def activate_panic_mode(self):
        if not self.positions:
            logger.info("PANIC MODE: Aucune position à liquider.")
            return
        logger.warning("🚨 PANIC MODE ACTIVATED! Liquidation de toutes les positions...")
        for position in list(self.positions.values()):
            closing_direction = 'SELL' if position.direction == 'BUY' else 'BUY'
            close_order = OrderEvent(
                timestamp=datetime.now(timezone.utc), symbol=position.symbol, order_type='MARKET',
                direction=closing_direction, quantity=abs(position.quantity)
            )
            await self.event_bus.put(close_order)
        logger.info("PANIC MODE: Tous les ordres de liquidation ont été envoyés.")
