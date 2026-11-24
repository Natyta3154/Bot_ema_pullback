"""
Script de Diagnóstico para MetaTrader 5 (IC Markets)
===================================================
Permite verificar rápidamente:
1. Conexión con el terminal MT5 local
2. Autenticación con la cuenta Demo de IC Markets
3. Información de la cuenta (balance, equidad, apalancamiento)
4. Descarga de datos OHLCV para el símbolo configurado
5. Estado de órdenes y posiciones abiertas
"""
import os
import MetaTrader5 as mt5
from dotenv import load_dotenv

load_dotenv()

login = int(os.getenv("MT5_LOGIN", "0")) if os.getenv("MT5_LOGIN", "0").strip().isdigit() else 0
password = os.getenv("MT5_PASSWORD", "")
server = os.getenv("MT5_SERVER", "ICMarketsSC-Demo")
path = os.getenv("MT5_PATH", "")
symbol = os.getenv("MT5_SYMBOL", "BTCUSD")

print("=" * 60)
print("🔍 DIAGNÓSTICO DE CONEXIÓN METATRADER 5 / IC MARKETS")
print("=" * 60)

init_kwargs = {}
if path:
    init_kwargs['path'] = path

if not mt5.initialize(**init_kwargs):
    print(f"❌ Error al inicializar MT5: {mt5.last_error()}")
    print("Asegúrate de tener el terminal de escritorio de MetaTrader 5 abierto en Windows.")
    exit(1)

print(f"✅ Terminal MT5 inicializado correctamente (Versión: {mt5.version()})")

if login > 0:
    print(f"🔐 Intentando autenticar cuenta {login} en servidor '{server}'...")
    auth = mt5.login(login=login, password=password, server=server)
    if not auth:
        print(f"❌ Error de login en MT5: {mt5.last_error()}")
        print("Revisa MT5_LOGIN, MT5_PASSWORD y MT5_SERVER en tu archivo .env.")
        mt5.shutdown()
        exit(1)

acc = mt5.account_info()
if acc:
    print(f"✅ Conectado a la cuenta: {acc.login}")
    print(f"   • Servidor: {acc.server}")
    print(f"   • Nombre: {acc.name}")
    print(f"   • Balance: {acc.balance} {acc.currency}")
    print(f"   • Equidad: {acc.equity} {acc.currency}")
    print(f"   • Margen Libre: {acc.margin_free} {acc.currency}")
    print(f"   • Apalancamiento: 1:{acc.leverage}")
else:
    print("⚠️ No se pudo obtener account_info()")

print("-" * 60)
print(f"📊 Verificando símbolo: {symbol}...")
if not mt5.symbol_select(symbol, True):
    print(f"⚠️ No se pudo seleccionar {symbol}. Comprueba si en tu cuenta el par tiene sufijo (ej: BTCUSD, BTCUSD.a, etc.).")
else:
    info = mt5.symbol_info(symbol)
    if info:
        tick = mt5.symbol_info_tick(symbol)
        bid = tick.bid if tick else "N/A"
        ask = tick.ask if tick else "N/A"
        print(f"✅ Símbolo activo: {symbol}")
        print(f"   • Bid: {bid} | Ask: {ask}")
        print(f"   • Tamaño de contrato: {info.trade_contract_size}")
        print(f"   • Lote Mínimo: {info.volume_min} | Paso: {info.volume_step} | Máximo: {info.volume_max}")

    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 5)
    if rates is not None and len(rates) > 0:
        print(f"✅ Descarga de velas 1H exitosa ({len(rates)} velas). Último precio de cierre: {rates[-1]['close']}")
    else:
        print(f"⚠️ No se pudieron descargar velas 1H para {symbol}: {mt5.last_error()}")

positions = mt5.positions_get(symbol=symbol)
print("-" * 60)
print(f"📋 Posiciones abiertas en {symbol}: {len(positions) if positions else 0}")
if positions:
    for p in positions:
        side = "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"   • Ticket: {p.ticket} | {side} {p.volume} @ {p.price_open} | SL: {p.sl} | TP: {p.tp} | Profit: {p.profit}")

mt5.shutdown()
print("=" * 60)
print("🏁 Diagnóstico completado.")
