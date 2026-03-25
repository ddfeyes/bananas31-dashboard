"""Configuration — loaded from environment variables with sensible defaults."""
import os

API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8768"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
OHLCV_INTERVAL_SECS = int(os.getenv("OHLCV_INTERVAL_SECS", "60"))

BSC_HTTP_RPC = os.getenv(
    "BSC_HTTP_RPC",
    "https://bsc-mainnet.nodereal.io/v1/4138a0b4c2044d54aca77d92d0bc7947",
)
BSC_WSS_RPC = os.getenv(
    "BSC_WSS_RPC",
    "wss://bsc-mainnet.nodereal.io/ws/v1/4138a0b4c2044d54aca77d92d0bc7947",
)
BSC_POOL = os.getenv(
    "BSC_POOL",
    "0x7f51bbf34156ba802deb0e38b7671dc4fa32041d",
)

DB_PATH = os.getenv("DB_PATH", "aggdash.db")
RING_BUFFER_MAX_TICKS = int(os.getenv("RING_BUFFER_MAX_TICKS", "50000"))
