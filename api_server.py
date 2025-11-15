# api_server.py
import docker
import yaml
import os
import logging
import json
import redis
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import APIKeyHeader
from datetime import datetime, timezone
from tenacity import retry, stop_after_attempt, wait_fixed
from fastapi.middleware.cors import CORSMiddleware

# Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = FastAPI()
CONFIG_PATH = 'config.yml'
LIVE_TRADER_SERVICE = 'live_trader'
#PROJECT_NAME = os.path.basename(os.getcwd()).replace("-", "").replace("_", "")
LIVE_TRADER_CONTAINER = "trading_bot_live"
API_KEY = os.getenv("API_KEY", "your-secret-api-key")  # À configurer via variable d'environnement

# Sécurité
api_key_header = APIKeyHeader(name="X-API-Key")

def verify_api_key(api_key: str = Depends(api_key_header)):
    if api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Clé API invalide")
    return api_key

# Clients
try:
    docker_client = docker.from_env()
    logger.info("Connecté à Docker avec succès.")
except Exception as e:
    logger.error(f"Erreur Docker: {e}")
    docker_client = None

try:
    with open(CONFIG_PATH, 'r') as f:
        config = yaml.safe_load(f)
    influx_config = config['data_acquisition']['influxdb']
    influx_url = influx_config['url'].replace("localhost", "influxdb")
except Exception as e:
    logger.error(f"Erreur de lecture de config.yml: {e}")
    config = {}

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
def connect_redis():
    client = redis.Redis(host='redis', port=6379, db=0, decode_responses=True)
    client.ping()
    return client

try:
    redis_client = connect_redis()
    logger.info("Connecté à Redis avec succès.")
except Exception as e:
    logger.error(f"Erreur de connexion à Redis: {e}")
    redis_client = None

# Routes de l'API
@app.get("/", include_in_schema=False)
async def get_control_panel():
    return FileResponse('index.html')

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    # Retourne un fichier favicon ou une réponse vide pour éviter l'erreur 404
    if os.path.exists("favicon.ico"):
        return FileResponse("favicon.ico")
    return JSONResponse(content={}, status_code=204)

def get_service_status(service_name: str):
    if not docker_client:
        return "docker_unavailable"
    try:
        containers = docker_client.containers.list(all=True, filters={"label": f"com.docker.compose.service={service_name}"})
        if not containers:
            return "not_found"
        return containers[0].status
    except docker.errors.NotFound:
        return "not_found"
    except Exception as e:
        logger.error(f"Erreur lors de la vérification du statut du service {service_name}: {e}")
        return "error"

@app.get("/api/bot/status")
async def get_bot_status(_: str = Depends(verify_api_key)):
    status = get_service_status(LIVE_TRADER_SERVICE)
    return JSONResponse(content={"service": LIVE_TRADER_SERVICE, "status": status})

@app.get("/api/portfolio/overview")
async def get_portfolio_overview(_: str = Depends(verify_api_key)):
    """Récupère l'état en temps réel du portefeuille depuis Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis non disponible")
    try:
        portfolio_state_json = redis_client.get("bot:portfolio:state")
        if not portfolio_state_json:
            return JSONResponse(content={"total_value": 10000, "pnl_value": 0, "pnl_pct": 0, "cash": 10000, "positions": []})
        state = json.loads(portfolio_state_json)
        required_fields = ["total_value", "pnl_value", "pnl_pct", "cash", "positions"]
        if not all(field in state for field in required_fields):
            raise ValueError("État du portefeuille incomplet")
        return JSONResponse(content=state)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'état du portefeuille: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Redis: {e}")

@app.get("/api/bot/stats")
async def get_bot_stats(_: str = Depends(verify_api_key)):
    """Récupère les statistiques de trading depuis Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis non disponible")
    try:
        stats_json = redis_client.get("bot:stats")
        if not stats_json:
            return JSONResponse(content={
                "total_trades": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_holding_time_hours": 0
            })
        stats = json.loads(stats_json)
        required_fields = ["total_trades", "win_rate", "profit_factor", "avg_holding_time_hours"]
        if not all(field in stats for field in required_fields):
            raise ValueError("Statistiques de trading incomplètes")
        return JSONResponse(content=stats)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des stats: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Redis: {e}")

@app.get("/api/portfolio/history")
async def get_portfolio_history(_: str = Depends(verify_api_key)):
    """Récupère l'historique des valeurs du portefeuille depuis Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis non disponible")
    try:
        history_json = redis_client.get("bot:portfolio:history")
        if not history_json:
            return JSONResponse(content={"labels": [], "total_value": [], "cash": []})
        return JSONResponse(content=json.loads(history_json))
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'historique: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Redis: {e}")

@app.get("/api/portfolio/trade_history")
async def get_trade_history(_: str = Depends(verify_api_key)):
    """Récupère l'historique des trades fermés depuis Redis."""
    if not redis_client:
        raise HTTPException(status_code=503, detail="Redis non disponible")
    try:
        history_json = redis_client.get("bot:trade_history")
        if not history_json:
            return JSONResponse(content=[])
        return JSONResponse(content=json.loads(history_json))
    except Exception as e:
        logger.error(f"Erreur lors de la récupération de l'historique des trades: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur Redis: {e}")

@app.get("/api/config")
async def get_config(_: str = Depends(verify_api_key)):
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        # Filtrer les données sensibles
        safe_config = {k: v for k, v in config.items() if k not in ['secrets', 'api_keys']}
        return JSONResponse(content=safe_config)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de config.yml: {e}")
        raise HTTPException(status_code=500, detail=f"Impossible de lire la config: {e}")

@app.post("/api/bot/start")
async def start_bot(_: str = Depends(verify_api_key)):
    if not docker_client:
        raise HTTPException(status_code=503, detail="Docker non disponible")
    try:
        container = docker_client.containers.get(LIVE_TRADER_CONTAINER)
        container.start()
        logger.info(f"Bot démarré: {LIVE_TRADER_CONTAINER}")
        return JSONResponse(content={"message": "Bot démarré."})
    except Exception as e:
        logger.error(f"Erreur lors du démarrage du bot: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur: {e}")

@app.post("/api/bot/stop")
async def stop_bot(_: str = Depends(verify_api_key)):
    if not docker_client:
        raise HTTPException(status_code=503, detail="Docker non disponible")
    try:
        container = docker_client.containers.get(LIVE_TRADER_CONTAINER)
        container.stop()
        logger.info(f"Bot arrêté: {LIVE_TRADER_CONTAINER}")
        return JSONResponse(content={"message": "Bot arrêté."})
    except Exception as e:
        logger.error(f"Erreur lors de l'arrêt du bot: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur: {e}")

@app.post("/api/bot/restart")
async def restart_bot(_: str = Depends(verify_api_key)):
    if not docker_client:
        raise HTTPException(status_code=503, detail="Docker non disponible")
    try:
        container = docker_client.containers.get(LIVE_TRADER_CONTAINER)
        container.restart()
        logger.info(f"Bot redémarré: {LIVE_TRADER_CONTAINER}")
        return JSONResponse(content={"message": "Bot redémarré."})
    except Exception as e:
        logger.error(f"Erreur lors du redémarrage du bot: {e}")
        raise HTTPException(status_code=500, detail=f"Erreur: {e}")

@app.post("/api/bot/panic")
async def trigger_panic_button(_: str = Depends(verify_api_key)):
    try:
        with open("panic.kill", "w") as f:
            f.write("panic")
        logger.info("Bouton panique activé, fichier panic.kill créé.")
        return JSONResponse(content={"message": "Bouton panique activé."})
    except Exception as e:
        logger.error(f"Erreur lors de la création du fichier panic: {e}")
        raise HTTPException(status_code=500, detail=f"Impossible de créer le fichier panic: {e}")

@app.get("/api/health")
async def health_check():
    """Vérifie l'état des dépendances."""
    status = {
        "docker": "connected" if docker_client else "disconnected",
        "redis": "connected" if redis_client and redis_client.ping() else "disconnected",
        "config": "available" if os.path.exists(CONFIG_PATH) else "missing"
    }
    return JSONResponse(content=status)

@app.get("/api/latest_analysis")
async def get_latest_analysis():
    """
    Retourne la dernière analyse effectuée par la stratégie.
    """
    if not redis_client:
        raise HTTPException(status_code=503, detail="Connexion à Redis non disponible.")
    
    try:
        analysis_data = redis_client.get("bot:latest_analysis")
        if not analysis_data:
            return {"status": "En attente de la première analyse du bot..."}
        return json.loads(analysis_data)
    except redis.exceptions.RedisError as e:
        raise HTTPException(status_code=500, detail=f"Erreur Redis: {e}")
# --- FIN DE L'AJOUT ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8008, reload=True)