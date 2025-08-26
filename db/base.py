import firebase_admin
from firebase_admin import credentials, firestore
import os

secrets_dir = os.getenv("SECRETS_DIR", ".secrets")
firebase_path = os.path.join(secrets_dir, "firebase1.json")

cred = credentials.Certificate(firebase_path)
firebase_admin.initialize_app(cred)

db = firestore.client()