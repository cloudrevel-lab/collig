import { createRouter, createWebHashHistory } from 'vue-router'
import DashboardView from './views/DashboardView.vue'
import BookmarksView from './views/BookmarksView.vue'
import NotesView from './views/NotesView.vue'
import DiaryView from './views/DiaryView.vue'
import ChatView from './views/ChatView.vue'
import SessionsView from './views/SessionsView.vue'

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat', name: 'Chat', component: ChatView },
  { path: '/dashboard', name: 'Dashboard', component: DashboardView },
  { path: '/bookmarks', name: 'Bookmarks', component: BookmarksView },
  { path: '/notes', name: 'Notes', component: NotesView },
  { path: '/diary', name: 'Diary', component: DiaryView },
  { path: '/sessions', name: 'Sessions', component: SessionsView },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

export default router
