<template>
  <div>
    <v-row align="center" class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-0">Bookmarks</h1>
      </v-col>
      <v-col cols="auto">
        <v-btn color="primary" prepend-icon="mdi-plus" @click="openDialog()">Add Bookmark</v-btn>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12">
        <v-text-field
          v-model="search"
          prepend-inner-icon="mdi-magnify"
          label="Search bookmarks..."
          variant="outlined"
          hide-details
          density="compact"
          clearable
          class="mb-2"
        />
      </v-col>
    </v-row>

    <v-data-table
      :headers="headers"
      :items="filteredBookmarks"
      :loading="loading"
      no-data-text="No bookmarks found"
      class="elevation-2 resizable-table"
      rounded="xl"
      :items-per-page="15"
      :items-per-page-options="[10, 15, 25, 50]"
      data-table-id="bookmarks"
    >
      <template v-slot:item.url="{ item }">
        <a :href="item.url" target="_blank" class="url-link text-primary text-decoration-none" :title="item.url">{{ item.url }}</a>
      </template>

      <template v-slot:item.description="{ item }">
        <div class="text-truncate">{{ item.description || '—' }}</div>
      </template>

      <template v-slot:item.tags="{ item }">
        <v-chip v-for="tag in parseTags(item.tags)" :key="tag" size="x-small" class="mr-1" color="primary">{{ tag }}</v-chip>
      </template>

      <template v-slot:item.timestamp="{ item }">
        {{ formatTimestamp(item.timestamp) }}
      </template>

      <template v-slot:item.actions="{ item }">
        <v-icon size="small" class="mr-2" @click="openDialog(item)">mdi-pencil</v-icon>
        <v-icon size="small" color="error" @click="confirmDelete(item)">mdi-delete</v-icon>
      </template>
    </v-data-table>

    <!-- Add / Edit Dialog -->
    <v-dialog v-model="dialog" max-width="600">
      <v-card rounded="xl">
        <v-card-title>{{ editItem ? 'Edit Bookmark' : 'Add Bookmark' }}</v-card-title>
        <v-divider />
        <v-card-text class="pt-4">
          <v-text-field
            v-model="form.url"
            label="URL"
            variant="outlined"
            placeholder="https://example.com"
            class="mb-2"
          />
          <v-text-field
            v-model="form.description"
            label="Description"
            variant="outlined"
            class="mb-2"
          />
          <v-text-field
            v-model="form.tags"
            label="Tags (comma-separated)"
            variant="outlined"
            placeholder="python, tutorial, web-dev"
          />
        </v-card-text>
        <v-divider />
        <v-card-actions class="pa-3">
          <v-spacer />
          <v-btn text @click="dialog = false">Cancel</v-btn>
          <v-btn color="primary" :loading="saving" @click="saveBookmark">{{ editItem ? 'Update' : 'Save' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- Delete Confirmation -->
    <v-dialog v-model="deleteDialog" max-width="400">
      <v-card rounded="xl">
        <v-card-title class="text-error">Delete Bookmark</v-card-title>
        <v-divider />
        <v-card-text class="pa-4">
          Are you sure you want to delete this bookmark?<br>
          <strong>{{ deleteItem?.url }}</strong>
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
import { ref, computed, onMounted, nextTick } from 'vue'
import { useResizableColumns } from '../composables/useResizableColumns'

const API_BASE = '/api'

const bookmarks = ref([])
const loading = ref(false)
const saving = ref(false)
const search = ref('')
const dialog = ref(false)
const deleteDialog = ref(false)
const editItem = ref(null)
const deleteItem = ref(null)
const form = ref({ url: '', description: '', tags: '' })

// Default widths (pixels) — persisted to localStorage via composable
const headers = [
  { title: 'URL', key: 'url' },
  { title: 'Description', key: 'description' },
  { title: 'Tags', key: 'tags' },
  { title: 'Added', key: 'timestamp' },
  { title: 'Actions', key: 'actions', sortable: false },
]

const filteredBookmarks = computed(() => {
  if (!search.value) return bookmarks.value
  const q = search.value.toLowerCase()
  return bookmarks.value.filter(bm =>
    bm.url.toLowerCase().includes(q) ||
    (bm.description && bm.description.toLowerCase().includes(q)) ||
    (bm.tags && bm.tags.toLowerCase().includes(q))
  )
})

async function loadBookmarks() {
  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/bookmarks`)
    const data = await res.json()
    bookmarks.value = data.bookmarks || []
  } catch (e) {
    console.error('Failed to load bookmarks:', e)
  } finally {
    loading.value = false
  }
}

function openDialog(item) {
  editItem.value = item || null
  form.value = item
    ? { url: item.url, description: item.description, tags: item.tags }
    : { url: '', description: '', tags: '' }
  dialog.value = true
}

async function saveBookmark() {
  if (!form.value.url) return
  saving.value = true
  try {
    const method = editItem.value ? 'PUT' : 'POST'
    const url = editItem.value
      ? `${API_BASE}/bookmarks/${editItem.value.id}`
      : `${API_BASE}/bookmarks`

    const res = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    if (!res.ok) throw new Error(await res.text())
    dialog.value = false
    await loadBookmarks()
  } catch (e) {
    console.error('Failed to save bookmark:', e)
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
    const res = await fetch(`${API_BASE}/bookmarks/${deleteItem.value.id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await res.text())
    deleteDialog.value = false
    await loadBookmarks()
  } catch (e) {
    console.error('Failed to delete bookmark:', e)
  } finally {
    saving.value = false
  }
}

function parseTags(tags) {
  if (!tags) return []
  return tags.split(',').map(t => t.trim()).filter(Boolean)
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

// Initialize resizable columns
const { initResizers } = useResizableColumns('bookmarks')
onMounted(async () => {
  await loadBookmarks()
  await nextTick()
  setTimeout(() => {
    initResizers()
  }, 300)
})
</script>

<style scoped>
.url-link {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>

<style>
/* Global styles for resizable table columns — must be unscoped to affect Vuetify internals */
.resizable-table th {
  position: relative;
  user-select: none;
}

.col-resizer {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: col-resize;
  background: transparent;
  transition: background 0.15s;
  z-index: 1;
}

.col-resizer:hover,
.col-resizer:active {
  background: rgba(var(--v-theme-primary), 0.3);
}

.resizable-table td {
  overflow: hidden;
  white-space: nowrap;
}
</style>
