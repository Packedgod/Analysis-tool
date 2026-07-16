# Vibe Analysis

Vibe Analysis is a local, evidence-first financial research application. It is
derived from the research, simulation, and shadow-agent parts of Vibe-Trading,
but has no broker connectivity, account access, mandate flow, or order tools.

## What it does

- Finds annual reports, quarterly results, presentations, and filings on a
  company's verified official website.
- Extracts and compares income statement, balance-sheet, cash-flow, and
  per-share data across current and prior reporting years.
- Collects dated qualitative evidence from Reuters, Mint, Economic Times,
  Times of India, Moneycontrol, regulators, exchanges, rating agencies, Yahoo
  Finance/yfinance, and Google Finance.
- Analyzes only the factors supplied in the research brief and clearly
  separates facts, calculations, interpretations, risks, and missing data.
- Accepts strategy documents in PDF, Word, text, spreadsheet, JSON, Markdown,
  or Pine formats and converts them into transparent historical simulations.
- Retains shadow strategy extraction, shadow backtests, research teams,
  factor analysis, correlation, reports, and reproducible run artifacts.

## Start on this Windows device

Open File Explorer and double-click `Start Vibe Analysis.cmd`. The application
opens at <http://127.0.0.1:8900> and automatically restarts its local service if
it stops. Launching from File Explorer is important because restricted terminal
processes may not have outbound access to report, news, market-data, or model
providers.

## Fresh installation

Requirements: Python 3.11+, Node.js 20+, and an OpenAI-compatible API endpoint.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
npm --prefix frontend ci
npm --prefix frontend run build
```

Copy `agent/.env.example` to `agent/.env`, then configure the LLM provider. Do
not commit `.env`; it may contain credentials. Start the server with:

```powershell
.\.venv\Scripts\python.exe -m cli._legacy serve --host 127.0.0.1 --port 8900
```

## Research rules

- Issuer documents and regulator/exchange filings outrank third-party summaries.
- News evidence must retain publisher, date, title, and URL.
- Missing or inaccessible evidence is disclosed rather than fabricated.
- Uploaded files are treated as untrusted research material and are never
  executed.
- Backtests and shadow results are simulations, not investment advice.
- Brokerage is permanently disabled in this product, regardless of environment
  variables or copied Vibe-Trading configuration.

## License and attribution

This fork retains the upstream MIT license and notices from
[HKUDS/Vibe-Trading](https://github.com/HKUDS/Vibe-Trading).

