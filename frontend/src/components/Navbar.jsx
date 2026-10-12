import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { TOKEN_KEY, USER_KEY } from '../api/client.js'
import { useCart } from '../context/CartContext.jsx'

export default function Navbar() {
  const navigate = useNavigate()
  const location = useLocation()
  const { totalCount } = useCart()
  const [user, setUser] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)

  // 路由切换时重新读取登录用户信息
  useEffect(() => {
    const raw = localStorage.getItem(USER_KEY)
    setUser(raw ? JSON.parse(raw) : null)
    setMenuOpen(false)
  }, [location.pathname])

  const handleLogout = () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    setUser(null)
    setMenuOpen(false)
    navigate('/login')
  }

  const linkClass = (active) =>
    `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
      active
        ? 'bg-pink-500 text-white shadow-sm shadow-pink-500/30'
        : 'text-pink-100/80 hover:bg-pink-500/15 hover:text-pink-300'
    }`

  const navLinks = (
    <>
      <Link to="/" className={linkClass(location.pathname === '/')}>
        首页
      </Link>
      <Link to="/chat" className={linkClass(location.pathname === '/chat')}>
        智能助手
      </Link>
      <Link
        to="/cart"
        className={`${linkClass(location.pathname === '/cart')} relative`}
      >
        购物车
        {totalCount > 0 && (
          <span className="ml-1 inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-pink-400 px-1.5 text-xs font-bold text-[#1a1625]">
            {totalCount}
          </span>
        )}
      </Link>
      {user && (
        <Link to="/pets" className={linkClass(location.pathname === '/pets')}>
          我的宠物
        </Link>
      )}
      {user && (
        <Link to="/orders" className={linkClass(location.pathname === '/orders')}>
          我的订单
        </Link>
      )}
    </>
  )

  return (
    <header className="sticky top-0 z-40 border-b border-pink-500/15 bg-[#1a1625]/90 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {/* Logo */}
        <Link to="/" className="flex items-center gap-2">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-pink-400 to-rose-500 text-lg shadow-lg shadow-pink-500/30">
            🐾
          </span>
          <span className="bg-gradient-to-r from-pink-300 to-rose-400 bg-clip-text text-xl font-extrabold tracking-wide text-transparent">
            PetPals
          </span>
        </Link>

        {/* 桌面端导航 */}
        <nav className="hidden items-center gap-1 md:flex">
          {navLinks}
          {user ? (
            <div className="ml-2 flex items-center gap-2 border-l border-pink-500/20 pl-3">
              <span className="text-sm text-pink-200/70">
                你好，<span className="font-medium text-pink-200">{user.username}</span>
              </span>
              <button
                onClick={handleLogout}
                className="rounded-lg px-3 py-1.5 text-sm font-medium text-pink-100/80 transition hover:bg-pink-500/15 hover:text-pink-300"
              >
                退出
              </button>
            </div>
          ) : (
            <div className="ml-2 flex items-center gap-1 border-l border-pink-500/20 pl-3">
              <Link to="/login" className={linkClass(location.pathname === '/login')}>
                登录
              </Link>
              <Link
                to="/register"
                className="rounded-lg bg-gradient-to-r from-pink-500 to-rose-500 px-4 py-1.5 text-sm font-medium text-white shadow-sm shadow-pink-500/30 transition hover:from-pink-400 hover:to-rose-400"
              >
                注册
              </Link>
            </div>
          )}
        </nav>

        {/* 移动端汉堡按钮 */}
        <button
          onClick={() => setMenuOpen((v) => !v)}
          aria-label="切换导航菜单"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-pink-200 transition hover:bg-pink-500/15 md:hidden"
        >
          <div className="space-y-1.5">
            <span
              className={`block h-0.5 w-5 bg-current transition-transform ${
                menuOpen ? 'translate-y-2 rotate-45' : ''
              }`}
            />
            <span className={`block h-0.5 w-5 bg-current transition ${menuOpen ? 'opacity-0' : ''}`} />
            <span
              className={`block h-0.5 w-5 bg-current transition-transform ${
                menuOpen ? '-translate-y-2 -rotate-45' : ''
              }`}
            />
          </div>
        </button>
      </div>

      {/* 移动端下拉菜单 */}
      {menuOpen && (
        <nav className="border-t border-pink-500/15 bg-[#221b31] px-4 py-3 md:hidden">
          <div className="flex flex-col gap-1">
            {navLinks}
            {user ? (
              <>
                <span className="px-3 pt-2 text-sm text-pink-200/70">
                  你好，<span className="font-medium text-pink-200">{user.username}</span>
                </span>
                <button
                  onClick={handleLogout}
                  className="rounded-lg px-3 py-2 text-left text-sm font-medium text-pink-100/80 transition hover:bg-pink-500/15"
                >
                  退出登录
                </button>
              </>
            ) : (
              <div className="mt-1 flex gap-2">
                <Link
                  to="/login"
                  className="flex-1 rounded-lg border border-pink-500/40 py-2 text-center text-sm font-medium text-pink-200"
                >
                  登录
                </Link>
                <Link
                  to="/register"
                  className="flex-1 rounded-lg bg-gradient-to-r from-pink-500 to-rose-500 py-2 text-center text-sm font-medium text-white"
                >
                  注册
                </Link>
              </div>
            )}
          </div>
        </nav>
      )}
    </header>
  )
}
