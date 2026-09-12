import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import api, { TOKEN_KEY, USER_KEY } from '../api/client.js'

export default function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [form, setForm] = useState({ email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChange = (e) => setForm({ ...form, [e.target.name]: e.target.value })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { data } = await api.post('/login', form)
      localStorage.setItem(TOKEN_KEY, data.access_token)
      // 再请求一次用户信息，用于导航栏展示
      const me = await api.get('/me')
      localStorage.setItem(USER_KEY, JSON.stringify(me.data))

      const redirectTo = location.state?.from || '/'
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || '登录失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-md">
      <h1 className="mb-6 text-center text-2xl font-bold text-gray-800">登录 PetPals</h1>
      <form onSubmit={handleSubmit} className="space-y-4 rounded-2xl bg-white p-6 shadow-sm">
        {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">邮箱</label>
          <input
            name="email"
            type="email"
            required
            value={form.email}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-orange-400"
            placeholder="you@example.com"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">密码</label>
          <input
            name="password"
            type="password"
            required
            value={form.password}
            onChange={handleChange}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 outline-none focus:border-orange-400"
            placeholder="至少 6 位"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full rounded-lg bg-orange-500 py-2.5 font-medium text-white hover:bg-orange-600 disabled:bg-gray-300"
        >
          {loading ? '登录中...' : '登录'}
        </button>
        <p className="text-center text-sm text-gray-500">
          还没有账号？<Link to="/register" className="text-orange-600 hover:underline">立即注册</Link>
        </p>
      </form>
    </div>
  )
}
