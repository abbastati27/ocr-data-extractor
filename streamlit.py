import streamlit as st
import requests

st.set_page_config(page_title="Bulk Document Extractor", layout="centered")
st.title("📂 Bulk Document Entity Extractor")
st.write("Upload multiple documents (PDF, DOCX, PNG, JPG) and extract key fields automatically into Google Sheets.")

uploaded_files = st.file_uploader("Choose files", type=["pdf", "docx", "png", "jpg", "jpeg"], accept_multiple_files=True)
API_URL = "https://n8n.srv1028016.hstgr.cloud/webhook-test/fe263796-2e1e-4918-a227-fe7a667d1224"

if uploaded_files:
    st.info(f"{len(uploaded_files)} file(s) selected.")
    if st.button("Start Extraction"):
        files = [("files", (f.name, f, "multipart/form-data")) for f in uploaded_files]
        try:
            with st.spinner("Extracting all documents..."):
                response = requests.post(API_URL, files=files)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    st.success(f"Extraction complete. {len(results)} files processed and added to Google Sheet.")

                    for r in results:
                        st.subheader(f"📄 {r['filename']}")
                        for key, val in r["extracted_entities"].items():
                            st.write(f"**{key}**: {val}")
                        st.markdown("---")

                else:
                    st.error(f"Error: {response.json().get('error', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            st.error(f"Connection error: {e}")
