import { computed, ref } from 'vue'

const STORAGE_KEY = 'collig-terminal-color'

function initialTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'light' ? 'colligTerminalLight' : 'colligTerminalDark'
  } catch (_) {
    return 'colligTerminalDark'
  }
}

// Module-level state so the standalone app bar and TerminalView agree.
const terminalTheme = ref(initialTheme())

export function useTerminalTheme() {
  const isDark = computed(() => terminalTheme.value === 'colligTerminalDark')

  function setTheme(mode) {
    terminalTheme.value = mode === 'light' ? 'colligTerminalLight' : 'colligTerminalDark'
    try {
      localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
    } catch (_) {
      // Ignore storage failures; the current view still switches.
    }
  }

  function toggle() {
    setTheme(isDark.value ? 'light' : 'dark')
  }

  return { terminalTheme, isDark, setTheme, toggle }
}
