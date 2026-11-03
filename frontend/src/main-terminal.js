import { createApp } from 'vue'
import TerminalStandalone from './TerminalStandalone.vue'
import { createColligVuetify } from './vuetify'

// The standalone terminal is dark by default; TerminalView owns the
// terminal-scoped light/dark switch and persists it separately.
createApp(TerminalStandalone).use(createColligVuetify('dark')).mount('#app')
