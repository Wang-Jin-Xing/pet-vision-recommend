import { Navigate, useLocation } from 'react-router-dom'
import { TOKEN_KEY } from '../api/client.js'

// 登录保护：未登录时跳转到登录页，并记住来源地址
export default function ProtectedRoute({ children }) {
  const location = useLocation()
  const token = localStorage.getItem(TOKEN_KEY)

  if (!token) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return children
}
