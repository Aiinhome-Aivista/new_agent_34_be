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

    port = int(os.getenv("PORT",3052) or os.getenv("FLASK_PORT", 3052))
    app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False))
