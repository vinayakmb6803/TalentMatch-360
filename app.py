# app.py -- Streamlit version of TalentMatch-360
import os
import re
import json
from typing import Optional, List, Dict
from io import BytesIO

import streamlit as st
import PyPDF2 as pdf
import google.generativeai as genai

# -------------------------
# Config / Secrets
# -------------------------
st.set_page_config(page_title="TalentMatch-360", layout="wide")
st.title("📄 TalentMatch-360 — Resume Analyzer (Streamlit)")

import os
import streamlit as st
from dotenv import load_dotenv
import google.generativeai as genai

# Load from .env
load_dotenv()

# Get API key (environment variable)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

if not GOOGLE_API_KEY:
    st.error("GOOGLE_API_KEY not found. Add it to your .env file or Streamlit secrets.")
    st.stop()

# Configure Gemini API
genai.configure(api_key=GOOGLE_API_KEY)


# -------------------------
# Prompt template (escaped braces)
# -------------------------
INPUT_PROMPT = """
You are TalentMatch-360 ATS. Compare RESUME to JOB DESCRIPTION and return ONLY valid JSON matching this schema:

{{
  "Domain": "",
  "JD Match": "85%",
  "TotalExperience": "X years",
  "RelevantExperience": "Y years",
  "MatchingSkills": [],
  "MissingKeywords": [],
  "Strengths": "",
  "Weaknesses": "",
  "ProfileSummary": "",
  "PreviousCompanies": []
}}

Resume:
{text}

Job Description:
{jd}
"""

# -------------------------
# Helpers
# -------------------------
def get_gemini_response(prompt: str, model_name: str = "models/gemini-1.5-pro-latest") -> str:
    """Call Gemini and return text (safe wrapper)."""
    model = genai.GenerativeModel(model_name=model_name)
    resp = model.generate_content(prompt)
    return getattr(resp, "text", str(resp))

def extract_pdf_text_bytes(file_bytes: BytesIO) -> str:
    """Extract text from PDF bytes (works with uploaded file.read())."""
    file_bytes.seek(0)
    reader = pdf.PdfReader(file_bytes)
    text = ""
    for p in reader.pages:
        text += p.extract_text() or ""
    return text.strip()

def extract_contact_info(text: str):
    email = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)
    phone = re.search(r'(\+91[-\s]?)?\b\d{10}\b', text)
    return (email.group(0) if email else "Not found", phone.group(0) if phone else "Not found")

def extract_json_obj(text: str) -> Optional[Dict]:
    """Try to extract the first JSON object from the text response and parse it robustly."""
    # Find first {...} block (greedy)
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return None
    raw = m.group(0)
    # Try direct load
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try lightweight cleaning: remove trailing commas, fix smart quotes, etc.
        cleaned = raw
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*\]', ']', cleaned)
        cleaned = cleaned.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
        try:
            return json.loads(cleaned)
        except Exception:
            return None

# -------------------------
# Session-state initializers
# -------------------------
if "history" not in st.session_state:
    st.session_state.history = []  # list of {"role":"bot"/"user", "text": "..."}
if "last_analysis" not in st.session_state:
    st.session_state.last_analysis = {}
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""
if "multi_analyses" not in st.session_state:
    st.session_state.multi_analyses = []  # list of analyses dictionaries
if "multi_resume_texts" not in st.session_state:
    st.session_state.multi_resume_texts = []
if "best_resume" not in st.session_state:
    st.session_state.best_resume = {}

# -------------------------
# UI: Left column = inputs, Right column = results/history
# -------------------------
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader("Upload & Analyze")
    jd = st.text_area("Paste Job Description (required)", height=180)

    st.markdown("**Single resume analysis**")
    single_file = st.file_uploader("Upload a single resume (PDF)", type=["pdf"], key="single_uploader")

    if st.button("Analyze single resume"):
        if not jd or not single_file:
            st.warning("Please provide Job Description and upload a resume.")
        else:
            try:
                bytes_io = BytesIO(single_file.read())
                resume_text = extract_pdf_text_bytes(bytes_io)
            except Exception as e:
                st.error(f"Error reading PDF: {e}")
                raise

            # store raw resume text for follow-ups
            st.session_state.resume_text = resume_text

            email, phone = extract_contact_info(resume_text)
            prompt = INPUT_PROMPT.format(text=resume_text, jd=jd)
            with st.spinner("Calling gemini for analysis..."):
                try:
                    raw = get_gemini_response(prompt)
                except Exception as e:
                    st.error(f"Error calling Gemini API: {e}")
                    raw = None

            parsed = extract_json_obj(raw) if raw else None
            if not parsed:
                st.session_state.last_raw_response = raw
                st.error("Could not parse JSON from model response. Check logs/raw response.")
            else:
                st.session_state.last_analysis = parsed
                # Build user-friendly messages
                messages = [
                    "✅ Resume received — starting TalentMatch-360 analysis...",
                    f"📌 Domain: {parsed.get('Domain','N/A')} — ✅ JD Match: {parsed.get('JD Match','N/A')}",
                    f"🧾 Total Experience: {parsed.get('TotalExperience','N/A')} — 🎯 Relevant: {parsed.get('RelevantExperience','N/A')}",
                    "💡 Matching Skills: " + (", ".join(parsed.get("MatchingSkills", [])) or "None"),
                    "❌ Missing Keywords: " + (", ".join(parsed.get("MissingKeywords", [])) or "None"),
                    f"👍 Strengths: {parsed.get('Strengths','N/A')} \n👎 Weaknesses: {parsed.get('Weaknesses','N/A')}",
                    f"🏢 Previous Companies: " + (", ".join(parsed.get("PreviousCompanies", [])) or "None"),
                    f"🧠 Profile Summary: {parsed.get('ProfileSummary','N/A')}",
                    f"📧 Email: {email} | 📱 Phone: {phone}"
                ]
                for m in messages:
                    st.session_state.history.append({"role": "bot", "text": m})
                st.success("Analysis complete. See results on the right.")

    st.markdown("---")
    st.markdown("**Multi-resume analysis (max 5)**")
    multi_files = st.file_uploader("Upload multiple resumes (PDFs)", type=["pdf"], accept_multiple_files=True, key="multi_uploader")
    if st.button("Analyze multiple resumes"):
        if not jd or not multi_files:
            st.warning("Please provide Job Description and upload resumes.")
        elif len(multi_files) > 5:
            st.warning("You can upload a maximum of 5 resumes at a time.")
        else:
            all_analyses = []
            all_texts = []
            failed = False
            with st.spinner("Analyzing resumes (one by one)..."):
                for f in multi_files:
                    try:
                        b = BytesIO(f.read())
                        resume_text = extract_pdf_text_bytes(b)
                    except Exception as e:
                        st.error(f"Error reading {f.name}: {e}")
                        failed = True
                        break

                    prompt = INPUT_PROMPT.format(text=resume_text, jd=jd)
                    try:
                        raw = get_gemini_response(prompt)
                    except Exception as e:
                        st.error(f"Error calling Gemini for {f.name}: {e}")
                        failed = True
                        break

                    parsed = extract_json_obj(raw)
                    if not parsed:
                        st.error(f"Could not parse JSON from {f.name}. Stored raw in session.")
                        st.session_state.last_raw_response = raw
                        failed = True
                        break

                    parsed["Filename"] = f.name
                    all_analyses.append(parsed)
                    all_texts.append(resume_text)

            if not failed:
                st.session_state.multi_analyses = all_analyses
                st.session_state.multi_resume_texts = all_texts

                # Ask Gemini to pick the best resume
                compare_prompt = (
                    "You are TalentMatch-360 ATS. Here is the job description:\n"
                    + jd
                    + "\n\nHere are the analyses of multiple resumes:\n"
                    + json.dumps(all_analyses)
                    + "\n\nFrom these, pick the SINGLE best resume (based ONLY on fit to JD, skills, and experience). "
                      "Return JSON with fields: { \"BestResumeFilename\": \"\", \"Reason\": \"\" }"
                )
                with st.spinner("Asking Gemini to select best resume..."):
                    try:
                        ranking_raw = get_gemini_response(compare_prompt)
                        ranking = extract_json_obj(ranking_raw)
                    except Exception as e:
                        st.error(f"Error ranking resumes: {e}")
                        ranking = None

                if ranking:
                    st.session_state.best_resume = ranking
                    st.session_state.history.append({"role": "bot", "text": f"✅ Multi-resume analysis done. Best resume: {ranking.get('BestResumeFilename','N/A')}"})
                    st.success("Multi-resume analysis complete. See results on the right.")
                else:
                    st.error("Could not parse ranking from model.")

    st.markdown("---")
    st.subheader("Follow-up question")
    user_q = st.text_input("Ask a follow-up question about the last analyzed resume(s)")
    if st.button("Ask"):
        if not user_q:
            st.warning("Type a question first.")
        else:
            st.session_state.history.append({"role": "user", "text": user_q})
            # Prepare context: prefer multi_analyses if present, otherwise last_analysis
            context_analysis = st.session_state.multi_analyses if st.session_state.multi_analyses else st.session_state.last_analysis
            context_resume = "\n\n".join(st.session_state.multi_resume_texts) if st.session_state.multi_resume_texts else st.session_state.resume_text

            followup_prompt = (
                "You are TalentMatch-360 assistant. Use this resume text(s) and structured analysis as context:\n"
                + json.dumps({"resume": context_resume, "analysis": context_analysis})
                + "\n\nUser question: " + user_q + "\nAnswer concisely."
            )
            with st.spinner("Querying Gemini..."):
                try:
                    reply = get_gemini_response(followup_prompt)
                except Exception as e:
                    reply = f"Error calling Gemini: {e}"

            st.session_state.history.append({"role": "bot", "text": reply})
            st.success("Answer received. See chat history on the right.")

with col2:
    st.subheader("Results & Chat History")
    # Display last single analysis summary
    if st.session_state.last_analysis:
        st.markdown("### Last single-resume analysis (structured)")
        st.json(st.session_state.last_analysis)

    # Display multi analyses
    if st.session_state.multi_analyses:
        st.markdown("### Multi-resume analyses")
        # Show each analysis in an expander
        for a in st.session_state.multi_analyses:
            filename = a.get("Filename", "Unknown")
            with st.expander(filename):
                st.json(a)

    # Show best resume if present
    if st.session_state.best_resume:
        st.markdown("### Best resume (from multi-upload)")
        st.json(st.session_state.best_resume)

    # Chat / history viewer
    st.markdown("### Chat / Activity log")
    if st.session_state.history:
        for item in reversed(st.session_state.history[-50:]):  # show latest 50
            role = item.get("role", "bot")
            text = item.get("text", "")
            if role == "user":
                st.markdown(f"**You:** {text}")
            else:
                st.markdown(f"**Bot:** {text}")
    else:
        st.info("No activity yet. Upload a resume and run analysis.")

    st.markdown("---")
    st.markdown("**Developer tools**")
    if st.button("Clear session state"):
        for k in list(st.session_state.keys()):
            del st.session_state[k]
        st.experimental_rerun()
