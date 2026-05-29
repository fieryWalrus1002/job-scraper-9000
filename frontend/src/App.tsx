import { useState, useEffect } from 'react'
import reactLogo from './assets/react.svg'
import viteLogo from './assets/vite.svg'
import heroImg from './assets/hero.png'
import './App.css'

function App() {
  const [backendStatus, setBackendStatus] = useState<string>('Connecting...')
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null)

  useEffect(() => {
    // Hit our local FastAPI endpoint wiht some basic health check
    fetch('http://localhost:8000/health')
      .then((res) => {
        if (!res.ok) throw new Error('Server error')
        return res.json()
      })
      .then((data) => {
        if (data.status === 'healthy') {
          setBackendStatus('+1 Health for backend')
          setIsHealthy(true)
        } else {
          setBackendStatus(`Unexpected status: ${data.status}`)
          setIsHealthy(false)
        }
      })
      .catch((err) => {
        console.error('Failed to connect to backend:', err)
        setBackendStatus('Disconnected (x_x)')
        setIsHealthy(false)
      })
  }, [])

  return (
    <>
      <section id="center">
        <div className="hero">
          <img src={heroImg} className="base" width="170" height="179" alt="Job Scraper" />
          <img src={reactLogo} className="framework" alt="React logo" />
          <img src={viteLogo} className="vite" alt="Vite logo" />
        </div>

        <div>
          <h1>Job Scraper 9000</h1>
          <p>Local Management Dashboard</p>
        </div>

        <div
          className="counter"
          style={{
            backgroundColor: isHealthy === true ? '#1b4332' : isHealthy === false ? '#641111' : '#242424',
            color: '#ffffff',
            padding: '12px 24px',
            borderRadius: '8px',
            fontWeight: 'bold',
            marginTop: '20px',
            display: 'inline-block'
          }}
        >
          API Status: {backendStatus}
        </div>
      </section>

      <div className="ticks"></div>

      <section id="next-steps">
        <div id="docs" style={{ width: '100%', maxWidth: '600px', margin: '0 auto' }}>
          <h2>Integration Verified</h2>
          <p>
            The frontend layer is cleanly consuming the backend API. Next up, we can transition this static check into a TanStack Query hook to pull real, scraped rows from our local <code>data/</code> partition!
          </p>
        </div>
      </section>

      <div className="ticks"></div>
      <section id="spacer"></section>
    </>
  )
}

export default App
