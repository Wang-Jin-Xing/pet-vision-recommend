import axios from 'axios'

export const TOKEN_KEY = 'petvision_token'
export const USER_KEY = 'petvision_user'

// 统一的 axios 实例，baseURL 通过 Vite 代理转发到 FastAPI 后端
const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动带上 JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 时清除登录态并跳转登录页
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default api
