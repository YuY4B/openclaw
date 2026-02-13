# 🌦️ Polymarket Weather Bot - Operation First Dollar
Target: $1.00 Profit (First Milestone) -> $100 -> $1000

## 👥 Core Team
- **CEO (hakua)**: Vision & Funding ($100 Budget)
- **Antigravity (CTO)**: Implementation & Deployment
- **Strategist**: Risk Management & Market Analysis

## 🛠️ The Plan (Phase 1: Proof of Concept)

### 1. Data Source (The "Alpha")
We need faster/better weather data than the market.
- **NOAA API**: Official US gov weather data (Primary source). Free.
- **OpenWeatherMap**: Backup source.
- **Target Location**: New York (Highest volume market usually).

### 2. Market Interface
We need to trade programmatically.
- **Polymarket (via Polygon)**:
  - Wallet: Needs $USDC.e & $POL (Matic) for gas.
  - API: Using `clob-client` or direct contract interaction?
  - **Simmer SDK**: Check if this simplifies the process. If not, build custom lightweight bot.

### 3. Strategy (Arbitrage Logic)
- **Condition**: If NOAA forecast says "Temp > 70F" with 90% confidence, and Market price for "Temp > 70F" is trading at 40¢ (40% probability), **BUY "YES"**.
- **Exit**: Sell when price corrects to 80¢+ or hold until resolution (binary payout $1).
- **Risk per trade**: Minimized (e.g., $5) to test logic.

## ✅ TODO List
- [ ] **Infrastructure**: Get OpenClaw stable & connected to Discord (Done).
- [ ] **Research**: Verify "Simmer SDK" availability and docs.
- [ ] **Wallet**: Create a fresh EVM wallet for the bot.
- [ ] **Funding**: Deposit small amount ($10-$20) for testing.
- [ ] **Code**: Implement `weather-monitor.ts` (Fetch NOAA data).
- [ ] **Code**: Implement `market-scanner.ts` (Fetch Polymarket odds).
- [ ] **Integration**: Connect both and paper-trade (simulate buys) in Discord logs.
- [ ] **LIVE**: Execute first real trade ($1).

## 📝 Notes & Ideas
- "Simmer SDK" might be a wrapper around Polymarket's CLOB (Central Limit Order Book) API.
- We need to handle Polygon network gas fees (very low, but non-zero).
- **Speed is key**: Weather data updates periodically. We need to fetch it the second it drops.
