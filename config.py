from pydantic_settings import BaseSettings, SettingsConfigDict

class Config(BaseSettings):
    # API Keys
    HL_SECRET_KEY: str
    HL_WALLET_ADDRESS: str
    PAGERDUTY_ROUTING_KEY: str
    
    # Environment
    ENV: str = "production"
    
    # Database / Redis
    POSTGRES_URL: str = "postgresql://bot_user:bot_password@localhost:5432/bot_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Risk Limits
    MAX_LOSS_USD: float = 50.0  # $50 max loss
    MAX_POSITION_USD: float = 50.0 # $50 max notional initially
    MAX_ORDER_SIZE: float = 50.0 # max size per child order
    
    # Trading params
    SYMBOL: str = "ETH"
    BTC_BETA: float = 0.8
    EWMA_WINDOW_SAMPLES: int = 100
    SPREAD_CANCEL_THRESHOLD: float = 0.5 # USD deviation limit
    
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

# To instantiate, users should have their .env setup.
# settings = Config()
