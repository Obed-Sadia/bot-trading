# src/ml_module/models.py

import torch
import torch.nn as nn

class PricePredictorLSTM(nn.Module):
    """
    Un modèle LSTM pour la classification binaire (hausse ou non).
    Il prend une séquence de features en entrée.
    """
    def __init__(self, input_dim: int, hidden_dim: int, n_layers: int, dropout: float):
        super(PricePredictorLSTM, self).__init__()
        self.hidden_dim = hidden_dim
        self.n_layers = n_layers

        # Couche LSTM
        self.lstm = nn.LSTM(
            input_dim,
            hidden_dim,
            n_layers,
            batch_first=True, 
            dropout=dropout
        )
        
        # Couche de sortie linéaire
        self.fc = nn.Linear(hidden_dim, 1)

    def forward(self, x):
        # Initialiser les états cachés
        h0 = torch.zeros(self.n_layers, x.size(0), self.hidden_dim).to(x.device)
        c0 = torch.zeros(self.n_layers, x.size(0), self.hidden_dim).to(x.device)
        
        # Passer dans le LSTM
        out, _ = self.lstm(x, (h0, c0))
        
        # Ne prendre que la sortie du dernier pas de temps
        out = self.fc(out[:, -1, :])
        return out