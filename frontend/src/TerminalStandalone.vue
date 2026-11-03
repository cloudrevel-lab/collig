<template>
  <v-app>
    <v-app-bar elevation="1" density="compact">
      <v-app-bar-title>
        <span class="brand">Collig</span>
        <span class="brand-sub">Terminal</span>
      </v-app-bar-title>
      <v-spacer />
      <v-chip size="small" variant="tonal" color="primary" class="me-2">
        sandboxed
      </v-chip>
    </v-app-bar>
    <v-main>
      <v-container fluid class="pa-4">
        <TerminalView standalone />
      </v-container>
    </v-main>
  </v-app>
</template>

<script setup>
import TerminalView from './views/TerminalView.vue'
</script>

<style scoped>
.brand {
  font-weight: 700;
  letter-spacing: 0.02em;
}
.brand-sub {
  margin-left: 8px;
  opacity: 0.6;
  font-weight: 400;
  font-size: 0.9em;
}
</style>
