<template>
  <div class="chat-page">
    <v-row align="center" class="mb-3">
      <v-col>
        <h1 class="text-h5 mb-0">
          Chat
          <v-chip v-if="currentSessionId" size="small" class="ml-2" variant="tonal" color="primary">
            Session: {{ currentSessionId.substring(0, 8) }}...
          </v-chip>
          <v-chip v-else size="small" class="ml-2" variant="tonal" color="grey">
            New session (will be created on first message)
          </v-chip>
        </h1>
        <p v-if="sessionStats.summary?.interaction_count" class="text-body-2 text-medium-emphasis mt-1 mb-0">
          {{ sessionStats.summary.interaction_count }} turns · {{ sessionStats.summary.total_tokens || 0 }} tokens total
        </p>
      </v-col>
      <v-col cols="auto" class="d-flex gap-2 align-center">
        <v-chip size="small" :color="llmProvider ? 'success' : 'grey'">
          <v-icon size="small" start>mdi-circle</v-icon>
          {{ llmProvider || 'Not Connected' }}
        </v-chip>
        <v-btn size="small" variant="outlined" :to="`/sessions`" prepend-icon="mdi-format-list-bulleted">
          All Sessions
        </v-btn>
        <v-btn
          size="small"
          :variant="showTrace ? 'flat' : 'outlined'"
          :color="showTrace ? 'primary' : undefined"
          prepend-icon="mdi-code-tags"
          @click="toggleTrace"
        >
          {{ showTrace ? 'Hide Trace' : 'Show Trace' }}
        </v-btn>
      </v-col>
    </v-row>

    <v-row no-gutters class="chat-main-row" style="height: calc(100vh - 200px);">
      <!-- Chat Column -->
      <v-col :cols="showTrace ? chatCols : 12" class="pe-0 pe-md-2">
        <v-card rounded="xl" elevation="2" class="chat-card h-100 d-flex flex-column">
          <!-- Messages -->
          <v-card-text class="messages-area flex-grow-1" ref="messagesContainer">
            <div v-if="messages.length === 0" class="empty-state text-center">
              <v-icon size="80" color="grey-darken-1">mdi-chat-outline</v-icon>
              <p class="text-h6 mt-4 text-medium-emphasis">Start a conversation</p>
              <p class="text-body-2 text-medium-emphasis">
                {{ currentSessionId ? 'Continue your previous work' : 'Send a message to get started' }}
              </p>
            </div>

            <div
              v-for="(msg, idx) in messages"
              :key="idx"
              :class="[
                'message-bubble',
                msg.role,
                {
                  'clickable-bot': msg.role === 'ai' && msg.invocation_id,
                  'trace-linked-active':
                    msg.role === 'ai' &&
                    msg.invocation_id &&
                    selectedInvocationId === msg.invocation_id,
                },
              ]"
              :data-invocation-id="msg.invocation_id || null"
              @click="onMessageBubbleClick(msg, idx, $event)"
            >
              <div class="message-header">
                <span class="message-role">
                  {{ msg.role === 'user' ? 'You' : 'Collig' }}
                </span>
                <span v-if="msg.timestamp" class="message-time">{{ formatTimestamp(msg.timestamp) }}</span>
                <v-btn
                  v-if="msg.role === 'ai' && msg.hasTrace"
                  size="x-small"
                  variant="text"
                  class="trace-btn"
                  :icon="activeTraceForIdx === idx ? 'mdi-chevron-up' : 'mdi-chevron-down'"
                  @click.stop="toggleMessageTrace(idx, msg)"
                >
                  Inline Trace
                </v-btn>
              </div>
              <div class="message-content">
                <template v-if="msg.role === 'ai'">
                  <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
                  <div class="message-meta-row">
                    <div class="message-tokens" v-if="msg.tokens">
                      <v-chip size="x-small" variant="tonal">
                        prompt: {{ msg.tokens.prompt }} · completion: {{ msg.tokens.completion }} · total: {{ msg.tokens.total }}
                      </v-chip>
                    </div>
                    <div v-if="msg.invocation_id" class="message-trace-hint">
                      <v-icon size="14" class="me-1">mdi-mouse-pointer-click</v-icon>
                      Click to open trace
                    </div>
                  </div>
                </template>
                <template v-else>
                  {{ msg.content }}
                </template>
              </div>

              <!-- Inline trace panel for this message -->
              <div v-if="msg.role === 'ai' && activeTraceForIdx === idx && messageTraces[idx]"
                   class="inline-trace">
                <MessageTraceViewer :trace="messageTraces[idx]" />
              </div>
            </div>

            <div v-if="loading" class="message-bubble ai">
              <div class="message-header">
                <span class="message-role">Collig</span>
              </div>
              <div class="message-content">
                <v-progress-circular indeterminate size="20" width="2" color="primary" />
                <span class="ml-2 text-medium-emphasis">Thinking...</span>
              </div>
            </div>
          </v-card-text>

          <v-divider />

          <!-- Input -->
          <v-card-actions class="pa-3 input-area">
            <v-textarea
              v-model="input"
              placeholder="Type your message... (Shift+Enter for newline)"
              variant="outlined"
              density="comfortable"
              rows="1"
              auto-grow
              max-rows="8"
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
      </v-col>

      <!-- Trace Sidebar Column -->
      <v-col v-if="showTrace" :cols="traceCols" class="ps-0 ps-md-2">
        <v-card rounded="xl" elevation="2" class="trace-card h-100 d-flex flex-column">
          <v-card-title class="pt-3 pb-2 text-h6 d-flex align-center">
            <v-icon class="me-2">mdi-code-tags</v-icon>
            Trace &amp; LLM Calls
            <v-spacer />
            <v-btn size="x-small" variant="text" icon="mdi-refresh" :disabled="!currentSessionId" @click="loadTraces">
              Refresh
            </v-btn>
          </v-card-title>
          <v-divider />

          <v-tabs v-model="traceTab" density="comfortable" align-tabs="start">
            <v-tab value="invocations">Per Turn ({{ traceSummaries.length }})</v-tab>
            <v-tab value="session-stats">Session Stats</v-tab>
          </v-tabs>
          <v-divider />

          <!-- Invocations Tab (plain conditional render, NOT v-window — v-window keeps inactive item trees alive during transitions) -->
          <div
            v-if="traceTab === 'invocations'"
            class="flex-grow-1 d-flex flex-column overflow-hidden"
          >
            <div v-if="traceSummaries.length === 0" class="text-center pa-6 text-medium-emphasis">
              No traces yet for this session.<br>Send a message to see LLM and tool call details.
            </div>
            <template v-else>
              <v-list density="compact" lines="two" class="trace-summaries-list overflow-y-auto" style="flex-shrink:0;max-height:35%;min-height:120px;">
                <v-list-item
                  v-for="(sum, sIdx) in traceSummaries"
                  :key="sum.invocation_id"
                  :active="selectedInvocationId === sum.invocation_id"
                  link
                  @click="selectInvocation(sum.invocation_id)"
                >
                  <template v-slot:prepend>
                    <v-avatar size="36" :color="getInvocationColor(sum)" variant="tonal">
                      <v-icon size="20">{{ getInvocationIcon(sum) }}</v-icon>
                    </v-avatar>
                  </template>
                  <v-list-item-title class="text-truncate">
                    Turn {{ traceSummaries.length - sIdx }}
                    <span class="text-medium-emphasis font-weight-regular" style="font-size:0.8em;">
                      · {{ sum.total_tokens || 0 }} tok
                    </span>
                  </v-list-item-title>
                  <v-list-item-subtitle class="text-truncate">
                    {{ sum.user_message_preview || '(empty)' }}
                  </v-list-item-subtitle>
                  <template v-slot:append>
                    <div class="text-right">
                      <v-chip v-if="sum.llm_call_count" size="x-small" variant="tonal" color="primary" class="mb-1">
                        {{ sum.llm_call_count }} LLM
                      </v-chip>
                      <v-chip v-if="sum.tool_call_count" size="x-small" variant="tonal" color="success" class="d-block">
                        {{ sum.tool_call_count }} tools
                      </v-chip>
                    </div>
                  </template>
                </v-list-item>
              </v-list>
              <v-divider />
            </template>
            <div class="trace-detail flex-grow-1 overflow-y-auto pa-3">
              <MessageTraceViewer v-if="selectedInvocationDetail" :trace="selectedInvocationDetail" />
              <div v-else class="text-medium-emphasis text-center pa-4">
                Select a turn above to see its detailed trace.
              </div>
            </div>
          </div>

          <!-- Session Stats Tab (plain conditional render — same pattern, NO v-window, no transition overlap) -->
          <div
            v-else-if="traceTab === 'session-stats'"
            class="flex-grow-1 overflow-y-auto pa-4"
          >
            <div v-if="sessionStats.summary && sessionStats.summary.total_tokens">
              <v-row>
                <v-col cols="12" sm="6">
                  <v-card variant="tonal" color="primary" class="pa-4 text-center">
                    <div class="text-h4">{{ sessionStats.summary.total_tokens || 0 }}</div>
                    <div class="text-caption text-medium-emphasis">Total Tokens</div>
                  </v-card>
                </v-col>
                <v-col cols="12" sm="6">
                  <v-card variant="tonal" color="secondary" class="pa-4 text-center">
                    <div class="text-h4">{{ sessionStats.summary.interaction_count || 0 }}</div>
                    <div class="text-caption text-medium-emphasis">Total Turns</div>
                  </v-card>
                </v-col>
                <v-col cols="12" sm="4">
                  <v-card variant="tonal" class="pa-4 text-center">
                    <div class="text-h5">{{ sessionStats.summary.total_prompt_tokens || 0 }}</div>
                    <div class="text-caption text-medium-emphasis">Prompt Tokens</div>
                  </v-card>
                </v-col>
                <v-col cols="12" sm="4">
                  <v-card variant="tonal" class="pa-4 text-center">
                    <div class="text-h5">{{ sessionStats.summary.total_completion_tokens || 0 }}</div>
                    <div class="text-caption text-medium-emphasis">Completion Tokens</div>
                  </v-card>
                </v-col>
                <v-col cols="12" sm="4">
                  <v-card variant="tonal" class="pa-4 text-center">
                    <div class="text-h5">{{ sessionStats.summary.avg_total_tokens || 0 }}</div>
                    <div class="text-caption text-medium-emphasis">Avg Tokens/Turn</div>
                  </v-card>
                </v-col>
              </v-row>
              <div class="mt-4">
                <div class="text-subtitle-2 mb-2">Timestamps</div>
                <div class="text-body-2 text-medium-emphasis">
                  First turn: {{ formatTimestamp(sessionStats.summary.first_interaction) }}<br>
                  Last turn: {{ formatTimestamp(sessionStats.summary.last_interaction) }}
                </div>
              </div>
            </div>
            <div v-else class="text-center pa-6 text-medium-emphasis">
              No usage recorded yet for this session.
            </div>
          </div>

          <div v-else class="flex-grow-1 d-flex align-center justify-center text-medium-emphasis pa-6">
            Select a tab above.
          </div>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, defineComponent, h } from 'vue'
import { useRoute } from 'vue-router'
import { marked } from 'marked'

const route = useRoute()
const API_BASE = '/api'

// --- Trace sub-component (defined inline to avoid extra files) ---
const MessageTraceViewer = defineComponent({
  name: 'MessageTraceViewer',
  props: { trace: { type: Object, required: true } },
  setup(props) {
    const llmTab = ref(0)
    const toolTab = ref(0)
    // full-prompt (system+messages+tools) is the default: it answers the
    // user's question "how was the prompt token count calculated".
    const llmSubtab = ref('full-prompt') // full-prompt | prompt | messages | tools-sent | response | raw-request | raw-response | usage
    const topTab = ref('summary') // summary | llm | tools | flow

    const llmCalls = computed(() => props.trace?.llm_calls || [])
    const toolCalls = computed(() => props.trace?.tool_calls || [])
    const events = computed(() => {
      const evs = props.trace?.events || []
      if (Array.isArray(evs)) return evs
      return []
    })
    const currentLlm = computed(() => llmCalls.value[llmTab.value] || null)
    const currentTool = computed(() => toolCalls.value[toolTab.value] || null)

    function prettyJSON(val) {
      try {
        if (val == null) return '(empty)'
        if (typeof val === 'string') {
          try { return JSON.stringify(JSON.parse(val), null, 2) } catch { return val }
        }
        return JSON.stringify(val, null, 2)
      } catch { return String(val) }
    }

    function hasData(v) {
      if (v == null) return false
      if (typeof v === 'string') return v !== ''
      if (Array.isArray(v)) return v.length > 0
      if (typeof v === 'object') return Object.keys(v).length > 0
      return true
    }

    function duration(ms) {
      if (ms == null) return '-'
      if (ms < 1000) return `${ms} ms`
      return `${(ms / 1000).toFixed(2)} s`
    }

    function eventIcon(type) {
      switch (type) {
        case 'LLM_START': return 'mdi-robot-excited'
        case 'LLM_DONE': return 'mdi-robot'
        case 'TOOL_START': return 'mdi-wrench-clock'
        case 'TOOL_DONE': return 'mdi-wrench-check-outline'
        case 'FINAL': return 'mdi-check-circle-outline'
        default: return 'mdi-circle-small'
      }
    }
    function eventColor(type) {
      switch (type) {
        case 'LLM_START': return 'primary'
        case 'LLM_DONE': return 'primary'
        case 'TOOL_START': return 'success'
        case 'TOOL_DONE': return 'success'
        case 'FINAL': return 'info'
        default: return 'grey'
      }
    }
    function eventTitle(e) {
      if (!e) return ''
      const parts = []
      switch (e.type) {
        case 'LLM_START': parts.push('LLM Call start')
          if (e.ref) { const [, i] = e.ref.split(':'); parts.push(`#${Number(i) + 1}`) } break
        case 'LLM_DONE': parts.push('LLM Call done')
          if (e.ref) { const [, i] = e.ref.split(':'); parts.push(`#${Number(i) + 1}`) } break
        case 'TOOL_START': parts.push('Tool start')
          if (e.ref) { const [, i] = e.ref.split(':'); parts.push(`#${Number(i) + 1}`) } break
        case 'TOOL_DONE': parts.push('Tool done')
          if (e.ref) { const [, i] = e.ref.split(':'); parts.push(`#${Number(i) + 1}`) } break
        case 'FINAL': parts.push('Final answer')
          break
        default: parts.push(e.type)
      }
      return parts.join(' ')
    }

    return () => {
      const tr = props.trace
      if (!tr) return h('div', 'No trace data')
      const totalLlmTok = tr.total_tokens || 0
      // With the backend fallback these are nearly always populated, but keep
      // the guard so older traces that genuinely have nothing still hide the
      // tab instead of showing an empty view.
      const hasRawReq = hasData(currentLlm.value?.raw_request)
      const hasRawResp = hasData(currentLlm.value?.raw_response)
      // (note: Full Prompt tab is ALWAYS rendered; its body renders a
      // friendly "no structured prompt data yet" card if system_prompt / messages /
      // tools are all empty, so old traces or no-data states never hide the tab.

      return h('div', { class: 'trace-viewer' }, [
        // Header
        h('div', { class: 'trace-head mb-3' }, [
          h('div', { class: 'text-subtitle-2 font-weight-bold' }, 'Turn Trace'),
          h('div', { class: 'text-body-2 text-medium-emphasis' }, [
            `Started ${tr.started_at || ''}`,
            tr.finished_at ? ` · Finished ${tr.finished_at}` : '',
          ].join('')),
          h('div', { class: 'mt-2' }, [
            h('v-chip', { size: 'x-small', variant: 'tonal', class: 'me-1' }, `LLM calls: ${llmCalls.value.length}`),
            h('v-chip', { size: 'x-small', variant: 'tonal', color: 'success', class: 'me-1' }, `Tool calls: ${toolCalls.value.length}`),
            totalLlmTok
              ? h('v-chip', { size: 'x-small', variant: 'tonal', color: 'primary' }, `Total: ${totalLlmTok} tokens`)
              : null,
          ].filter(Boolean)),
        ]),

        // Top-level tabs: Summary, LLM Calls, Tool Calls, Tool-Selection Flow
        h('v-tabs', {
          density: 'compact',
          modelValue: topTab.value,
          'onUpdate:modelValue': v => { topTab.value = v },
          alignTabs: 'start',
          bgColor: 'transparent',
          class: 'mb-2',
          window: '__none__',
        }, {
          default: () => [
            h('v-tab',
              { value: 'summary' },
              () => [
                h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: '6px', lineHeight: 1 } }, [
                  h('span', { style: { fontFamily: 'Material Design Icons', fontSize: '16px', lineHeight: '1' } }, 'ⓘ'),
                  h('span', 'Summary'),
                ]),
              ]
            ),
            h('v-tab',
              { value: 'llm' },
              () => [
                h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: '6px', lineHeight: 1 } }, [
                  h('span', { style: { fontFamily: 'Material Design Icons', fontSize: '16px', lineHeight: '1' } }, '🤖'),
                  h('span', `LLM (${llmCalls.value.length})`),
                ]),
              ]
            ),
            h('v-tab',
              { value: 'tools' },
              () => [
                h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: '6px', lineHeight: 1 } }, [
                  h('span', { style: { fontFamily: 'Material Design Icons', fontSize: '16px', lineHeight: '1' } }, '🔧'),
                  h('span', `Tools (${toolCalls.value.length})`),
                ]),
              ]
            ),
            events.value.length
              ? h('v-tab',
                  { value: 'flow' },
                  () => [
                    h('span', { style: { display: 'inline-flex', alignItems: 'center', gap: '6px', lineHeight: 1 } }, [
                      h('span', { style: { fontFamily: 'Material Design Icons', fontSize: '16px', lineHeight: '1' } }, '🗺'),
                      h('span', `Flow / Tool Selection (${events.value.length})`),
                    ]),
                  ]
                )
              : null,
          ].filter(Boolean)
        }),
        h('v-divider'),

        // Summary tab
        topTab.value === 'summary'
          ? h('div', { class: 'pa-1' }, [
              h('div', { class: 'text-caption text-medium-emphasis mb-2' }, 'Turn at a glance'),
              tr.user_message
                ? h('div', { class: 'mb-2' }, [
                    h('div', { class: 'text-caption font-weight-bold mb-1' }, 'User message'),
                    h('pre', { class: 'trace-code' }, tr.user_message),
                  ])
                : null,
              tr.final_answer
                ? h('div', { class: 'mb-2' }, [
                    h('div', { class: 'text-caption font-weight-bold mb-1' }, 'Final answer'),
                    h('pre', { class: 'trace-code' }, tr.final_answer),
                  ])
                : null,
              h('div', { class: 'usage-grid' }, [
                kv('LLM calls', String(llmCalls.value.length)),
                kv('Tool calls', String(toolCalls.value.length)),
                kv('Total prompt tokens', String(tr.total_prompt_tokens || 0)),
                kv('Total completion tokens', String(tr.total_completion_tokens || 0)),
                kv('Total tokens', String(tr.total_tokens || 0)),
              ]),
            ])
          : null,

        // LLM calls tab
        topTab.value === 'llm'
          ? (llmCalls.value.length
              ? h('div', { class: 'mt-1' }, [
                  llmCalls.value.length > 1
                    ? h('v-tabs', {
                        density: 'compact',
                        modelValue: llmTab.value,
                        'onUpdate:modelValue': v => llmTab.value = v,
                        bgColor: 'transparent',
                        class: 'mb-2',
                        window: '__none__',
                      }, {
                        default: () => llmCalls.value.map((_, i) =>
                          h('v-tab', { value: i }, `Call ${i + 1}`)
                        )
                      })
                    : null,
                  currentLlm.value
                    ? h('div', { class: 'llm-call' }, [
                        h('div', { class: 'text-caption text-medium-emphasis mb-2' }, [
                          currentLlm.value.model ? `Model: ${currentLlm.value.model}` : '',
                          currentLlm.value.duration_ms != null ? ` · ${duration(currentLlm.value.duration_ms)}` : '',
                          currentLlm.value.total_tokens ? ` · ${currentLlm.value.total_tokens} tokens` : '',
                          currentLlm.value.error ? ' · ERROR' : '',
                        ].filter(Boolean).join('')),
                        h('v-tabs', {
                          density: 'compact',
                          modelValue: llmSubtab.value,
                          'onUpdate:modelValue': v => llmSubtab.value = v,
                          alignTabs: 'start',
                          bgColor: 'transparent',
                          window: '__none__',
                        }, {
                          default: () => [
                            h('v-tab',
                              { value: 'full-prompt' },
                              () => 'Full Prompt'
                            ),
                            h('v-tab',
                              { value: 'prompt' },
                              () => 'System Prompt'
                            ),
                            h('v-tab',
                              { value: 'messages' },
                              () => 'Messages'
                            ),
                            h('v-tab',
                              { value: 'tools-sent' },
                              () => 'Tools Sent'
                            ),
                            h('v-tab',
                              { value: 'response' },
                              () => 'Response'
                            ),
                            hasRawReq
                              ? h('v-tab', { value: 'raw-request' }, () => 'Raw Request')
                              : null,
                            hasRawResp
                              ? h('v-tab', { value: 'raw-response' }, () => 'Raw Response')
                              : null,
                            h('v-tab',
                              { value: 'usage' },
                              () => 'Usage'
                            ),
                          ].filter(Boolean)
                        }),
                        h('v-divider'),
                        llmSubtab.value === 'full-prompt'
                          ? (() => {
                              const sections = []
                              const sp = currentLlm.value?.system_prompt
                              if (sp) {
                                sections.push(
                                  h('div', { class: 'mb-3' }, [
                                    h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                      'System Instruction (',
                                      String(sp.length),
                                      ' chars, ~',
                                      String(Math.ceil(sp.length / 4)),
                                      ' estimated tokens)',
                                    ]),
                                    h('pre', { class: 'trace-code' }, sp),
                                  ])
                                )
                              }
                              const msgs = currentLlm.value?.messages || []
                              if (msgs.length) {
                                sections.push(
                                  h('div', { class: 'mb-3' }, [
                                    h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                      'Conversation Messages (',
                                      String(msgs.length),
                                      ' entries)',
                                    ]),
                                    ...msgs.map((m, mi) => {
                                      const body = m.content || ''
                                      return h('div', {
                                        class: 'mb-1 pa-2 rounded',
                                        style: {
                                          background:
                                            m.role === 'user'
                                              ? 'rgba(var(--v-theme-primary), 0.08)'
                                              : 'rgba(var(--v-theme-on-surface), 0.05)',
                                          borderLeft:
                                            m.role === 'user'
                                              ? '3px solid rgb(var(--v-theme-primary))'
                                              : '3px solid rgba(var(--v-theme-on-surface), 0.35)',
                                        },
                                      }, [
                                        h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                          String(mi + 1),
                                          '. ',
                                          (m.role || '?').toUpperCase(),
                                          ' (',
                                          String(body.length),
                                          ' chars)',
                                        ]),
                                        h('pre', { class: 'trace-code mb-0' }, body),
                                      ])
                                    }),
                                  ])
                                )
                              }
                              const tls = currentLlm.value?.tools || []
                              if (tls.length) {
                                sections.push(
                                  h('div', { class: 'mb-2' }, [
                                    h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                      'Tool Schemas Sent (',
                                      String(tls.length),
                                      ' tools — schema accounts for a large fraction of prompt tokens)',
                                    ]),
                                    ...tls.map((t, ti) => {
                                      const name = t.name || '(unnamed)'
                                      const desc = t.description || ''
                                      const params = t.parameters || {}
                                      return h('details', { class: 'mb-1 pa-2 rounded', style: { background: 'rgba(var(--v-theme-success), 0.06)', borderLeft: '3px solid rgb(var(--v-theme-success))' } }, [
                                        h('summary', { class: 'text-caption font-weight-bold cursor-pointer' }, [
                                          String(ti + 1),
                                          '. ',
                                          name,
                                          ' — ',
                                          desc.slice(0, 80),
                                          desc.length > 80 ? '…' : '',
                                        ]),
                                        h('pre', { class: 'trace-code mt-2 mb-0' }, prettyJSON({
                                          name: name,
                                          description: desc,
                                          parameters: params,
                                        })),
                                      ])
                                    }),
                                  ])
                                )
                              }
                              if (!sections.length) {
                                return h('div', { class: 'text-medium-emphasis pa-2' }, 'No structured prompt data for this LLM call.')
                              }
                              const tot = (sp?.length || 0) +
                                msgs.reduce((a, m) => a + (m?.content?.length || 0), 0) +
                                (() => {
                                  try { return JSON.stringify(tls || []).length } catch { return 0 }
                                })()
                              sections.unshift(
                                h('div', { class: 'mb-3 pa-2 rounded text-body-2', style: { background: 'rgba(var(--v-theme-primary), 0.08)' } }, [
                                  h('v-icon', { size: 16, class: 'me-1 align-middle' }, 'mdi-information-outline'),
                                  'Total constructed prompt length: ~',
                                  h('strong', String(tot)),
                                  ' chars ≈ ',
                                  h('strong', String(Math.ceil(tot / 4))),
                                  ' estimated tokens. Exact counts from provider are in the Usage tab.',
                                ])
                              )
                              return sections
                            })()
                          : null,
                        llmSubtab.value === 'prompt'
                          ? h('pre', { class: 'trace-code' }, currentLlm.value.system_prompt || '(none)')
                          : null,
                        llmSubtab.value === 'messages'
                          ? h('pre', { class: 'trace-code' }, prettyJSON(currentLlm.value.messages || []))
                          : null,
                        llmSubtab.value === 'tools-sent'
                          ? h('pre', { class: 'trace-code' }, prettyJSON(currentLlm.value.tools || []))
                          : null,
                        llmSubtab.value === 'response'
                          ? h('div', [
                              h('div', { class: 'text-caption font-weight-bold mb-1' }, 'Response text:'),
                              h('pre', { class: 'trace-code' }, currentLlm.value.response_text || '(no text)'),
                              Array.isArray(currentLlm.value.tool_calls_planned) && currentLlm.value.tool_calls_planned.length
                                ? [
                                    h('div', { class: 'text-caption font-weight-bold mt-3 mb-1' }, 'Planned tool calls:'),
                                    h('pre', { class: 'trace-code' }, prettyJSON(currentLlm.value.tool_calls_planned)),
                                  ]
                                : null,
                              currentLlm.value.error
                                ? [
                                    h('div', { class: 'text-caption font-weight-bold mt-3 mb-1 text-error' }, 'Error:'),
                                    h('pre', { class: 'trace-code text-error' }, String(currentLlm.value.error)),
                                  ]
                                : null,
                            ])
                          : null,
                        llmSubtab.value === 'raw-request'
                          ? h('div', [
                              h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                'Raw LLM request (full LlmRequest payload):',
                              ]),
                              h('pre', { class: 'trace-code' }, prettyJSON(currentLlm.value.raw_request)),
                            ])
                          : null,
                        llmSubtab.value === 'raw-response'
                          ? h('div', [
                              h('div', { class: 'text-caption font-weight-bold mb-1' }, [
                                'Raw LLM response (full LlmResponse payload):',
                              ]),
                              h('pre', { class: 'trace-code' }, prettyJSON(currentLlm.value.raw_response)),
                            ])
                          : null,
                        llmSubtab.value === 'usage'
                          ? h('div', { class: 'usage-grid' }, [
                              kv('Prompt tokens', currentLlm.value.prompt_tokens || 0),
                              kv('Completion tokens', currentLlm.value.completion_tokens || 0),
                              kv('Total tokens', currentLlm.value.total_tokens || 0),
                            ])
                          : null,
                      ])
                    : null,
                ])
              : h('div', { class: 'text-center text-medium-emphasis pa-4' }, 'No LLM calls recorded for this turn.'))
          : null,

        // Tool calls tab
        topTab.value === 'tools'
          ? (toolCalls.value.length
              ? h('div', { class: 'mt-1' }, [
                  toolCalls.value.length > 1
                    ? h('v-tabs', {
                        density: 'compact',
                        modelValue: toolTab.value,
                        'onUpdate:modelValue': v => toolTab.value = v,
                        bgColor: 'transparent',
                        class: 'mb-2',
                        window: '__none__',
                      }, {
                        default: () => toolCalls.value.map((tc, i) =>
                          h('v-tab', { value: i }, `${tc.name || 'tool'} #${i + 1}`)
                        )
                      })
                    : null,
                  currentTool.value
                    ? h('div', { class: 'tool-call' }, [
                        h('div', { class: 'text-caption text-medium-emphasis mb-2' }, [
                          currentTool.value.name || 'tool',
                          currentTool.value.duration_ms != null ? ` · ${duration(currentTool.value.duration_ms)}` : '',
                          currentTool.value.error ? ' · ERROR' : '',
                        ].filter(Boolean).join('')),
                        h('div', { class: 'text-caption font-weight-bold mb-1' }, 'Arguments:'),
                        h('pre', { class: 'trace-code' }, prettyJSON(currentTool.value.args || {})),
                        h('div', { class: 'text-caption font-weight-bold mt-3 mb-1' }, 'Result:'),
                        h('pre', { class: 'trace-code' }, prettyJSON(currentTool.value.result || '(empty)')),
                        currentTool.value.error
                          ? [
                              h('div', { class: 'text-caption font-weight-bold mt-3 mb-1 text-error' }, 'Error:'),
                              h('pre', { class: 'trace-code text-error' }, String(currentTool.value.error)),
                            ]
                          : null,
                      ])
                    : null,
                ])
              : h('div', { class: 'text-center text-medium-emphasis pa-4' }, 'No tool calls recorded for this turn.'))
          : null,

        // Flow / Tool Selection Graph tab
        topTab.value === 'flow'
          ? (events.value.length
              ? h('div', { class: 'flow-timeline mt-2' }, [
                  h('div', { class: 'text-caption text-medium-emphasis mb-2' }, [
                    'Ordered event timeline for this turn — oldest (top) → newest (bottom). LLM rounds and tool calls are linked via the llm:N / tool:N chips.',
                  ]),
                  ...events.value.map((ev, eIdx) => {
                    const isLast = eIdx === events.value.length - 1
                    const ec = eventColor(ev.type)
                    const typeCls = `flow-type-${ev.type || 'UNKNOWN'}`
                    return h('div', { class: ['flow-row', typeCls].join(' ') }, [
                      h('div', { class: 'flow-rail-col' }, [
                        h('div', {
                          class: ['flow-node-badge', typeCls].join(' '),
                          style: {
                            width: '32px',
                            height: '32px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            color: 'rgb(var(--v-theme-' + (ec || 'grey') + '))',
                            background: 'rgba(var(--v-theme-' + (ec || 'grey') + '), 0.12)',
                            border: '1px solid rgba(var(--v-theme-' + (ec || 'grey') + '), 0.35)',
                            flexShrink: 0,
                          },
                        }, [
                          h('span', {
                            style: {
                              fontFamily: 'Material Design Icons',
                              fontSize: '16px',
                              lineHeight: 1,
                              display: 'inline-block',
                            },
                          }, eventIcon(ev.type) ? '' : ''),
                          h('span', {
                            style: {
                              fontSize: '13px',
                              fontWeight: 700,
                              lineHeight: 1,
                            },
                          }, String(eIdx + 1)),
                        ]),
                        !isLast
                          ? h('div', {
                              class: 'flow-connector',
                              style: {
                                width: '2px',
                                flex: '1 1 auto',
                                minHeight: '18px',
                                marginTop: '4px',
                                marginBottom: '4px',
                                background:
                                  'linear-gradient(to bottom, rgba(var(--v-theme-on-surface), 0.22), rgba(var(--v-theme-on-surface), 0.08))',
                              },
                            })
                          : null,
                      ]),
                      h('div', { class: 'flow-body', style: { flex: '1 1 auto', paddingBottom: isLast ? '2px' : '12px' } }, [
                        h('div', { class: 'd-flex align-center gap-2 flex-wrap' }, [
                          h('div', {
                            class: 'text-subtitle-2 font-weight-bold',
                            style: { color: 'rgb(var(--v-theme-' + (ec || 'on-surface') + '))' },
                          }, eventTitle(ev)),
                          ev.ref
                            ? h('span', {
                                class: 'text-caption',
                                style: {
                                  padding: '2px 8px',
                                  borderRadius: '999px',
                                  border: '1px solid rgba(var(--v-theme-' + (ec || 'grey') + '), 0.4)',
                                  color: 'rgb(var(--v-theme-' + (ec || 'grey') + '))',
                                  background: 'rgba(var(--v-theme-' + (ec || 'grey') + '), 0.06)',
                                  fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
                                  fontSize: '0.7rem',
                                },
                              }, ev.ref)
                            : null,
                        ]),
                        ev.at
                          ? h('div', {
                              class: 'text-caption text-medium-emphasis mt-1',
                            }, ev.at)
                          : null,
                        ev.summary
                          ? h('div', {
                              class: 'text-body-2 mt-2',
                              style: { lineHeight: 1.55 },
                            }, ev.summary)
                          : null,
                      ]),
                    ])
                  }),
                ])
              : h('div', { class: 'text-center text-medium-emphasis pa-4' },
                  'No flow events recorded for this turn (traces written before this feature do not have events).'))
          : null,
      ])

      function kv(k, v) {
        return h('div', { class: 'kv-row' }, [
          h('span', { class: 'kv-label' }, k),
          h('span', { class: 'kv-value' }, String(v)),
        ])
      }
    }
  },
})

// --- Main script ---
const messages = ref([])
const messageTraces = ref({}) // index -> trace object
const input = ref('')
const loading = ref(false)
const messagesContainer = ref(null)
const llmProvider = ref('')
const currentSessionId = ref(null)
const showTrace = ref(false)
const traceTab = ref('invocations')
const traceSummaries = ref([])
const invocationsData = ref({}) // invocation_id -> full trace
const selectedInvocationId = ref(null)
const activeTraceForIdx = ref(null)
const sessionStats = ref({ summary: null })

const chatCols = 8
const traceCols = 4

const selectedInvocationDetail = computed(() => {
  return selectedInvocationId.value ? invocationsData.value[selectedInvocationId.value] : null
})

function renderMarkdown(text) {
  try {
    return marked.parse(text || '')
  } catch {
    return text
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

function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

function toggleTrace() {
  showTrace.value = !showTrace.value
}

// --- Message <-> Trace bidirectional wiring ---------------------------------
// When the user clicks a bot-response bubble:
//   (a) opens the trace sidebar if closed,
//   (b) selects the corresponding invocation in the sidebar,
//   (c) optionally scrolls the trace detail into view,
//   (d) if the invocation is already selected, it toggles the sidebar closed.
// The small "Inline Trace" button on the header keeps its original behavior.
function onMessageBubbleClick(msg, idx, ev) {
  if (msg.role !== 'ai' || !msg.invocation_id) return
  const invId = msg.invocation_id

  // If click was *directly* on the inline toggle button, don't also do
  // the sidebar behavior (button uses @click.stop to prevent bubbling).
  // This is a small defensive check -- the @click.stop on the VBtn should
  // already stop propagation so we only get here on bubble/header/content
  // clicks.
  if (ev && ev.target && typeof ev.target.closest === 'function') {
    if (ev.target.closest('.trace-btn') || ev.target.closest('.inline-trace')) return
  }

  const already = showTrace.value && selectedInvocationId.value === invId
  if (already) {
    // Second click on same bubble → close trace panel
    showTrace.value = false
    selectedInvocationId.value = null
    return
  }
  showTrace.value = true
  selectedInvocationId.value = invId

  // If we don't yet have the trace payload for this AI message (e.g. user
  // loaded an old session via browser nav), lazy-fetch it so the inline
  // trace button works too.
  if (!messageTraces.value[idx] && currentSessionId.value) {
    fetch(`${API_BASE}/traces/${currentSessionId.value}/${invId}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) messageTraces.value[idx] = data })
      .catch(() => {})
  }

  nextTick(() => {
    // Scroll the detail panel into view inside the trace column
    const el = document.querySelector('.trace-detail')
    if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' })
  })
}

// Ensure AI messages from session history also get an invocation_id, so
// clicking them can jump to the matching trace. The session JSON stores
// messages in order, and traces list invocations in start order, so we
// walk the list of AI messages and, for each one that matches a
// non-yet-matched invocation by turn order, attach invocation_id + hasTrace.
function linkHistoryMessagesToTraces() {
  const invIds = (traceSummaries.value || []).map(s => s.invocation_id)
  if (!invIds.length) return
  let invCursor = 0
  // Walk messages *in order*, skipping user ones; every AI message maps
  // to the next invocation (one user → one invocation → one AI reply).
  messages.value.forEach((m, i) => {
    if (m.role !== 'ai') return
    if (m.invocation_id) return // already linked (most recent from sendMessage)
    if (invCursor >= invIds.length) return
    const id = invIds[invCursor++]
    m.invocation_id = id
    m.hasTrace = true
    if (invocationsData.value[id]) messageTraces.value[i] = invocationsData.value[id]
  })
}

// Ensure the trace panel sidebar ↔ messages highlight is synced after
// every trace reload (including the initial onMounted load for a saved
// session, plus the post-chat reload).
function syncAfterTracesLoaded() {
  linkHistoryMessagesToTraces()
}

function toggleMessageTrace(idx, msg) {
  if (activeTraceForIdx.value === idx) {
    activeTraceForIdx.value = null
  } else {
    activeTraceForIdx.value = idx
    if (!messageTraces.value[idx] && msg.invocation_id && currentSessionId.value) {
      fetch(`${API_BASE}/traces/${currentSessionId.value}/${msg.invocation_id}`)
        .then(r => r.ok ? r.json() : null)
        .then(data => { if (data) messageTraces.value[idx] = data })
        .catch(() => {})
    }
  }
}

async function ensureSession() {
  if (currentSessionId.value) return currentSessionId.value
  try {
    const res = await fetch(`${API_BASE}/sessions`, { method: 'POST' })
    const data = await res.json()
    currentSessionId.value = data.session_id
    return currentSessionId.value
  } catch (e) {
    console.error('Failed to create session:', e)
    return null
  }
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return
  const sessionId = await ensureSession()
  if (!sessionId) return

  messages.value.push({ role: 'user', content: text, timestamp: new Date().toISOString() })
  input.value = ''
  scrollToBottom()

  loading.value = true
  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, session_id: sessionId, include_history: true }),
    })

    let data
    const contentType = res.headers.get('content-type') || ''
    const textBody = await res.text()

    try {
      data = contentType.includes('application/json') || textBody.trim().startsWith('{') || textBody.trim().startsWith('[')
        ? JSON.parse(textBody)
        : null
    } catch {
      data = null
    }

    if (!res.ok) {
      let errMsg = `Server error (HTTP ${res.status})`
      if (data) {
        if (typeof data.detail === 'string') {
          errMsg = data.detail
        } else if (data.detail && typeof data.detail === 'object') {
          errMsg = data.detail.error || data.detail.message || JSON.stringify(data.detail)
        } else if (typeof data.error === 'string') {
          errMsg = data.error
        } else {
          errMsg = JSON.stringify(data)
        }
      } else if (textBody) {
        errMsg = textBody.length > 300 ? textBody.slice(0, 300) + '…' : textBody
      }
      throw new Error(errMsg)
    }

    if (!data) {
      throw new Error('Invalid response from server (expected JSON)')
    }

    const aiMsg = {
      role: 'ai',
      content: data.response || 'No response received.',
      timestamp: new Date().toISOString(),
      invocation_id: null,
      hasTrace: false,
    }
    if (data.total_tokens) {
      aiMsg.tokens = {
        prompt: data.prompt_tokens,
        completion: data.completion_tokens,
        total: data.total_tokens,
      }
    }
    messages.value.push(aiMsg)
    // Reload traces
    await loadTraces()
    // Auto-link most recent trace to most recent AI message
    const latest = traceSummaries.value[traceSummaries.value.length - 1]
    if (latest) {
      aiMsg.invocation_id = latest.invocation_id
      aiMsg.hasTrace = true
      messageTraces.value[messages.value.length - 1] = invocationsData.value[latest.invocation_id] || null
    }
  } catch (e) {
    messages.value.push({
      role: 'ai',
      content: `Error: ${e.message}`,
      timestamp: new Date().toISOString(),
    })
  } finally {
    loading.value = false
    scrollToBottom()
    loadSessionStats().catch(() => {})
  }
}

async function loadSessionHistory() {
  if (!currentSessionId.value) {
    messages.value = []
    return
  }
  try {
    const res = await fetch(`${API_BASE}/sessions/${currentSessionId.value}`)
    if (!res.ok) return
    const data = await res.json()
    const msgs = (data.messages || []).map(m => ({
      role: m.role === 'assistant' ? 'ai' : (m.role || 'user'),
      content: m.content || '',
      timestamp: m.timestamp,
    }))
    messages.value = msgs
    scrollToBottom()
  } catch (e) {
    console.error('Failed to load session history:', e)
  }
}

async function loadTraces() {
  if (!currentSessionId.value) {
    traceSummaries.value = []
    invocationsData.value = {}
    selectedInvocationId.value = null
    return
  }
  try {
    const res = await fetch(`${API_BASE}/traces/${currentSessionId.value}`)
    if (!res.ok) return
    const data = await res.json()
    traceSummaries.value = data.invocation_summaries || []
    invocationsData.value = data.invocations || {}
    syncAfterTracesLoaded()
  } catch (e) {
    console.error('Failed to load traces:', e)
  }
}

async function loadSessionStats() {
  if (!currentSessionId.value) {
    sessionStats.value = { summary: null }
    return
  }
  try {
    const res = await fetch(`${API_BASE}/stats/tokens/${currentSessionId.value}`)
    if (res.ok) sessionStats.value = await res.json()
  } catch {}
}

function selectInvocation(id) {
  selectedInvocationId.value = id
}

function getInvocationIcon(sum) {
  if (sum.tool_call_count) return 'mdi-wrench'
  if (sum.llm_call_count) return 'mdi-robot'
  return 'mdi-message-text'
}

function getInvocationColor(sum) {
  if (sum.tool_call_count) return 'success'
  if (sum.llm_call_count) return 'primary'
  return 'grey'
}

function detectProvider() {
  fetch(`${API_BASE}/config/llm`)
    .then(r => r.ok ? r.json() : null)
    .then(data => { if (data?.config?.provider) llmProvider.value = data.config.provider })
    .catch(() => { llmProvider.value = 'AI Assistant' })
}

onMounted(async () => {
  const sid = route.params.sessionId
  if (sid) currentSessionId.value = sid
  detectProvider()
  await loadSessionHistory()
  await loadTraces()
  await loadSessionStats()
})

watch(() => route.params.sessionId, async (sid) => {
  currentSessionId.value = sid || null
  activeTraceForIdx.value = null
  messageTraces.value = {}
  await loadSessionHistory()
  await loadTraces()
  await loadSessionStats()
})
</script>

<style scoped>
.chat-main-row {
  min-height: 500px;
}

.chat-page {
  width: 100%;
}

.chat-card, .trace-card {
  overflow: hidden;
}

.messages-area {
  overflow-y: auto;
  padding: 16px;
  scroll-behavior: smooth;
}

.empty-state {
  padding: 60px 20px;
}

.message-bubble {
  margin-bottom: 20px;
  max-width: 85%;
  transition: background-color 120ms ease, outline-color 120ms ease,
    transform 120ms ease, box-shadow 120ms ease;
}

.message-bubble.user {
  margin-left: auto;
}

.message-bubble.ai {
  margin-right: auto;
}

/* Bot bubbles that have a linked trace are clickable. */
.message-bubble.ai.clickable-bot {
  cursor: pointer;
}
.message-bubble.ai.clickable-bot:hover .message-content {
  background: rgba(var(--v-theme-primary), 0.08);
  outline: 1px dashed rgba(var(--v-theme-primary), 0.5);
  outline-offset: 2px;
}

/* Applied when the *matching* turn is selected in the Trace sidebar. */
.message-bubble.ai.trace-linked-active .message-content {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: 2px;
  background: rgba(var(--v-theme-primary), 0.10);
  box-shadow: 0 0 0 4px rgba(var(--v-theme-primary), 0.08);
}

.message-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 6px;
}

.message-trace-hint {
  display: inline-flex;
  align-items: center;
  font-size: 0.7rem;
  color: rgba(var(--v-theme-on-surface), 0.45);
}
.message-bubble.ai.trace-linked-active .message-trace-hint {
  color: rgba(var(--v-theme-primary), 0.9);
}

/* Flow / tool-selection timeline */
:deep(.trace-viewer .flow-timeline) {
  padding: 4px 2px 12px 2px;
}
:deep(.trace-viewer .flow-row) {
  display: flex;
  gap: 10px;
  align-items: stretch;
}
:deep(.trace-viewer .flow-rail-col) {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 36px;
}
:deep(.trace-viewer .flow-node) {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
}
:deep(.trace-viewer .flow-connector) {
  width: 2px;
  flex: 1 1 auto;
  min-height: 18px;
  background: linear-gradient(
    to bottom,
    rgba(var(--v-theme-on-surface), 0.18),
    rgba(var(--v-theme-on-surface), 0.06)
  );
}
:deep(.trace-viewer .flow-body) {
  flex: 1 1 auto;
  padding: 2px 4px 12px 2px;
  border-bottom: 1px dashed rgba(var(--v-theme-on-surface), 0.08);
  margin-bottom: 4px;
}
:deep(.trace-viewer .flow-row:last-child .flow-body) {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 2px;
}

.message-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.message-role {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  color: rgba(var(--v-theme-on-surface), 0.5);
}

.message-time {
  font-size: 0.7rem;
  color: rgba(var(--v-theme-on-surface), 0.35);
}

.trace-btn {
  margin-left: auto;
  font-size: 0.7rem;
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
  margin-top: 6px;
}

.inline-trace {
  margin-top: 12px;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.1);
  border-radius: 10px;
  padding: 12px;
  background: rgba(var(--v-theme-on-surface), 0.02);
}

.input-area {
  padding: 12px;
}

.markdown-body :first-child { margin-top: 0; }
.markdown-body :last-child { margin-bottom: 0; }
.markdown-body p { margin-bottom: 8px; }
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
.markdown-body pre code { background: none; padding: 0; }
.markdown-body ul, .markdown-body ol { padding-left: 24px; }
.markdown-body table {
  border-collapse: collapse;
  margin: 8px 0;
}
.markdown-body th, .markdown-body td {
  border: 1px solid rgba(var(--v-theme-on-surface), 0.12);
  padding: 6px 12px;
}

/* Trace viewer styles */
:deep(.trace-summaries-list) {
  max-height: 35%;
  min-height: 120px;
}

:deep(.trace-viewer .trace-head) {
  border-bottom: 1px solid rgba(var(--v-theme-on-surface), 0.08);
  padding-bottom: 12px;
}

:deep(.trace-viewer .trace-code) {
  background: rgba(var(--v-theme-on-surface), 0.05);
  border-radius: 8px;
  padding: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  max-height: 400px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

:deep(.trace-viewer .llm-call),
:deep(.trace-viewer .tool-call) {
  padding: 8px;
  border-radius: 8px;
  background: rgba(var(--v-theme-on-surface), 0.02);
}

:deep(.trace-viewer .usage-grid) {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 0;
}

:deep(.trace-viewer .kv-row) {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  border-radius: 6px;
  background: rgba(var(--v-theme-on-surface), 0.04);
}

:deep(.trace-viewer .kv-label) {
  font-weight: 600;
  font-size: 0.85rem;
}

:deep(.trace-viewer .kv-value) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.85rem;
}
</style>
