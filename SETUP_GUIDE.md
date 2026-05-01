# PasteWise Setup Guide

## ⚠️ CRITICAL: Model Configuration Issues Found & Fixed

### Issues That Were Causing Model Errors:

1. **❌ Invalid API Key** - The old hardcoded key was invalid/expired
2. **❌ Wrong Model Name** - `gemini-2.0-flash` doesn't exist  
3. **❌ Missing .env File** - Application wasn't reading your configuration

### ✅ What Was Fixed:

- Removed hardcoded API key from `backend/gemini_client.py`
- Changed model to **`gemini-1.5-flash`** (valid, free-tier model)
- Updated `backend/.env.example` with proper placeholder

---

## 🔧 How to Fix & Set Up

### Step 1: Get a Free Gemini API Key

1. Go to: **https://aistudio.google.com/app/apikey**
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the generated key

### Step 2: Create `.env` File

In the **`backend/`** directory, create a new file named **`.env`** with:

```env
GEMINI_API_KEY=paste_your_key_here
GEMINI_MODEL=gemini-1.5-flash
GEMINI_MAX_TOKENS=512
```

**Replace `paste_your_key_here` with your actual API key from Step 1**

### Step 3: Restart the Backend

```bash
# Stop the current backend (Ctrl+C)
# Then restart:
cd backend
uvicorn main:app --reload
```

### Step 4: Test

1. Open the extension options page
2. You should see the backend is connected
3. Try pasting code on a coding site - it should now work!

---

## 📋 Verification Checklist

- [ ] `.env` file created in `backend/` directory
- [ ] `GEMINI_API_KEY` is set to a valid key (not placeholder text)
- [ ] `GEMINI_MODEL` is `gemini-1.5-flash` or `gemini-1.5-pro`
- [ ] Backend restarted after creating `.env`
- [ ] Extension can detect pastes without errors
- [ ] Model returns summaries and tags

---

## 🐛 If It Still Doesn't Work:

1. **Check backend logs** - They should show: `Gemini configured model=gemini-1.5-flash`
2. **Verify API key** - Test it at https://aistudio.google.com/app/apikey
3. **Check .env location** - File must be in `backend/` directory exactly
4. **Check permissions** - API key might have quota limits or access restrictions
5. **Clear cache** - Extension cache might have old errors

---

## 📚 Files Changed:

- `backend/gemini_client.py` - Removed hardcoded API key, updated model name
- `backend/.env.example` - Updated with correct model and placeholder key
- `SETUP_GUIDE.md` - This file (new)

