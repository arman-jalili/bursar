import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './gate.css'
import { installInspector } from './inspector'
import App from './App.tsx'

// Wrap window.fetch before the first render: a panel that misses the calls made at boot is a
// panel that cannot answer "is this page really talking to the service?".
installInspector()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
