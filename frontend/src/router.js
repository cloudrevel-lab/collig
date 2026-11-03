import { createRouter, createWebHashHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import BookmarksView from './views/BookmarksView.vue'
import NotesView from './views/NotesView.vue'
import DiaryView from './views/DiaryView.vue'
import ChatView from './views/ChatView.vue'
import SessionsView from './views/SessionsView.vue'
import TerminalView from './views/TerminalView.vue'

// Port 5005 keeps Chat as its landing view; port 5006 injects
// __COLLIG_LANDING_VIEW__ = 'terminal' so the same SPA lands on the terminal.
const landingView = window.__COLLIG_LANDING_VIEW__ === 'terminal' ? '/terminal' : '/chat'

const routes = [
  { path: '/', redirect: landingView },
  { path: '/chat/:sessionId?', name: 'Chat', component: ChatView, props: true },
  { path: '/terminal', name: 'Terminal', component: TerminalView },
  { path: '/dashboard', name: 'Dashboard', component: DashboardView },
  { path: '/bookmarks', name: 'Bookmarks', component: BookmarksView },
  { path: '/notes', name: 'Notes', component: NotesView },
  { path: '/diary', name: 'Diary', component: DiaryView },
  { path: '/sessions', name: 'Sessions', component: SessionsView },
  { path: '/config', name: 'Settings', component: () => import('./views/ConfigView.vue') },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
