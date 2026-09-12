import { Link } from 'react-router-dom'

const footerLinks = [
  {
    title: '逛一逛',
    links: [
      { label: '首页商品', to: '/' },
      { label: '购物车', to: '/cart' },
      { label: '我的订单', to: '/orders' },
    ],
  },
  {
    title: '养宠助手',
    links: [
      { label: '智能问答', to: '/chat' },
      { label: '登录', to: '/login' },
      { label: '注册账号', to: '/register' },
    ],
  },
]

export default function Footer() {
  return (
    <footer className="mt-12 border-t border-pink-500/15 bg-[#15111e]">
      <div className="mx-auto grid max-w-7xl grid-cols-1 gap-8 px-4 py-10 sm:grid-cols-2 lg:grid-cols-4">
        {/* 品牌区 */}
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-pink-400 to-rose-500 text-lg shadow-lg shadow-pink-500/30">
              🐾
            </span>
            <span className="bg-gradient-to-r from-pink-300 to-rose-400 bg-clip-text text-xl font-extrabold text-transparent">
              PetPals
            </span>
          </div>
          <p className="mt-3 text-sm leading-relaxed text-pink-100/50">
            精选宠物食品、玩具与洗护用品，
            <br />
            让每一只毛孩子都被温柔以待。
          </p>
        </div>

        {/* 链接列 */}
        {footerLinks.map((group) => (
          <div key={group.title}>
            <h4 className="mb-3 text-sm font-semibold text-pink-200">
              {group.title}
            </h4>
            <ul className="space-y-2">
              {group.links.map((link) => (
                <li key={link.label}>
                  <Link
                    to={link.to}
                    className="text-sm text-pink-100/50 transition hover:text-pink-300"
                  >
                    {link.label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}

        {/* 联系方式 */}
        <div>
          <h4 className="mb-3 text-sm font-semibold text-pink-200">联系我们</h4>
          <ul className="space-y-2 text-sm text-pink-100/50">
            <li>📧 hello@petpals.demo</li>
            <li>🕐 客服时间 9:00 - 21:00</li>
            <li className="flex gap-3 pt-1 text-lg">
              <span className="cursor-pointer transition hover:scale-110">🐱</span>
              <span className="cursor-pointer transition hover:scale-110">🐶</span>
              <span className="cursor-pointer transition hover:scale-110">🐰</span>
            </li>
          </ul>
        </div>
      </div>

      <div className="border-t border-pink-500/10 py-4 text-center text-xs text-pink-100/35">
        © 2026 PetPals 宠物生活服务平台 · 用心陪伴每一爪 🐾
      </div>
    </footer>
  )
}
