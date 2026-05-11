# PasteWise: AI-Powered Code Paste Interceptor

[![Gemini](https://img.shields.io/badge/AI-Google%20Gemini-blue)](https://aistudio.google.com/)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97-Hugging%20Face-orange)](https://huggingface.co/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688)](https://fastapi.tiangolo.com/)
[![Chrome Extension](https://img.shields.io/badge/Extension-Manifest%20V3-blueviolet)](https://developer.chrome.com/docs/extensions/mv3/intro/)

**PasteWise** is a next-generation Chrome extension designed to transform the way developers interact with copied code. Instead of mindless pasting, PasteWise intercepts code transfers on major platforms, analyzes them with state-of-the-art AI, and provides instant, meaningful insights to help you learn and verify *before* the code hits your editor.

---

##  Features that Empower Developers

*    **Intelligent Interception** - Seamlessly detects code pastes in online editors across 15+ supported platforms.
*    **Dual-AI Intelligence** - Leverage the power of **Google Gemini 2.0** (Flash/Pro) or **Hugging Face** models (Mistral, Llama, etc.).
*    **Resilient Architecture** - Built-in **Auto-Failover** ensures that if one AI provider is down, the other takes over instantly.
*    **Deep Dive Mode** - Go beyond summaries with line-by-line interactive annotations for complex logic.
*    **Learning Dashboard** - Track your growth with detailed statistics, concept coverage maps, and daily streaks.
*    **Lightning Performance** - Advanced SHA-256 caching ensures instant responses for recurring code snippets.
*    **Privacy First** - Local history and stats tracking that you control.

---

## 🏗️ How It Works

1.  **Intercept**: The extension monitors clipboard events on sites like LeetCode or GitHub.
2.  **Analyze**: Code is sent to the local FastAPI backend.
3.  **Process**: The backend identifies the language, tags concepts, and queries the configured AI provider.
4.  **Insight**: A non-intrusive popup appears, giving you the "What", "How", and "Why" of the code.
5.  **Growth**: Your interaction is recorded (privately) to build your learning profile.

---

## 🛠️ Tech Stack

### Backend (Python/FastAPI)
- **FastAPI**: High-performance web framework for the API layer.
- **SQLAlchemy/SQLite**: Robust data persistence for stats and history.
- **Google Generative AI**: Integration with the Gemini 1.5 family.
- **Hugging Face API**: Support for open-source model inference.
- **Pygments**: Local code analysis and language detection.

### Frontend (Chrome Extension)
- **Manifest V3**: Modern extension architecture for security and performance.
- **Vanilla JS/CSS**: Sleek, dependency-free UI with glassmorphism design.
- **Chart.js**: (Optional) For future data visualizations in the dashboard.

---

##  Quick Start

Ready to stop pasting and start learning?

1.  **Setup the Backend**:
    -   `pip install -r backend/requirements.txt`
    -   Configure your `.env` with your Gemini/HF keys.
    -   Run `uvicorn backend.main:app --reload`
2.  **Install the Extension**:
    -   Load the `extension/` folder via `chrome://extensions/` in Developer Mode.

###  [Read the Full Setup Guide (Step-by-Step)](SETUP_GUIDE.md)

---

##  Supported Platforms

PasteWise is optimized for:
-  **GitHub**
-  **LeetCode**
-  **Replit**
-  **CodePen**
-  **CodeSandbox**
-  **StackBlitz**
-  **Codeforces & AtCoder**
-  **Kaggle & Google Colab**
- ...and many more!

---

##  Recent Improvements

-  **Unified AI Interface**: Seamlessly switch between Gemini and Hugging Face.
-  **Concept Heatmaps**: Visualized learning progress in the dashboard.
-  **Optimized Caching**: Reduced latency for common boilerplate code.
-  **Health Probes**: Real-time monitoring of AI provider availability.

--

<p align="center">
  Built with ❤️ for the developer community.
</p>
