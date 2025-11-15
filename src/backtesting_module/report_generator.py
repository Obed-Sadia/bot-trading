# src/backtesting_module/report_generator.py

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

class ReportGenerator:
    """
    Génère un rapport de performance à partir des résultats d'un backtest.
    """
    def __init__(self, equity_curve: pd.Series, trades: list):
        self.equity = equity_curve
        self.trades = trades
        self.returns = self.equity.pct_change().dropna()

    def _calculate_max_drawdown(self):
        """Calcule le drawdown maximum en pourcentage."""
        cumulative_max = self.equity.cummax()
        drawdown = (self.equity - cumulative_max) / cumulative_max
        return abs(drawdown.min())

    def _calculate_sharpe_ratio(self, risk_free_rate=0.0):
        """Calcule le Sharpe Ratio annualisé (suppose des données journalières)."""
        if self.returns.std() == 0: return 0.0
        excess_returns = self.returns - risk_free_rate / 252
        return np.sqrt(252) * excess_returns.mean() / excess_returns.std()

    def generate_summary(self):
        """Affiche un résumé des métriques de performance clés."""
        total_return = (self.equity.iloc[-1] / self.equity.iloc[0]) - 1
        max_drawdown = self._calculate_max_drawdown()
        sharpe = self._calculate_sharpe_ratio()

        print("\n--- Rapport de Performance ---")
        print(f"Période de test:          {self.equity.index.min().date()} à {self.equity.index.max().date()}")
        print(f"Rendement Total:          {total_return:.2%}")
        print(f"Maximum Drawdown:         {max_drawdown:.2%}")
        print(f"Sharpe Ratio (Ann.):      {sharpe:.2f}")
        print(f"Nombre total de trades:   {len(self.trades)}")
        # D'autres métriques comme le Sortino Ratio, Profit Factor, etc. peuvent être ajoutées ici.

    def plot_equity_curve(self):
        """Affiche le graphique de la courbe des capitaux."""
        plt.style.use('seaborn-v0_8-darkgrid')
        fig, ax = plt.subplots(figsize=(14, 7))
        
        # Courbe des capitaux
        ax.plot(self.equity.index, self.equity, label='Valeur du Portefeuille', color='blue', lw=2)
        
        # High-water mark
        ax.plot(self.equity.index, self.equity.cummax(), label='High-Water Mark', color='green', ls='--', lw=1)
        
        ax.set_title('Performance du Portefeuille (Equity Curve)', fontsize=16)
        ax.set_xlabel('Date', fontsize=12)
        ax.set_ylabel('Valeur du Portefeuille ($)', fontsize=12)
        ax.legend()
        ax.grid(True)
        
        print("\nAffichage du graphique de performance...")
        plt.show()