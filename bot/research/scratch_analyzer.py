import sys, os
import pandas as pd
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from bot.config import settings
from bot.strategies.factory import StrategyFactory
from bot.backtest.data_loader import DataLoader

def run():
    start_date = "2026-05-01"
    end_date = "2026-07-05"
    loader = DataLoader(symbol="BTC/USDT")
    dfs = {
        '15m': loader.fetch_data('15m', start_date, end_date),
        '30m': loader.fetch_data('30m', start_date, end_date),
        '1h': loader.fetch_data('1h', start_date, end_date)
    }
    
    strat = StrategyFactory.create_strategy(settings.ACTIVE_STRATEGY, None, None)
    strat.analyze_market(dfs)
    
    df_t = dfs['15m']
    df_e = dfs['30m']
    df_m = dfs['1h']
    
    counts = {'OK':0, 'REJECT_BEARISH': 0, 'REJECT_BULLISH': 0, 'REJECT_BODY': 0, 'REJECT_CLOSE_BELOW_EMA': 0, 'REJECT_CLOSE_ABOVE_EMA': 0, 'REJECT_RSI': 0, 'PULLBACK_MISS': 0, 'NO_TREND': 0, 'TOTAL': 0}
    
    for i in range(50, len(df_t)):
        raw_ts = df_t.index[i]
        if isinstance(raw_ts, (int)): ts = pd.to_datetime(raw_ts, unit='ms')
        else: ts = pd.to_datetime(raw_ts)
        
        counts['TOTAL'] += 1
        
        # Fast lookup
        e_ts = ts.floor('30min')
        if e_ts not in df_e.index:
            try: e_ts = int(e_ts.timestamp() * 1000)
            except: continue
        if e_ts not in df_e.index: continue
        
        m_ts = ts.floor('h')
        if m_ts not in df_m.index:
            try: m_ts = int(m_ts.timestamp() * 1000)
            except: continue
        if m_ts not in df_m.index: continue
            
        idx_e = df_e.index.get_loc(e_ts)
        idx_m = df_m.index.get_loc(m_ts)
        
        df_sub = {
            '15m': df_t.iloc[:i+1],
            '30m': df_e.iloc[:idx_e+1],
            '1h': df_m.iloc[:idx_m+1]
        }
        
        res = strat.generate_signal(df_t['close'].iloc[i], 1000, df_sub)
        reason = res.get('reason', '')
        if reason:
            counts[reason] = counts.get(reason, 0) + 1
            
    print(counts)

if __name__ == '__main__':
    run()
