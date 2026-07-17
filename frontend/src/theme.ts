import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'

export const OracleTheme = definePreset(Aura, {
  semantic: {
    colorScheme: {
      light: {
        surface: {
          0: '#FFFFFF',
          50: '#F7F8F9',
          100: '#EEF0F2',
          200: '#DFE3E7',
          300: '#C7CBD1',
          400: '#9AA0A8',
          500: '#6B7178',
          600: '#4A4F56',
          700: '#3A3E44',
          800: '#2A2D32',
          900: '#1D2027',
          950: '#111318',
        },
        text: {
          color: '#1D2027',
          hoverColor: '#111318',
          mutedColor: '#6B7178',
          hoverMutedColor: '#4A4F56',
        },
        content: {
          background: '#FFFFFF',
          hoverBackground: '#F7F8F9',
          borderColor: 'rgba(17,19,24,0.08)',
        },
        formField: {
          background: '#FFFFFF',
          borderColor: 'rgba(17,19,24,0.12)',
          hoverBorderColor: 'rgba(17,19,24,0.22)',
          placeholderColor: '#9AA0A8',
        },
        overlay: {
          select: { background: '#FFFFFF', borderColor: 'rgba(17,19,24,0.08)' },
          popover: { background: '#FFFFFF', borderColor: 'rgba(17,19,24,0.08)' },
          modal: { background: '#FFFFFF', borderColor: 'rgba(17,19,24,0.08)' },
        },
      },
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
