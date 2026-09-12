import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../api/client.js'
import { useCart } from '../context/CartContext.jsx'

// 分类 -> emoji（与首页 ProductCard 保持一致的静态映射）
const CATEGORY_EMOJI = {
  宠物食品: '🥘',
  玩具: '🧶',
  洗护: '🧴',
  零食: '🦴',
  日用品: '🏠',
}

function EmptyCart() {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-white/5 bg-[#241d33] px-6 py-20 text-center shadow-lg shadow-black/20">
      <span className="text-6xl">🛒</span>
      <h2 className="mt-4 text-lg font-bold text-pink-50">购物车还是空的</h2>
      <p className="mt-2 text-sm text-pink-100/50">
        去首页挑选心仪的好物，给毛孩子一个惊喜吧～
      </p>
      <Link
        to="/"
        className="mt-6 rounded-xl bg-gradient-to-r from-pink-500 to-rose-500 px-8 py-2.5 text-sm font-semibold text-white shadow-md shadow-pink-500/25 transition hover:from-pink-400 hover:to-rose-400"
      >
        去逛逛
      </Link>
    </div>
  )
}

export default function Cart() {
  const navigate = useNavigate()
  const {
    items,
    increment,
    decrement,
    removeItem,
    clearCart,
    totalCount,
    totalPrice,
  } = useCart()
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const handleCheckout = async () => {
    setError('')
    setSubmitting(true)
    try {
      await api.post('/orders', {
        items: items.map((it) => ({ product_id: it.id, quantity: it.quantity })),
      })
      clearCart()
      navigate('/orders')
    } catch (err) {
      setError(err.response?.data?.detail || '下单失败，请稍后重试')
    } finally {
      setSubmitting(false)
    }
  }

  if (items.length === 0) {
    return (
      <div>
        <h1 className="mb-5 text-2xl font-bold text-pink-50">🛒 我的购物车</h1>
        <EmptyCart />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-pink-50">
          🛒 我的购物车
          <span className="ml-2 text-sm font-normal text-pink-100/50">
            共 {totalCount} 件
          </span>
        </h1>
        <button
          onClick={clearCart}
          className="text-sm text-pink-100/40 transition hover:text-pink-300"
        >
          清空购物车
        </button>
      </div>

      {/* 商品列表 */}
      <div className="space-y-3">
        {items.map((item) => {
          const atStock =
            typeof item.stock === 'number' && item.quantity >= item.stock
          return (
            <div
              key={item.id}
              className="flex items-center gap-4 rounded-2xl border border-white/5 bg-[#241d33] p-4 shadow-lg shadow-black/20"
            >
              {/* 商品图标 */}
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-pink-500/20 to-fuchsia-500/20 text-3xl">
                {CATEGORY_EMOJI[item.category] || '🎁'}
              </div>

              {/* 名称与单价 */}
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-pink-50">{item.name}</p>
                <p className="mt-0.5 text-sm text-pink-300">
                  ¥{item.price.toFixed(2)}
                  <span className="text-pink-100/35"> / 件</span>
                </p>
              </div>

              {/* 数量步进器 */}
              <div className="flex items-center gap-1 rounded-xl border border-pink-500/20 bg-[#1a1625] p-1">
                <button
                  onClick={() => decrement(item.id)}
                  aria-label="减少数量"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-pink-200 transition hover:bg-pink-500/20"
                >
                  −
                </button>
                <span className="w-8 text-center text-sm font-semibold text-pink-50">
                  {item.quantity}
                </span>
                <button
                  onClick={() => increment(item.id)}
                  disabled={atStock}
                  aria-label="增加数量"
                  className="flex h-7 w-7 items-center justify-center rounded-lg text-pink-200 transition enabled:hover:bg-pink-500/20 disabled:cursor-not-allowed disabled:text-pink-100/25"
                >
                  +
                </button>
              </div>

              {/* 小计 */}
              <div className="w-20 shrink-0 text-right">
                <p className="font-bold text-pink-400">
                  ¥{(item.price * item.quantity).toFixed(2)}
                </p>
                <button
                  onClick={() => removeItem(item.id)}
                  className="mt-1 text-xs text-pink-100/35 transition hover:text-rose-400"
                >
                  删除
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* 库存提示 */}
      {items.some((it) => typeof it.stock === 'number' && it.quantity >= it.stock) && (
        <p className="mt-3 text-center text-xs text-amber-300/80">
          ⚠️ 部分商品已达库存上限，无法继续增加
        </p>
      )}

      {/* 错误提示 */}
      {error && (
        <p className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          {error}
        </p>
      )}

      {/* 结算栏 */}
      <div className="sticky bottom-4 mt-6 flex items-center justify-between rounded-2xl border border-pink-500/20 bg-[#241d33] p-5 shadow-xl shadow-pink-900/30">
        <div>
          <p className="text-sm text-pink-100/50">
            共 <span className="font-semibold text-pink-200">{totalCount}</span> 件商品
          </p>
          <p className="mt-1 text-lg text-pink-100/70">
            合计：
            <span className="text-2xl font-extrabold text-pink-400">
              ¥{totalPrice.toFixed(2)}
            </span>
          </p>
        </div>
        <button
          onClick={handleCheckout}
          disabled={submitting}
          className="rounded-xl bg-gradient-to-r from-pink-500 to-rose-500 px-10 py-3 text-sm font-semibold text-white shadow-lg shadow-pink-500/30 transition hover:from-pink-400 hover:to-rose-400 disabled:from-gray-500 disabled:to-gray-500"
        >
          {submitting ? '提交中…' : '提交订单'}
        </button>
      </div>
    </div>
  )
}
