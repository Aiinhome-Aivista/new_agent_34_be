from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_cors import CORS
import redis
import logging

logger = logging.getLogger("fraud_agent.extensions")

db = SQLAlchemy()
migrate = Migrate()
cors = CORS()

redis_client = None

def init_redis(app):
    global redis_client
    try:
        redis_client = redis.Redis.from_url(
            app.config["REDIS_URL"],
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0
        )
        redis_client.ping()
        logger.info("Successfully connected to Redis.")
    except Exception as e:
        logger.warning(f"Redis is not available or connection failed: {e}. Falling back to memory lock if needed.")
        redis_client = None
    return redis_client
