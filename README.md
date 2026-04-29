# PredictMotion

**Monte Carlo simulation engine for the Spanish Segunda División (Liga Hypermotion).**  
Fetches live standings from the ESPN API and runs 40,000 stochastic simulations to estimate each team's probability of promotion, playoff qualification, or relegation.

---

## Features

- **Live data** — standings pulled directly from the ESPN Sports API at every update cycle
- **40,000 Monte Carlo iterations** per refresh, modelling every remaining matchday with historical home/draw/away probabilities
- **Deterministic hourly results** — seeded PRNG ensures every user in the same hour sees identical simulation output
- **Synchronized auto-refresh** — data updates on the hour mark, not relative to when you loaded the page
- **Three outcome zones** tracked per team: direct promotion (top 2), promotion playoff (top 6), relegation (bottom 4)
- **Zero dependencies** — pure vanilla JS, HTML5 and CSS3; no frameworks, no build step
- **Dark UI** with color-coded zone rows, animated probability bars, and team logos with fallback avatars

---

## Preview

| Zone | Positions | Color |
|---|---|---|
| Direct promotion | 1st – 2nd | Green |
| Promotion playoff | 3rd – 6th | Blue |
| Relegation | 19th – 22nd | Red |

---

## How It Works

1. On load (and every hour on the hour), the app fetches current standings from the ESPN API
2. Each simulation run draws a fresh random schedule for unknown matchdays and samples match outcomes using weighted probabilities:
   - Home win: 42%
   - Draw: 27%
   - Away win: 31%
3. After 40,000 simulated seasons, final position frequencies are converted into percentages and rendered as probability bars
4. The PRNG is seeded with the current UTC hour, so all concurrent visitors run the same sequence of random numbers and see identical results

---

## Run Locally

No installation required beyond Python 3.

```bash
python start.py
```

This starts a local HTTP server on port `8765` and opens the app in your default browser automatically.

---

## Project Structure

```
predictmotion/
├── index.html          # Single-page app — UI, simulation engine, ESPN API client
├── hypermotion_sim.py  # Standalone Python simulator (local use / validation)
├── start.py            # Local development server
├── privacy.html        # Privacy policy (GDPR / AdSense compliant)
├── ads.txt             # AdSense inventory declaration
└── logos/              # Team badge fallbacks (24 clubs)
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Data | ESPN Sports API (public, read-only) |
| Simulation | Monte Carlo — mulberry32 PRNG, seeded per UTC hour |
| Server (local) | Python 3 `http.server` |
| Fonts | Inter via Google Fonts |

---

## Data Source

Standings are fetched from the public ESPN API endpoint:

```
https://site.api.espn.com/apis/v2/sports/soccer/esp.2/standings
```

No API key required.

---

## License

MIT
