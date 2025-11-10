import os
import tempfile
import pytesseract
import spacy
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
from PIL import Image
import docx
import json
import gspread
from google.oauth2.service_account import Credentials

from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_community.callbacks import get_openai_callback


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable not set")
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

# Load spaCy model
nlp = spacy.load("en_core_web_sm")

app = Flask(__name__)

# ------------------------- Google Sheets Setup -------------------------
# SERVICE_ACCOUNT_FILE = "ocr-data-extractor-b941e8d4a2af.json"   # your JSON key filename
SPREADSHEET_NAME = "Entities"           # your Google Sheet name

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
cred_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")

if cred_json:
    # Convert the JSON string from environment to a temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_json:
        temp_json.write(cred_json.encode())
        temp_json.flush()
        creds = Credentials.from_service_account_file(temp_json.name, scopes=SCOPES)
else:
    # Fallback for local dev (if you still have the file locally)
    SERVICE_ACCOUNT_FILE = "ocr-data-extractor-b941e8d4a2af.json"
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# Authorize gspread
client = gspread.authorize(creds)

try:
    sheet = client.open(SPREADSHEET_NAME).sheet1
except Exception:
    sheet = client.create(SPREADSHEET_NAME).sheet1
    sheet.append_row(["Filename", "Address", "Bill To", "Company Name", "Email", "Invoice", "Invoice Date", "Mobile No", "Total Amount"])

# ------------------------- Text extraction helpers -------------------------

def extract_text_from_docx(path):
    doc = docx.Document(path)
    return "\n".join([p.text for p in doc.paragraphs if p.text])

def extract_text_from_image(path):
    img = Image.open(path)
    return pytesseract.image_to_string(img)

def extract_text_from_pdf(path):
    text = ""
    try:
        reader = PdfReader(path)
        for page in reader.pages:
            if page.extract_text():
                text += page.extract_text() + "\n"
    except Exception:
        pass
    if not text.strip():  # fallback to OCR
        images = convert_from_path(path)
        for img in images:
            text += pytesseract.image_to_string(img) + "\n"
    return text

# ------------------------- LLM-based extraction -------------------------

def extract_entities_llm(text):
    model = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    template = """You are an information extraction assistant. 
From the following document text, extract the information below and return it in JSON with these exact keys:
- Address
- Bill To
- Company Name
- Email
- Invoice
- Invoice Date
- Mobile No
- Total Amount

If a field is not present, set its value to "Not found".  
Return valid JSON only (no markdown, no explanations).

Text:
{text}
"""
    prompt = PromptTemplate(template=template, input_variables=["text"])
    chain = prompt | model

    with get_openai_callback() as cb:
        response = chain.invoke({"text": text})
        print("\n📊 ----- OpenAI Token Usage Summary -----")
        print(f"Prompt Tokens   : {cb.prompt_tokens}")
        print(f"Completion Tokens: {cb.completion_tokens}")
        print(f"Total Tokens     : {cb.total_tokens}")
        print(f"Cost (USD)       : ${cb.total_cost:.6f}")
        print("----------------------------------------\n")

    content = response.content.strip()
    json_start = content.find("{")
    json_end = content.rfind("}") + 1
    if json_start != -1 and json_end != -1:
        content = content[json_start:json_end]

    try:
        parsed = json.loads(content)
    except Exception:
        print("⚠️ Could not parse LLM JSON, returning raw string")
        parsed = {"Raw Response": response.content}

    return parsed


# ------------------------- Flask route -------------------------

@app.route("/extract", methods=["POST"])
def extract():
    if "files" not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist("files")
    results = []

    for file in files:
        if file.filename == "":
            continue

        filename = secure_filename(file.filename)
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            file.save(tmp.name)
            filepath = tmp.name

        try:
            # Extract text depending on file type
            if filename.lower().endswith(".pdf"):
                text = extract_text_from_pdf(filepath)
            elif filename.lower().endswith(".docx"):
                text = extract_text_from_docx(filepath)
            elif filename.lower().endswith((".png", ".jpg", ".jpeg")):
                text = extract_text_from_image(filepath)
            else:
                continue

            # Extract entities using LLM
            extracted_entities = extract_entities_llm(text)

            # Append to Google Sheet
            row = [
                filename,
                extracted_entities.get("Address", "Not found"),
                extracted_entities.get("Bill To", "Not found"),
                extracted_entities.get("Company Name", "Not found"),
                extracted_entities.get("Email", "Not found"),
                extracted_entities.get("Invoice", "Not found"),
                extracted_entities.get("Invoice Date", "Not found"),
                extracted_entities.get("Mobile No", "Not found"),
                extracted_entities.get("Total Amount", "Not found"),
            ]
            sheet.append_row(row)

            results.append({"filename": filename, "extracted_entities": extracted_entities})

        finally:
            os.remove(filepath)

    return jsonify({"results": results})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
