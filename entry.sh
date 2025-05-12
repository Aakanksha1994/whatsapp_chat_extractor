#!/bin/bash
# Activate Python virtual environment if it exists
if [ -d "/opt/venv" ]; then
    source /opt/venv/bin/activate
fi

# Get port from environment or use default
PORT=${PORT:-3000}

# Start the application
exec gunicorn simple_app:app --bind "0.0.0.0:$PORT" 