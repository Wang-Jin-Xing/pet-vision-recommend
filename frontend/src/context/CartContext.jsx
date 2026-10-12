import { createContext, useContext, useEffect, useMemo, useReducer } from 'react'

// 购物车全局状态：useReducer 管理 + localStorage 持久化（刷新不丢）
const CartContext = createContext(null)

const STORAGE_KEY = 'petvision_cart'

// ---------- 从 localStorage 读取初始购物车（带容错与数据清洗） ----------
function loadInitialItems() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter(
        (it) =>
          it &&
          typeof it.id === 'number' &&
          Number.isInteger(it.quantity) &&
          it.quantity > 0,
      )
      .map((it) => ({
        id: it.id,
        name: String(it.name || `商品 ${it.id}`),
        price: Number(it.price) || 0,
        category: it.category || undefined,
        stock: typeof it.stock === 'number' ? it.stock : undefined,
        quantity: it.quantity,
      }))
  } catch {
    return []
  }
}

// ---------- Reducer ----------
function cartReducer(state, action) {
  switch (action.type) {
    // 加入购物车：已存在则累加（不超过库存），不存在则新建快照
    case 'ADD': {
      const p = action.product
      const found = state.find((it) => it.id === p.id)
      const addQty = action.quantity ?? 1
      if (found) {
        const maxQty = p.stock ?? Number.MAX_SAFE_INTEGER
        return state.map((it) =>
          it.id === p.id
            ? { ...it, quantity: Math.min(it.quantity + addQty, maxQty) }
            : it,
        )
      }
      const qty = Math.min(addQty, p.stock ?? Number.MAX_SAFE_INTEGER)
      return [
        ...state,
        {
          id: p.id,
          name: p.name,
          price: p.price,
          category: p.category,
          stock: p.stock,
          quantity: Math.max(1, qty),
        },
      ]
    }

    // 数量 +1（受库存上限约束）
    case 'INCREMENT':
      return state.map((it) => {
        if (it.id !== action.id) return it
        const next = it.quantity + 1
        if (typeof it.stock === 'number' && next > it.stock) return it
        return { ...it, quantity: next }
      })

    // 数量 -1：减到 0 时自动移除
    case 'DECREMENT':
      return state
        .map((it) =>
          it.id === action.id ? { ...it, quantity: it.quantity - 1 } : it,
        )
        .filter((it) => it.quantity > 0)

    // 直接设置数量：<=0 移除，超出库存截断
    case 'SET_QUANTITY':
      if (action.quantity <= 0) {
        return state.filter((it) => it.id !== action.id)
      }
      return state.map((it) => {
        if (it.id !== action.id) return it
        const qty =
          typeof it.stock === 'number'
            ? Math.min(action.quantity, it.stock)
            : action.quantity
        return { ...it, quantity: qty }
      })

    case 'REMOVE':
      return state.filter((it) => it.id !== action.id)

    case 'CLEAR':
      return []

    default:
      return state
  }
}

export function CartProvider({ children }) {
  const [items, dispatch] = useReducer(cartReducer, undefined, loadInitialItems)

  // 每次变化都写入 localStorage，刷新 / 重开浏览器后仍保留
  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
    } catch {
      // 隐私模式或存储满时静默失败，不影响购物车功能
    }
  }, [items])

  const addItem = (product, quantity = 1) =>
    dispatch({ type: 'ADD', product, quantity })
  const increment = (id) => dispatch({ type: 'INCREMENT', id })
  const decrement = (id) => dispatch({ type: 'DECREMENT', id })
  // 兼容旧调用名
  const updateQuantity = (id, quantity) =>
    dispatch({ type: 'SET_QUANTITY', id, quantity })
  const removeItem = (id) => dispatch({ type: 'REMOVE', id })
  const clearCart = () => dispatch({ type: 'CLEAR' })

  const totalCount = items.reduce((sum, it) => sum + it.quantity, 0)
  const totalPrice = items.reduce((sum, it) => sum + it.price * it.quantity, 0)

  const value = useMemo(
    () => ({
      items,
      addItem,
      increment,
      decrement,
      updateQuantity,
      removeItem,
      clearCart,
      totalCount,
      totalPrice,
    }),
    [items, totalCount, totalPrice],
  )

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart() {
  return useContext(CartContext)
}
