import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'

export const OracleTheme = definePreset(Aura, {
  semantic: {
    colorScheme: {
      dark: {
        surface: {
          0: '#F2F3F5',
          50: '#C7CBD1',
          100: '#9AA0A8',
          200: '#6B7178',
          300: '#5D636B',
          400: '#4A4F56',
          500: '#3A3E44',
          600: '#2A2D32',
          700: '#1D2027',
          800: '#17191E',
          900: '#111318',
          950: '#0B0C0F',
        },
        text: {
          color: '#F2F3F5',
          hoverColor: '#F2F3F5',
          mutedColor: '#9AA0A8',
          hoverMutedColor: '#C7CBD1',
        },
        content: {
          background: '#131519',
          hoverBackground: '#191c21',
          borderColor: 'rgba(255,255,255,0.08)',
        },
        formField: {
          background: '#17191E',
          borderColor: 'rgba(255,255,255,0.09)',
          hoverBorderColor: 'rgba(255,255,255,0.16)',
          placeholderColor: '#6B7178',
        },
        overlay: {
          select: { background: '#17191E', borderColor: 'rgba(255,255,255,0.09)' },
          popover: { background: '#17191E', borderColor: 'rgba(255,255,255,0.09)' },
          modal: { background: '#131519', borderColor: 'rgba(255,255,255,0.09)' },
        },
      },
    },
  },
})
