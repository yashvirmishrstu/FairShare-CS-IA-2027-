import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'fairshare_production_secret_key_2026'
    DATABASE = os.path.join(BASE_DIR, 'data', 'fairshare.db')
    
    # Default Algorithmic Weightings & Settings
    DEFAULT_VISIT_WEIGHT = 10.0      # 10 points per visit
    DEFAULT_SPENDING_WEIGHT = 0.5     # 0.5 points per $ spent
    DEFAULT_REFERRAL_WEIGHT = 50.0   # 50 points per guest referral
    DEFAULT_FACILITY_WEIGHT = 0.2     # 0.2 points per facility-minute used
    DEFAULT_LOYALTY_WEIGHT = 5.0      # 5 points per month of membership
    DEFAULT_TIER_MULTIPLIERS = {'Member': 1.0, 'Premium': 1.15, 'VIP': 1.30}
    DEFAULT_PROFIT_POOL = 10000.00   # $10,000 reward pool funding the coupon marketplace
    DEFAULT_POINTS_VALUE_DOLLARS = 0.50  # each point is worth $0.50 against the yearly fee
    DEFAULT_YEARLY_FEE = 1200.00     # standard yearly club membership fee
