import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client.js'

// 订单状态流转顺序
const STATUS_FLOW = ['pending', 'paid', 'shipped', 'delivered']

// 状态 -> 文案 + 彩色标签样式（固定完整类名，供 Tailwind 静态收集）
const STATUS_MAP = {
  pending: {
    label: '待支付',
    badge: 'bg-yellow-400/15 text-yellow-300 ring-1 ring-yellow-400/40',
    dot: 'bg-yellow-400',
    step: 'text-yellow-300',
  },
  paid: {
    label: '已支付',
    badge: 'bg-sky-400/15 text-sky-300 ring-1 ring-sky-400/40',
    dot: 'bg-sky-400',
    step: 'text-sky-300',
  },
  shipped: {
    label: '已发货',
    badge: 'bg-purple-400/15 text-purple-300 ring-1 ring-purple-400/40',
    dot: 'bg-purple-400',
    step: 'text-purple-300',
  },
  delivered: {
    label: '已送达',
    badge: 'bg-emerald-400/15 text-emerald-300 ring-1 ring-emerald-400/40',
    dot: 'bg-emerald-400',
    step: 'text-emerald-300',
  },
}

function StatusBadge({ status }) {
  const meta = STATUS_MAP[status]
  if (!meta) {
    return (
      <span className="rounded-full bg-white/10 px-3 py-1 text-xs font-medium text-pink-100/60 ring-1 ring-white/15">
        {status}
      </span>
    )
  }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${meta.badge}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  )
}

// 订单进度条：待支付 → 已支付 → 已发货 → 已送达
function StatusSteps({ status }) {
  const currentIndex = STATUS_FLOW.indexOf(status)
  if (currentIndex === -1) return null
  return (
    <div className="mt-3 flex items-center">
      {STATUS_FLOW.map((key, idx) => {
        const reached = idx <= currentIndex
        const meta = STATUS_MAP[key]
        return (
          <div key={key} className="flex flex-1 items-center last:flex-none">
            <div className="flex flex-col items-center gap-1">
              <span
                className={`h-2 w-2 rounded-full ${
                  reached ? meta.dot : 'bg-white/15'
                }`}
              />
              <span
                className={`text-[10px] ${
                  reached ? meta.step : 'text-pink-100/30'
                }`}
              >
                {meta.label}
              </span>
            </div>
            {idx < STATUS_FLOW.length - 1 && (
              <span
                className={`mx-1 mb-4 h-px flex-1 ${
                  idx < currentIndex ? 'bg-pink-400/60' : 'bg-white/10'
                }`}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

function EmptyOrders() {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-white/5 bg-[#241d33] px-6 py-20 text-center shadow-lg shadow-black/20">
      <span className="text-6xl">📦</span>
      <h2 className="mt-4 text-lg font-bold text-pink-50">还没有订单</h2>
      <p className="mt-2 text-sm text-pink-100/50">
        挑选好物下单后，就能在这里查看订单状态啦～
      </p>
      <Link
        to="/"
        className="mt-6 rounded-xl bg-gradient-to-r from-pink-500 to-rose-500 px-8 py-2.5 text-sm font-semibold text-white shadow-md shadow-pink-500/25 transition hover:from-pink-400 hover:to-rose-400"
      >
        去购物
      </Link>
    </div>
  )
}

export default function Orders() {
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadOrders = () => {
    setLoading(true)
    setError('')
    api
      .get('/orders')
      .then((res) => setOrders(res.data))
      .catch(() => setError('订单加载失败，请稍后重试'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadOrders()
  }, [])

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-5 text-2xl font-bold text-pink-50">📦 我的订单</h1>

      {loading ? (
        <div className="space-y-4">
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="rounded-2xl border border-white/5 bg-[#241d33] p-5"
            >
              <div className="flex justify-between">
                <div className="skeleton h-4 w-40 rounded" />
                <div className="skeleton h-5 w-16 rounded-full" />
              </div>
              <div className="mt-4 space-y-2">
                <div className="skeleton h-3 w-full rounded" />
                <div className="skeleton h-3 w-2/3 rounded" />
              </div>
            </div>
          ))}
        </div>
      ) : error ? (
        <div className="rounded-2xl border border-rose-500/30 bg-rose-500/10 p-10 text-center">
          <p className="text-4xl">😿</p>
          <p className="mt-3 text-sm text-rose-200">{error}</p>
          <button
            onClick={loadOrders}
            className="mt-4 rounded-lg bg-pink-500 px-5 py-2 text-sm font-medium text-white transition hover:bg-pink-400"
          >
            重新加载
          </button>
        </div>
      ) : orders.length === 0 ? (
        <EmptyOrders />
      ) : (
        <div className="space-y-4">
          {orders.map((order) => (
            <div
              key={order.id}
              className="rounded-2xl border border-white/5 bg-[#241d33] p-5 shadow-lg shadow-black/20"
            >
              {/* 订单头：单号 / 时间 / 状态标签 */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/5 pb-3">
                <div className="text-sm text-pink-100/50">
                  <span className="font-semibold text-pink-200">
                    订单号 #{order.id}
                  </span>
                  <span className="mx-2 text-pink-100/20">|</span>
                  {new Date(order.created_at).toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </div>
                <StatusBadge status={order.status} />
              </div>

              {/* 商品明细 */}
              <ul className="mt-3 space-y-2">
                {order.items.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-center justify-between text-sm"
                  >
                    <span className="flex min-w-0 items-center gap-2 text-pink-100/80">
                      <span className="text-base">🛍️</span>
                      <span className="truncate">{item.product_name}</span>
                      <span className="shrink-0 text-pink-100/40">
                        × {item.quantity}
                      </span>
                    </span>
                    <span className="shrink-0 text-pink-100/60">
                      ¥{(item.price * item.quantity).toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>

              {/* 状态进度 + 总价 */}
              <StatusSteps status={order.status} />
              <div className="mt-3 flex items-center justify-end border-t border-white/5 pt-3">
                <span className="text-sm text-pink-100/50">
                  共 {order.items.reduce((s, it) => s + it.quantity, 0)} 件，合计
                </span>
                <span className="ml-2 text-xl font-extrabold text-pink-400">
                  ¥{order.total.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
