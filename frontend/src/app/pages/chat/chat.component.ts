import { CommonModule } from '@angular/common';
import {
  AfterViewChecked,
  Component,
  ElementRef,
  ViewChild,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { DocumentService } from '../../services/document.service';
import { ChatMessage, LoadedDocument } from '../../models/chat.model';

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  templateUrl: './chat.component.html',
  styleUrl: './chat.component.css',
})
export class ChatComponent implements AfterViewChecked {
  private readonly api = inject(DocumentService);

  @ViewChild('threadEnd') private threadEnd?: ElementRef<HTMLDivElement>;

  readonly messages = signal<ChatMessage[]>([]);
  readonly draft = signal('');
  readonly thinking = signal(false);

  // ---- Attached document state ----
  readonly attachedDoc = signal<LoadedDocument | null>(null);
  readonly uploading = signal(false);
  readonly dragOver = signal(false);
  readonly uploadError = signal('');

  // ---- Show/hide the grounding source ----
  readonly showSources = signal(true);

  private nextId = 1;
  private shouldScroll = false;

  readonly canSend = computed(
    () => this.draft().trim().length > 0 && !this.thinking() && !this.uploading()
  );

  ngAfterViewChecked(): void {
    if (this.shouldScroll) {
      this.threadEnd?.nativeElement.scrollIntoView({ behavior: 'smooth' });
      this.shouldScroll = false;
    }
  }

  // ---- File upload ----
  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) {
      this.upload(file);
    }
    input.value = '';
  }

  onDragOver(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(true);
  }

  onDragLeave(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
  }

  onDrop(event: DragEvent): void {
    event.preventDefault();
    this.dragOver.set(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) {
      this.upload(file);
    }
  }

  private upload(file: File): void {
    this.uploadError.set('');
    this.uploading.set(true);
    this.api.uploadDocument(file).subscribe({
      next: (res) => {
        this.uploading.set(false);
        this.attachedDoc.set({
          filename: res.filename,
          size: res.size,
          characters: res.stored_text_length,
        });
      },
      error: () => {
        this.uploading.set(false);
        this.uploadError.set("Upload failed. Is the backend running on port 8000?");
      },
    });
  }

  removeDoc(): void {
    this.attachedDoc.set(null);
    this.uploadError.set('');
  }

  toggleSources(): void {
    this.showSources.update((v) => !v);
  }

  // ---- Sending ----
  send(): void {
    const question = this.draft().trim();
    if (!question || this.thinking()) {
      return;
    }

    const hasDoc = !!this.attachedDoc();
    this.push('user', question);
    this.draft.set('');

    const placeholder = this.push('assistant', '', { pending: true });
    this.thinking.set(true);

    this.api.ask(question, hasDoc).subscribe({
      next: (res) => {
        this.thinking.set(false);
        this.patch(placeholder.id, {
          text: res.answer || 'No answer returned.',
          grounding: hasDoc && res.context_used ? res.context_preview : undefined,
          pending: false,
        });
      },
      error: () => {
        this.thinking.set(false);
        this.patch(placeholder.id, {
          text: "Couldn't reach the backend. Make sure it's running on port 8000.",
          pending: false,
          error: true,
        });
      },
    });
  }

  onEnter(event: Event): void {
    const e = event as KeyboardEvent;
    if (!e.shiftKey) {
      e.preventDefault();
      this.send();
    }
  }

  useSuggestion(text: string): void {
    this.draft.set(text);
    this.send();
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private push(role: 'user' | 'assistant', text: string, extra: Partial<ChatMessage> = {}): ChatMessage {
    const message: ChatMessage = { id: this.nextId++, role, text, ...extra };
    this.messages.update((list) => [...list, message]);
    this.shouldScroll = true;
    return message;
  }

  private patch(id: number, patch: Partial<ChatMessage>): void {
    this.messages.update((list) =>
      list.map((m) => (m.id === id ? { ...m, ...patch } : m))
    );
    this.shouldScroll = true;
  }

  trackById(_i: number, m: ChatMessage): number {
    return m.id;
  }
}