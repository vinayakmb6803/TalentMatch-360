from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import os, re, json
import PyPDF2 as pdf
import google.generativeai as genai

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12 MB uploads

# Configure Gemini client
GEN_KEY = os.getenv("GOOGLE_API_KEY")
if not GEN_KEY:
    raise RuntimeError("GOOGLE_API_KEY not found in environment (.env)")
genai.configure(api_key=GEN_KEY)

# Prompt template (with escaped curly braces + PreviousCompanies field)
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

def get_gemini_response(prompt: str) -> str:
    model = genai.GenerativeModel(model_name="models/gemini-1.5-pro-latest")
    resp = model.generate_content(prompt)
    return getattr(resp, "text", str(resp))

def extract_pdf_text(file_storage) -> str:
    file_storage.stream.seek(0)
    reader = pdf.PdfReader(file_storage.stream)
    text = ""
    for p in reader.pages:
        text += p.extract_text() or ""
    return text.strip()

def extract_contact_info(text: str):
    email = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b', text)
    phone = re.search(r'(\+91[-\s]?)?\b\d{10}\b', text)
    return (email.group(0) if email else "Not found", phone.group(0) if phone else "Not found")

def extract_json_obj(text: str):
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return None
    raw = m.group(0)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r',\s*}', '}', raw)
        cleaned = re.sub(r',\s*\]', ']', cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None

@app.route("/")
def index():
    session.setdefault("history", [])
    return render_template("chat.html")

@app.route("/upload", methods=["POST"])
def upload():
    jd = request.form.get("jd", "").strip()
    file = request.files.get("resume")
    if not jd or not file:
        return jsonify({"error": "Please provide both Job Description and a resume (PDF)."}), 400

    try:
        resume_text = extract_pdf_text(file)
    except Exception as e:
        return jsonify({"error": f"Error reading PDF: {e}"}), 400

    # store raw resume text for follow-up questions
    session["resume_text"] = resume_text

    email, phone = extract_contact_info(resume_text)
    prompt = INPUT_PROMPT.format(text=resume_text, jd=jd)

    try:
        raw = get_gemini_response(prompt)
    except Exception as e:
        return jsonify({"error": f"Error calling Gemini API: {e}"}), 500

    parsed = extract_json_obj(raw)
    if not parsed:
        session['last_raw_response'] = raw
        return jsonify({"error": "Could not parse JSON from model response. Check server logs."}), 500

    # Save last analysis in session
    session['last_analysis'] = parsed
    session.modified = True

    # Build step-by-step messages
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

    # Append to session history
    h = session.get("history", [])
    for m in messages:
        h.append({"role": "bot", "text": m})
    session["history"] = h
    session.modified = True

    return jsonify({"messages": messages})

@app.route("/get", methods=["POST"])
def get_msg():
    user_msg = request.form.get("msg", "").strip()
    if not user_msg:
        return jsonify({"error": "Empty message"}), 400

    history = session.get("history", [])
    history.append({"role": "user", "text": user_msg})

    parsed = session.get("last_analysis") or {}
    resume_text = session.get("resume_text", "")

    if re.search(r'\b(show|repeat|analysis|summary)\b', user_msg, re.I):
        if not parsed:
            reply = "No previous analysis found. Please upload resume + JD first."
        else:
            reply = (
                f"Summary — Domain: {parsed.get('Domain','N/A')}; "
                f"JD Match: {parsed.get('JD Match','N/A')}; "
                f"Top skills: {', '.join(parsed.get('MatchingSkills', [])[:6]) or 'None'}; "
                f"Previous Companies: {', '.join(parsed.get('PreviousCompanies', [])) or 'None'}"
            )
    else:
        followup_prompt = (
            "You are TalentMatch-360 assistant. Use this resume text and structured analysis as context:\n"
            + json.dumps({"resume": resume_text, "analysis": parsed})
            + "\n\nUser question: " + user_msg + "\nAnswer concisely."
        )
        try:
            reply = get_gemini_response(followup_prompt)
        except Exception as e:
            reply = f"Error calling Gemini: {e}"

    history.append({"role": "bot", "text": reply})
    session["history"] = history
    session.modified = True
    return jsonify({"reply": reply})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
