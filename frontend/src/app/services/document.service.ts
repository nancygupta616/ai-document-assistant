import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { environment } from '../../environments/environment';
import { AskResponse, UploadResponse } from '../models/chat.model';

/**
 * The single place that talks to the FastAPI backend.
 */
@Injectable({ providedIn: 'root' })
export class DocumentService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = environment.apiBaseUrl;

  /** POST /documents/upload  (multipart, field "file"). */
  uploadDocument(file: File): Observable<UploadResponse> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<UploadResponse>(
      `${this.baseUrl}/documents/upload`,
      formData
    );
  }

  /**
   * POST /ask with { question, use_document }.
   * - use_document = true  -> answer strictly from the uploaded document
   * - use_document = false -> normal general-purpose chat
   */
  ask(question: string, useDocument: boolean): Observable<AskResponse> {
    return this.http.post<AskResponse>(`${this.baseUrl}/ask`, {
      question,
      use_document: useDocument,
    });
  }
}