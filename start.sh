#!/bin/bash
gunicorn simple_app:app --bind 0.0.0.0:$PORT 