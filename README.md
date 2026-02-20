<p align="center">
  <img src="https://raw.githubusercontent.com/Adityasharma0101911/Zenith-Frontend/main/public/zenith-logo.png" alt="Zenith Logo" width="120" />
</p>

<h1 align="center">Zenith — Backend</h1>

<p align="center">
  <strong>Flask API server powering the Zenith AI wellness platform</strong><br/>
  Authentication · AI assistants · Financial transactions · Health tracking
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776ab?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Flask-3.x-000?logo=flask" alt="Flask" />
  <img src="https://img.shields.io/badge/SQLite-WAL_Mode-003b57?logo=sqlite" alt="SQLite" />
  <img src="https://img.shields.io/badge/AI-Backboard.io-ff6b35" alt="Backboard.io" />
</p>

---

## Overview

This is the **Flask backend** for [Zenith](https://github.com/Adityasharma0101911/Zenith-Frontend) — a student wellness platform with AI-powered financial, academic, and health guidance. The server handles user authentication, survey persistence, AI brief generation, real-time chat, purchase evaluation, and stress tracking.

### Key Features

| Feature | Description |
|---|---|
| **Token-Based Auth** | Secure registration & login with hashed passwords and bearer tokens |
| **Three AI Sections** | Guardian (finance), Scholar (academics), Vitals (health) — each with dedicated AI assistants |
| **AI Brief Generation** | Personalized welcome briefs with numbered insights and example questions |
| **AI Chat** | Conversational AI powered by Backboard.io with per-user thread persistence |
| **Purchase Evaluation** | AI-driven spending decisions — approves, denies, or warns based on context |
| **Survey System** | Stores personalized survey data that shapes all AI interactions |
| **Stress Tracking** | Daily pulse logs with calendar heatmap data |
| **PII Protection** | Automatic redaction of names, locations, and emails before sending to AI |
| **Thread Pool** | Non-blocking AI calls via `ThreadPoolExecutor` to keep the server responsive |

---

## Tech Stack

- **Framework** — Flask with Flask-CORS
- **Database** — SQLite with WAL mode (zero-config, file-based)
- **AI Provider** — [Backboard.io](https://backboard.io) (assistant + thread API)
- **Auth** — Werkzeug password hashing + secure token generation
- **Environment** — python-dotenv for configuration

---

## Project Structure

```
zenith-backend/
├── app.py                  # Main Flask app — all API endpoints  
├── database.py             # SQLite schema, migrations, connection pooling
├── ai_service.py           # Legacy AI advice helper
├── backboard_service.py    # Backboard.io API (assistants, threads, chat)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create this)
└── mock_data/
    └── user_context.json   # Sample user context for testing
```

---

## API Endpoints

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/register` | Create account (username, password) |
| `POST` | `/api/login` | Login and receive auth token |

### User & Survey

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/user` | Get current user profile |
| `POST` | `/api/survey` | Save personalization survey data |
| `GET` | `/api/survey` | Retrieve saved survey data |

### AI

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/ai/brief?section=` | Generate AI welcome brief for a section |
| `POST` | `/api/ai/chat` | Send a message to the AI (section + message) |
| `POST` | `/api/ai/reset` | Reset AI thread for a section |

### Financial

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/balance` | Get current balance |
| `POST` | `/api/balance` | Set balance |
| `POST` | `/api/transaction/attempt` | Submit a purchase for AI evaluation |
| `POST` | `/api/purchase/execute` | Execute an approved purchase |
| `GET` | `/api/transactions` | Get transaction history |

### Health

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/pulse` | Log daily stress level (1–5) |
| `GET` | `/api/pulse/history` | Get stress history for calendar heatmap |

---

## Getting Started

### Prerequisites

- **Python 3.10+**
- A **Backboard.io** API key ([sign up here](https://backboard.io))

### Installation

```bash
# Clone the repository
git clone https://github.com/Adityasharma0101911/Zenith-Backend.git
cd Zenith-Backend

# Create virtual environment (recommended)
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Create a `.env` file in the project root:

```env
BACKBOARD_API_KEY=your_backboard_api_key_here
BACKBOARD_BASE_URL=https://app.backboard.io/api
```

| Variable | Required | Description |
|---|---|---|
| `BACKBOARD_API_KEY` | Yes | Your Backboard.io API key |
| `BACKBOARD_BASE_URL` | No | Backboard API base URL (defaults to `https://app.backboard.io/api`) |

### Run the Server

```bash
python app.py
```

The server starts on **http://localhost:5000** by default.

---

## Database

Zenith uses **SQLite** with WAL (Write-Ahead Logging) mode for concurrent read/write access. The database file (`zenith.db`) is created automatically on first run.

### Tables

| Table | Purpose |
|---|---|
| `users` | Accounts, hashed passwords, tokens, survey data, balance |
| `transactions` | Purchase ledger with AI evaluation status |
| `ai_assistants` | Cached Backboard.io assistant IDs per section |
| `user_threads` | Per-user AI thread IDs for conversation persistence |
| `ai_briefs` | Cached AI welcome briefs to reduce API calls |
| `pulse_logs` | Daily stress level entries for heatmap |

The schema auto-migrates — new columns are added safely via `ALTER TABLE` on startup.

---

## Security

- Passwords are hashed with Werkzeug's `generate_password_hash` (PBKDF2)
- All authenticated endpoints require a `Bearer` token in the `Authorization` header
- PII (names, locations, emails) is automatically redacted before sending text to the AI
- Transaction amounts are validated server-side (must be positive numbers)
- Input validation on all endpoints prevents missing-field crashes

---

## Frontend

The frontend lives in a separate repository:  
**[Zenith Frontend](https://github.com/Adityasharma0101911/Zenith-Frontend)** — Next.js 14 + TypeScript + Tailwind CSS + GSAP

---

## License

This project is developed for educational purposes as part of the Zenith student wellness initiative.
