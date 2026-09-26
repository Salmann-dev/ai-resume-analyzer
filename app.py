import json
import os
import uuid
from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import pdfplumber
from docx import Document
from google import genai

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "resume-analyzer-secret-key")

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "docx"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_pdf(filepath):
    text_content = []
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            extracted = page.extract_text()
            if extracted:
                text_content.append(extracted)
    return "\n".join(text_content).strip()

def extract_text_from_docx(filepath):
    doc = Document(filepath)
    text_content = [paragraph.text for paragraph in doc.paragraphs if paragraph.text]
    return "\n".join(text_content).strip()

def analyze_resume_with_gemini(resume_text, job_description=""):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set. Please set it in your environment or .env file.")

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = f"""You are an expert technical recruiter and resume evaluator.
Evaluate the following resume against the provided job description (if any) or standard industry expectations for the candidate's career level.

Resume Text:
\"\"\"
{resume_text}
\"\"\"

Job Description:
\"\"\"
{job_description if job_description.strip() else "None provided. Analyze the resume generally for overall role alignment, technical depth, career progression, and communication quality."}
\"\"\"

Return ONLY a valid JSON object with no additional text, markdown fences, or commentary. The JSON must adhere to this exact structure:
{{
  "match_score": <number between 0 and 100 representing alignment or overall strength>,
  "strengths": [<array of key strengths as strings>],
  "weaknesses": [<array of areas of improvement or gaps as strings>],
  "missing_keywords": [<array of relevant industry skills, tools, or keywords missing or under-emphasized>],
  "summary": "<concise paragraph summarizing the evaluation and overall fit>"
}}"""

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
    )

    response_text = response.text.strip()

    if response_text.startswith("```"):
        lines = response_text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        response_text = "\n".join(lines).strip()

    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")
    if start_idx != -1 and end_idx != -1:
        response_text = response_text[start_idx:end_idx + 1]

    data = json.loads(response_text)

    return {
        "match_score": int(data.get("match_score", 0)),
        "strengths": data.get("strengths", []),
        "weaknesses": data.get("weaknesses", []),
        "missing_keywords": data.get("missing_keywords", []),
        "summary": data.get("summary", ""),
    }

analyze_resume_with_claude = analyze_resume_with_gemini

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    if "resume" not in request.files:
        flash("Please upload a resume file.", "error")
        return redirect(url_for("index"))

    file = request.files["resume"]
    if file.filename == "":
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    if not allowed_file(file.filename):
        flash("Invalid file format. Please upload a PDF or DOCX document.", "error")
        return redirect(url_for("index"))

    job_description = request.form.get("job_description", "").strip()

    original_filename = secure_filename(file.filename)
    extension = original_filename.rsplit(".", 1)[1].lower()
    temp_filename = f"{uuid.uuid4().hex}_{original_filename}"
    filepath = os.path.join(UPLOAD_FOLDER, temp_filename)

    try:
        file.save(filepath)

        if extension == "pdf":
            resume_text = extract_text_from_pdf(filepath)
        elif extension == "docx":
            resume_text = extract_text_from_docx(filepath)
        else:
            resume_text = ""

        if not resume_text or len(resume_text.strip()) < 20:
            flash("Could not extract readable text from the document. Please ensure the file contains searchable text rather than scanned images.", "error")
            return redirect(url_for("index"))

        result = analyze_resume_with_gemini(resume_text, job_description)
        return render_template("result.html", result=result)

    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"An error occurred while analyzing the resume: {str(e)}", "error")
        return redirect(url_for("index"))
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
