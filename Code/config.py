import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'fairshare_production_secret_key_2026'
    DATABASE = os.path.join(BASE_DIR, 'data', 'fairshare.db')
    
    # Default Algorithmic Weightings & Settings
    DEFAULT_VISIT_WEIGHT = 10.0      # 10 points per visit
    DEFAULT_SPENDING_WEIGHT = 0.5     # 0.5 points per $ spent
    DEFAULT_REFERRAL_WEIGHT = 50.0   # 50 points per guest referral
    DEFAULT_PROFIT_POOL = 10000.00   # $10,000 profit sharing pool
