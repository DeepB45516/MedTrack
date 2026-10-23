"""Vercel serverless entry point — exposes the Flask WSGI app as `app`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wsgi_loader import load_app

app = load_app()
