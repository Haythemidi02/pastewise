# PasteWise - AI-Powered Code Paste Interceptor

An intelligent Chrome extension that intercepts code pastes from GitHub, LeetCode, Replit, and other coding platforms. It analyzes the code with Google Gemini AI and provides explanations before you paste.

## Features

- 🎯 **Automatic Code Interception** - Detects when you're about to paste code into a code editor
- 🤖 **AI-Powered Analysis** - Uses Google Gemini to explain code snippets
- 📋 **Quick Explain** - 3-sentence summary with concept tags
- 🔍 **Deep Dive** - Line-by-line annotation of the code
- 📊 **Statistics Dashboard** - Track your learning with streak counters and concept coverage
- ⚡ **Smart Caching** - Identical code snippets are never analyzed twice
- 🌐 **Cross-Platform** - Works on CodePen, Replit, LeetCode, CodeSandbox, and more

## ⚠️ Important: Model Configuration Issues Fixed

We found and fixed critical issues that were preventing the model from working:

- ❌ **Old Issue**: Invalid hardcoded API key
- ❌ **Old Issue**: Non-existent model name (`gemini-2.0-flash`)
- ✅ **Fixed**: Removed hardcoded API key
- ✅ **Fixed**: Updated to valid model (`gemini-1.5-flash`)
- ✅ **Fixed**: Better error messages

## Quick Start

### Prerequisites

- Python 3.9+ with pip
- Chrome browser
- Google account for free Gemini API key

### 1. Get Your Gemini API Key

1. Go to: https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the generated key

### 2. Set Up Backend

```bash
cd backend

# Create .env file with your API key:
# On Windows:
echo GEMINI_API_KEY=your_key_here > .env
echo GEMINI_MODEL=gemini-1.5-flash >> .env
echo GEMINI_MAX_TOKENS=512 >> .env

# Or manually create backend/.env with:
# GEMINI_API_KEY=your_api_key_here
# GEMINI_MODEL=gemini-1.5-flash
# GEMINI_MAX_TOKENS=512

# Install dependencies
pip install -r requirements.txt

# Start the backend server
uvicorn main:app --reload
```

You should see:
```
✅ Gemini configured  model=gemini-1.5-flash  max_tokens=512
```

### 3. Load Extension

1. Open Chrome DevTools (Right-click → Inspect or press F12)
2. Go to **chrome://extensions/**
3. Enable **Developer mode** (top-right toggle)
4. Click **Load unpacked**
5. Select the `extension/` folder
6. The PasteWise icon should appear in your toolbar

### 4. Test It

1. Go to any coding platform (CodePen, Replit, LeetCode, etc.)
2. Copy some code
3. Try to paste it into a code editor
4. PasteWise popup should appear with an explanation!

## File Structure

```
pastewise/
├── backend/                 # Python FastAPI backend
│   ├── main.py             # FastAPI app and routes
│   ├── gemini_client.py    # Google Gemini API integration ✅ FIXED
│   ├── models.py           # Pydantic request/response schemas
│   ├── language_detector.py # Auto-detect programming language
│   ├── concept_tagger.py   # Extract concept tags from code
│   ├── cache.py            # SQLite caching layer
│   ├── database.py         # Database initialization
│   ├── stats.py            # Learning statistics tracking
│   ├── requirements.txt    # Python dependencies
│   ├── .env.example        # ✅ FIXED: Updated with valid model
│   └── .env               # ✅ CREATE THIS: Your configuration
│
├── extension/              # Chrome extension
│   ├── manifest.json      # Extension metadata
│   ├── popup.html         # Toolbar popup UI
│   ├── popup.js           # Popup logic
│   ├── content.js         # Paste interceptor script
│   ├── service_worker.js  # Background service worker
│   ├── options.html       # Settings page
│   ├── options.js         # Settings logic
│   ├── dashboard.html     # Statistics dashboard
│   ├── dashboard.js       # Dashboard logic
│   ├── content.css        # Popup styles
│   └── icons/             # Extension icons
│
├── README.md              # This file
└── SETUP_GUIDE.md         # Detailed setup instructions ✅ NEW
```

## Configuration

### Backend Configuration

Create or edit `backend/.env`:

```env
# Required: Your Gemini API key from https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIza...your_key_here

# Optional: Model name (default: gemini-1.5-flash)
GEMINI_MODEL=gemini-1.5-flash

# Optional: Max response tokens (default: 512)
GEMINI_MAX_TOKENS=512

# Optional: SQLite database location (default: backend/pastewise.db)
# DATABASE_URL=sqlite:////path/to/pastewise.db
```

### Available Models

- `gemini-1.5-flash` (recommended - free tier, fast)
- `gemini-1.5-pro` (more capable, paid tier)

## API Endpoints

### POST /explain
Explain a code snippet

**Request:**
```json
{
  "code": "const add = (a, b) => a + b;",
  "mode": "quick"
}
```

**Response (quick mode):**
```json
{
  "summary": "An arrow function that adds two numbers.",
  "tags": ["arrow function", "addition"],
  "coverage_score": 45,
  "language": "javascript"
}
```

### POST /record-paste
Record when user pastes code

**Request:**
```json
{
  "read_first": true,
  "snippet": "const add = (a, b) =>...",
  "tags": ["arrow function"]
}
```

### GET /stats
Get learning statistics

**Response:**
```json
{
  "total_intercepts": 42,
  "read_before_paste": 28,
  "total_concepts": 156,
  "streak_days": 5,
  "today_intercepts": 3,
  "today_read": 2,
  "top_concepts": [
    {"tag": "recursion", "count": 12},
    {"tag": "async/await", "count": 9}
  ],
  "active_days": ["2024-01-15", "2024-01-16"],
  "daily_counts": [...]
}
```

### GET /health
Health check

## Troubleshooting

### "AI model is unavailable" Error

1. **Check API Key**
   - Verify `GEMINI_API_KEY` in `backend/.env`
   - Get a new key: https://aistudio.google.com/app/apikey

2. **Check Model Name**
   - Ensure `GEMINI_MODEL=gemini-1.5-flash` in `.env`
   - Don't use `gemini-2.0-flash` (doesn't exist)

3. **Check Backend is Running**
   - Look for `✅ Gemini configured` in terminal
   - If you see `⚠️ GEMINI_API_KEY is not set`, create `.env` file

4. **Check Quota**
   - Free Gemini API has rate limits
   - Wait a few seconds and try again

### "Could not reach backend" Error

1. Make sure backend is running on `http://localhost:8000`
2. Check for CORS errors in browser console
3. Restart the backend server

### Extension not detecting pastes

1. Reload the extension (chrome://extensions → refresh)
2. Hard refresh the webpage (Ctrl+Shift+R or Cmd+Shift+R)
3. Try on a different coding platform (CodePen, Replit, etc.)

## Development

### Backend Development

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Extension Development

1. Edit files in `extension/`
2. Go to chrome://extensions
3. Click the refresh icon for PasteWise
4. Test on a coding site

### Database Reset

```bash
rm backend/pastewise.db
# Restart backend - it will recreate the database
```

## Issues Fixed

✅ **Model Configuration (CRITICAL)**
- Removed invalid hardcoded API key
- Updated to valid model name (`gemini-1.5-flash`)
- Improved error messages in fallback responses
- Better logging at startup

See [SETUP_GUIDE.md](SETUP_GUIDE.md) for detailed setup instructions.

## License

MIT

## Support

For issues and feature requests, check the console logs:
- Backend logs: Terminal where you ran `uvicorn`
- Frontend logs: Chrome DevTools Console (F12 → Console tab)

