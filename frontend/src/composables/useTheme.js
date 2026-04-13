// composable/useTheme.js
import { useTheme } from 'vuetify'

export function useThemeToggle() {
  const theme = useTheme()

  function toggleTheme() {
    const newTheme = theme.global.current.value.dark ? 'light' : 'dark'
    theme.global.name.value = newTheme
    localStorage.setItem('collig-theme', newTheme)
  }

  function isDark() {
    return theme.global.current.value.dark
  }

  return { toggleTheme, isDark, theme }
}
