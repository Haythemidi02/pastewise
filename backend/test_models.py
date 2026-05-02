import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

models = genai.list_models()
for m in models:
    if "generateContent" in m.supported_generation_methods:
        print(m.name)
