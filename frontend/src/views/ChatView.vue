<template>
  <div class="chat-container">
    <v-row align="center" class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-0">Chat</h1>
      </v-col>
      <v-col cols="auto">
        <v-chip size="small" :color="llmProvider ? 'success' : 'grey'">
          <v-icon size="small" start>mdi-circle</v-icon>
          {{ llmProvider || 'Not Connected' }}
        </v-chip>
      </v-col>
    </v-row>

    <v-card rounded="xl" elevation="2" class="chat-card">
      <!-- Messages Area -->
      <v-card-text class="messages-area" ref="messagesContainer">
        <div v-if="messages.length === 0" class="empty-state text-center">
          <v-icon size="80" color="grey-darken-1">mdi-chat-outline</v-icon>
          <p class="text-h6 mt-4 text-medium-emphasis">Start a conversation</p>
          <p class="text-body-2 text-medium-emission">Send a message to get started</p>
        </div>

        <div
          v-for="(msg, idx) in messages"
          :key="idx"
          :class="['message-bubble', msg.role]"
        >
          <div class="message-role">
            {{ msg.role === 'user' ? 'You' : 'Collig' }}
          </div>
          <div class="message-content">
            <template v-if="msg.role === 'ai'">
              <!-- Render markdown for AI responses -->
              <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
              <div class="message-tokens" v-if="msg.tokens">
                ({{ msg.tokens.total }} tokens)
              </div>
            </template>
            <template v-else>
              {{ msg.content }}
            </template>
          </div>
        </div>

        <div v-if="loading" class="message-bubble ai">
          <div class="message-role">Collig</div>
          <div class="message-content">
            <v-progress-circular indeterminate size="20" width="2" color="primary" />
            <span class="ml-2 text-medium-emission">Thinking...</span>
          </div>
        </div>
      </v-card-text>

      <v-divider />

      <!-- Input Area -->
      <v-card-actions class="pa-3 input-area">
        <v-textarea
          v-model="input"
          placeholder="Type your message..."
          variant="outlined"
          density="comfortable"
          rows="1"
          auto-grow
          max-rows="6"
          hide-details
          :disabled="loading"
          @keydown.enter.exact.prevent="sendMessage"
          class="flex-grow-1"
        />
        <v-btn
          color="primary"
          :loading="loading"
          :disabled="!input.trim()"
          icon="mdi-send"
          @click="sendMessage"
          class="ml-2 align-self-end"
          size="large"
        />
      </v-card-actions>
    </v-card>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import { marked } from 'marked'

const API_BASE = '/api'

const messages = ref([])
const input = ref('')
const loading = ref(false)
const messagesContainer = ref(null)
const llmProvider = ref('')

function renderMarkdown(text) {
  try {
    return marked.parse(text || '')
  } catch {
    return text
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  // Add user message
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  scrollToBottom()

  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
    const data = await res.json()

    const aiMsg = {
      role: 'ai',
      content: data.response || 'No response received.',
    }
    if (data.total_tokens) {
      aiMsg.tokens = {
        prompt: data.prompt_tokens,
        completion: data.completion_tokens,
        total: data.total_tokens,
      }
    }
    messages.value.push(aiMsg)
  } catch (e) {
    messages.value.push({
      role: 'ai',
      content: `Error: ${e.message}`,
    })
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

onMounted(() => {
  // Detect provider from health or config
  llmProvider.value = 'AI Assistant'
})
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 120px);
}

.chat-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  scroll-behavior: smooth;
}

.empty-state {
  padding: 60px 20px;
}

.message-bubble {
  margin-bottom: 16px;
  max-width: 80%;
}

.message-bubble.user {
  margin-left: auto;
}

.message-bubble.ai {
  margin-right: auto;
}

.message-role {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: rgba(var(--v-theme-on-surface), 0.5);
  margin-bottom: 4px;
}

.message-content {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
}

.message-bubble.user .message-content {
  background: rgba(var(--v-theme-primary), 0.12);
  border-bottom-right-radius: 4px;
}

.message-bubble.ai .message-content {
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-bottom-left-radius: 4px;
}

.message-tokens {
  font-size: 0.7rem;
  color: rgba(var(--v-theme-on-surface), 0.4);
  margin-top: 4px;
}

.input-area {
  padding: 12px;
}

.markdown-body :first-child {
  margin-top: 0;
}
.markdown-body :last-child {
  margin-bottom: 0;
}

.markdown-body p {
  margin-bottom: 8px;
}

.markdown-body code {
  background: rgba(var(--v-theme-on-surface), 0.08);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.markdown-body pre {
  background: rgba(var(--v-theme-on-surface), 0.1);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.markdown-body pre code {
  background: none;
  padding: 0;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 24px;
}

.markdown-body table {
  border-collapse: collapse;
  margin: 8px 0;
}

.markdown-body th,
.markdown-body td {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  padding: 6px 12px;
}
</style>
