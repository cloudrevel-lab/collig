<template>
  <v-sheet color="transparent" class="fill-height">
    <v-row class="mb-4">
      <v-col>
        <h1 class="text-h4 mb-1">Settings</h1>
        <p class="text-subtitle-1 text-medium-emphasis">
          Configure LLM providers, enable or disable skills, and edit raw configuration.
        </p>
      </v-col>
    </v-row>

    <v-tabs v-model="tab" color="primary" slider-color="primary" align-tabs="start" class="mb-4">
      <v-tab value="llm" prepend-icon="mdi-brain">LLM Provider</v-tab>
      <v-tab value="skills" prepend-icon="mdi-puzzle-outline">Skills</v-tab>
      <v-tab value="raw" prepend-icon="mdi-code-json">Raw Config</v-tab>
    </v-tabs>

    <v-window v-model="tab">
      <!-- ================= LLM TAB ================= -->
      <v-window-item value="llm">
        <v-card flat class="pa-4">
          <v-row>
            <v-col cols="12" md="6">
              <v-select
                v-model="form.provider"
                :items="providerItems"
                label="LLM Provider"
                variant="outlined"
                density="comfortable"
                :disabled="savingLlm"
                prepend-inner-icon="mdi-server-network-outline"
                hint="Choose a supported provider. 'custom' works with any OpenAI-compatible API."
                persistent-hint
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-autocomplete
                v-model="form.llm_model"
                :items="modelItems"
                label="Model"
                variant="outlined"
                density="comfortable"
                :disabled="savingLlm || loadingModels"
                prepend-inner-icon="mdi-robot-outline"
                :loading="loadingModels"
                clearable
                hint="Select a model from the provider. Click the refresh icon to re-fetch live."
                persistent-hint
              >
                <template #append-inner>
                  <v-btn
                    variant="text"
                    icon="mdi-refresh"
                    size="small"
                    :disabled="loadingModels || savingLlm"
                    @click="fetchModels(true)"
                    title="Refresh available models"
                  />
                </template>
              </v-autocomplete>
            </v-col>

            <v-col cols="12" md="6">
              <v-combobox
                v-model="form.provider_url"
                :items="baseUrlItems"
                :item-title="(it) => (typeof it === 'string' ? it : (it?.value || it?.url || ''))"
                :item-value="(it) => (typeof it === 'string' ? it : (it?.value || it?.url || ''))"
                :return-object="false"
                :label="fieldLabel('provider_url')"
                variant="outlined"
                density="comfortable"
                :disabled="savingLlm"
                prepend-inner-icon="mdi-link-variant"
                hint="Base URL for the provider API. Pick a preset or type a custom proxy/VPC endpoint; your prior URLs are remembered per provider."
                persistent-hint
                clearable
                hide-no-data
              >
                <template #prepend-item>
                  <v-list-item
                    v-if="!baseUrlItems.length"
                    title="No preset URLs for this provider yet."
                    subtitle="Type one above and Save to remember it."
                  />
                </template>
                <template #item="{ props, item: slotItem }">
                  <v-list-item v-bind="props">
                    <template #prepend>
                      <v-avatar
                        size="28"
                        :color="(isOfficialUrlChoice(slotItem) ? 'primary' : 'secondary') + '-lighten-5'"
                        class="mr-2 rounded-lg"
                      >
                        <v-icon
                          size="14"
                          :color="isOfficialUrlChoice(slotItem) ? 'primary' : 'secondary'"
                        >
                          {{ isOfficialUrlChoice(slotItem) ? 'mdi-check-decagram' : 'mdi-history' }}
                        </v-icon>
                      </v-avatar>
                    </template>
                    <v-list-item-title class="d-flex align-center gap-2">
                      <span class="text-body-2 font-mono" style="word-break: break-all;">
                        {{ urlFromChoice(slotItem) }}
                      </span>
                      <v-chip
                        size="x-small"
                        density="ultra-compact"
                        variant="flat"
                        :color="(isOfficialUrlChoice(slotItem) ? 'primary' : 'secondary')"
                      >
                        {{ urlChoiceKind(slotItem) }}
                      </v-chip>
                    </v-list-item-title>
                    <v-list-item-subtitle v-if="labelFromChoice(slotItem)" class="text-caption" style="opacity: 0.85">
                      {{ labelFromChoice(slotItem) }}
                    </v-list-item-subtitle>
                  </v-list-item>
                </template>
              </v-combobox>
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="form.api_key"
                :label="fieldLabel('api_key')"
                variant="outlined"
                density="comfortable"
                :disabled="!isWritable('api_key') || savingLlm"
                :type="showApiKey ? 'text' : 'password'"
                prepend-inner-icon="mdi-key-variant"
                autocomplete="new-password"
                :hint="isWritable('api_key') ? 'API key for the selected provider.' : 'Key not configurable for the selected provider.'"
                persistent-hint
              >
                <template #append-inner>
                  <v-btn
                    variant="text"
                    :icon="showApiKey ? 'mdi-eye-off' : 'mdi-eye'"
                    size="small"
                    @click="showApiKey = !showApiKey"
                  />
                </template>
              </v-text-field>
            </v-col>

            <v-col cols="12">
              <v-card flat class="pa-4" variant="tonal" elevation="0">
                <v-row class="align-center mb-2">
                  <v-col cols="12" md="6" class="py-0">
                    <div class="text-subtitle-1 font-weight-medium d-flex align-center gap-2">
                      <v-icon size="18" color="primary">mdi-database-search-outline</v-icon>
                      Cached Available Models
                    </div>
                    <div class="text-caption text-medium-emphasis">
                      Models discovered and cached locally after a successful refresh.
                      This list is used as the source of the Model dropdown above.
                    </div>
                  </v-col>
                  <v-col cols="12" md="6" class="py-0 d-flex justify-md-end justify-start">
                    <v-chip
                      size="small"
                      variant="tonal"
                      color="primary"
                      class="mr-2"
                    >
                      {{ normalizedAvailableModels.length }} model{{ normalizedAvailableModels.length === 1 ? '' : 's' }}
                    </v-chip>
                    <v-btn
                      size="small"
                      variant="text"
                      prepend-icon="mdi-refresh"
                      :loading="loadingModels"
                      :disabled="savingLlm || loadingModels"
                      @click="fetchModels(true)"
                    >
                      Refresh from provider
                    </v-btn>
                  </v-col>
                </v-row>
                <v-progress-linear
                  v-if="loadingModels"
                  indeterminate
                  color="primary"
                  class="mb-2"
                />
                <v-alert
                  v-if="!loadingModels && normalizedAvailableModels.length === 0"
                  type="info"
                  variant="tonal"
                  density="compact"
                  class="mb-0 mt-2"
                >
                  No cached models yet. Click <strong>Refresh from provider</strong> (or the
                  refresh icon next to the Model dropdown) to fetch the list.
                </v-alert>
                <v-virtual-scroll
                  v-else
                  :items="normalizedAvailableModels"
                  item-height="52"
                  height="320"
                >
                  <template #default="{ item, index }">
                    <v-list-item
                      :key="item.id"
                      class="px-2"
                      :class="index === normalizedAvailableModels.length - 1 ? '' : 'border-b border-opacity-50 border-divider'"
                    >
                      <template #prepend>
                        <v-avatar
                          size="36"
                          color="primary"
                          variant="tonal"
                          class="ml-1 mr-3"
                        >
                          <v-icon size="18" color="primary">
                            {{ modelIconFor(item) }}
                          </v-icon>
                        </v-avatar>
                      </template>
                      <v-list-item-title class="text-body-2 font-weight-medium">
                        <span class="font-mono text-caption">{{ item.id }}</span>
                        <v-chip
                          v-if="item.id === form.llm_model"
                          size="x-small"
                          color="success"
                          variant="flat"
                          class="ml-2 align-middle"
                        >
                          SELECTED
                        </v-chip>
                      </v-list-item-title>
                      <v-list-item-subtitle class="text-caption text-medium-emphasis">
                        {{ item.description || 'No description available.' }}
                      </v-list-item-subtitle>
                      <template #append>
                        <div class="d-flex flex-column align-end gap-1 mr-1">
                          <v-chip
                            v-if="item.context_length"
                            size="x-small"
                            variant="tonal"
                            prepend-icon="mdi-text-box-multiple-outline"
                          >
                            {{ formatContextLength(item.context_length) }}
                          </v-chip>
                          <span
                            v-if="item.owned_by"
                            class="text-caption text-medium-emphasis"
                          >
                            by {{ item.owned_by }}
                          </span>
                        </div>
                      </template>
                    </v-list-item>
                  </template>
                </v-virtual-scroll>
              </v-card>
            </v-col>

            <v-col cols="12">
              <v-card flat class="pa-4" variant="tonal" elevation="0">
                <v-row class="align-center mb-3">
                  <v-col cols="12" md="6" class="py-0">
                    <div class="text-subtitle-1 font-weight-medium d-flex align-center gap-2">
                      <v-icon size="18" color="primary">mdi-connection</v-icon>
                      Test Connection
                    </div>
                    <div class="text-caption text-medium-emphasis">
                      Validates the current (unsaved draft) provider, Base URL, API key,
                      and model with a real tiny ping call (≈32 tokens). You do not
                      need to Save first.
                    </div>
                  </v-col>
                  <v-col cols="12" md="6" class="py-0 d-flex justify-md-end justify-start gap-2">
                    <v-btn
                      v-if="testResult"
                      size="small"
                      variant="text"
                      prepend-icon="mdi-delete-sweep-outline"
                      :disabled="testingConn"
                      @click="testResult = null"
                    >
                      Clear
                    </v-btn>
                    <v-btn
                      size="small"
                      variant="flat"
                      color="primary"
                      prepend-icon="mdi-send-outline"
                      :loading="testingConn"
                      :disabled="testingConn || savingLlm || loadingModels"
                      @click="runTestConnection"
                    >
                      Run connection test
                    </v-btn>
                  </v-col>
                </v-row>

                <v-progress-linear
                  v-if="testingConn"
                  indeterminate
                  color="primary"
                  class="mb-2"
                />

                <v-alert
                  v-if="!testingConn && !testResult"
                  type="info"
                  variant="tonal"
                  density="comfortable"
                  class="mb-0"
                >
                  Click <strong>Run connection test</strong> above to send a tiny
                  ping request against the currently selected provider + URL + key +
                  model. The round-trip transcript appears below.
                </v-alert>

                <div v-if="testResult" class="mt-1">
                  <v-row class="mb-3">
                    <v-col cols="12" md="4">
                      <v-card variant="outlined" class="pa-3 h-100">
                        <div class="d-flex align-center gap-2 mb-1">
                          <v-icon size="16" :color="testResult.ok ? 'success' : 'error'">
                            {{ testResult.ok ? 'mdi-check-circle-outline' : 'mdi-alert-circle-outline' }}
                          </v-icon>
                          <span class="text-caption text-uppercase font-weight-bold" :class="testResult.ok ? 'text-success' : 'text-error'">
                            Result
                          </span>
                        </div>
                        <div class="text-subtitle-2 font-weight-bold" :class="testResult.ok ? 'text-success' : 'text-error'">
                          {{ testResult.status }}
                        </div>
                        <div class="text-caption text-medium-emphasis mt-1">
                          Started: {{ testResult.started_at }}
                          <br/>
                          Duration: {{ testResult.duration_ms }} ms
                          <span v-if="testResult.ttft_ms != null">
                            <br/>TTFT: {{ testResult.ttft_ms }} ms
                          </span>
                        </div>
                      </v-card>
                    </v-col>
                    <v-col cols="12" md="8">
                      <v-card variant="outlined" class="pa-3 h-100">
                        <div class="text-caption text-uppercase font-weight-bold text-medium-emphasis mb-1">
                          Target
                        </div>
                        <div class="d-flex flex-wrap gap-1">
                          <v-chip size="x-small" variant="tonal">
                            provider: <strong class="ml-1">{{ testResult.provider ?? '—' }}</strong>
                          </v-chip>
                          <v-chip size="x-small" variant="tonal">
                            model: <strong class="ml-1">{{ testResult.model ?? '—' }}</strong>
                          </v-chip>
                          <v-chip size="x-small" variant="tonal" class="maxw-100">
                            url: <span class="ml-1 text-truncate">{{ testResult.base_url ?? '—' }}</span>
                          </v-chip>
                        </div>
                        <div v-if="testResult.error" class="mt-2">
                          <div class="text-caption text-uppercase font-weight-bold text-error mb-1">
                            {{ testResult.error.class || 'Error' }}
                          </div>
                          <pre
                            class="bg-error-container text-error pa-2 rounded text-body-2 my-0 pre-wrap"
                            style="white-space: pre-wrap; word-break: break-word;"
                          >{{ testResult.error.message || '' }}</pre>
                          <v-alert
                            v-if="testResult.error.body"
                            type="error"
                            variant="tonal"
                            density="compact"
                            class="mt-2"
                          >
                            <template #text>
                              <pre style="white-space: pre-wrap; word-break: break-word; margin: 0; max-height: 140px; overflow: auto;">{{ testResult.error.body }}</pre>
                            </template>
                          </v-alert>
                        </div>
                        <div v-else-if="testResult.response" class="mt-2">
                          <div class="text-caption text-uppercase font-weight-bold text-success mb-1">
                            Reply
                          </div>
                          <pre class="bg-success-container text-on-success-container pa-2 rounded text-body-2 my-0" style="white-space: pre-wrap; word-break: break-word;">{{ testResult.response.text || '(empty)' }}</pre>
                          <div class="text-caption text-medium-emphasis mt-1 d-flex flex-wrap gap-2">
                            <span>finish_reason: <strong>{{ testResult.response.finish_reason ?? '—' }}</strong></span>
                            <span
                              v-if="testResult.response.usage && testResult.response.usage.prompt_tokens != null"
                            >
                              prompt_tokens: <strong>{{ testResult.response.usage.prompt_tokens }}</strong>
                            </span>
                            <span
                              v-if="testResult.response.usage && testResult.response.usage.completion_tokens != null"
                            >
                              completion_tokens: <strong>{{ testResult.response.usage.completion_tokens }}</strong>
                            </span>
                            <span
                              v-if="testResult.response.usage && testResult.response.usage.total_tokens != null"
                            >
                              total_tokens: <strong>{{ testResult.response.usage.total_tokens }}</strong>
                            </span>
                          </div>
                          <v-alert
                            v-if="testResult.validation && !testResult.validation.matched"
                            type="warning"
                            variant="tonal"
                            density="compact"
                            class="mt-2"
                          >
                            Expected reply prefix <strong>{{ testResult.validation.expected_reply_prefix }}</strong>
                            was not returned; the endpoint may behave unexpectedly.
                          </v-alert>
                        </div>
                      </v-card>
                    </v-col>
                  </v-row>

                  <v-card variant="outlined" class="pa-3">
                    <div class="text-caption text-uppercase font-weight-bold text-medium-emphasis mb-2 d-flex align-center justify-space-between">
                      <span>Connection transcript</span>
                      <span>
                        {{ testResult.log && testResult.log.length }} step{{ testResult.log && testResult.log.length === 1 ? '' : 's' }}
                      </span>
                    </div>
                    <v-virtual-scroll
                      v-if="testResult.log && testResult.log.length"
                      :items="testResult.log"
                      item-height="58"
                      height="260"
                    >
                      <template #default="{ item, index }">
                        <v-list-item class="px-0 py-1" border="opacity">
                          <template #prepend>
                            <v-avatar size="32" :color="phaseColor(item.phase)" variant="tonal">
                              <v-icon size="16" :color="phaseColor(item.phase)">
                                {{ phaseIcon(item.phase) }}
                              </v-icon>
                            </v-avatar>
                          </template>
                          <template #title>
                            <div class="d-flex align-center gap-2 flex-wrap">
                              <span class="font-mono text-caption text-medium-emphasis">
                                [{{ index + 1 }}]
                              </span>
                              <span class="font-weight-medium">
                                {{ item.phase }}
                              </span>
                              <v-chip size="x-small" variant="outline">
                                +{{ Math.round(item.ts * 1000) }} ms
                              </v-chip>
                              <v-chip
                                v-if="item.duration_ms != null"
                                size="x-small"
                                variant="tonal"
                              >
                                step: {{ item.duration_ms }} ms
                              </v-chip>
                            </div>
                          </template>
                          <template #subtitle>
                            <pre class="my-1 pa-2 rounded text-caption pre-wrap maxh-160"
                                 :class="item.phase && item.phase.toLowerCase().includes('error') ? 'bg-error-container text-error' : 'bg-surface-container-low text-medium-emphasis'"
                                 style="white-space: pre-wrap; word-break: break-word; overflow: auto;"
                            >{{ formatStepBody(item) }}</pre>
                          </template>
                        </v-list-item>
                      </template>
                    </v-virtual-scroll>
                  </v-card>
                </div>
              </v-card>
            </v-col>

            <v-col v-if="llmRuntimeWarning" cols="12" class="pt-0">
              <v-alert type="warning" variant="tonal" density="comfortable" closable @click:close="llmRuntimeWarning = ''">
                <template #prepend>
                  <v-icon size="18">mdi-alert-circle-outline</v-icon>
                </template>
                <template #title>Runtime switch notice</template>
                <div style="white-space: pre-wrap; word-break: break-word;">{{ llmRuntimeWarning }}</div>
              </v-alert>
            </v-col>

            <v-col cols="12" class="d-flex align-center justify-space-between flex-wrap gap-2">
              <div>
                <v-chip size="large" variant="tonal" class="mr-2">
                  Current: <strong class="ml-1">{{ liveSummary }}</strong>
                </v-chip>
                <v-chip
                  v-if="lastSavedLlm"
                  size="large"
                  color="success"
                  variant="tonal"
                  prepend-icon="mdi-check-circle-outline"
                >
                  Saved {{ lastSavedLlm }}
                </v-chip>
              </div>
              <div>
                <v-btn
                  color="primary"
                  variant="flat"
                  :disabled="savingLlm || loadingModels"
                  :loading="savingLlm"
                  prepend-icon="mdi-content-save-outline"
                  @click="saveLlmConfig"
                >
                  Save
                </v-btn>
              </div>
            </v-col>
          </v-row>
        </v-card>
      </v-window-item>

      <!-- ================= SKILLS TAB ================= -->
      <v-window-item value="skills">
        <v-card flat class="pa-4">
          <v-row class="mb-3 align-center">
            <v-col cols="12" md="6">
              <p class="text-body-1 text-medium-emphasis mb-0">
                Toggle skill availability. Disabled skills will not be exposed to the agent as tools.
              </p>
            </v-col>
            <v-col cols="12" md="6" class="d-flex justify-md-end justify-start">
              <v-btn
                variant="text"
                size="small"
                :disabled="loadingSkills"
                @click="loadSkills"
                prepend-icon="mdi-refresh"
              >
                Refresh
              </v-btn>
            </v-col>
          </v-row>

          <v-progress-linear
            v-if="loadingSkills"
            indeterminate
            color="primary"
            class="mb-4"
          />

          <v-data-table
            :items="skills"
            :headers="skillHeaders"
            :loading="loadingSkills"
            loading-text="Loading skills…"
            density="comfortable"
            items-per-page="-1"
            hide-default-footer
          >
            <template #item.enabled="{ item }">
              <v-switch
                :model-value="item.enabled"
                hide-details
                density="compact"
                color="success"
                :disabled="togglingSkill === item.name"
                :loading="togglingSkill === item.name"
                @update:model-value="(val) => toggleSkill(item, val)"
              />
            </template>
            <template #item.tools="{ item }">
              <v-chip
                v-if="item.tool_count"
                size="small"
                variant="tonal"
                color="primary"
                class="mr-2"
              >
                {{ item.tool_count }} tool{{ item.tool_count === 1 ? '' : 's' }}
              </v-chip>
              <v-tooltip v-if="item.tool_names?.length" location="top">
                <template #activator="{ props }">
                  <v-btn
                    v-bind="props"
                    variant="text"
                    icon="mdi-information-outline"
                    size="x-small"
                  />
                </template>
                <div class="text-caption pa-2" style="max-width: 320px;">
                  <div v-for="(t, idx) in item.tool_names" :key="t + idx">
                    • {{ t }}
                  </div>
                </div>
              </v-tooltip>
            </template>
          </v-data-table>
        </v-card>
      </v-window-item>

      <!-- ================= RAW CONFIG TAB ================= -->
      <v-window-item value="raw">
        <v-card flat class="pa-4">
          <v-row class="mb-3 align-center">
            <v-col cols="12" md="6">
              <p class="text-body-1 text-medium-emphasis mb-0">
                Edit the raw <code>config.json</code>. Changes are merged into the live config.
              </p>
            </v-col>
            <v-col cols="12" md="6" class="d-flex justify-md-end justify-start gap-2">
              <v-btn
                variant="text"
                :disabled="loadingRaw || savingRaw"
                @click="loadRawConfig"
                prepend-icon="mdi-refresh"
              >
                Reload
              </v-btn>
              <v-btn
                variant="outlined"
                :disabled="loadingRaw || savingRaw"
                @click="formatRawConfig"
                prepend-icon="mdi-format-indent-increase"
              >
                Format JSON
              </v-btn>
              <v-btn
                color="primary"
                variant="flat"
                :disabled="loadingRaw || savingRaw || !rawValid"
                :loading="savingRaw"
                prepend-icon="mdi-content-save-outline"
                @click="saveRawConfig"
              >
                Save Config
              </v-btn>
            </v-col>
          </v-row>

          <v-progress-linear
            v-if="loadingRaw"
            indeterminate
            color="primary"
            class="mb-4"
          />

          <v-textarea
            v-model="rawConfigText"
            label="config.json"
            variant="outlined"
            density="comfortable"
            rows="20"
            auto-grow
            hide-details="auto"
            :disabled="loadingRaw || savingRaw"
            :error="!rawValid && rawConfigText.length > 0"
            :error-messages="rawValid ? [] : ['Invalid JSON — check syntax before saving.']"
            class="font-mono text-caption"
          />

          <v-row class="mt-3">
            <v-col cols="12" class="d-flex align-center justify-space-between flex-wrap gap-2">
              <v-chip
                v-if="rawValid && rawConfigText.length > 0"
                color="success"
                variant="tonal"
                size="small"
                prepend-icon="mdi-check-circle-outline"
              >
                Valid JSON
              </v-chip>
              <v-chip
                v-else-if="rawConfigText.length > 0"
                color="error"
                variant="tonal"
                size="small"
                prepend-icon="mdi-alert-circle-outline"
              >
                Invalid JSON
              </v-chip>
              <v-chip
                v-if="lastSavedRaw"
                size="small"
                color="primary"
                variant="tonal"
                prepend-icon="mdi-check-circle-outline"
              >
                Saved {{ lastSavedRaw }}
              </v-chip>
            </v-col>
          </v-row>
        </v-card>
      </v-window-item>
    </v-window>
  </v-sheet>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'

const tab = ref('llm')
const showApiKey = ref(false)

// ---------- LLM tab ----------
const loadingLlm = ref(false)
const savingLlm = ref(false)
const loadingModels = ref(false)
const projectingProvider = ref(false)
const testingConn = ref(false)
const testResult = ref(null)
const llmRuntimeWarning = ref('')
const lastSavedLlm = ref('')
const llmConfig = ref({ config: {}, fields: [], provider: '', real_provider: '', providers_supported: [] })
const form = ref({
  provider: '',
  provider_url: '',
  llm_model: '',
  api_key: '',
  available_models: [],
})
const providerItems = computed(() =>
  llmConfig.value.providers_supported.map(p => ({
    title: p.charAt(0).toUpperCase() + p.slice(1),
    value: p,
  }))
)
const _urlChoicesForCurrentProvider = computed(() => {
  const fields = Array.isArray(llmConfig.value?.fields) ? llmConfig.value.fields : []
  const f = fields.find(x => x && x.key === 'provider_url')
  const c = f && Array.isArray(f.choices) ? f.choices : []
  return c
})
const baseUrlItems = computed(() => {
  // Combobox items. For each preset/remembered row coming from the backend,
  // we wrap it so that:
  //   - `value` is the URL string (always! This is what ends up in form.provider_url
  //     when the user selects the row from the dropdown. Also used as item-title
  //     so the closed combobox INPUT shows the actual URL — never a human label.)
  //   - `title` is the same URL string (used by Vuetify as fallback display).
  //   - `raw` carries the backend-originated dict untouched so helper functions
  //     can read official / remembered / label flags for the dropdown decoration.
  //
  // If the user typed a URL that isn't in choices yet we prepend it as a draft
  // row so the combobox shows it selected.
  const fromChoices = _urlChoicesForCurrentProvider.value.map(row => {
    const url = (row && typeof row === 'object') ? String(row.url || '').trim() : String(row || '').trim()
    const raw = typeof row === 'object' ? { ...row, url } : { url, official: false, remembered: false }
    return {
      title: url,
      value: url,
      raw,
    }
  })
  const current = (form.value.provider_url || '').trim()
  if (!current) return fromChoices
  const present = fromChoices.some(x => x.value === current)
  if (present) return fromChoices
  return [
    { title: current, value: current, raw: { url: current, official: false, remembered: false } },
    ...fromChoices,
  ]
})
function _rawFromSlotItem(slotItem) {
  // Defensive: Vuetify's #item `item` slot arg shape varies; unwrap until we
  // find the object with { url, official, remembered, label }.
  if (!slotItem) return null
  if (slotItem.raw && typeof slotItem.raw === 'object') return slotItem.raw
  if (typeof slotItem.props?.item?.raw === 'object') return slotItem.props.item.raw
  if (typeof slotItem.item?.raw === 'object') return slotItem.item.raw
  if (typeof slotItem === 'object' && ('url' in slotItem || 'official' in slotItem)) return slotItem
  if (slotItem.value && typeof slotItem.value === 'object' && 'url' in slotItem.value) return slotItem.value
  return null
}
function urlFromChoice(slotItem) {
  const r = _rawFromSlotItem(slotItem)
  if (r && r.url) return String(r.url)
  if (slotItem?.value != null && typeof slotItem.value === 'string') return slotItem.value
  if (slotItem?.title != null && typeof slotItem.title === 'string') return slotItem.title
  return String(slotItem || '')
}
function labelFromChoice(slotItem) {
  const r = _rawFromSlotItem(slotItem)
  if (!r) return ''
  const label = String(r.label || '').trim()
  const url = String(r.url || '').trim()
  if (label && label !== url) return label
  return ''
}
function isOfficialUrlChoice(slotItem) {
  const r = _rawFromSlotItem(slotItem)
  return !!(r && r.official)
}
function urlChoiceKind(slotItem) {
  const r = _rawFromSlotItem(slotItem)
  if (!r) return 'Custom'
  if (r.official) return 'Official'
  if (r.remembered) return 'Remembered'
  return 'Custom'
}
function baseUrlItemTitle(it) {
  // Fallback: always return URL string.
  if (it == null) return ''
  if (typeof it === 'string') return it
  if (typeof it.value === 'string') return it.value
  if (typeof it.url === 'string') return it.url
  if (typeof it.title === 'string') return it.title
  return String(it)
}
const modelItems = computed(() => {
  // The Model dropdown shows ONLY the cached available_models list for
  // the currently selected provider (+ current model, in case cache is
  // still empty).  Refresh populates the cache; dropdown never does its
  // own provider-API calls.
  const cache = normalizedAvailableModels.value
  const fromCache = Array.isArray(cache) ? cache.map(m => ({ title: m.id + (m.context_length ? ` · ${formatContextLength(m.context_length)}` : ''), subtitle: m.description, value: m.id })) : []
  const curr = form.value.llm_model ? [{
    title: form.value.llm_model,
    value: form.value.llm_model,
  }] : []
  const seenIds = new Set()
  const out = []
  for (const o of [...curr, ...fromCache]) {
    if (!o || !o.value) continue
    if (seenIds.has(o.value)) continue
    seenIds.add(o.value)
    out.push(o)
  }
  return out
})
const liveSummary = computed(() => {
  // Show only the SAVED (persisted) provider + model here, not the
  // currently-drafted values in the form.  Only updates after Save.
  const savedProvider = llmConfig.value.real_provider || llmConfig.value.provider || llmConfig.value.config?.provider || '(none)'
  const savedModel = llmConfig.value.config?.llm_model || '(no model)'
  return `${savedProvider} / ${savedModel}`
})
const draftSummary = computed(() => {
  // Optional: quick preview of what will be saved on Save (not used in chip yet)
  const p = form.value.provider || '(none)'
  const m = form.value.llm_model || '(no model)'
  return `${p} / ${m}`
})
const normalizedAvailableModels = computed(() => {
  // Normalize cached available_models into list[dict] {id, description?, context_length?, owned_by?}.
  // Handles legacy list[str] (from old cached configs) or new list[dict] from refreshed backend.
  const raw = form.value.available_models
  if (!Array.isArray(raw)) return []
  const out = []
  const seen = new Set()
  for (const m of raw) {
    if (m == null) continue
    let entry
    if (typeof m === 'string' || typeof m === 'number') {
      entry = { id: String(m) }
    } else if (typeof m === 'object') {
      if (!m.id) continue
      entry = { id: String(m.id) }
      if (typeof m.description === 'string' && m.description.trim()) entry.description = m.description.trim()
      if (typeof m.owned_by === 'string' && m.owned_by.trim()) entry.owned_by = m.owned_by.trim()
      const ctx = Number(m.context_length)
      if (Number.isFinite(ctx) && ctx > 0) entry.context_length = Math.floor(ctx)
    } else {
      continue
    }
    if (seen.has(entry.id)) continue
    seen.add(entry.id)
    if (!entry.description) {
      entry.description = summarizeCachedModel(entry, form.value.provider)
    }
    out.push(entry)
  }
  return out.sort((a, b) => a.id.localeCompare(b.id))
})
function summarizeCachedModel(entry, provider) {
  const id = (entry.id || '').toLowerCase()
  const parts = []
  const prov = (provider || '').toLowerCase()
  if (prov === 'custom' || id.includes('gpt') || prov === 'openai') {
    if (id.includes('gpt-5')) parts.push('OpenAI next-gen reasoning model')
    else if (id.includes('gpt-4o')) parts.push('OpenAI flagship multimodal model')
    else if (id.includes('gpt-4')) parts.push('OpenAI GPT-4 large reasoning model')
    else if (id.includes('o1') || id.includes('o3') || id.includes('o4')) parts.push('OpenAI reasoning / o-series model')
    else if (id.includes('gpt-3.5') || id.includes('gpt-35')) parts.push('OpenAI GPT-3.5 fast general-purpose model')
  }
  if (!parts.length && (prov === 'deepseek' || id.includes('deepseek'))) {
    if (id.includes('r1') || id.includes('reason')) parts.push('DeepSeek reasoning (R1) model')
    else if (id.includes('coder')) parts.push('DeepSeek code-specialized model')
    else parts.push('DeepSeek-family model')
  }
  if (!parts.length && (prov === 'dashscope' || id.includes('qwen'))) {
    parts.push('DashScope / Qwen-family model')
  }
  if (!parts.length && (prov === 'ollama' || prov === 'llama' || id.includes('llama'))) {
    parts.push('Local / Ollama-family model')
  }
  if (!parts.length) {
    if (entry.owned_by) parts.push(`${entry.owned_by} model`)
    else parts.push((prov || 'Custom endpoint').trim().replace(/^./, c => c.toUpperCase()) + ' model')
  }
  if (entry.context_length) parts.push(`${formatContextLength(entry.context_length)} context`)
  return parts.join(' — ')
}
function formatContextLength(n) {
  const v = Number(n) || 0
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M tok`
  if (v >= 1000) return `${Math.floor(v / 1000)}K tok`
  return `${v} tok`
}
function modelIconFor(entry) {
  const id = (entry.id || '').toLowerCase()
  const prov = (form.value.provider || '').toLowerCase()
  if (prov === 'ollama' || prov === 'llama' || id.includes('llama')) return 'mdi-server-network'
  if (prov === 'custom') return 'mdi-cloud-outline'
  if (id.includes('reason') || id.includes('r1') || id.includes('qwq') || id.startsWith('o')) return 'mdi-head-snowflake-outline'
  if (id.includes('vision') || id.includes('4o')) return 'mdi-image-outline'
  if (id.includes('coder') || id.includes('code')) return 'mdi-code-tags'
  if (id.includes('qwen')) return 'mdi-star-four-points-outline'
  return 'mdi-robot-outline'
}
const _fieldMap = computed(() => {
  const map = {}
  for (const f of (llmConfig.value.fields || [])) map[f.key] = f
  return map
})
function fieldLabel(key) {
  return _fieldMap.value[key]?.label || key
}
function isWritable(key) {
  return _fieldMap.value[key]?.writable !== false
}

async function projectProviderFields(newProvider, { populateModels = true } = {}) {
  if (!newProvider) return
  projectingProvider.value = true
  try {
    const res = await fetch(`/api/config/llm?provider=${encodeURIComponent(newProvider)}`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    // Keep the projection metadata so labels / writable bits reflect the target provider
    llmConfig.value = {
      ...llmConfig.value,
      fields: data.fields || [],
      provider: data.provider || newProvider,
      real_provider: data.real_provider || llmConfig.value.real_provider,
      providers_supported: data.providers_supported || llmConfig.value.providers_supported,
    }
    const cfg = data.config || {}
    form.value.provider_url = cfg.provider_url || ''
    form.value.llm_model = cfg.llm_model || ''
    form.value.api_key = cfg.api_key || ''
    form.value.available_models = Array.isArray(cfg.available_models) ? [...cfg.available_models] : []
    if (populateModels && (!form.value.available_models || form.value.available_models.length === 0)) {
      // Attempt a cache-only model fetch for this provider so the dropdown still has items.
      fetchModels(false).catch(() => {})
    }
  } catch (e) {
    console.error('Failed to project provider fields', e)
  } finally {
    projectingProvider.value = false
  }
}

async function loadLlmConfig() {
  loadingLlm.value = true
  llmRuntimeWarning.value = ''
  try {
    const res = await fetch('/api/config/llm')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    llmConfig.value = data
    const cfg = data.config || {}
    form.value = {
      provider: cfg.provider || '',
      provider_url: cfg.provider_url || '',
      llm_model: cfg.llm_model || '',
      api_key: cfg.api_key || '',
      available_models: Array.isArray(cfg.available_models) ? [...cfg.available_models] : [],
    }
  } catch (e) {
    console.error('Failed to load LLM config', e)
  } finally {
    loadingLlm.value = false
  }
}

async function saveLlmConfig() {
  savingLlm.value = true
  llmRuntimeWarning.value = ''
  try {
    const payload = { ...form.value }
    if (!payload.api_key) delete payload.api_key
    const res = await fetch('/api/config/llm', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
    const data = await res.json()
    lastSavedLlm.value = new Date().toLocaleTimeString()
    if (data && typeof data === 'object' && data.runtime_warning) {
      llmRuntimeWarning.value = String(data.runtime_warning)
    } else {
      llmRuntimeWarning.value = ''
    }
    await loadLlmConfig()
  } catch (e) {
    console.error('Failed to save LLM config', e)
    alert('Failed to save LLM config: ' + e.message)
  } finally {
    savingLlm.value = false
  }
}

async function fetchModels(force = false) {
  loadingModels.value = true
  try {
    const params = new URLSearchParams()
    if (form.value.provider) params.set('provider', form.value.provider)
    if (force) {
      params.set('refresh', 'true')
      // When the user clicks refresh, pass the CURRENT (unsaved draft) values
      // of base URL + API key to the endpoint. This lets them probe a Custom
      // endpoint or proxy URL without saving first.
      if (form.value.provider_url) params.set('base_url', form.value.provider_url)
      if (form.value.api_key && isWritable('api_key')) params.set('api_key', form.value.api_key)
    }
    const url = '/api/config/models' + (params.toString() ? `?${params.toString()}` : '')
    const res = await fetch(url)
    if (!res.ok) {
      const txt = await res.text()
      throw new Error(`HTTP ${res.status}: ${txt || res.statusText}`)
    }
    const data = await res.json()
    const models = Array.isArray(data.models) ? data.models : []
    // Normalize: accept both list[str] (legacy) and list[dict] (new enriched)
    form.value.available_models = models
    // If a model list is returned, pre-select the first valid id if nothing is chosen yet.
    if (models.length && !form.value.llm_model) {
      const first = models[0]
      form.value.llm_model = typeof first === 'string' ? first : (first?.id || '')
    }
    if (force) {
      // After a successful refresh, persist the enriched model list to the
      // active provider's LLM settings (dual-writes to flat + per-provider caches).
      const modelsAsDicts = models.map(m => (typeof m === 'string' ? { id: m } : m))
      try {
        const saveRes = await fetch('/api/config/llm', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            available_models: modelsAsDicts,
            provider: form.value.provider || undefined,
          }),
        })
        if (!saveRes.ok) {
          const t = await saveRes.text()
          console.warn('Failed to persist refreshed available_models:', saveRes.status, t)
        }
      } catch (persistErr) {
        console.warn('Failed to persist refreshed available_models:', persistErr)
      }
    }
  } catch (e) {
    console.error('Failed to fetch models', e)
    alert('Failed to fetch models: ' + e.message)
  } finally {
    loadingModels.value = false
  }
}

async function runTestConnection() {
  testingConn.value = true
  try {
    const res = await fetch('/api/config/llm/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: form.value.provider || undefined,
        provider_url: form.value.provider_url || undefined,
        llm_model: form.value.llm_model || undefined,
        api_key: form.value.api_key || undefined,
      }),
    })
    const text = await res.text()
    let parsed
    try {
      parsed = text ? JSON.parse(text) : null
    } catch (e) {
      parsed = {
        ok: false,
        status: 'parse_error',
        started_at: new Date().toTimeString().slice(0, 8),
        duration_ms: 0,
        error: {
          class: 'ParseError',
          message: e.message,
          body: text.slice(0, 4000),
        },
        log: [{
          ts: 0,
          phase: 'http.parse_error',
          status: res.status,
          body_preview: text.slice(0, 1000),
        }],
      }
    }
    if (parsed && typeof parsed === 'object') {
      testResult.value = parsed
    } else {
      testResult.value = {
        ok: false,
        status: 'unknown',
        error: { message: `Unexpected response (HTTP ${res.status})`, body: text.slice(0, 2000) },
        log: [],
      }
    }
  } catch (e) {
    testResult.value = {
      ok: false,
      status: 'network_error',
      started_at: new Date().toTimeString().slice(0, 8),
      duration_ms: 0,
      error: {
        class: e.name || 'Error',
        message: e.message,
      },
      log: [{
        ts: 0,
        phase: 'network.error',
        message: e.message,
      }],
    }
  } finally {
    testingConn.value = false
  }
}

function phaseColor(phase) {
  const p = (phase || '').toString().toLowerCase()
  if (p.includes('error')) return 'error'
  if (p.startsWith('resolve') || p.startsWith('client')) return 'secondary'
  if (p.startsWith('request')) return 'primary'
  if (p.startsWith('response') || p.includes('.ok')) return 'success'
  if (p.startsWith('validate')) return 'warning'
  return 'surface-variant'
}

function phaseIcon(phase) {
  const p = (phase || '').toString().toLowerCase()
  if (p.includes('error')) return 'mdi-alert-circle-outline'
  if (p.startsWith('resolve')) return 'mdi-cog-outline'
  if (p.startsWith('validate')) return 'mdi-shield-check-outline'
  if (p.startsWith('client')) return 'mdi-connection'
  if (p.startsWith('request')) return 'mdi-send-outline'
  if (p.startsWith('response')) return 'mdi-reply-outline'
  return 'mdi-dots-horizontal'
}

function _sortedJSON(obj, indent = 2) {
  if (obj == null) return 'null'
  if (typeof obj !== 'object') return JSON.stringify(obj, null, indent)
  // Hide sensitive values in UI if any sneaked in
  const sanitize = (key, value) => {
    const k = (key || '').toString().toLowerCase()
    if ((k.includes('key') || k.includes('secret') || k.includes('token')) &&
        typeof value === 'string' && value.length > 8) {
      return value.slice(0, 4) + '••••' + value.slice(-2)
    }
    return value
  }
  try {
    return JSON.stringify(obj, sanitize, indent)
  } catch (_e) {
    return String(obj)
  }
}

function formatStepBody(item) {
  if (!item || typeof item !== 'object') return ''
  const parts = []
  const ignored = new Set(['phase', 'ts', 'step'])
  for (const [k, v] of Object.entries(item)) {
    if (ignored.has(k)) continue
    if (v == null || v === '') continue
    parts.push(`${k} = ${typeof v === 'object' ? _sortedJSON(v, 2) : String(v)}`)
  }
  return parts.join('\n')
}

const _providerSwitchInFlight = ref(false)
watch(
  () => form.value.provider,
  (newProvider, oldProvider) => {
    if (!newProvider) return
    // Skip during initial load (oldProvider is undefined/empty) to avoid double-fetching
    // after loadLlmConfig() already populated the form.
    if (!oldProvider && !_providerSwitchInFlight.value) return
    _providerSwitchInFlight.value = true
    projectProviderFields(newProvider, { populateModels: true }).finally(() => {
      _providerSwitchInFlight.value = false
    })
  },
  { flush: 'post' }
)

// ---------- Skills tab ----------
const loadingSkills = ref(false)
const togglingSkill = ref('')
const skills = ref([])
const skillHeaders = [
  { title: 'Enabled', key: 'enabled', width: '110px', align: 'center' },
  { title: 'Skill', key: 'name' },
  { title: 'Description', key: 'description' },
  { title: 'Tools', key: 'tools', width: '260px' },
]

async function loadSkills() {
  loadingSkills.value = true
  try {
    const res = await fetch('/api/skills')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    skills.value = await res.json()
  } catch (e) {
    console.error('Failed to load skills', e)
  } finally {
    loadingSkills.value = false
  }
}

async function toggleSkill(item, enabled) {
  togglingSkill.value = item.name
  try {
    const res = await fetch('/api/skills/toggle', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ skill_name: item.name, enabled }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    item.enabled = enabled
  } catch (e) {
    console.error('Failed to toggle skill', e)
    alert('Failed to toggle skill: ' + e.message)
    item.enabled = !enabled
  } finally {
    togglingSkill.value = ''
  }
}

// ---------- Raw config tab ----------
const loadingRaw = ref(false)
const savingRaw = ref(false)
const rawConfigText = ref('')
const rawValid = ref(true)
const lastSavedRaw = ref('')

function validateRaw() {
  if (!rawConfigText.value.trim()) {
    rawValid.value = true
    return
  }
  try {
    JSON.parse(rawConfigText.value)
    rawValid.value = true
  } catch {
    rawValid.value = false
  }
}
watch(rawConfigText, validateRaw)

async function loadRawConfig() {
  loadingRaw.value = true
  try {
    const res = await fetch('/api/config')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    rawConfigText.value = JSON.stringify(data, null, 2)
    rawValid.value = true
  } catch (e) {
    console.error('Failed to load raw config', e)
  } finally {
    loadingRaw.value = false
  }
}

function formatRawConfig() {
  try {
    const obj = JSON.parse(rawConfigText.value || '{}')
    rawConfigText.value = JSON.stringify(obj, null, 2)
    rawValid.value = true
  } catch {
    rawValid.value = false
    alert('Cannot format invalid JSON.')
  }
}

async function saveRawConfig() {
  if (!rawValid.value) return
  savingRaw.value = true
  try {
    const obj = JSON.parse(rawConfigText.value)
    const res = await fetch('/api/config', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(obj),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`)
    lastSavedRaw.value = new Date().toLocaleTimeString()
    await loadRawConfig()
  } catch (e) {
    console.error('Failed to save raw config', e)
    alert('Failed to save raw config: ' + e.message)
  } finally {
    savingRaw.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadLlmConfig(), loadSkills(), loadRawConfig()])
})
</script>
