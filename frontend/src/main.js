import { createApp } from 'vue'
import App from './App.vue'

// Vuetify
import 'vuetify/styles'
import { createVuetify } from 'vuetify'
import '@mdi/font/css/materialdesignicons.css'
import * as components from 'vuetify/components'
import * as directives from 'vuetify/directives'

// Router
import router from './router'

const savedTheme = localStorage.getItem('collig-theme') || 'light'

const vuetify = createVuetify({
  components,
  directives,
  theme: {
    defaultTheme: savedTheme,
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
    },
  },
})

const app = createApp(App)
app.use(vuetify)
app.use(router)
app.mount('#app')
