import { useState } from 'react'
import { useCart } from '../context/CartContext.jsx'

// 分类 -> emoji 的静态映射（避免动态拼接 Tailwind 类名/资源名）
const CATEGORY_EMOJI = {
  宠物食品: '🥘',
  玩具: '🧶',
  洗护: '🧴',
  零食: '🦴',
  日用品: '🏠',
}

export default function ProductCard({ product }) {
  const { addItem } = useCart()
  const [added, setAdded] = useState(false)
  const soldOut = product.stock <= 0
  const emoji = CATEGORY_EMOJI[product.category] || '🎁'

  const handleAdd = () => {
    addItem(product)
    setAdded(true)
    setTimeout(() => setAdded(false), 1200)
  }

  return (
    <div className="group flex flex-col overflow-hidden rounded-2xl border border-white/5 bg-[#241d33] shadow-lg shadow-black/20 transition duration-300 hover:-translate-y-1 hover:border-pink-400/40 hover:shadow-pink-500/15">
      {/* 商品图占位区 */}
      <div className="relative flex h-40 items-center justify-center bg-gradient-to-br from-pink-500/20 via-rose-500/10 to-fuchsia-500/20">
        <span className="text-5xl transition duration-300 group-hover:scale-110">
          {emoji}
        </span>
        <span className="absolute left-3 top-3 rounded-full bg-black/35 px-2.5 py-0.5 text-xs font-medium text-pink-200 backdrop-blur">
          {product.category}
        </span>
        {soldOut && (
          <span className="absolute right-3 top-3 rounded-full bg-gray-700/80 px-2.5 py-0.5 text-xs text-gray-300">
            已售罄
          </span>
        )}
      </div>

      <div className="flex flex-1 flex-col p-4">
        <h3 className="font-semibold leading-snug text-pink-50">{product.name}</h3>
        <p className="mt-1.5 line-clamp-2 flex-1 text-sm leading-relaxed text-pink-100/50">
          {product.description}
        </p>

        {/* 标签 */}
        {product.tags?.length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {product.tags.slice(0, 3).map((tag) => (
              <span
                key={tag}
                className="rounded-full bg-pink-500/10 px-2 py-0.5 text-xs text-pink-300"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <div className="mt-3 flex items-end justify-between">
          <div>
            <span className="text-lg font-bold text-pink-400">
              ¥{product.price.toFixed(2)}
            </span>
            {product.suitable && (
              <p className="mt-0.5 text-xs text-pink-100/40">适合：{product.suitable}</p>
            )}
          </div>
          <span className="text-xs text-pink-100/40">库存 {product.stock}</span>
        </div>

        <button
          onClick={handleAdd}
          disabled={soldOut}
          className={`mt-3.5 w-full rounded-xl py-2 text-sm font-medium transition ${
            soldOut
              ? 'cursor-not-allowed bg-white/5 text-pink-100/30'
              : added
                ? 'bg-emerald-500/90 text-white'
                : 'bg-gradient-to-r from-pink-500 to-rose-500 text-white shadow-md shadow-pink-500/25 hover:from-pink-400 hover:to-rose-400'
          }`}
        >
          {soldOut ? '已售罄' : added ? '✓ 已加入购物车' : '加入购物车'}
        </button>
      </div>
    </div>
  )
}
