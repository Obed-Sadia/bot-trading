# main_sentiment_acquirer.py

import asyncio
import aiohttp
import yaml
import logging
import logging.handlers
import os
import praw
from prometheus_client import start_http_server
from src.data_module.recorder import Recorder 
from src.data_module.schemas import RawSentimentPost
from src.monitoring import MESSAGES_PROCESSED

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    if logger.hasHandlers(): logger.handlers.clear()
    if not os.path.exists('logs'): os.makedirs('logs')
    fh = logging.handlers.RotatingFileHandler('logs/sentiment_acquirer.log', maxBytes=5*1024*1024, backupCount=3)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    logger.addHandler(ch)

async def cryptopanic_collector(api_key: str, recorder: Recorder, interval: int):
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={api_key}&public=true"
    async with aiohttp.ClientSession() as session:
        while True:
            logging.info("[CryptoPanic] Collecte des nouvelles...")
            try:
                async with session.get(url) as response:
                    # Gérer les erreurs de limite de débit
                    if response.status == 429:
                        logging.warning("[CryptoPanic] Limite d'API atteinte. Attente prolongée de 12 heures.")
                        await asyncio.sleep(43200) # Attendre 12 heures
                        continue
                    response.raise_for_status() # Lève une exception pour les autres erreurs HTTP

                    data = await response.json()
                    posts_to_save = [RawSentimentPost(source='cryptopanic', symbol=p.get('currencies', [{}])[0].get('code', "GENERAL"), text=p['title']) for p in data.get('results', []) if p.get('title')]
                    
                    if posts_to_save:
                        # Utiliser run_in_executor car le recorder est synchrone
                        await asyncio.get_event_loop().run_in_executor(None, recorder.save_sentiment_posts, posts_to_save)
                        MESSAGES_PROCESSED.labels(exchange='cryptopanic').inc(len(posts_to_save))
                        logging.info(f"[CryptoPanic] {len(posts_to_save)} titres enregistrés.")

            except Exception as e:
                logging.error(f"[CryptoPanic] Erreur: {e}")
            
            logging.info(f"[CryptoPanic] Prochaine collecte dans {interval} secondes.")
            await asyncio.sleep(interval)

def fetch_reddit_sync(api_keys: dict, subreddits: list) -> list:
    logging.info("[Reddit] Collecte des nouveaux posts...")
    try:
        reddit = praw.Reddit(client_id=api_keys['reddit_client_id'], client_secret=api_keys['reddit_client_secret'], user_agent=api_keys['reddit_user_agent'])
        posts_to_save = [RawSentimentPost(source='reddit', symbol=sub_name.upper(), text=s.title) for sub_name in subreddits for s in reddit.subreddit(sub_name).new(limit=10)]
        return posts_to_save
    except Exception as e:
        logging.error(f"[Reddit] Erreur: {e}")
        return []

async def reddit_collector(api_keys: dict, subreddits: list, recorder: Recorder, interval: int):
    loop = asyncio.get_event_loop()
    while True:
        posts = await loop.run_in_executor(None, fetch_reddit_sync, api_keys, subreddits)
        if posts:
            await loop.run_in_executor(None, recorder.save_sentiment_posts, posts)
            MESSAGES_PROCESSED.labels(exchange='reddit').inc(len(posts))
            logging.info(f"[Reddit] {len(posts)} titres enregistrés.")
        
        logging.info(f"[Reddit] Prochaine collecte dans {interval} secondes.")
        await asyncio.sleep(interval)

async def main():
    setup_logging()
    logging.info("Lancement du module d'acquisition de sentiment...")
    start_http_server(8001)
    logging.info("Serveur de métriques de sentiment démarré sur le port 8001.")
    
    with open('config.yml', 'r') as f: config = yaml.safe_load(f)
    
    api_keys = config.get('api_keys', {}); 
    influx_config = config['data_acquisition']['influxdb']; 
    sentiment_config = config.get('sentiment_sources', {})
    
    recorder = Recorder(influx_config)
    tasks = []

    # Démarrer CryptoPanic seulement si la clé est présente
    if 'cryptopanic' in api_keys and api_keys['cryptopanic']:
        interval = sentiment_config.get('cryptopanic_poll_interval_seconds', 43200) # Par défaut: 12 heures
        tasks.append(asyncio.create_task(cryptopanic_collector(api_keys['cryptopanic'], recorder, interval)))
    
    # Démarrer Reddit seulement si les clés sont présentes
    if 'reddit_client_id' in api_keys and 'reddit_subreddits' in sentiment_config:
        interval = sentiment_config.get('reddit_poll_interval_seconds', 1800) # Par défaut: 30 minutes
        tasks.append(asyncio.create_task(reddit_collector(api_keys, sentiment_config['reddit_subreddits'], recorder, interval)))
        
    if not tasks:
        logging.warning("Aucune source de sentiment configurée. Arrêt.")
        return

    try:
        await asyncio.gather(*tasks)
    finally:
        recorder.close()
        logging.info("Collecteur de sentiment arrêté.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nArrêt demandé par l'utilisateur.")