import { createRouter, createWebHashHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import BookmarksView from './views/BookmarksView.vue'
import NotesView from './views/NotesView.vue'
import DiaryView from './views/DiaryView.vue'
import ChatView from './views/ChatView.vue'
import SessionsView from './views/SessionsView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat/:sessionId?', name: 'Chat', component: ChatView, props: true },
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
