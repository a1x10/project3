"""Один раз: подключает Spotify для команды «Стелла, лайк»."""
import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import spotify_api

spotify_api.login()
