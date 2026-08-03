import io
import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai

from app.config import GEMINI_API_KEY, GEMINI_MODEL


# --------------------------------------------------------------------------- #
# Text helpers                                                                #
# --------------------------------------------------------------------------- #

def extract_text_from_upload(filename: str, content: bytes) -> str:
    """Extract readable text from an uploaded file based on its extension.

    Supports PDF (.pdf), Word (.docx), and plain text (.txt, .md, etc.).
    """
    name = (filename or "").lower()

    # ---- PDF ----
    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            parts = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(parts).strip()
        except Exception:
            return ""

    # ---- Word .docx ----
    if name.endswith(".docx"):
        try:
            import docx
            document = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in document.paragraphs).strip()
        except Exception:
            return ""

    # ---- Plain text (.txt, .md, .csv, etc.) ----
    return content.decode("utf-8", errors="ignore").strip()

def chunk_text(text: str, chunk_size: int = 400) -> list[str]:
    """Split text into smaller chunks for retrieval-style prompting."""
    if not text.strip():
        return []

    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    current_length = 0

    for word in words:
        if current_length + len(word) + 1 > chunk_size and current:
            chunks.append(" ".join(current))
            current = [word]
            current_length = len(word)
        else:
            current.append(word)
            current_length += len(word) + 1

    if current:
        chunks.append(" ".join(current))

    return chunks


def select_relevant_chunk(question: str, chunks: list[str]) -> str:
    """Pick the chunk whose content best matches the question."""
    if not chunks:
        return ""

    normalized_question = question.lower()
    scored_chunks = []
    for chunk in chunks:
        chunk_lower = chunk.lower()
        score = sum(word in chunk_lower for word in normalized_question.split())
        scored_chunks.append((score, chunk))

    scored_chunks.sort(key=lambda item: item[0], reverse=True)
    return scored_chunks[0][1] if scored_chunks else ""


# --------------------------------------------------------------------------- #
# App setup + CORS                                                            #
# --------------------------------------------------------------------------- #
app = FastAPI(title="AI Document Assistant", version="0.1.0")

# Allow the Angular dev server (and any local origin) to call this API.
# For a real deployment, replace ["*"] with your actual frontend domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.document_store_path = Path(__file__).resolve().parent / "document_store.json"
app.state.last_document_text = ""


# --------------------------------------------------------------------------- #
# Document store (persisted to disk)                                          #
# --------------------------------------------------------------------------- #
def load_document_store() -> dict:
    """Load the persisted document store from disk if it exists."""
    path = app.state.document_store_path
    if not path.exists():
        return {}

    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def save_document_store(store: dict) -> None:
    """Persist the document store to disk."""
    path = app.state.document_store_path
    with path.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)


def get_current_document_text() -> str:
    """Retrieve the latest uploaded document text from the persisted store."""
    store = load_document_store()
    return store.get("last_document_text", "")


def save_current_document_text(text: str) -> None:
    """Save the latest uploaded document text to the persisted store."""
    store = load_document_store()
    store["last_document_text"] = text
    save_document_store(store)
    app.state.last_document_text = text


class QuestionRequest(BaseModel):
    question: str
    use_document: bool = True

# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #
@app.get("/health")
def health_check():
    """Return a simple health status for monitoring."""
    return {"status": "ok"}


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Accept a document upload, store its text, and return file info."""
    content = await file.read()
    text = extract_text_from_upload(file.filename, content)
    save_current_document_text(text)
    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "stored_text_length": len(text),
    }


@app.post("/documents/read-text")
async def read_text_file(file: UploadFile = File(...)):
    """Read the contents of an uploaded text file."""
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    return {
        "filename": file.filename,
        "text_preview": text[:500],
        "total_characters": len(text),
    }


@app.post("/ask")
async def ask_question(payload: QuestionRequest):
    """Answer a question with Gemini.

    - If a document is loaded, the answer is grounded strictly in that document.
    - If no document is loaded, it behaves as a general-purpose assistant.
    """
    context_text = app.state.last_document_text or get_current_document_text()
    has_context = bool(context_text.strip()) and payload.use_document

    # Small documents (like resumes) are sent in full so nothing is missed.
    # Large ones fall back to the most relevant chunks.
    MAX_FULL_CHARS = 12000
    if len(context_text) <= MAX_FULL_CHARS:
        context_for_model = context_text
    else:
        chunks = chunk_text(context_text)
        scored = sorted(
            chunks,
            key=lambda c: sum(w in c.lower() for w in payload.question.lower().split()),
            reverse=True,
        )
        context_for_model = "\n\n".join(scored[:5])

    context_preview = context_for_model[:200]

    if not GEMINI_API_KEY:
        return {
            "answer": "Gemini API key is not configured. Add GEMINI_API_KEY to backend/.env.",
            "model": GEMINI_MODEL,
            "api_key_configured": False,
            "context_used": has_context,
            "context_preview": context_preview,
        }

    # Build the prompt based on whether we have a document to ground in.
    if has_context:
        prompt = (
            "You are an AI Document Assistant.\n\n"
            "Answer ONLY from the document below. If the answer is not in the "
            'document, reply exactly: "I couldn\'t find the answer in the '
            'uploaded document."\n\n'
            f"Document:\n{context_for_model}\n\n"
            f"Question:\n{payload.question}\n"
        )
    else:
        prompt = (
            "You are a helpful AI assistant. Answer the user's question clearly "
            f"and concisely.\n\nQuestion:\n{payload.question}\n"
        )

    # Call Gemini using the correct google-genai SDK method.
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        answer = (response.text or "").strip() or "No answer returned."
    except Exception as exc:  # noqa: BLE001 - surface the error to the client
        return {
            "answer": f"The AI request failed: {exc}",
            "model": GEMINI_MODEL,
            "api_key_configured": True,
            "context_used": has_context,
            "context_preview": context_preview,
        }

    return {
        "answer": answer,
        "model": GEMINI_MODEL,
        "api_key_configured": True,
        "context_used": has_context,
        "context_preview": context_preview,
    }