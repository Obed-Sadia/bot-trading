# main_backtest.py (à la racine du projet)

import yaml
from src.backtesting_module.engine import BacktestEngine
from src.trading_module import strategy_loader # Importe le chargeur de stratégie

def run_backtest():
    """
    Charge la configuration, initialise le moteur de backtest et le lance.
    """
    # Charger la configuration depuis le fichier YAML
    try:
        with open('config.yml', 'r') as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        print("Erreur : Le fichier 'config.yml' est introuvable. Veuillez le créer.")
        return

    # --- Configuration du Backtest ---
    # Sélectionner la stratégie et ses paramètres à partir de la config
    active_strategy_name = config.get('active_strategy')
    if not active_strategy_name:
        print("Erreur : 'active_strategy' non définie dans config.yml.")
        return
        
    strategy_params = config.get('strategies', {}).get(active_strategy_name)
    if strategy_params is None:
        print(f"Erreur : Paramètres pour la stratégie '{active_strategy_name}' introuvables dans config.yml.")
        return

    # Définir les autres paramètres du backtest
    backtest_config = {
        "csv_path": "./data/raw/BTC_USDT-1h.csv", 
        "symbol": "BTC/USDT",
        "initial_capital": 10000.0,
    }

    print(f"--- Lancement du backtest pour la stratégie: {active_strategy_name} ---")

    # Créer le moteur de backtest
    engine = BacktestEngine(
        csv_path=backtest_config["csv_path"],
        symbol=backtest_config["symbol"],
        initial_capital=backtest_config["initial_capital"],
        strategy_loader=strategy_loader,  # On passe le module de chargement
        strategy_name=active_strategy_name,
        strategy_params=strategy_params
    )
    
    # Lancer le moteur
    engine.run()

if __name__ == '__main__':
    run_backtest()