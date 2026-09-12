import { Route, Routes, useLocation } from 'react-router-dom'
import Navbar from './components/Navbar.jsx'
import Footer from './components/Footer.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import Home from './pages/Home.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Cart from './pages/Cart.jsx'
import Orders from './pages/Orders.jsx'
import Chat from './pages/Chat.jsx'

export default function App() {
  const location = useLocation()
  // 聊天页为左右分栏的全屏布局：不显示 Footer，主区占满剩余视口高度
  const isChat = location.pathname === '/chat'

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main
        className={
          isChat
            ? 'h-[calc(100vh-56px)] px-4 py-4'
            : 'mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6'
        }
      >
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/cart"
            element={
              <ProtectedRoute>
                <Cart />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <Orders />
              </ProtectedRoute>
            }
          />
          <Route
            path="/chat"
            element={
              <ProtectedRoute>
                <Chat />
              </ProtectedRoute>
            }
          />
        </Routes>
      </main>
      {!isChat && <Footer />}
    </div>
  )
}
