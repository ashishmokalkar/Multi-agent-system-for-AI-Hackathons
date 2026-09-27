import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import Highlight from './Highlight'
import './styles.css'

const content = window.location.pathname.startsWith('/highlight') ? <Highlight /> : <App />

createRoot(document.getElementById('root')!).render(
  <StrictMode>{content}</StrictMode>,
)
