import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from app.main import app, chunk_text, select_relevant_chunk


class DocumentContextTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.state.last_document_text = ""

    def test_upload_and_ask_use_document_context(self):
        response = self.client.post(
            "/documents/upload",
            files={"file": ("notes.txt", b"Paris is the capital of France.", "text/plain")},
        )

        self.assertEqual(response.status_code, 200)

        ask_response = self.client.post(
            "/ask",
            json={"question": "What is the capital of France?"},
        )

        self.assertEqual(ask_response.status_code, 200)
        body = ask_response.json()
        self.assertTrue(body["context_used"])
        self.assertIn("Paris is the capital of France.", body["context_preview"])

    def test_select_relevant_chunk_prefers_matching_section(self):
        text = "The Eiffel Tower is in Paris.\n\nThe capital of France is Paris.\n\nPython is a programming language."
        chunks = chunk_text(text, chunk_size=250)
        selected = select_relevant_chunk("What is the capital of France?", chunks)

        self.assertIn("capital of France", selected)
        self.assertIn("Paris", selected)

    def test_root_serves_frontend_page(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI Document Assistant", response.text)
        self.assertIn("Ask a question about your document", response.text)

    def test_ui_page_is_served(self):
        response = self.client.get("/ui")

        self.assertEqual(response.status_code, 200)
        self.assertIn("AI Document Assistant", response.text)
        self.assertIn("Upload a text document", response.text)
