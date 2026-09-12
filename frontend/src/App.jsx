import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar.jsx'
import ChatPage from './pages/ChatPage.jsx'
import UploadPage from './pages/UploadPage.jsx'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        {/* <Sidebar /> */}

        <div className="app-main">
          <Routes>
            <Route path="/" element={<Navigate to="/chat/1" replace />} />
            <Route path="/chat/:chatId" element={<ChatPage />} />
            <Route path="/upload" element={<UploadPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}
