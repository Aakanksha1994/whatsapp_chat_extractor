#!/usr/bin/env python
"""
Run script for Railway deployment
"""
import os
from simple_app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port) 