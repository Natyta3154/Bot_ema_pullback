import ccxt
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')

client = ccxt.binance({
    'apiKey': api_key,
    'secret': api_secret,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

try:
    print('Testing connection...')
    positions = client.fapiPrivateV2GetPositionRisk({'symbol': 'BTCUSDT'})
    for pos in positions:
        print(f"Symbol: {pos['symbol']}, Leverage: {pos['leverage']}, Margin Mode: {pos['marginType']}, Position Amt: {pos['positionAmt']}")
except Exception as e:
    print(f'Error: {e}')
