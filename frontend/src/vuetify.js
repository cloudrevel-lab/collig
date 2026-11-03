import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import '@mdi/font/css/materialdesignicons.css'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

const savedTheme = localStorage.getItem('collig-theme') || 'light'

const terminalDark = {
  dark: true,
  colors: {
    background: '#0d1117',
    surface: '#161b22',
    'surface-variant': '#21262d',
    primary: '#7ee787',
    'primary-darken-1': '#56d364',
    secondary: '#79c0ff',
    'secondary-darken-1': '#58a6ff',
    error: '#ff7b72',
    info: '#79c0ff',
    success: '#7ee787',
    warning: '#d29922',
  },
}

const terminalLight = {
  dark: false,
  colors: {
    background: '#fbfbfd',
    surface: '#ffffff',
    'surface-variant': '#eaeef2',
    primary: '#1f6feb',
    'primary-darken-1': '#0969da',
    secondary: '#8250df',
    'secondary-darken-1': '#6f42c1',
    error: '#cf222e',
    info: '#0969da',
    success: '#1a7f37',
    warning: '#9a6700',
  },
}

// Shared by the full console (main.js) and the standalone terminal
// (main-terminal.js).  The terminal-specific themes are used by
// v-theme-provider inside TerminalView, so switching the terminal does not
// repaint the rest of the admin console.
export function createColligVuetify(defaultTheme = savedTheme) {
  return createVuetify({
    components,
    directives,
    theme: {
      defaultTheme,
      themes: {
        light: {
          dark: false,
          colors: {
            background: '#F5F5F5',
            surface: '#FFFFFF',
            'surface-variant': '#E7E0EC',
            primary: '#1976D2',
            'primary-darken-1': '#1565C0',
            secondary: '#009688',
            'secondary-darken-1': '#00796B',
            error: '#B00020',
            info: '#2196F3',
            success: '#4CAF50',
            warning: '#FB8C00',
          },
        },
        dark: {
          dark: true,
          colors: {
            background: '#121212',
            surface: '#1E1E1E',
            'surface-variant': '#4A4458',
            primary: '#64B5F6',
            'primary-darken-1': '#42A5F5',
            secondary: '#4DB6AC',
            'secondary-darken-1': '#26A69A',
            error: '#CF6679',
            info: '#90CAF9',
            success: '#81C784',
            warning: '#FFB74D',
          },
        },
        colligTerminalDark: terminalDark,
        colligTerminalLight: terminalLight,
      },
    },
  })
}

export const vuetify = createColligVuetify()
