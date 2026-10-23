export type PetSnapshot = {
  state: string
  caption: string | null
  hasResult: boolean
  isPaused: boolean
  isMuted: boolean
  connected: boolean
  lastPollAt: string | null
  history: Array<{
    timestamp: string
    state: string
    caption: string | null
  }>
}

declare module 'claude-code' {
  interface PluginState {
    'k2-pet-mod': { snapshot: PetSnapshot }
  }
}
