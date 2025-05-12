"""
Main entry point for Railway deployment
"""
import os
from simple_app import app

# Get port from environment
port = int(os.environ.get("PORT", 3000))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port) 