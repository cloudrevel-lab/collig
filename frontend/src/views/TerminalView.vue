<template>
  <div :class="['terminal-page', { 'terminal-page--standalone': standalone }]">
    <v-row align="center" class="mb-3">
      <v-col>
        <h1 class="text-h5 mb-1">Terminal</h1>
        <p class="text-body-2 text-medium-emphasis mb-0">
          The real Collig CLI in a browser. Commands, colours, prompt_toolkit menus and
          <code>!shell</code> all work inside an isolated container.
        </p>
      </v-col>
      <v-col cols="auto" class="d-flex align-center flex-wrap gap-2">
        <v-chip size="small" :color="status.ready ? 'success' : 'warning'" variant="tonal">
          <v-icon size="small" start>{{ status.ready ? 'mdi-shield-check' : 'mdi-alert-outline' }}</v-icon>
          {{ status.ready ? 'Sandbox ready' : 'Not ready' }}
        </v-chip>
        <v-chip size="small" variant="tonal" color="info">
          <v-icon size="small" start>mdi-docker</v-icon>
          {{ status.backend || 'docker' }}
        </v-chip>
        <v-chip size="small" variant="tonal" color="grey">
          <v-icon size="small" start>mdi-lan-disconnect</v-icon>
          network: {{ status.network || 'internal' }}
        </v-chip>
        <v-btn
          size="small"
          variant="outlined"
          color="primary"
          prepend-icon="mdi-play"
          :loading="connecting"
          :disabled="connecting || !!sessionId"
          @click="connect"
        >
          Connect
        </v-btn>
        <v-btn
          size="small"
          variant="outlined"
          prepend-icon="mdi-refresh"
          :disabled="connecting || !sessionId"
          @click="reconnect"
        >
          Reconnect
        </v-btn>
        <v-btn
          size="small"
          variant="outlined"
          color="error"
          prepend-icon="mdi-close"
          :disabled="!sessionId"
          @click="closeSession"
        >
          Close
        </v-btn>
      </v-col>
    </v-row>

    <v-alert
      v-if="status.enabled === false"
      type="info"
      variant="tonal"
      class="mb-3"
      density="compact"
    >
      The web terminal is disabled. Set <code>COLLIG_TERMINAL_ENABLED=1</code> and restart the server.
    </v-alert>

    <v-alert
      v-else-if="status.ready === false"
      type="warning"
      variant="tonal"
      class="mb-3"
      density="compact"
    >
      {{ status.reason || 'The terminal backend is not ready.' }}
      <div class="text-caption mt-1">
        Build the sandbox image once with <code>make terminal-image</code>.
      </div>
    </v-alert>

    <v-alert
      v-else-if="error"
      type="error"
      variant="tonal"
      class="mb-3"
      density="compact"
      closable
      @click:close="error = ''"
    >
      {{ error }}
    </v-alert>

    <v-alert
      v-if="authRequired && !sessionId"
      type="info"
      variant="tonal"
      class="mb-3"
      density="compact"
    >
      This server is not accepting terminal access from this address without a token.
      Ask the operator for the value of <code>COLLIG_TERMINAL_TOKEN</code>.
    </v-alert>

    <v-card v-if="authRequired && !sessionId" class="mb-3 pa-4" variant="outlined">
      <div class="d-flex flex-wrap align-center gap-3">
        <v-text-field
          v-model="token"
          label="Terminal access token"
          variant="outlined"
          density="compact"
          type="password"
          hide-details
          class="token-field"
          @keyup.enter="connect"
        />
        <v-btn color="primary" :loading="connecting" :disabled="!token" @click="connect">
          Connect
        </v-btn>
      </div>
    </v-card>

    <v-theme-provider :theme="terminalTheme">
      <v-card :class="['terminal-card', 'terminal-window--' + windowMode]" rounded="lg" elevation="3">
      <div class="terminal-toolbar">
        <div class="terminal-toolbar-left">
          <span class="terminal-dot red"></span>
          <span class="terminal-dot amber"></span>
          <span class="terminal-dot green"></span>
          <span class="terminal-title">{{ sessionId ? 'collig — sandbox ' + sessionId.substring(0, 8) : 'collig — not connected' }}</span>
          <span class="window-mode-label">{{ currentWindowLabel }}</span>
        </div>
        <div class="terminal-toolbar-right">
          <div class="terminal-window-controls" role="group" aria-label="Terminal window layout">
            <v-btn
              v-for="mode in windowModes"
              :key="mode.id"
              :icon="mode.icon"
              size="x-small"
              variant="text"
              :color="windowMode === mode.id ? 'primary' : 'white'"
              :class="['window-control-btn', { 'window-control-active': windowMode === mode.id }]"
              :title="mode.label"
              :aria-label="mode.label"
              :aria-pressed="windowMode === mode.id"
              @click="setWindowMode(mode.id)"
            />
          </div>
          <v-btn
            :icon="isDark ? 'mdi-white-balance-sunny' : 'mdi-weather-night'"
            size="x-small"
            variant="text"
            color="white"
            :title="isDark ? 'Switch terminal to light' : 'Switch terminal to dark'"
            :aria-label="isDark ? 'Switch terminal to light' : 'Switch terminal to dark'"
            class="terminal-theme-btn"
            @click="toggleTerminalTheme"
          />
          <div class="terminal-hint">
            <v-icon size="small">mdi-folder-lock-outline</v-icon>
            /workspace only · no host filesystem
          </div>
        </div>
      </div>
        <div ref="terminalEl" class="terminal-host"></div>
      </v-card>
    </v-theme-provider>

    <div class="terminal-footnote">
      <strong>Security model:</strong> each browser session runs the CLI in a fresh
      Docker container with a read-only root, only its own <code>/workspace</code> and
      <code>$HOME</code> mounted, no capabilities, and an internal-only network. The
      provider API key is never inside the sandbox; a per-session relay and proxy
      inject it on the host. <code>!ls /home</code> sees the container's own home,
      not the server's users.
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { useTerminalTheme } from '../composables/useTerminalTheme'

defineProps({
  standalone: { type: Boolean, default: false },
})

const { terminalTheme, isDark, toggle: toggleTerminalThemeState } = useTerminalTheme()

const WINDOW_STORAGE_KEY = 'collig-terminal-window-mode'
const windowModes = [
  { id: 'normal', icon: 'mdi-window-restore', label: 'Restore normal window', state: 'Normal' },
  { id: 'max', icon: 'mdi-window-maximize', label: 'Maximize', state: 'Maximized' },
  { id: 'left', icon: 'mdi-dock-left', label: 'Snap to left half', state: 'Left half' },
  { id: 'right', icon: 'mdi-dock-right', label: 'Snap to right half', state: 'Right half' },
  { id: 'bottom', icon: 'mdi-dock-bottom', label: 'Snap to bottom half', state: 'Bottom half' },
]
const validWindowModes = new Set(windowModes.map((mode) => mode.id))

function loadWindowMode() {
  try {
    const saved = localStorage.getItem(WINDOW_STORAGE_KEY)
    if (saved && validWindowModes.has(saved)) return saved
  } catch (_) {
    // localStorage can be unavailable in hardened/private browsers.
  }
  return 'normal'
}

function fitTerminalWindow() {
  if (!fitAddon || !terminalEl.value || terminalEl.value.clientWidth <= 0) return
  try {
    fitAddon.fit()
  } catch (_) {
    // Ignore transient zero-size layouts while a snap transition runs.
  }
}

const terminalEl = ref(null)
const status = ref({})
const token = ref(sessionStorage.getItem('collig-terminal-token') || '')
const authRequired = ref(false)
const connecting = ref(false)
const error = ref('')
const sessionId = ref('')
const socketState = ref('idle')
const windowMode = ref(loadWindowMode())
const currentWindowLabel = computed(
  () => windowModes.find((mode) => mode.id === windowMode.value)?.state || 'Normal',
)

function setWindowMode(mode) {
  if (!validWindowModes.has(mode)) return
  windowMode.value = mode
  try {
    localStorage.setItem(WINDOW_STORAGE_KEY, mode)
  } catch (_) {
    // Ignore persistence failures; the layout still applies for this view.
  }
  nextTick(() => {
    requestAnimationFrame(() => {
      fitTerminalWindow()
      // A second pass catches the final flex/card dimensions after the fixed
      // positioning and any CSS transition settle.
      setTimeout(fitTerminalWindow, 120)
    })
  })
}

let term = null
let fitAddon = null
let socket = null
let resizeObserver = null
let pingTimer = null
let dataDisposable = null
let resizeDisposable = null

function apiHeaders() {
  return {
    'Content-Type': 'application/json',
    'X-Collig-Terminal-Token': token.value,
  }
}

function xtermTheme() {
  const dark = isDark.value
  return dark
    ? {
        background: '#0d1117',
        foreground: '#d7dde8',
        cursor: '#7ee787',
        selectionBackground: '#264f78',
        black: '#0d1117',
        brightBlack: '#6e7681',
        red: '#ff7b72',
        green: '#7ee787',
        yellow: '#d29922',
        blue: '#79c0ff',
        magenta: '#d2a8ff',
        cyan: '#56d4dd',
        white: '#d7dde8',
        brightWhite: '#ffffff',
      }
    : {
        background: '#fbfbfd',
        foreground: '#24292f',
        cursor: '#1f6feb',
        selectionBackground: '#c8e1ff',
        black: '#24292f',
        brightBlack: '#57606a',
        red: '#cf222e',
        green: '#116329',
        yellow: '#9a6700',
        blue: '#0969da',
        magenta: '#8250df',
        cyan: '#1b7c83',
        white: '#f6f8fa',
        brightWhite: '#ffffff',
      }
}

function applyXtermTheme() {
  if (!term) return
  term.options.theme = xtermTheme()
  term.refresh(0, Math.max(0, term.rows - 1))
}

function toggleTerminalTheme() {
  toggleTerminalThemeState()
  nextTick(applyXtermTheme)
}

function ensureTerminal() {
  if (term) return
  term = new Terminal({
    convertEol: false,
    cursorBlink: true,
    scrollback: 5000,
    fontFamily: '"SFMono-Regular", "Cascadia Code", "Roboto Mono", Menlo, monospace',
    fontSize: 13,
    lineHeight: 1.25,
    theme: xtermTheme(),
    allowProposedApi: true,
  })
  fitAddon = new FitAddon()
  term.loadAddon(fitAddon)
  term.open(terminalEl.value)
  fitAddon.fit()

  dataDisposable = term.onData((data) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'input', data }))
    }
  })
  resizeDisposable = term.onResize(({ cols, rows }) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'resize', cols, rows }))
    }
  })
}

async function loadBootstrap() {
  try {
    const res = await fetch('/api/terminal/bootstrap')
    const data = await res.json()
    status.value = data
    if (data.token) {
      token.value = data.token
      authRequired.value = false
    } else {
      authRequired.value = !token.value
    }
    if ((data.token || token.value) && data.ready) {
      await nextTick()
      await connect()
    }
  } catch (err) {
    error.value = 'Could not reach the terminal API: ' + err
  }
}

async function connect() {
  if (connecting.value) return
  if (!token.value) {
    authRequired.value = true
    return
  }
  if (!status.value.ready) {
    error.value = status.value.reason || 'Terminal backend is not ready.'
    return
  }
  connecting.value = true
  error.value = ''
  sessionStorage.setItem('collig-terminal-token', token.value)
  try {
    await nextTick()
    ensureTerminal()
    fitAddon.fit()
    const cols = term.cols || 120
    const rows = term.rows || 32
    const res = await fetch('/api/terminal/sessions', {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ cols, rows }),
    })
    if (res.status === 401) {
      authRequired.value = true
      error.value = 'The terminal access token was rejected.'
      return
    }
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      error.value = data.detail || ('Could not create terminal session (' + res.status + ')')
      return
    }
    sessionId.value = data.session_id
    term.reset()
    term.writeln('\x1b[2mConnecting to sandbox ' + data.session_id.substring(0, 8) + '…\x1b[0m')
    openSocket(data.ticket, cols, rows)
  } catch (err) {
    error.value = 'Could not start terminal: ' + err
  } finally {
    connecting.value = false
  }
}

function openSocket(ticket, cols, rows) {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url =
    scheme + '//' + window.location.host + '/api/terminal/ws?ticket=' +
    encodeURIComponent(ticket) + '&cols=' + cols + '&rows=' + rows
  socket = new WebSocket(url)
  socket.binaryType = 'arraybuffer'
  socket.onopen = () => {
    socketState.value = 'open'
    if (pingTimer) clearInterval(pingTimer)
    pingTimer = setInterval(() => {
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: 'ping' }))
      }
    }, 30000)
  }
  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      term.write(new Uint8Array(event.data))
      return
    }
    try {
      const payload = JSON.parse(event.data)
      if (payload.type === 'error') {
        error.value = payload.message
      } else if (payload.type === 'timeout') {
        term.writeln('\r\n\x1b[33mSession closed after the idle timeout.\x1b[0m')
      } else if (payload.type === 'exit') {
        term.writeln('\r\n\x1b[2mSession ended.\x1b[0m')
      }
    } catch (_) {
      // Ignore non-JSON control frames.
    }
  }
  socket.onerror = () => {
    socketState.value = 'error'
    error.value = 'Terminal connection error.'
  }
  socket.onclose = () => {
    socketState.value = 'closed'
    if (pingTimer) clearInterval(pingTimer)
    pingTimer = null
  }
}

async function reconnect() {
  if (socket) {
    socket.close()
    socket = null
  }
  if (!sessionId.value) {
    await connect()
    return
  }
  try {
    const res = await fetch(
      '/api/terminal/sessions/' + encodeURIComponent(sessionId.value) + '/ticket',
      { method: 'POST', headers: apiHeaders(), body: '{}' },
    )
    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      error.value = data.detail || 'Could not reconnect.'
      return
    }
    ensureTerminal()
    fitAddon.fit()
    openSocket(data.ticket, term.cols || 120, term.rows || 32)
  } catch (err) {
    error.value = 'Could not reconnect: ' + err
  }
}

async function closeSession() {
  if (socket) {
    socket.close()
    socket = null
  }
  const sid = sessionId.value
  sessionId.value = ''
  if (pingTimer) clearInterval(pingTimer)
  if (sid) {
    try {
      await fetch('/api/terminal/sessions/' + encodeURIComponent(sid), {
        method: 'DELETE',
        headers: apiHeaders(),
      })
    } catch (_) {
      // Best-effort; the server also reaps idle sessions.
    }
  }
  if (term) {
    term.reset()
    term.writeln('\x1b[2mDisconnected. Press Connect to start a new sandbox.\x1b[0m')
  }
}

onMounted(async () => {
  await nextTick()
  resizeObserver = new ResizeObserver(() => {
    if (fitAddon && terminalEl.value && terminalEl.value.clientWidth > 0) {
      try {
        fitAddon.fit()
      } catch (_) {
        // Ignore transient zero-size layouts.
      }
    }
  })
  if (terminalEl.value) resizeObserver.observe(terminalEl.value)
  await loadBootstrap()
})

onBeforeUnmount(() => {
  if (socket) socket.close()
  if (pingTimer) clearInterval(pingTimer)
  if (resizeObserver) resizeObserver.disconnect()
  if (dataDisposable) dataDisposable.dispose()
  if (resizeDisposable) resizeDisposable.dispose()
  if (term) term.dispose()
  term = null
})
</script>

<style scoped>
.terminal-page {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 150px);
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow: hidden;
}
.terminal-page--standalone {
  min-height: calc(100vh - 112px);
}
.terminal-page--standalone .terminal-host {
  height: calc(100vh - 260px);
  max-height: calc(100vh - 260px);
}
.gap-2 {
  gap: 8px;
}
.gap-3 {
  gap: 12px;
}
.terminal-card {
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #0d1117;
  width: 100%;
  min-width: 0;
}
/* Snap modes are intentionally viewport-fixed: like a desktop window, they
   float above the admin chrome and can be restored from the title bar. */
.terminal-window--max,
.terminal-window--left,
.terminal-window--right,
.terminal-window--bottom {
  position: fixed;
  z-index: 3000;
  margin: 0 !important;
  border-radius: 0 !important;
  max-width: none;
  max-height: none;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.5);
}
.terminal-window--max {
  inset: 0;
  width: 100vw;
  height: 100vh;
}
.terminal-window--left {
  top: 0;
  left: 0;
  width: 50vw;
  height: 100vh;
  border-right: 1px solid rgba(255, 255, 255, 0.12);
}
.terminal-window--right {
  top: 0;
  right: 0;
  width: 50vw;
  height: 100vh;
  border-left: 1px solid rgba(255, 255, 255, 0.12);
}
.terminal-window--bottom {
  left: 0;
  bottom: 0;
  width: 100vw;
  height: 50vh;
  border-top: 1px solid rgba(255, 255, 255, 0.12);
}
.terminal-window--max .terminal-host,
.terminal-window--left .terminal-host,
.terminal-window--right .terminal-host,
.terminal-window--bottom .terminal-host {
  height: auto;
  max-height: none;
  min-height: 0;
}
@media (max-width: 760px) {
  .terminal-window--left,
  .terminal-window--right {
    width: 100vw;
  }
  .terminal-window--bottom {
    height: 60vh;
  }
  .terminal-hint,
  .window-mode-label {
    display: none;
  }
}
.terminal-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 10px 8px 14px;
  background: #161b22;
  color: #c9d1d9;
  font-size: 12px;
}
.terminal-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex: 1;
}
.terminal-toolbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.terminal-window-controls {
  display: flex;
  align-items: center;
  gap: 1px;
  padding: 1px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
}
.terminal-window-controls :deep(.v-btn) {
  width: 26px;
  height: 26px;
  min-width: 26px;
  opacity: 0.72;
}
.terminal-window-controls :deep(.v-btn.window-control-active) {
  opacity: 1;
  background: rgba(var(--v-theme-primary), 0.22);
}
.window-mode-label {
  margin-left: 4px;
  font-size: 11px;
  opacity: 0.5;
  white-space: nowrap;
}
.terminal-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  display: inline-block;
}
.terminal-dot.red { background: #ff5f56; }
.terminal-dot.amber { background: #ffbd2e; }
.terminal-dot.green { background: #27c93f; }
.terminal-title {
  margin-left: 6px;
  opacity: 0.8;
  font-family: Menlo, monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.terminal-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  opacity: 0.7;
}
.terminal-host {
  flex: 1;
  min-height: 460px;
  min-width: 0;
  height: calc(100vh - 310px);
  max-height: calc(100vh - 310px);
  overflow: hidden;
  padding: 8px 4px 8px 12px;
}
.token-field {
  min-width: 320px;
  max-width: 460px;
}
.terminal-footnote {
  margin-top: 12px;
  padding: 10px 14px;
  border-left: 3px solid rgb(var(--v-theme-primary));
  background: rgba(var(--v-theme-primary), 0.06);
  font-size: 12px;
  line-height: 1.5;
}
</style>
