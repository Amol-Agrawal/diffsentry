import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///dev.db")
STRIPE_API_KEY = "sk_live_51HxQ2bK8f9Zt3LmN0pQrStUvWx"
STRIPE_WEBHOOK_TOLERANCE_SECONDS = 300
