# 🚀 SNABBGUIDE - 5/1 SLOB Backtester

## Steg 1: Installation (5 min)

```bash
# Navigera till projektmappen
cd /path/to/slob-backtester

# Installera alla dependencies
pip install -r requirements.txt --break-system-packages

# Alternativt, installera manuellt:
pip install yfinance pandas numpy matplotlib pytz --break-system-packages
```

## Steg 2: Kör din första backtest (2 min)

```bash
python slob_backtester.py
```

Det kommer att:
1. Ladda ner 30 dagars US100-data
2. Skanna efter 5/1 SLOB setups
3. Simulera alla trades
4. Generera performance-rapport
5. Skapa equity curve-chart

## Steg 3: Granska resultat (5 min)

Efter körningen, titta på:

### Terminal Output
```
================================================================================
PERFORMANCE REPORT
================================================================================

TOTAL TRADES: 15
WINS: 9 | LOSSES: 6
WIN RATE: 60.0%

TOTAL P&L: 12,500.00 SEK
AVERAGE WIN: 2,500.00 SEK
AVERAGE LOSS: -1,200.00 SEK
AVG RISK/REWARD: 1:2.08

INITIAL CAPITAL: 50,000.00 SEK
FINAL CAPITAL: 62,500.00 SEK
TOTAL RETURN: 25.00%
```

### Genererade filer
- `equity_curve.png` - Visa kapitalutveckling över tid
- `trades_log.csv` - Öppna i Excel för detaljerad analys

## Steg 4: Justera parametrar (10 min)

Öppna `slob_backtester.py` och hitta `class SLOBConfig`.

### Exempel 1: Testa längre period
```python
BACKTEST_DAYS = 60  # Ändra från 30 till 60
```

### Exempel 2: Striktare no-wick kriterier
```python
NO_WICK_MAX_PIPS = 5           # Ändra från 8 till 5
NO_WICK_MIN_BODY_PIPS = 20     # Ändra från 15 till 20
```

### Exempel 3: Bättre risk/reward
```python
MIN_RR = 2.0  # Ändra från 1.5 till 2.0
```

Kör om backtesten efter varje ändring!

## Steg 5: Förstå strategin (15 min)

### Visualisera ett setup
Lägg till denna kod i slutet av `main()`:

```python
# Efter: df, setups, trades = main()

# Visa första setup
if setups:
    setup = setups[0]
    print(f"\nFÖRSTA SETUP:")
    print(f"  Datum: {setup['date']}")
    print(f"  Entry: {setup['entry_price']:.2f}")
    print(f"  SL: {setup['sl_level']:.2f}")
    print(f"  TP: {setup['lse_low']:.2f}")
```

### Rita ett setup (avancerat)
```python
def plot_setup(df, setup):
    """Visualisera ett enskilt setup"""
    # Hämta data runt setup
    start_idx = max(0, setup['liq1_idx'] - 50)
    end_idx = min(len(df), setup['entry_idx'] + 100)
    
    data = df.iloc[start_idx:end_idx]
    
    plt.figure(figsize=(15, 8))
    
    # Plotta candlesticks (förenklat)
    plt.plot(data.index, data['Close'], color='black', linewidth=1)
    
    # Markera LIQ nivåer
    plt.axhline(y=setup['liq1_level'], color='red', 
                linestyle='--', label='LSE High (LIQ #1)')
    plt.axhline(y=setup['lse_low'], color='green', 
                linestyle='--', label='LSE Low (TP)')
    
    # Markera entry och SL
    entry_time = df.index[setup['entry_idx']]
    plt.scatter(entry_time, setup['entry_price'], 
                color='blue', s=100, marker='v', label='Entry')
    plt.axhline(y=setup['sl_level'], color='orange', 
                linestyle=':', label='Stop Loss')
    
    plt.legend()
    plt.title(f"Setup: {setup['date']}")
    plt.tight_layout()
    plt.savefig(f"setup_{setup['date']}.png")
    print(f"Setup chart saved: setup_{setup['date']}.png")

# Använd funktionen
plot_setup(df, setups[0])
```

## Steg 6: Vidareutveckling med Claude Code

1. Öppna Claude Code (från terminalen)
2. Klistra in innehållet från `CLAUDE_CODE_PROMPT.md`
3. Låt Claude Code förbättra koden steg för steg

Prioriterade förbättringar:
- [ ] Bättre data sources (Polygon.io, Alpha Vantage)
- [ ] Interaktiva charts (Plotly)
- [ ] ML-baserad setup-filtrering
- [ ] Parameter optimization
- [ ] Live trading alerts

## ⚠️ Vanliga problem

### Problem: "No M1 data available"
**Lösning**: Minska BACKTEST_DAYS till 7-14 dagar

### Problem: "No setups found"
**Lösning**: 
1. Kontrollera att du testar rätt tidsperiod (senaste 30 dagarna)
2. Justera parametrar (gör dem mindre strikta)
3. Testa en längre period

### Problem: "ModuleNotFoundError"
**Lösning**: 
```bash
pip install [missing_module] --break-system-packages
```

### Problem: Långsam körning
**Lösning**: Minska BACKTEST_DAYS eller optimera loops

## 📊 Nästa steg

1. **Validera strategin**: Testa på olika tidsperioder (bull market, bear market, sideways)
2. **Paper trading**: Kör strategin live med fake pengar i 1-2 månader
3. **Risk management**: Lägg till max drawdown-protection
4. **Automation**: Bygg alerts för när setups uppstår
5. **Live trading**: Bara om paper trading visar konsekvent profit!

## 💡 Tips

- **Börja konservativt**: Använd mindre position size (20-30%)
- **Förstå varje trade**: Granska varje setup manuellt först
- **Dokumentera**: Håll en trading journal
- **Backtesta mer**: Ju mer data, desto bättre
- **Machine Learning**: Kan förbättra win rate med 10-20%

## 🎯 Success Metrics

En "bra" backtest visar:
- Win rate: 55-70%
- Average R:R: >1.5:1
- Max drawdown: <20%
- Profit factor: >1.5
- Konsistens: Profits i olika marknadsförhållanden

---

**Lycka till med din trading! 🚀📈**

*Remember: Backtest → Paper Trade → Small Live → Scale Up*
