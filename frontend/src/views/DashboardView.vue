<template>
  <div>
    <v-row>
      <v-col cols="12">
        <h1 class="text-h4 mb-4">Dashboard</h1>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="4">
        <v-card rounded="xl" elevation="2">
          <v-card-text class="text-center pa-6">
            <v-icon size="48" color="primary">mdi-bookmark</v-icon>
            <div class="text-h3 mt-2">{{ stats.bookmarks }}</div>
            <div class="text-body-1 text-medium-emphasis">Total Bookmarks</div>
          </v-card-text>
          <v-card-actions>
            <v-btn text color="primary" to="/bookmarks" class="flex-grow-1">Manage Bookmarks</v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="4">
        <v-card rounded="xl" elevation="2">
          <v-card-text class="text-center pa-6">
            <v-icon size="48" color="secondary">mdi-note-text</v-icon>
            <div class="text-h3 mt-2">{{ stats.notes }}</div>
            <div class="text-body-1 text-medium-emphasis">Total Notes</div>
          </v-card-text>
          <v-card-actions>
            <v-btn text color="secondary" to="/notes" class="flex-grow-1">Manage Notes</v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="4">
        <v-card rounded="xl" elevation="2">
          <v-card-text class="text-center pa-6">
            <v-icon size="48" color="success">mdi-chat</v-icon>
            <div class="text-h3 mt-2">{{ stats.chatSessions }}</div>
            <div class="text-body-1 text-medium-emphasis">Chat Sessions</div>
          </v-card-text>
          <v-card-actions>
            <v-btn text color="success" to="/sessions" class="flex-grow-1">Manage Sessions</v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-4">
      <v-col cols="12">
        <v-card rounded="xl" elevation="2">
          <v-card-title class="pt-4">Recent Bookmarks</v-card-title>
          <v-divider />
          <v-list v-if="recentBookmarks.length" lines="two" class="pa-2">
            <v-list-item
              v-for="bm in recentBookmarks"
              :key="bm.id"
              :prepend-icon="mdiLink"
            >
              <v-list-item-title>{{ bm.description || bm.url }}</v-list-item-title>
              <v-list-item-subtitle>{{ bm.url }}</v-list-item-subtitle>
              <template v-slot:append>
                <v-chip size="small" class="mr-2">{{ formatTimestamp(bm.timestamp) }}</v-chip>
              </template>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center text-medium-emphasis pa-6">
            No bookmarks yet.
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-row class="mt-4">
      <v-col cols="12">
        <v-card rounded="xl" elevation="2">
          <v-card-title class="pt-4">
            Recent Chat Sessions
            <v-spacer />
            <v-btn text size="small" color="primary" to="/sessions">View All</v-btn>
          </v-card-title>
          <v-divider />
          <v-list v-if="recentSessions.length" lines="two" class="pa-2">
            <v-list-item
              v-for="sess in recentSessions"
              :key="sess.id"
              :to="`/sessions`"
            >
              <v-list-item-title>{{ sess.preview || 'Empty session' }}</v-list-item-title>
              <v-list-item-subtitle>
                {{ sess.id.substring(0, 8) }}... · {{ sess.message_count }} messages · {{ formatTimestamp(sess.last_activity) }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-center text-medium-emphasis pa-6">
            No chat sessions yet.
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { mdiLink } from '@mdi/js'

const stats = ref({ bookmarks: 0, notes: 0, chatSessions: 0 })
const recentBookmarks = ref([])
const recentSessions = ref([])

const API_BASE = '/api'

async function loadDashboard() {
  try {
    const [bmRes, noteRes, sessRes] = await Promise.all([
      fetch(`${API_BASE}/bookmarks`),
      fetch(`${API_BASE}/notes`),
      fetch(`${API_BASE}/sessions`),
    ])
    const bmData = await bmRes.json()
    const noteData = await noteRes.json()
    const sessData = await sessRes.json()
    stats.value.bookmarks = bmData.total || 0
    stats.value.notes = noteData.total || 0
    stats.value.chatSessions = sessData.total || 0
    recentBookmarks.value = (bmData.bookmarks || []).slice(0, 5)
    recentSessions.value = (sessData.sessions || []).slice(0, 5)
  } catch (e) {
    console.error('Failed to load dashboard:', e)
  }
}

function formatTimestamp(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return ts
  }
}

onMounted(loadDashboard)
</script>
