import io
import json
from pathlib import Path

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai

from app.config import GEMINI_API_KEY, GEMINI_MODEL

# Embedding model used to turn text into vectors for semantic search (RAG).
EMBED_MODEL = "gemini-embedding-001"
TOP_K = 4  # how many most-relevant chunks to send to the model


# --------------------------------------------------------------------------- #
# Text helpers                                                                #
# --------------------------------------------------------------------------- #
def extract_text_from_upload(filename: str, content: bytes) -> str:
    """Extract readable text from an uploaded file based on its extension."""
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            parts = [page.extract_text() or "" for page in reader.pages]
            return "\n".join(parts).strip()
        except Exception:
            return ""

    if name.endswith(".docx"):
        try:
            import docx
            document = docx.Document(io.BytesIO(content))
            return "\n".join(p.text for p in document.paragraphs).strip()
        except Exception:
            return ""

    return content.decode("utf-8", errors="ignore").strip()


def chunk_text(text: str, chunk_size: int = 400) -> list[str]:
    """Split text into smaller chunks for retrieval."""
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


def is_realtime_question(question: str) -> bool:
    """Return True if the question is asking for real-time date/time info."""
    q = question.lower()
    keywords = [
        "current time", "current date", "time and date", "date and time",
        "what time", "what date", "today's date", "todays date",
        "what is the time", "what is the date", "current day", "time right now",
        "date today", "time now",
    ]
    return any(k in q for k in keywords)


# --------------------------------------------------------------------------- #
# RAG helpers: embeddings + similarity                                        #
# --------------------------------------------------------------------------- #
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Turn a list of texts into embedding vectors using Gemini."""
    if not texts:
        return []
    client = genai.Client(api_key=GEMINI_API_KEY)
    vectors: list[list[float]] = []
    for text in texts:
        result = client.models.embed_content(model=EMBED_MODEL, contents=text)
        # google-genai returns .embeddings (list); each has .values
        vectors.append(list(result.embeddings[0].values))
    return vectors


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (1.0 = identical meaning)."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def top_relevant_chunks(question: str, chunks: list[str],
                        vectors: list[list[float]], k: int = TOP_K) -> str:
    """Embed the question and return the k most semantically similar chunks."""
    if not chunks or not vectors:
        return ""
    q_vec = embed_texts([question])[0]
    scored = [
        (cosine_similarity(q_vec, vec), chunk)
        for chunk, vec in zip(chunks, vectors)
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return "\n\n".join(chunk for _, chunk in scored[:k])


# --------------------------------------------------------------------------- #
# App setup + CORS                                                            #
# --------------------------------------------------------------------------- #
app = FastAPI(title="AI Document Assistant", version="0.2.0")

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
    path = app.state.document_store_path
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}


def save_document_store(store: dict) -> None:
    path = app.state.document_store_path
    with path.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)


def get_current_document_text() -> str:
    store = load_document_store()
    return store.get("last_document_text", "")


def get_stored_chunks_and_vectors() -> tuple[list[str], list[list[float]]]:
    """Return the saved chunks and their embedding vectors, if any."""
    store = load_document_store()
    return store.get("chunks", []), store.get("vectors", [])


def save_document(text: str, chunks: list[str], vectors: list[list[float]]) -> None:
    """Persist the document text plus its chunks and embeddings."""
    store = load_document_store()
    store["last_document_text"] = text
    store["chunks"] = chunks
    store["vectors"] = vectors
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
    return {"status": "ok"}


@app.post("/documents/upload")
async def upload_document(file: UploadFile = File(...)):
    """Upload a document: extract text, chunk it, embed each chunk, and store."""
    content = await file.read()
    text = extract_text_from_upload(file.filename, content)

    chunks = chunk_text(text)
    vectors: list[list[float]] = []
    if chunks and GEMINI_API_KEY:
        try:
            vectors = embed_texts(chunks)
        except Exception:
            vectors = []  # fall back gracefully if embedding fails

    save_document(text, chunks, vectors)

    return {
        "filename": file.filename,
        "content_type": file.content_type,
        "size": len(content),
        "stored_text_length": len(text),
        "chunks": len(chunks),
        "embedded": len(vectors) > 0,
    }


@app.post("/ask")
async def ask_question(payload: QuestionRequest):
    """Answer a question using RAG when a document is loaded."""
    context_text = app.state.last_document_text or get_current_document_text()
    has_context = bool(context_text.strip()) and payload.use_document

    # Real-time date/time questions get a fixed reply (general chat only).
    if not has_context and is_realtime_question(payload.question):
        return {
            "answer": (
                "I don't have real-time capabilities to provide the current time "
                "and date. You can check the time and date on your device or use "
                "an online service for the most accurate information. How else may "
                "I assist you today?"
            ),
            "model": GEMINI_MODEL,
            "api_key_configured": bool(GEMINI_API_KEY),
            "context_used": False,
            "context_preview": "",
        }

    # --- RAG retrieval: use semantic search over embedded chunks ---
    context_for_model = ""
    if has_context:
        chunks, vectors = get_stored_chunks_and_vectors()
        if chunks and vectors and len(chunks) == len(vectors):
            try:
                context_for_model = top_relevant_chunks(
                    payload.question, chunks, vectors
                )
            except Exception:
                context_for_model = context_text[:4000]
        else:
            # No embeddings available (e.g. old upload) -> use raw text.
            context_for_model = context_text[:4000]

    context_preview = context_for_model[:200]

    if not GEMINI_API_KEY:
        return {
            "answer": "Gemini API key is not configured. Add GEMINI_API_KEY to backend/.env.",
            "model": GEMINI_MODEL,
            "api_key_configured": False,
            "context_used": has_context,
            "context_preview": context_preview,
        }

    if has_context:
        prompt = (
            "You are an AI Document Assistant.\n\n"
            "Answer ONLY from the document excerpts below. If the answer is not in "
            'them, reply exactly: "I couldn\'t find the answer in the uploaded '
            'document."\n\n'
            f"Document excerpts:\n{context_for_model}\n\n"
            f"Question:\n{payload.question}\n"
        )
    else:
        prompt = (
            "You are a helpful AI assistant. Answer the user's question clearly "
            "and concisely.\n\n"
            "IMPORTANT: You do not have access to real-time information. If the user "
            "asks about the current date, time, weather, live news, or stock prices, "
            "politely explain that you do not have real-time capabilities and suggest "
            "they check their device or a live source. Never make up such values.\n\n"
            f"Question:\n{payload.question}\n"
        )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        answer = (response.text or "").strip() or "No answer returned."
    except Exception as exc:  # noqa: BLE001
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