# IndustrialIQ — Predictive Maintenance Monitor

Industry 4.0 machine health monitoring system combining AI computer vision and sensor threshold analysis.

## Project Structure
```
industrialiq/
├── app.py                  Flask backend
├── requirements.txt        Python deps
├── .env.example            API key template
├── .gitignore
├── uploads/                Temp image storage (auto-created)
├── templates/
│   └── index.html          Main HTML template
└── static/
    ├── css/style.css       Dashboard stylesheet
    └── js/main.js          Frontend logic
```

## Quick Start

```bash
# 1. Create virtualenv
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set API key
cp .env.example .env
# Edit .env and add: ANTHROPIC_API_KEY=sk-ant-...

# 4. Run
python app.py
# Open http://localhost:5000
```

## Sensor Thresholds
| Sensor      | Safe        | Warning      | Critical  |
|-------------|-------------|--------------|-----------|
| Temperature | 0–80 °C     | 80–110 °C    | >110 °C   |
| Vibration   | 0–4.5 mm/s  | 4.5–11.2     | >11.2     |
| RPM         | 1200–1800   | 800–1200     | <800      |
| Noise       | 0–85 dB     | 85–110       | >110      |
| Pressure    | 3–8 bar     | 8–12         | >12       |
| Current     | 0–15 A      | 15–25        | >25       |

## API
- POST /api/analyze — multipart form with sensor values + optional image
- GET  /api/health  — system status check
