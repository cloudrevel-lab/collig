<template>
  <div>
    <v-row align="center" class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-0">Chat Sessions</h1>
      </v-col>
      <v-col cols="auto">
        <v-btn color="error" variant="outlined" prepend-icon="mdi-delete-sweep"
          :disabled="selected.length === 0" @click="confirmDeleteSelected">
          Delete Selected ({{ selected.length }})
        </v-btn>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          label="Search sessions..."
          variant="outlined"
          hide-details
          density="compact"
          clearable
          class="mb-2"
        />
      </v-col>
    </v-row>

    <v-data-table
      v-model="selected"
      :headers="headers"
      :items="filteredSessions"
      :loading="loading"
      no-data-text="No sessions found"
      show-select
      class="elevation-2"
      rounded="xl"
      :items-per-page="15"
      :items-per-page-options="[15, 25, 50, -1]"
      items-per-page-text="Sessions per page"
      :search="search"
    >
      <template v-slot:item.id="{ item }">
        <v-tooltip location="top">
          <template v-slot:activator="{ props }">
            <code v-bind="props" class="session-id">{{ item.id.substring(0, 12) }}...</code>
          </template>
          <span>{{ item.id }}</span>
        </v-tooltip>
      </template>

      <template v-slot:item.preview="{ item }">
        <div class="text-truncate" style="max-width: 350px;">{{ item.preview || '—' }}</div>
      </template>

      <template v-slot:item.message_count="{ item }">
        <v-chip size="small">{{ item.message_count }}</v-chip>
      </template>

      <template v-slot:item.created_at="{ item }">
        {{ formatTimestamp(item.created_at) }}
      </template>

      <template v-slot:item.last_activity="{ item }">
        {{ formatTimestamp(item.last_activity) }}
      </template>

      <template v-slot:item.actions="{ item }">
        <v-icon size="small" class="mr-2" color="info" @click="viewSession(item)">mdi-eye</v-icon>
        <v-icon size="small" color="error" @click="confirmDelete(item)">mdi-delete</v-icon>
      </template>
    </v-data-table>

    <!-- View Session Dialog -->
    <v-dialog v-model="viewDialog" max-width="800" scrollable>
      <v-card rounded="xl">
        <v-card-title>
          Session {{ viewingSession?.id?.substring(0, 8) }}...
        </v-card-title>
        <v-divider />
        <v-card-text class="pt-4" style="max-height: 60vh; overflow-y: auto;">
          <div v-if="viewingSession" class="session-messages">
            <div
              v-for="(msg, idx) in viewingSession.messages"
              :key="idx"
              :class="['msg-bubble', msg.role]"
            >
              <div class="msg-role">{{ msg.role === 'user' ? 'You' : 'Collig' }}</div>
              <div class="msg-content">{{ msg.content }}</div>
              <div class="msg-time">{{ formatTimestamp(msg.timestamp) }}</div>
            </div>
          </div>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn text @click="viewDialog = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Confirmation (single) -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card rounded="xl">
        <v-card-title class="text-error">Delete Session</v-card-title>
        <v-divider />
        <v-card-text class="pa-4">
          Are you sure you want to delete this session?<br>
          <code>{{ deleteItem?.id?.substring(0, 12) }}...</code>
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn text @click="deleteDialog = false">Cancel</v-btn>
          <v-btn color="error" :loading="saving" @click="executeDelete">Delete</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'

const API_BASE = '/api'

const sessions = ref([])
const loading = ref(false)
const saving = ref(false)
const search = ref('')
const selected = ref([])
const viewDialog = ref(false)
const deleteDialog = ref(false)
const viewingSession = ref(null)
const deleteItem = ref(null)

const headers = [
  { title: 'Session ID', key: 'id', width: '20%' },
  { title: 'Preview', key: 'preview', width: '35%' },
  { title: 'Messages', key: 'message_count', width: '10%' },
  { title: 'Created', key: 'created_at', width: '15%' },
  { title: 'Last Activity', key: 'last_activity', width: '15%' },
  { title: 'Actions', key: 'actions', sortable: false, width: '5%' },
]

const filteredSessions = computed(() => {
  if (!search.value) return sessions.value
  const q = search.value.toLowerCase()
  return sessions.value.filter(s =>
    s.id.toLowerCase().includes(q) ||
    (s.preview && s.preview.toLowerCase().includes(q))
  )
})

async function loadSessions() {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/sessions`)
    const data = await res.json()
    sessions.value = data.sessions || []
  } catch (e) {
    console.error('Failed to load sessions:', e)
  } finally {
    loading.value = false
  }
}

async function viewSession(item) {
  try {
    const res = await fetch(`${API_BASE}/sessions/${item.id}`)
    if (!res.ok) throw new Error('Session not found')
    viewingSession.value = await res.json()
    viewDialog.value = true
  } catch (e) {
    console.error('Failed to load session:', e)
  }
}

function confirmDelete(item) {
  deleteItem.value = item
  deleteDialog.value = true
}

async function executeDelete() {
  if (!deleteItem.value) return
  saving.value = true
  try {
    const res = await fetch(`${API_BASE}/sessions/${deleteItem.value.id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await res.text())
    deleteDialog.value = false
    await loadSessions()
  } catch (e) {
    console.error('Failed to delete session:', e)
  } finally {
    saving.value = false
  }
}

async function confirmDeleteSelected() {
  if (!selected.value.length) return
  saving.value = true
  try {
    await Promise.all(
      selected.value.map(s =>
        fetch(`${API_BASE}/sessions/${s.id}`, { method: 'DELETE' })
      )
    )
    selected.value = []
    await loadSessions()
  } catch (e) {
    console.error('Failed to delete sessions:', e)
  } finally {
    saving.value = false
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

onMounted(loadSessions)
</script>

<style scoped>
.session-id {
  font-size: 0.85rem;
  color: rgba(var(--v-theme-on-surface), 0.7);
}

.session-messages {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.5;
}

.msg-bubble.user {
  align-self: flex-end;
  background: rgba(var(--v-theme-primary), 0.1);
  border-bottom-right-radius: 3px;
}

.msg-bubble.ai {
  align-self: flex-start;
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-bottom-left-radius: 3px;
}

.msg-role {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  color: rgba(var(--v-theme-on-surface), 0.4);
  margin-bottom: 4px;
}

.msg-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.msg-time {
  font-size: 0.65rem;
  color: rgba(var(--v-theme-on-surface), 0.3);
  margin-top: 4px;
}
</style>
