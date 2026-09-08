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
      <v-col cols="12" md="3">
        <v-card rounded="xl" elevation="2" color="primary" variant="tonal">
          <v-card-text class="pa-5">
            <div class="d-flex align-center justify-space-between mb-2">
              <span class="text-subtitle-2 font-weight-medium text-medium-emphasis">Total Tokens</span>
              <v-icon size="22">mdi-chart-bubble</v-icon>
            </div>
            <div class="text-h4 font-weight-bold">{{ formatNumber(tokenStats.total_tokens) }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              avg {{ formatNumber(tokenStats.avg_tokens_per_turn) }} / turn
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card rounded="xl" elevation="2" color="info" variant="tonal">
          <v-card-text class="pa-5">
            <div class="d-flex align-center justify-space-between mb-2">
              <span class="text-subtitle-2 font-weight-medium text-medium-emphasis">Interactions</span>
              <v-icon size="22">mdi-swap-horizontal</v-icon>
            </div>
            <div class="text-h4 font-weight-bold">{{ formatNumber(tokenStats.total_interactions) }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              across {{ formatNumber(tokenStats.sessions_with_stats) }} sessions
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card rounded="xl" elevation="2" color="warning" variant="tonal">
          <v-card-text class="pa-5">
            <div class="d-flex align-center justify-space-between mb-2">
              <span class="text-subtitle-2 font-weight-medium text-medium-emphasis">Prompt Tokens</span>
              <v-icon size="22">mdi-send</v-icon>
            </div>
            <div class="text-h4 font-weight-bold">{{ formatNumber(tokenStats.total_prompt_tokens) }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              {{ promptRatio }}% of total
            </div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="3">
        <v-card rounded="xl" elevation="2" color="success" variant="tonal">
          <v-card-text class="pa-5">
            <div class="d-flex align-center justify-space-between mb-2">
              <span class="text-subtitle-2 font-weight-medium text-medium-emphasis">Completion Tokens</span>
              <v-icon size="22">mdi-reply</v-icon>
            </div>
            <div class="text-h4 font-weight-bold">{{ formatNumber(tokenStats.total_completion_tokens) }}</div>
            <div class="text-caption text-medium-emphasis mt-1">
              {{ completionRatio }}% of total
            </div>
          </v-card-text>
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
import { computed, ref, onMounted } from 'vue'
import { mdiLink } from '@mdi/js'

const stats = ref({ bookmarks: 0, notes: 0, chatSessions: 0 })
const recentBookmarks = ref([])
const recentSessions = ref([])
const tokenStats = ref({
  total_tokens: 0,
  total_interactions: 0,
  total_prompt_tokens: 0,
  total_completion_tokens: 0,
  avg_tokens_per_turn: 0,
  sessions_with_stats: 0,
})

const API_BASE = '/api'

const promptRatio = computed(() => {
  const total = tokenStats.value.total_tokens || 0
  if (!total) return 0
  return Math.round((tokenStats.value.total_prompt_tokens / total) * 100)
})
const completionRatio = computed(() => {
  const total = tokenStats.value.total_tokens || 0
  if (!total) return 0
  return Math.round((tokenStats.value.total_completion_tokens / total) * 100)
})

function formatNumber(n) {
  if (n === null || n === undefined || isNaN(n)) return '0'
  try {
    return new Intl.NumberFormat().format(Math.round(Number(n)))
  } catch {
    return String(Math.round(Number(n) || 0))
  }
}

async function loadDashboard() {
  try {
    const [bmRes, noteRes, sessRes, tokenRes] = await Promise.allSettled([
      fetch(`${API_BASE}/bookmarks`),
      fetch(`${API_BASE}/notes`),
      fetch(`${API_BASE}/sessions`),
      fetch(`${API_BASE}/stats/tokens`),
    ])
    if (bmRes.status === 'fulfilled' && bmRes.value.ok) {
      const bmData = await bmRes.value.json()
      stats.value.bookmarks = bmData.total || 0
      recentBookmarks.value = (bmData.bookmarks || []).slice(0, 5)
    }
    if (noteRes.status === 'fulfilled' && noteRes.value.ok) {
      const noteData = await noteRes.value.json()
      stats.value.notes = noteData.total || 0
    }
    if (sessRes.status === 'fulfilled' && sessRes.value.ok) {
      const sessData = await sessRes.value.json()
      stats.value.chatSessions = sessData.total || 0
      recentSessions.value = (sessData.sessions || []).slice(0, 5)
    }
    if (tokenRes.status === 'fulfilled' && tokenRes.value.ok) {
      const tData = await tokenRes.value.json()
      tokenStats.value = {
        total_tokens: tData.total_tokens || 0,
        total_interactions: tData.total_interactions || 0,
        total_prompt_tokens: tData.total_prompt_tokens || 0,
        total_completion_tokens: tData.total_completion_tokens || 0,
        avg_tokens_per_turn: tData.avg_tokens_per_turn || 0,
        sessions_with_stats: tData.sessions_with_stats || 0,
      }
    }
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
