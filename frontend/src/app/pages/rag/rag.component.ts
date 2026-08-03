import { CommonModule } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { DocumentService } from '../../services/document.service';
import { ChatMessage, LoadedDocument } from '../../models/chat.model';

@Component({
  selector: 'app-rag',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './rag.component.html',
  styleUrl: './rag.component.css',
})
export class RagComponent {
  private readonly api = inject(DocumentService);

  readonly loadedDocument = signal<LoadedDocument | null>(null);
  readonly uploading = signal(false);
  readonly uploadError = signal('');

  readonly answers = signal<ChatMessage[]>([]);
  readonly question = signal('');
  readonly thinking = signal(false);

  private nextId = 1;

  readonly canAsk = computed(
    () =>
      this.question().trim().length > 0 &&
      !!this.loadedDocument() &&
      !this.thinking()
  );

  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.upload(file);
    }
    input.value = '';
  }

  private upload(file: File): void {
    this.uploadError.set('');
    this.uploading.set(true);
    this.api.uploadDocument(file).subscribe({
      next: (res) => {
        this.uploading.set(false);
        this.loadedDocument.set({
          filename: res.filename,
          size: res.size,
          characters: res.stored_text_length,
        });
      },
      error: () => {
        this.uploading.set(false);
        this.uploadError.set(
          "Upload failed. Make sure the backend is running on port 8000."
        );
      },
    });
  }

  ask(): void {
    const q = this.question().trim();
    if (!q || !this.loadedDocument() || this.thinking()) {
      return;
    }

    this.push('user', q);
    this.question.set('');

    const placeholder = this.push('assistant', '', { pending: true });
    this.thinking.set(true);

    this.api.ask(q, true).subscribe({
      next: (res) => {
        this.thinking.set(false);
        this.patch(placeholder.id, {
          text: res.answer || 'No answer returned.',
          grounding: res.context_used ? res.context_preview : undefined,
          pending: false,
        });
      },
      error: () => {
        this.thinking.set(false);
        this.patch(placeholder.id, {
          text: "Something went wrong talking to the backend.",
          pending: false,
          error: true,
        });
      },
    });
  }

  reset(): void {
    this.answers.set([]);
    this.loadedDocument.set(null);
    this.question.set('');
    this.uploadError.set('');
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private push(role: 'user' | 'assistant', text: string, extra: Partial<ChatMessage> = {}): ChatMessage {
    const m: ChatMessage = { id: this.nextId++, role, text, ...extra };
    this.answers.update((list) => [...list, m]);
    return m;
  }

  private patch(id: number, patch: Partial<ChatMessage>): void {
    this.answers.update((list) =>
      list.map((m) => (m.id === id ? { ...m, ...patch } : m))
    );
  }

  trackById(_i: number, m: ChatMessage): number {
    return m.id;
  }
}