"""
Chunks the 6 ParcelPilot PDFs, embeds each chunk with OpenAI's
text-embedding-3-small, and inserts into the Neon `documents` table.

Usage:
    export DATABASE_URL="postgresql://...neon.tech/neondb?sslmode=require"
    export OPENAI_API_KEY="sk-..."
    python3 embed_docs.py /path/to/pdf/folder
"""

import os
import sys
import glob
import psycopg2
from openai import OpenAI
from pypdf import PdfReader

DATABASE_URL = os.environ["DATABASE_URL"]
client = OpenAI()  # reads OPENAI_API_KEY from env automatically

# Metadata per file: (doc_status, effective_date, account_id)
# account_id is None for general policy docs, set for customer-specific contracts
DOC_METADATA = {
    "02_Support_Policy_v2_DEPRECATED.pdf": ("DEPRECATED", "2025-01-01", None),
    "01_Support_Policy_v3_CURRENT.pdf": ("CURRENT", "2026-05-01", None),
    "03_Cancellation_and_Service_Credit_SOP_v4.pdf": ("CURRENT", "2026-06-15", None),
    "04_Product_Operations_Guide_and_Known_Issues.pdf": ("CURRENT", "2026-08-14", None),
    "05_Northstar_Logistics_Enterprise_Agreement.pdf": ("CURRENT", "2026-01-01", "ACCT-001"),
    "06_LumenWorks_Service_Agreement.pdf": ("CURRENT", "2026-03-01", "ACCT-002"),
}


def chunk_text(text, chunk_size=800, overlap=100):
    """Simple sliding-window chunker on characters, tries to break on paragraph/section boundaries."""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) > chunk_size and current:
            chunks.append(current.strip())
            # keep overlap: take tail of previous chunk
            current = current[-overlap:] + "\n" + para
        else:
            current += "\n" + para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def embed(text):
    resp = client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


def main():
    pdf_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    total = 0
    for filename, (status, eff_date, account_id) in DOC_METADATA.items():
        path = os.path.join(pdf_dir, filename)
        if not os.path.exists(path):
            print(f"WARNING: {path} not found, skipping")
            continue

        reader = PdfReader(path)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        chunks = chunk_text(full_text)

        for chunk in chunks:
            vec = embed(chunk)
            cur.execute(
                """
                INSERT INTO documents (content, embedding, doc_name, doc_status, effective_date, account_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (chunk, vec, filename, status, eff_date, account_id),
            )
            total += 1

        print(f"{filename}: {len(chunks)} chunks embedded")

    conn.commit()
    cur.close()
    conn.close()
    print(f"Done. {total} chunks inserted into documents.")


if __name__ == "__main__":
    main()
