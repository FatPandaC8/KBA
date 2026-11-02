import { ref, onMounted } from 'vue'

export type PaletteName = 'slate' | 'terracotta' | 'moss' | 'ochre'

export interface PaletteOption {
  id: PaletteName
  name: string
  accentColor: string
  nodeFill: string
  description: string
}

export const PALETTES: PaletteOption[] = [
  {
    id: 'slate',
    name: 'Editorial Slate',
    accentColor: '#2C3E50',
    nodeFill: '#F1F5F9',
    description: 'Crisp editorial monochrome with steel-slate accents.'
  },
  {
    id: 'terracotta',
    name: 'Terracotta Stone',
    accentColor: '#9C4221',
    nodeFill: '#FDF2E9',
    description: 'Warm burnt clay and earthenware hues.'
  },
  {
    id: 'moss',
    name: 'Olive Moss',
    accentColor: '#2D3B2D',
    nodeFill: '#F4F7F4',
    description: 'Subdued forest lichen and deep pine tones.'
  },
  {
    id: 'ochre',
    name: 'Ochre Sand',
    accentColor: '#6B4F1D',
    nodeFill: '#FAF6ED',
    description: 'Mineral umber and warm sunlit sand.'
  }
]

const currentPalette = ref<PaletteName>('slate')

export const usePalette = () => {
  const setPalette = (palette: PaletteName) => {
    currentPalette.value = palette
    if (typeof window !== 'undefined') {
      localStorage.setItem('gusby_palette', palette)
      document.documentElement.setAttribute('data-palette', palette)
    }
  }

  const initPalette = () => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('gusby_palette') as PaletteName
      if (saved && PALETTES.some(p => p.id === saved)) {
        setPalette(saved)
      } else {
        setPalette('slate')
      }
    }
  }

  return {
    currentPalette,
    palettes: PALETTES,
    setPalette,
    initPalette
  }
}
