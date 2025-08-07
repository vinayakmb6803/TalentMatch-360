import streamlit as st
import google.generativeai as genai
import os
import PyPDF2 as pdf
from dotenv import load_dotenv
import json
import re

# Load environment variables from .env file
load_dotenv()

# Configure Gemini with your API Key
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Function to interact with Gemini
def get_gemini_response(prompt):
    model = genai.GenerativeModel(model_name="models/gemini-1.5-pro-latest")
    response = model.generate_content(prompt)
    return response.text

# Function to extract text from uploaded PDF
def input_pdf_text(uploaded_file):
    reader = pdf.PdfReader(uploaded_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

# Function to extract email and phone
def extract_contact_info(text):
    email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)
    email = email_match.group(0) if email_match else "Not found"

    phone_match = re.search(r'(\+91[-\s]?)?\b\d{10}\b', text)
    phone = phone_match.group(0) if phone_match else "Not found"

    return email, phone

# Prompt template with strict JSON format
input_prompt = """
You are an intelligent ATS (Applicant Tracking System) with domain knowledge across fields like Software, Data Science, Marketing, HR, etc.

Your job is to analyze a resume against a job description and return structured insights.

---
**TASKS:**

1. Identify the **domain** of the JD.
2. Extract from the resume:
   - **Total Experience** in years (based on employment history).
   - **Relevant Experience** in years (based on JD matching).
3. Calculate **JD Match Percentage**.
4. List **Matching Skills** and **Missing Keywords**.
5. Summarize **Strengths**, **Weaknesses**, and give a **Profile Summary**.

---
**STRICT OUTPUT FORMAT (JSON only):**

{{
  "Domain": "",
  "JD Match": "85%",
  "TotalExperience": "X years",
  "RelevantExperience": "Y years",
  "MatchingSkills": [],
  "MissingKeywords": [],
  "Strengths": "",
  "Weaknesses": "",
  "ProfileSummary": ""
}}

Resume:
{text}

Job Description:
{jd}
"""

# -------------------- Streamlit UI --------------------
st.set_page_config(page_title="TalentMatch 360", layout="centered")
st.title("TalentMatch 360")
st.markdown("🔍 **An intelligent ATS-powered resume analyzer for perfect job-candidate alignment!  "   
"Upload your resume and paste the Job Description to get a full ATS-style evaluation.**")

# Inputs
jd = st.text_area("📌 Paste the Job Description", height=250)
uploaded_file = st.file_uploader("📎 Upload Your Resume (PDF)", type="pdf", help="Upload your resume as a PDF file")

# Submit
if st.button("🚀 Analyze"):
    if uploaded_file is not None and jd.strip():
        with st.spinner("Analyzing resume against job description..."):
            resume_text = input_pdf_text(uploaded_file)

            # Extract contact info
            email, phone = extract_contact_info(resume_text)

            # Prepare prompt
            formatted_prompt = input_prompt.format(text=resume_text, jd=jd)

            try:
                response = get_gemini_response(formatted_prompt)

                # Clean Gemini output in case it wraps with ```json or ```
                cleaned_response = response.strip().strip("```json").strip("```").strip()

                st.subheader("📝 ATS Evaluation Result")

                try:
                    result = json.loads(cleaned_response)

                    # Contact Info
                    st.markdown(f"### 📧 Email: `{email}`")
                    st.markdown(f"### 📱 Phone: `{phone}`")

                    # Main Output
                    st.markdown(f"### 📌 Domain: `{result.get('Domain', 'N/A')}`")
                    st.markdown(f"### ✅ JD Match: `{result.get('JD Match', 'N/A')}`")
                    st.markdown(f"### 🧾 Total Experience: `{result.get('TotalExperience', 'N/A')}`")
                    st.markdown(f"### 🎯 Relevant Experience: `{result.get('RelevantExperience', 'N/A')}`")

                    st.markdown("### 💡 Matching Skills:")
                    st.write(result.get("MatchingSkills", []))

                    st.markdown("### ❌ Missing Keywords:")
                    st.write(result.get("MissingKeywords", []))

                    st.markdown("### 👍 Strengths:")
                    st.markdown(result.get("Strengths", "N/A"))

                    st.markdown("### 👎 Weaknesses:")
                    st.markdown(result.get("Weaknesses", "N/A"))

                    st.markdown("### 🧠 Profile Summary:")
                    st.markdown(result.get("ProfileSummary", "N/A"))

                except json.JSONDecodeError:
                    st.warning("⚠️ Output was not a clean JSON. Showing raw output below:")
                    st.text_area("Raw Output", response, height=400)

            except Exception as e:
                st.error(f"❌ Error: {e}")
    else:
        st.warning("⚠️ Please upload a resume and paste the job description.")

# Footer
st.markdown("---")
st.markdown("Built with 💡 Gemini 1.5 Pro | Smart ATS by Vinayak Badiger")
