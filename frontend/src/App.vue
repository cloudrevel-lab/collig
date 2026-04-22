<template>
  <v-app>
    <v-navigation-drawer v-model="drawer" permanent>
      <v-list-item
        prepend-avatar="https://api.dicebear.com/7.x/bottts/svg?seed=collig"
        title="Collig"
        subtitle="Admin Console"
      />
      <v-divider />
      <v-list density="compact" nav>
        <v-list-item
          v-for="item in menuItems"
          :key="item.route"
          :to="item.route"
          :prepend-icon="item.icon"
          :title="item.title"
          link
          rounded="lg"
        />
      </v-list>
    </v-navigation-drawer>

    <v-app-bar elevation="1">
      <v-app-bar-title>{{ currentTitle }}</v-app-bar-title>
      <v-spacer />
      <v-btn
        :icon="isDark ? 'mdi-white-balance-sunny' : 'mdi-weather-night'"
        variant="text"
        @click="toggleTheme"
        :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
      />
    </v-app-bar>

    <v-main>
      <v-container fluid class="pa-4 fill-height">
        <router-view />
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useThemeToggle } from './composables/useTheme'

const drawer = ref(true)
const route = useRoute()
const { toggleTheme, isDark } = useThemeToggle()

const menuItems = [
  { title: 'Chat', icon: 'mdi-chat', route: '/chat' },
  { title: 'Dashboard', icon: 'mdi-view-dashboard', route: '/dashboard' },
  { title: 'Sessions', icon: 'mdi-format-list-bulleted', route: '/sessions' },
  { title: 'Bookmarks', icon: 'mdi-bookmark', route: '/bookmarks' },
  { title: 'Notes', icon: 'mdi-note-text', route: '/notes' },
  { title: 'Diary', icon: 'mdi-book-open-page-variant', route: '/diary' },
]

const currentTitle = computed(() => {
  const item = menuItems.find(i => i.route === route.path)
  return item ? item.title : 'Collig'
})
</script>
