import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { TextPromptProvider } from './components/ui/TextPromptProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TextPromptProvider>
      <App />
    </TextPromptProvider>
  </StrictMode>,
)
