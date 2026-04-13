<template>
  <div>
    <v-row align="center" class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-0">Notes</h1>
      </v-col>
      <v-col cols="auto">
        <v-btn color="secondary" prepend-icon="mdi-plus" @click="openDialog()">Add Note</v-btn>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          label="Search notes..."
          variant="outlined"
          hide-details
          density="compact"
          clearable
          class="mb-2"
        />
      </v-col>
    </v-row>

    <v-row v-if="loading">
      <v-col cols="12" class="text-center">
        <v-progress-circular indeterminate color="secondary" />
      </v-col>
    </v-row>

    <v-row v-else-if="filteredNotes.length === 0">
      <v-col cols="12" class="text-center text-medium-emission">
        <v-icon size="64" color="grey">mdi-note-text-outline</v-icon>
        <p class="text-body-1 mt-2">No notes found.</p>
      </v-col>
    </v-row>

    <v-row v-else>
      <v-col v-for="note in filteredNotes" :key="note.id" cols="12" md="6" lg="4">
        <v-card rounded="xl" elevation="2" class="d-flex flex-column fill-height">
          <v-card-text class="flex-grow-1">
            <p class="text-body-1" style="white-space: pre-wrap;">{{ note.content }}</p>
          </v-card-text>
          <v-divider />
          <v-card-actions>
            <v-chip size="small" variant="text">{{ formatTimestamp(note.timestamp) }}</v-chip>
            <v-spacer />
            <v-icon size="small" @click="openDialog(note)">mdi-pencil</v-icon>
            <v-icon size="small" color="error" class="ml-2" @click="confirmDelete(note)">mdi-delete</v-icon>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>

    <!-- Add / Edit Dialog -->
    <v-dialog v-model="dialog" max-width="600">
      <v-card rounded="xl">
        <v-card-title>{{ editItem ? 'Edit Note' : 'Add Note' }}</v-card-title>
        <v-divider />
        <v-card-text class="pt-4">
          <v-textarea
            v-model="form.content"
            label="Note content"
            variant="outlined"
            rows="8"
            auto-grow
            autofocus
          />
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn text @click="dialog = false">Cancel</v-btn>
          <v-btn color="secondary" :loading="saving" @click="saveNote">{{ editItem ? 'Update' : 'Save' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Confirmation -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card rounded="xl">
        <v-card-title class="text-error">Delete Note</v-card-title>
        <v-divider />
        <v-card-text class="pa-4">
          Are you sure you want to delete this note?<br>
          <strong class="text-truncate d-inline-block" style="max-width: 300px;">{{ deleteItem?.content?.substring(0, 80) }}...</strong>
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

const notes = ref([])
const loading = ref(false)
const saving = ref(false)
const search = ref('')
const dialog = ref(false)
const deleteDialog = ref(false)
const editItem = ref(null)
const deleteItem = ref(null)
const form = ref({ content: '' })

const filteredNotes = computed(() => {
  if (!search.value) return notes.value
  const q = search.value.toLowerCase()
  return notes.value.filter(n => n.content.toLowerCase().includes(q))
})

async function loadNotes() {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/notes`)
    const data = await res.json()
    notes.value = data.notes || []
  } catch (e) {
    console.error('Failed to load notes:', e)
  } finally {
    loading.value = false
  }
}

function openDialog(item) {
  editItem.value = item || null
  form.value = item ? { content: item.content } : { content: '' }
  dialog.value = true
}

async function saveNote() {
  if (!form.value.content.trim()) return
  saving.value = true
  try {
    const method = editItem.value ? 'PUT' : 'POST'
    const url = editItem.value
      ? `${API_BASE}/notes/${editItem.value.id}`
      : `${API_BASE}/notes`

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) throw new Error(await res.text())
    dialog.value = false
    await loadNotes()
  } catch (e) {
    console.error('Failed to save note:', e)
  } finally {
    saving.value = false
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
    const res = await fetch(`${API_BASE}/notes/${deleteItem.value.id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await res.text())
    deleteDialog.value = false
    await loadNotes()
  } catch (e) {
    console.error('Failed to delete note:', e)
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

onMounted(loadNotes)
</script>
