"""Запустить на ПК: python google_auth.py credentials.json -> google_token.json (положить в stella/data/)."""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], ["https://www.googleapis.com/auth/calendar"])
creds = flow.run_local_server(port=0)
open("google_token.json", "w").write(creds.to_json())
print("Готово: google_token.json")
