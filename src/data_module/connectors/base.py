from abc import ABC, abstractmethod

class BaseConnector(ABC):
    """Classe de base abstraite pour les connecteurs WebSocket."""
    def __init__(self, symbols: list, recorder):
        self.symbols = symbols
        self.recorder = recorder
        self.exchange_name = "default"

    @abstractmethod
    async def connect(self):
        """Méthode principale pour se connecter et écouter le flux."""
        raise NotImplementedError