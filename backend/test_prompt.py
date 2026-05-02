import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
model = genai.GenerativeModel('gemini-2.5-flash', generation_config={'max_output_tokens': 2048, 'temperature': 0.2, 'top_p': 0.8})
prompt='''You are a concise code tutor helping a developer understand code they copied.

Analyse the unknown code below and respond with ONLY a valid JSON object — no markdown fences, no extra text before or after.

JSON schema (all fields required):
{
  "summary":        "<3 sentences max — plain English, no jargon>",
  "tags":           ["<concept>", ...],   // 3–6 tags from the list below
  "coverage_score": <integer 0–100>        // how well this covers real concepts
}

Code:
// just a test comment
'''
response = model.generate_content(prompt)
print('REASON:', response.candidates[0].finish_reason)
print('TEXT:', repr(response.text))
