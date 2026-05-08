# 🧠 PasteWise: AI-Powered Code Paste Interceptor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Gemini](https://img.shields.io/badge/AI-Google%20Gemini-blue)](https://aistudio.google.com/)

**PasteWise** is an intelligent Chrome extension that intercepts code pastes from GitHub, LeetCode, Replit, and other coding platforms. It analyzes the code with Google Gemini AI and provides explanations *before* you paste, helping you learn instead of just copying.

---

## ✨ Features

- 🎯 **Smart Interception** - Automatically detects code pastes in online editors.
- 🤖 **Gemini AI Analysis** - Get instant summaries and concept tags.
- 🔍 **Deep Dive Mode** - Line-by-line annotations for complex snippets.
- 📊 **Learning Dashboard** - Track your streaks, concept coverage, and history.
- ⚡ **Lightning Fast** - Intelligent caching ensures you never analyze the same code twice.
- 🌐 **Wide Support** - Works on GitHub, LeetCode, Replit, CodePen, and more.

---

## 🚀 Quick Start

Ready to level up your coding workflow? 

### 👉 [Read the Full Setup Guide (Detailed Steps)](SETUP_GUIDE.md)

## 🛠️ Configuration & Customization

PasteWise is highly configurable. You can adjust:
- **AI Model**: Choose between `gemini-1.5-flash` (fast & free) or `gemini-1.5-pro` (more advanced).
- **Privacy Mode**: Toggle history and statistics tracking.
- **Cache Settings**: Enable caching to save API tokens and speed up recurring snippets.

For detailed configuration options and API endpoint documentation, please refer to the [Setup Guide](SETUP_GUIDE.md).

---

## 📂 Project Structure

```bash
pastewise/
├── backend/                 # Python FastAPI backend
├── extension/               # Chrome extension source
├── icons/                   # High-res design assets
├── README.md                # Project overview
└── SETUP_GUIDE.md           # Step-by-step installation guide
```

---

## ✅ Recent Improvements

- 🚀 **Gemini 1.5 Integration**: Updated to the latest stable Google models.
- 🛠️ **Configurable Backend**: No more hardcoded keys; use environment variables.
- 📊 **Enhanced Dashboard**: Better visualization of learning concepts.
- 🐛 **Improved Error Handling**: Clearer guidance for API and connection issues.

---

## License

MIT

## Support

For issues and feature requests, check the console logs:
- Backend logs: Terminal where you ran `uvicorn`
- Frontend logs: Chrome DevTools Console (F12 → Console tab)

