import pandas as pd
import numpy as np
import itertools
import os
import sys

def main():
    print("Iniciando Fase 3: Descubrimiento de Edge Automático")
    
    # Cargar CSV de trades
    db_path = r"C:\Users\Usuario\Desktop\bot-simple-emas-moviles-rsi\bot\research\db\quantitative_trades.csv"
    
    if not os.path.exists(db_path):
        print(f"Error: No se encuentra la base de datos de trades en {db_path}")
        return
        
    df = pd.read_csv(db_path)
    print(f"Cargados {len(df)} trades base.")
    
    if len(df) == 0:
        print("No hay suficientes datos.")
        return
        
    # Discretizar variables
    if 'session' not in df.columns:
        # Asegurar que tenemos la sesión
        def get_session(h):
            if 0 <= h < 8: return 'Asia'
            elif 8 <= h < 16: return 'Londres'
            else: return 'Nueva York'
        df['session'] = df['utc_hour'].apply(get_session)
        
    df['session_bin'] = df['session'] # Asia, Londres, Nueva York
    
    # ADX Binning
    # adx > 25 (Trend), < 25 (Rango)
    df['adx_bin'] = np.where(df['adx'] >= 25, 'ADX_ALTO', 'ADX_BAJO')
    
    # Vol Ratio Binning
    df['vol_ratio_bin'] = np.where(df['vol_ratio'] >= 1.2, 'VOL_PICO', 
                                   np.where(df['vol_ratio'] >= 1.0, 'VOL_MEDIO', 'VOL_BAJO'))
                                   
    # Market Regime
    # Grouping market regimes to reduce fragmentation
    def group_regime(r):
        r = str(r)
        if 'TREND' in r:
            return 'TENDENCIA'
        elif 'VOLATILE' in r:
            return 'VOLATILIDAD'
        elif r in ['ACCUMULATION', 'DISTRIBUTION']:
            return 'TRANSICION'
        else:
            return 'SIDEWAYS'
            
    df['regime_bin'] = df['market_regime'].apply(group_regime)
    
    variables = {
        'session_bin': df['session_bin'].unique(),
        'adx_bin': df['adx_bin'].unique(),
        'vol_ratio_bin': df['vol_ratio_bin'].unique(),
        'regime_bin': df['regime_bin'].unique()
    }
    
    results = []
    
    # Evaluar combinaciones de 1 a 3 variables
    feature_names = list(variables.keys())
    
    for r in range(1, 4):
        for combo_keys in itertools.combinations(feature_names, r):
            # Para cada combinación de variables, cruzamos los valores posibles
            val_lists = [variables[k] for k in combo_keys]
            for combo_vals in itertools.product(*val_lists):
                
                # Construir mascara
                mask = pd.Series(True, index=df.index)
                for k, v in zip(combo_keys, combo_vals):
                    mask = mask & (df[k] == v)
                    
                df_sub = df[mask]
                n_trades = len(df_sub)
                
                if n_trades >= 15:
                    win_rate = (df_sub['pnl_usdt'] > 0).mean() * 100
                    mean_pnl = df_sub['pnl_usdt'].mean()
                    total_pnl = df_sub['pnl_usdt'].sum()
                    
                    # Calcular Profit Factor
                    gross_profit = df_sub[df_sub['pnl_usdt'] > 0]['pnl_usdt'].sum()
                    gross_loss = abs(df_sub[df_sub['pnl_usdt'] < 0]['pnl_usdt'].sum())
                    pf = gross_profit / gross_loss if gross_loss > 0 else (99.9 if gross_profit > 0 else 0)
                    
                    if n_trades > 0: # just record all
                        cond_str = " + ".join([f"{v}" for v in combo_vals])
                        results.append({
                            'Condiciones': cond_str,
                            'Variables': len(combo_keys),
                            'N Trades': n_trades,
                            'Win Rate %': win_rate,
                            'Profit Factor': pf,
                            'Expectancy': mean_pnl,
                            'Total PnL': total_pnl
                        })
                        
    # Ordenar resultados por Profit Factor
    results_df = pd.DataFrame(results)
    if len(results_df) > 0:
        results_df = results_df.sort_values(by='Profit Factor', ascending=False)
        
        # Generar Reporte MD
        report = "# 🚀 Fase 3: Descubrimiento Automático de Edge\n\n"
        report += f"Muestra base: {len(df)} trades.\n\n"
        report += "Combinaciones de contexto con **N >= 15**.\n\n"
        
        report += "| Condiciones | N Trades | Win Rate % | Profit Factor | Esperanza | PnL Total |\n"
        report += "| --- | --- | --- | --- | --- | --- |\n"
        
        for _, r in results_df.iterrows():
            report += f"| {r['Condiciones']} | {r['N Trades']} | {r['Win Rate %']:.1f}% | {r['Profit Factor']:.2f} | {r['Expectancy']:.4f} | {r['Total PnL']:.2f} |\n"
            
        report_path = r"C:\Users\Usuario\.gemini\antigravity-ide\brain\5b3e98b9-a148-48aa-9311-88783283d749\edge_discovery_report.md"
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
            
        print(f"¡Descubrimiento completado! Se encontraron {len(results_df)} segmentos rentables.")
        print(f"Reporte guardado en: {report_path}")
    else:
        print("No se encontraron segmentos con N >= 15 y Rentabilidad positiva.")

if __name__ == "__main__":
    main()
