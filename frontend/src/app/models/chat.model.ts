/** Shared types for the AI Assistant Hub. */

export type ChatRole = 'user' | 'assistant';

export interface ChatMessage {
  id: number;
  role: ChatRole;
  text: string;
  grounding?: string;
  pending?: boolean;
  error?: boolean;
}

export interface UploadResponse {
  filename: string;
  content_type: string;
  size: number;
  stored_text_length: number;
}

export interface AskResponse {
  answer: string;
  model: string;
  api_key_configured: boolean;
  context_used: boolean;
  context_preview: string;
}

export interface LoadedDocument {
  filename: string;
  size: number;
  characters: number;
}