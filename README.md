# 🧠 PasteWise: AI-Powered Code Paste Interceptor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Gemini](https://img.shields.io/badge/AI-Google%20Gemini-blue)](https://aistudio.google.com/)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-Hugging%20Face-orange)](https://huggingface.co/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)](https://fastapi.tiangolo.com/)

**PasteWise** is an intelligent Chrome extension that intercepts code pastes from GitHub, LeetCode, Replit, and other coding platforms. It analyzes the code with cutting-edge AI and provides explanations *before* you paste, helping you learn instead of just copying.

---

## ✨ Features

- 🎯 **Smart Interception** - Automatically detects code pastes in online editors.
- 🤖 **Dual-AI Architecture** - Choose between **Google Gemini 1.5** (Flash/Pro) and **Hugging Face** models.
- 🛡️ **Smart Failover** - Automatically switches to Gemini if the primary provider is unreachable.
- 🔍 **Deep Dive Mode** - Line-by-line annotations for complex snippets.
- 📊 **Learning Dashboard** - Track your streaks, concept coverage, and history.
- ⚡ **Lightning Fast** - Intelligent caching ensures you never analyze the same code twice.
- 🌐 **Wide Support** - Works on GitHub, LeetCode, Replit, CodePen, and more.

---

## 🚀 Quick Start

Ready to level up your coding workflow? 

### 👉 [Read the Full Setup Guide (Detailed Steps)](SETUP_GUIDE.md)

---

## 🛠️ Configuration & Customization

PasteWise is highly configurable. You can adjust:
- **AI Provider**: Toggle between Google Gemini and Hugging Face in the options.
- **AI Model**: Use `gemini-1.5-flash` for speed or specialized models from Hugging Face.
- **Privacy Mode**: Toggle history and statistics tracking.
- **Cache Settings**: Enable caching to save API tokens and speed up recurring snippets.

---

## 📂 Project Structure

```bash
pastewise/
├── backend/                 # Python FastAPI backend
│   ├── ai_client.py         # Unified AI provider interface
│   ├── gemini_client.py     # Google Gemini integration
│   ├── huggingface_client.py# Hugging Face integration
│   ├── main.py              # FastAPI application logic
│   └── database.py          # SQLite persistence
├── extension/               # Chrome extension source
├── icons/                   # High-res design assets
├── README.md                # Project overview
└── SETUP_GUIDE.md           # Step-by-step installation guide
```

---

## ✅ Recent Improvements

- 🚀 **Hugging Face Integration**: Added support for Hugging Face Inference API as a secondary/alternative provider.
- 🛡️ **Auto-Failover System**: Implemented automatic fallback to Gemini to ensure zero downtime during analysis.
- 🔐 **Security Hardening**: Scrubbed all legacy secrets from version control and implemented robust `.env` management.
- 🛠️ **Enhanced Gitignore**: Cleaned up the repository by excluding `venv/` and environment files.
- 📊 **Better Visualization**: Improved the dashboard's concept coverage tracking.

---

## License

MIT

## Support

For issues and feature requests, check the logs:
- Backend: Terminal where you ran `uvicorn`
- Frontend: Chrome DevTools Console (`F12` → Console)
