"""
Server file for Railway.com deployment
This simply imports the Flask app and runs it
"""

import os
from simple_app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port) 