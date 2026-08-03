import { Routes } from '@angular/router';

import { HubComponent } from './pages/hub/hub.component';
import { ChatComponent } from './pages/chat/chat.component';
import { RagComponent } from './pages/rag/rag.component';

export const routes: Routes = [
  { path: '', component: HubComponent },
  { path: 'chat', component: ChatComponent },
  { path: 'rag', component: RagComponent },
  { path: '**', redirectTo: '' },
];