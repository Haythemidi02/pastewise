# 🚀 Getting Started with PasteWise

PasteWise is an AI-powered Chrome extension that helps you **understand code before you paste it**. It intercepts pastes on popular coding platforms, analyzes them using Google Gemini AI, and provides instant insights, concept tags, and a learning dashboard.

Follow these steps to set up PasteWise on your local machine.

---

## 📋 Prerequisites

Before you begin, ensure you have:
1. **Google Chrome** browser installed.
2. **Python 3.9+** installed (check with `python --version`).
3. A **Google Gemini API Key** and/or a **Hugging Face Access Token**.

---

## 🛠️ Step 1: Get Your AI API Keys

PasteWise supports multiple AI providers for redundancy and flexibility.

### A. Google Gemini (Recommended)
1.  Go to [Google AI Studio](https://aistudio.google.com/app/apikey).
2.  Sign in and click **"Create API key"**.
3.  Copy the key.

### B. Hugging Face (Optional)
1.  Go to [Hugging Face Settings](https://huggingface.co/settings/tokens).
2.  Create a **New Token** (Type: Read).
3.  Copy the token.

---

## 🖥️ Step 2: Set Up the Backend

The backend is a FastAPI server that handles AI requests and stores your learning stats.

1.  **Open your terminal** (Command Prompt or PowerShell on Windows).
2.  **Navigate to the project directory**:
    ```bash
    cd path/to/pastewise
    ```
3.  **Create a virtual environment** (recommended):
    ```bash
    python -m venv venv
    .\venv\Scripts\activate
    ```
4.  **Install dependencies**:
    ```bash
    pip install -r backend/requirements.txt
    ```
5.  **Configure your API Key**:
    -   Open `.env` and configure your chosen provider(s):
        ```env
        # Primary Provider: gemini or hf
        AI_PROVIDER=gemini

        # Google Gemini Config
        GEMINI_API_KEY=your_gemini_key_here
        GEMINI_MODEL=gemini-1.5-flash

        # Hugging Face Config (Optional)
        HF_API_KEY=your_hf_token_here
        HF_MODEL=Mistral-7B-Instruct-v0.3
        ```
6.  **Start the server**:
    ```bash
    uvicorn backend.main:app --reload
    ```
    *You should see a message: `✅ Gemini configured model=gemini-1.5-flash`.*

---

## 🧩 Step 3: Install the Chrome Extension

1.  Open Chrome and navigate to `chrome://extensions/`.
2.  Turn on **"Developer mode"** in the top-right corner.
3.  Click **"Load unpacked"**.
4.  Select the `extension/` folder from the PasteWise project directory.
5.  **Pin the extension**: Click the puzzle icon in Chrome and pin PasteWise for easy access.

---

## 🎯 Step 4: Test Your Setup

1.  Go to any coding site (e.g., [LeetCode](https://leetcode.com), [GitHub](https://github.com), or [Replit](https://replit.com)).
2.  Copy a snippet of code.
3.  Try to **paste it** into a code editor on that site.
4.  **Boom!** A PasteWise popup will appear with an AI-generated explanation.
5.  Click **"Paste Anyway"** or **"Deep Dive"** to explore the code further.

---

## 📊 Step 5: Explore Your Dashboard

Open the PasteWise popup from your toolbar and click **"Open Dashboard"**. You can track:
-   **Learning Streak**: How many days in a row you've used PasteWise.
-   **Concept Coverage**: The programming concepts you've encountered.
-   **History**: A log of your recent pastes and analyses.

---

## ❓ Troubleshooting

-   **"Backend not reachable"**: Ensure your terminal is still running the `uvicorn` command.
-   **"AI Model Error"**: Double-check your API keys in `backend/.env`. If using Hugging Face, ensure your token has "Read" permissions.
-   **Failover Active**: If the backend terminal shows "HF temporarily unhealthy", it has automatically switched to Gemini for 5 minutes to ensure your experience remains smooth.
-   **Extension not showing up**: Make sure you are on one of the supported sites listed in `manifest.json` (GitHub, Replit, LeetCode, etc.).

---

## 🌟 Support the Project

If you find PasteWise helpful, feel free to:
-   Give it a ⭐ on GitHub!
-   Share it with your developer friends on LinkedIn.
-   Contribute to the code!

**Happy coding!** 🚀
