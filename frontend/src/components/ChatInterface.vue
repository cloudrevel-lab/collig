<script setup>
import { ref, onMounted, nextTick } from 'vue'

const messages = ref([
  { id: 1, role: 'assistant', content: 'Hello! I am Collig, your AI co-worker. How can I assist you today?' }
])
const newMessage = ref('')
const isLoading = ref(false)
const chatContainer = ref(null)

const scrollToBottom = async () => {
  await nextTick()
  if (chatContainer.value) {
    chatContainer.value.scrollTop = chatContainer.value.scrollHeight
  }
}

const sendMessage = async () => {
  if (!newMessage.value.trim() || isLoading.value) return

  const userMsg = newMessage.value.trim()
  messages.value.push({
    id: Date.now(),
    role: 'user',
    content: userMsg
  })
  newMessage.value = ''
  isLoading.value = true
  await scrollToBottom()

  try {
    const response = await fetch('http://localhost:8000/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message: userMsg }),
    })

    if (!response.ok) {
      throw new Error('Network response was not ok')
    }

    const data = await response.json()
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      content: data.response
    })
  } catch (error) {
    console.error('Error:', error)
    messages.value.push({
      id: Date.now() + 1,
      role: 'assistant',
      content: 'Sorry, I encountered an error connecting to the server. Please ensure the backend is running.'
    })
  } finally {
    isLoading.value = false
    await scrollToBottom()
  }
}
</script>

<template>
  <div class="chat-interface">
    <div class="header">
      <h1>Collig AI</h1>
      <div class="status-badge">Online</div>
    </div>
    
    <div class="messages" ref="chatContainer">
      <div v-for="msg in messages" :key="msg.id" :class="['message', msg.role]">
        <div class="message-content">
          <div class="role-label">{{ msg.role === 'user' ? 'You' : 'Collig' }}</div>
          <p>{{ msg.content }}</p>
        </div>
      </div>
      <div v-if="isLoading" class="message assistant">
        <div class="message-content loading">
          <span>Thinking...</span>
        </div>
      </div>
    </div>

    <div class="input-area">
      <input 
        v-model="newMessage" 
        @keyup.enter="sendMessage"
        placeholder="Type a command or ask a question..." 
        type="text" 
        :disabled="isLoading"
      />
      <button @click="sendMessage" :disabled="isLoading || !newMessage.trim()">Send</button>
    </div>
  </div>
</template>

<style scoped>
.chat-interface {
  display: flex;
  flex-direction: column;
  height: 100vh;
  max-width: 800px;
  margin: 0 auto;
  background-color: #1e1e1e;
  color: #e0e0e0;
  font-family: 'Inter', sans-serif;
}

.header {
  padding: 1rem;
  background-color: #2d2d2d;
  border-bottom: 1px solid #3d3d3d;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header h1 {
  margin: 0;
  font-size: 1.2rem;
  color: #fff;
}

.status-badge {
  background-color: #10b981;
  color: #fff;
  padding: 0.25rem 0.5rem;
  border-radius: 12px;
  font-size: 0.8rem;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.message {
  display: flex;
  max-width: 80%;
}

.message.user {
  align-self: flex-end;
}

.message.assistant {
  align-self: flex-start;
}

.message-content {
  padding: 0.8rem 1rem;
  border-radius: 12px;
  background-color: #3d3d3d;
  box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.message.user .message-content {
  background-color: #1e40af;
  color: white;
  border-bottom-right-radius: 2px;
}

.message.assistant .message-content {
  background-color: #4b5563;
  color: white;
  border-bottom-left-radius: 2px;
}

.role-label {
  font-size: 0.7rem;
  opacity: 0.7;
  margin-bottom: 0.2rem;
}

.input-area {
  padding: 1rem;
  background-color: #2d2d2d;
  border-top: 1px solid #3d3d3d;
  display: flex;
  gap: 0.5rem;
}

input {
  flex: 1;
  padding: 0.8rem;
  border-radius: 8px;
  border: 1px solid #4b5563;
  background-color: #1e1e1e;
  color: white;
  outline: none;
}

input:focus {
  border-color: #1e40af;
}

button {
  padding: 0.8rem 1.5rem;
  background-color: #1e40af;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background-color 0.2s;
}

button:hover:not(:disabled) {
  background-color: #1e3a8a;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
