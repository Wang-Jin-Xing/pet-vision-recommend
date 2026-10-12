import { useEffect, useMemo, useState } from 'react'
import api from '../api/client'
import ProductCard from '../components/ProductCard.jsx'

export default function Home() {
  const [products, setProducts] = useState([])
  const [keyword, setKeyword] = useState('')
  const [activeCategory, setActiveCategory] = useState('全部')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadProducts = (q = '') => {
    setLoading(true)
    setError('')
    api
      .get('/products', { params: q ? { keyword: q } : {} })
      .then((res) => setProducts(res.data))
      .catch(() => setError('商品加载失败，请确认后端服务已启动'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadProducts()
  }, [])

  const handleSearch = (e) => {
    e.preventDefault()
    loadProducts(keyword.trim())
  }

  // 从商品数据中聚合分类（保证与后端数据一致）
  const categories = useMemo(() => {
    const set = new Set(products.map((p) => p.category))
    return ['全部', ...set]
  }, [products])

  // 前端二次筛选分类（搜索结果上再筛分类）
  const visibleProducts =
    activeCategory === '全部'
      ? products
      : products.filter((p) => p.category === activeCategory)

  return (
    <div>
      {/* ===== Hero 横幅 ===== */}
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-pink-600 via-rose-500 to-fuchsia-600 px-6 py-12 shadow-2xl shadow-pink-900/40 sm:px-12 sm:py-16">
        {/* 装饰爪印 */}
        <span className="pointer-events-none absolute -right-6 -top-6 select-none text-[140px] opacity-15">
          🐾
        </span>
        <span className="pointer-events-none absolute bottom-2 right-24 select-none text-6xl opacity-20">
          🦴
        </span>
        <div className="relative max-w-xl">
          <span className="inline-block rounded-full bg-white/20 px-3 py-1 text-xs font-medium text-pink-50 backdrop-blur">
            🐱 毛孩子的精选好物 🐶
          </span>
          <h1 className="mt-4 text-3xl font-extrabold leading-tight text-white sm:text-4xl">
            宠物影像识别与荐购系统
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-pink-100 sm:text-base">
            精选宠物食品、玩具与洗护用品，还有 AI 智能助手随时解答养宠疑问，
            让爱宠生活更美好。
          </p>

          {/* 搜索框 */}
          <form onSubmit={handleSearch} className="mt-6 flex gap-2">
            <input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索商品名称或描述..."
              className="flex-1 rounded-xl border border-white/30 bg-white/95 px-4 py-2.5 text-sm text-gray-800 outline-none transition placeholder:text-gray-400 focus:ring-2 focus:ring-pink-300"
            />
            <button
              type="submit"
              className="rounded-xl bg-[#1a1625] px-6 py-2.5 text-sm font-semibold text-pink-200 transition hover:bg-[#2a2238] hover:text-pink-300"
            >
              搜索
            </button>
          </form>
        </div>
      </section>

      {/* ===== 分类筛选 ===== */}
      <div className="mt-8 flex flex-wrap items-center gap-2">
        {categories.map((cat) => (
          <button
            key={cat}
            onClick={() => setActiveCategory(cat)}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition ${
              activeCategory === cat
                ? 'bg-gradient-to-r from-pink-500 to-rose-500 text-white shadow-md shadow-pink-500/30'
                : 'border border-pink-500/25 bg-white/5 text-pink-100/70 hover:border-pink-400/50 hover:text-pink-300'
            }`}
          >
            {cat}
          </button>
        ))}
        <span className="ml-auto text-sm text-pink-100/40">
          共 {visibleProducts.length} 件商品
        </span>
      </div>

      {/* ===== 商品网格 ===== */}
      <div className="mt-5">
        {loading ? (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                key={i}
                className="overflow-hidden rounded-2xl border border-white/5 bg-[#241d33]"
              >
                <div className="skeleton h-40 w-full" />
                <div className="space-y-2.5 p-4">
                  <div className="skeleton h-4 w-3/4 rounded" />
                  <div className="skeleton h-3 w-full rounded" />
                  <div className="skeleton h-3 w-2/3 rounded" />
                  <div className="skeleton mt-2 h-9 w-full rounded-xl" />
                </div>
              </div>
            ))}
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-10 text-center">
            <p className="text-4xl">😿</p>
            <p className="mt-3 text-sm text-rose-200">{error}</p>
            <button
              onClick={() => loadProducts()}
              className="mt-4 rounded-lg bg-pink-500 px-5 py-2 text-sm font-medium text-white hover:bg-pink-400"
            >
              重新加载
            </button>
          </div>
        ) : visibleProducts.length === 0 ? (
          <div className="rounded-2xl border border-white/5 bg-[#241d33] p-12 text-center">
            <p className="text-4xl">🐾</p>
            <p className="mt-3 text-sm text-pink-100/50">
              {products.length === 0
                ? '商城正在备货中，稍后再来看看吧～'
                : '该分类下暂无商品，换个关键词试试？'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {visibleProducts.map((product) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
