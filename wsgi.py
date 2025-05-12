"""
WSGI entry point for Railway deployment
"""
from simple_app import app

# Standard WSGI entry point
application = app

if __name__ == "__main__":
    app.run() 