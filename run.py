import os
import sys
from pathlib import Path

# Ensure project root (new_agent_34_be) is in sys.path
root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app import create_app
from app.extensions import db

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        # Ensure database tables exist if running locally
        try:
            db.create_all()
        except Exception as e:
            app.logger.warning(f"Could not automatically create tables at startup: {e}")

    # Prioritize PORT or FLASK_PORT, defaulting to 3052 for production container
    raw_port = os.getenv("PORT") or os.getenv("FLASK_PORT") or "3052"
    try:
        port = int(raw_port)
    except (ValueError, TypeError):
        port = 3052

    debug = os.getenv("FLASK_DEBUG", "0").lower() in ("1", "true")
    app.logger.info(f"Starting FraudOps Backend on 0.0.0.0:{port} (debug={debug})")
    app.run(host="0.0.0.0", port=port, debug=debug)
