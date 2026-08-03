import { Injectable, signal } from '@angular/core';

type Theme = 'light' | 'dark';

/**
 * Manages the app's light/dark theme.
 * The choice is applied to <html data-theme="..."> and remembered in
 * localStorage so it persists across reloads.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly storageKey = 'assistant-theme';
  readonly theme = signal<Theme>(this.readInitial());

  constructor() {
    this.apply(this.theme());
  }

  toggle(): void {
    const next: Theme = this.theme() === 'dark' ? 'light' : 'dark';
    this.theme.set(next);
    this.apply(next);
    try {
      localStorage.setItem(this.storageKey, next);
    } catch {
      /* ignore storage errors */
    }
  }

  private readInitial(): Theme {
    try {
      const saved = localStorage.getItem(this.storageKey);
      if (saved === 'light' || saved === 'dark') {
        return saved;
      }
    } catch {
      /* ignore */
    }
    return 'dark'; // default: dark
  }

  private apply(theme: Theme): void {
    document.documentElement.setAttribute('data-theme', theme);
  }
}