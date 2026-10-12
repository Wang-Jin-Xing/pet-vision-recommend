import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import api, { TOKEN_KEY } from '../api/client.js'

// 预设快捷问题
const QUICK_QUESTIONS = [
  '幼猫刚到家需要准备什么？',
  '狗粮和猫粮有什么区别？',
  '宠物多久洗一次澡比较合适？',
  '狗狗疫苗接种时间怎么安排？',
]

const fmtTime = (iso) => {
  const d = new Date(iso)
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getMonth() + 1}-${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`
}

// ============ AI 消息气泡（Markdown 渲染：表格/代码块/列表等） ============
function AssistantBubble({ content, streaming }) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-pink-400 to-rose-500 text-lg shadow-sm">
        🐾
      </div>
      <div className="max-w-[78%] rounded-2xl rounded-tl-md bg-gray-100 px-4 py-2.5 text-sm leading-relaxed text-gray-800 shadow-sm">
        {content ? (
          <div className="md-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : (
          <span className="typing-dots" aria-label="正在输入">
            <i />
            <i />
            <i />
          </span>
        )}
        {streaming && content && (
          <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-pink-500 align-middle" />
        )}
      </div>
    </div>
  )
}

// ============ 用户消息气泡（右对齐粉色） ============
function UserBubble({ content }) {
  return (
    <div className="flex items-start justify-end gap-2.5">
      <div className="max-w-[78%] whitespace-pre-wrap rounded-2xl rounded-tr-md bg-gradient-to-r from-pink-500 to-rose-400 px-4 py-2.5 text-sm leading-relaxed text-white shadow-sm">
        {content}
      </div>
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-pink-100 text-base">
        🧑
      </div>
    </div>
  )
}

// ============ Agent 工作进度动画 ============
function ProgressCard({ progress }) {
  if (!progress) return null
  const doneSteps = progress.done || []
  return (
    <div className="flex items-start gap-2.5">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-pink-400 to-rose-500 text-lg shadow-sm">
        🐾
      </div>
      <div className="rounded-2xl rounded-tl-md border border-pink-100 bg-pink-50/70 px-4 py-3 text-sm shadow-sm">
        {doneSteps.map((label) => (
          <div key={label} className="flex items-center gap-2 py-0.5 text-gray-400">
            <span className="text-emerald-500">✓</span>
            <span className="line-through decoration-gray-300">{label}</span>
          </div>
        ))}
        <div className="flex items-center gap-2 py-0.5 font-medium text-pink-600">
          <span className="agent-spinner" />
          <span>{progress.label}</span>
          <span className="typing-dots typing-dots-sm">
            <i />
            <i />
            <i />
          </span>
        </div>
      </div>
    </div>
  )
}

// ============ 人工审核面板（模态） ============
function ReviewModal({ review, onDecide, deciding }) {
  if (!review) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
      <div className="w-full max-w-md animate-pop rounded-2xl bg-white p-6 shadow-2xl">
        <div className="mb-3 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-amber-100 text-2xl">
            ⚠️
          </div>
          <div>
            <h3 className="text-lg font-bold text-gray-800">{review.title}</h3>
            <span className="inline-block rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
              {review.action}
            </span>
          </div>
        </div>

        <div className="mb-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-600">
          <p className="mb-1 text-xs text-gray-400">你的请求</p>
          <p className="font-medium text-gray-800">{review.question}</p>
          <p className="mt-2 leading-relaxed">{review.description}</p>
        </div>

        <div className="flex justify-end gap-3">
          <button
            onClick={() => onDecide('rejected')}
            disabled={!!deciding}
            className="rounded-lg border border-gray-300 px-5 py-2 text-sm font-medium text-gray-600 transition hover:bg-gray-50 disabled:opacity-50"
          >
            {deciding === 'rejected' ? '提交中…' : '驳回'}
          </button>
          <button
            onClick={() => onDecide('approved')}
            disabled={!!deciding}
            className="rounded-lg bg-gradient-to-r from-pink-500 to-rose-400 px-5 py-2 text-sm font-medium text-white shadow-sm transition hover:from-pink-600 hover:to-rose-500 disabled:opacity-50"
          >
            {deciding === 'approved' ? '提交中…' : '确认继续'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ============ 主页面 ============
export default function Chat() {
  const [conversations, setConversations] = useState([])
  const [currentId, setCurrentId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [progress, setProgress] = useState(null)
  const [review, setReview] = useState(null)
  const [deciding, setDeciding] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(true)

  // 文档上传（RAG 知识库）
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')

  // 宠物档案：选中后推荐按档案条件走；也可以直接发一张照片即时识别
  const [pets, setPets] = useState([])
  const [profileId, setProfileId] = useState('')
  const [imageFile, setImageFile] = useState(null)
  const [imagePreview, setImagePreview] = useState('')
  const photoRef = useRef(null)

  const abortRef = useRef(null)
  const bottomRef = useRef(null)

  // 加载历史对话
  const loadHistory = async (selectThreadId = null) => {
    try {
      const { data } = await api.get('/history')
      setConversations(data)
      if (selectThreadId) {
        const conv = data.find((c) => c.thread_id === selectThreadId)
        if (conv) {
          setCurrentId(conv.thread_id)
          setMessages(conv.messages.map((m) => ({ ...m, pending: false, _uid: `srv-${m.id}` })))
        }
      }
    } catch {
      // 401 由拦截器处理，其余静默（左侧显示空列表）
    } finally {
      setHistoryLoading(false)
    }
  }

  useEffect(() => {
    loadHistory()
    // 拉取宠物档案，供下方"按档案推荐"下拉使用（没有档案也不影响正常问答）
    api
      .get('/pets')
      .then(({ data }) => setPets(data))
      .catch(() => {})
    return () => abortRef.current?.abort()
  }, [])

  // 消息或进度变化时滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, progress])

  const openConversation = (conv) => {
    if (streaming) return
    setReview(null)
    setProgress(null)
    setCurrentId(conv.thread_id)
    setMessages(conv.messages.map((m) => ({ ...m, pending: false, _uid: `srv-${m.id}` })))
  }

  const startNewChat = () => {
    if (streaming) return
    abortRef.current?.abort()
    setReview(null)
    setProgress(null)
    setCurrentId(null)
    setMessages([])
    setInput('')
  }

  const pushProgress = (label) => {
    setProgress((prev) => ({
      label,
      done: prev && prev.label !== label ? [...(prev.done || []), prev.label] : prev?.done || [],
    }))
  }

  // 把选中的照片读成 data URL —— 后端 vision_agent 收的就是这个格式
  const fileToDataUrl = (f) =>
    new Promise((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result)
      reader.onerror = reject
      reader.readAsDataURL(f)
    })

  const clearPhoto = () => {
    setImageFile(null)
    setImagePreview('')
    if (photoRef.current) photoRef.current.value = ''
  }

  const sendMessage = async (rawText) => {
    const text = (rawText ?? input).trim()
    // 只发照片不打字也允许，自动补一句默认问法
    if ((!text && !imageFile) || streaming) return
    const payloadText = text || '看看我家宠物适合用什么'

    setInput('')
    // 本地消息用随机 _uid，避免与历史消息的数字 id 撞 React key
    const userUid = `local-${crypto.randomUUID()}`
    const assistantKey = `local-${crypto.randomUUID()}`
    setMessages((prev) => [
      ...prev,
      { _uid: userUid, role: 'user', content: payloadText, pending: false },
      { _uid: assistantKey, role: 'assistant', content: '', pending: true },
    ])
    setStreaming(true)
    setProgress(null)

    const patchAssistant = (fn) =>
      setMessages((prev) =>
        prev.map((m) => (m._uid === assistantKey ? fn(m) : m)),
      )

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const token = localStorage.getItem(TOKEN_KEY)
      // 带上档案 id 或刚选的照片：后端据此按档案条件推荐，或先做一次识别
      const payload = { message: payloadText, thread_id: currentId }
      if (profileId) payload.pet_profile_id = Number(profileId)
      if (imageFile) payload.image_data_url = await fileToDataUrl(imageFile)

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      })
      if (imageFile) clearPhoto()

      if (!res.ok) {
        let detail = '服务暂时不可用，请稍后再试'
        try {
          detail = (await res.json()).detail || detail
        } catch {
          /* 忽略解析失败 */
        }
        patchAssistant((m) => ({ ...m, content: `⚠️ ${detail}`, pending: false }))
        setStreaming(false)
        setProgress(null)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let newThreadId = currentId

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        let sep
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          const raw = buffer.slice(0, sep)
          buffer = buffer.slice(sep + 2)

          let event = 'message'
          const dataLines = []
          for (const line of raw.split('\n')) {
            if (line.startsWith('event:')) event = line.slice(6).trim()
            else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
          }
          if (!dataLines.length) continue
          const data = JSON.parse(dataLines.join('\n'))

          if (event === 'thread') {
            newThreadId = data.thread_id
            setCurrentId(data.thread_id)
          } else if (event === 'progress') {
            pushProgress(data.label)
          } else if (event === 'review_required') {
            setReview(data)
          } else if (event === 'delta') {
            patchAssistant((m) => ({ ...m, content: m.content + data.text }))
          } else if (event === 'answer') {
            patchAssistant((m) => ({ ...m, content: data.content }))
          } else if (event === 'error') {
            patchAssistant((m) => ({
              ...m,
              content: `⚠️ ${data.message || '助手处理失败'}`,
              pending: false,
            }))
          } else if (event === 'done') {
            newThreadId = data.thread_id
            patchAssistant((m) => ({ ...m, pending: false }))
          }
        }
      }

      setCurrentId(newThreadId)
      await loadHistory(newThreadId)
    } catch (err) {
      if (err.name === 'AbortError') {
        patchAssistant((m) => ({ ...m, content: '已取消本次请求。', pending: false }))
      } else {
        patchAssistant((m) => ({
          ...m,
          content: '⚠️ 网络异常，请确认后端服务已启动后重试。',
          pending: false,
        }))
      }
    } finally {
      setStreaming(false)
      setProgress(null)
      setReview(null)
    }
  }

  // 审核确认 / 驳回：POST /api/review，用 Command(resume=...) 恢复工作流
  const handleDecide = async (decision) => {
    if (!review || deciding) return
    setDeciding(decision)
    try {
      await api.post('/review', {
        thread_id: review.thread_id || review.review_id,
        decision,
      })
      setReview(null)
    } catch (err) {
      window.alert(err.response?.data?.detail || '审核提交失败，请重试')
    } finally {
      setDeciding(null)
    }
  }

  // 文档上传
  const handleUpload = async () => {
    if (!file) return
    setUploading(true)
    setUploadMsg('')
    const formData = new FormData()
    formData.append('file', file)
    try {
      const { data } = await api.post('/upload', formData)
      setUploadMsg(`已切分为 ${data.chunks} 个片段并加入知识库`)
      setFile(null)
    } catch (err) {
      setUploadMsg(err.response?.data?.detail || '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const currentTitle =
    conversations.find((c) => c.thread_id === currentId)?.title || '新对话'

  return (
    <div className="flex h-full gap-4">
      {/* ===== 左侧：对话列表 ===== */}
      <aside className="flex w-72 shrink-0 flex-col overflow-hidden rounded-2xl bg-white shadow-sm">
        <div className="border-b border-pink-100 p-3">
          <button
            onClick={startNewChat}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-pink-500 to-rose-500 px-4 py-2 text-sm font-medium text-white shadow-sm shadow-pink-500/25 transition hover:from-pink-400 hover:to-rose-400"
          >
            <span className="text-base">＋</span> 新建对话
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          {historyLoading ? (
            <p className="px-2 py-4 text-center text-sm text-gray-400">加载中…</p>
          ) : conversations.length === 0 ? (
            <p className="px-2 py-4 text-center text-sm text-gray-400">
              暂无历史对话
            </p>
          ) : (
            conversations.map((conv) => (
              <button
                key={conv.thread_id}
                onClick={() => openConversation(conv)}
                className={`mb-1 w-full rounded-xl border px-3 py-2.5 text-left transition ${
                  conv.thread_id === currentId
                    ? 'border-pink-300 bg-pink-50'
                    : 'border-transparent hover:bg-pink-50/60'
                }`}
              >
                <p className="truncate text-sm font-medium text-gray-800">
                  {conv.title}
                </p>
                <div className="mt-0.5 flex items-center justify-between text-xs text-gray-400">
                  <span>{conv.messages.length} 条消息</span>
                  <span>{fmtTime(conv.updated_at)}</span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* 知识库文档上传（折叠收纳） */}
        <details className="border-t border-pink-100">
          <summary className="cursor-pointer select-none px-4 py-2.5 text-xs font-medium text-gray-500 hover:text-pink-600">
            📄 上传知识库资料（txt / md）
          </summary>
          <div className="space-y-2 px-4 pb-3">
            <input
              type="file"
              accept=".txt,.md"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full text-xs text-gray-500 file:mr-2 file:rounded file:border-0 file:bg-pink-100 file:px-2 file:py-1 file:text-xs file:text-pink-700 hover:file:bg-pink-200"
            />
            <button
              onClick={handleUpload}
              disabled={!file || uploading}
              className="w-full rounded-lg bg-pink-500 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-pink-600 disabled:bg-gray-300"
            >
              {uploading ? '上传中…' : '上传'}
            </button>
            {uploadMsg && <p className="text-xs text-gray-500">{uploadMsg}</p>}
          </div>
        </details>
      </aside>

      {/* ===== 右侧：聊天主区域 ===== */}
      <section className="flex flex-1 flex-col overflow-hidden rounded-2xl bg-white shadow-sm">
        {/* 顶部标题栏 */}
        <header className="flex items-center justify-between border-b border-pink-100 px-5 py-3">
          <h1 className="truncate text-base font-bold text-gray-800">
            🤖 {currentTitle}
          </h1>
          <span className="shrink-0 rounded-full bg-pink-50 px-3 py-1 text-xs text-pink-600">
            RAG 知识库问答
          </span>
        </header>

        {/* 消息区 */}
        <div className="flex-1 space-y-4 overflow-y-auto bg-pink-50/30 px-5 py-4">
          {messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-pink-400 to-rose-500 text-3xl shadow-md shadow-pink-500/30">
                🐾
              </div>
              <h2 className="text-xl font-bold text-gray-800">
                你好，我是 PetPals 智能助手
              </h2>
              <p className="mt-1 text-sm text-gray-500">
                基于知识库为你解答养宠问题，试试下面的问题 👇
              </p>
              <div className="mt-6 grid w-full max-w-lg grid-cols-1 gap-3 sm:grid-cols-2">
                {QUICK_QUESTIONS.map((q) => (
                  <button
                    key={q}
                    onClick={() => sendMessage(q)}
                    disabled={streaming}
                    className="rounded-xl border border-pink-200 bg-white px-4 py-3 text-left text-sm text-gray-700 shadow-sm transition hover:-translate-y-0.5 hover:border-pink-400 hover:shadow-md disabled:opacity-50"
                  >
                    <span className="mr-1.5">💬</span>
                    {q}
                  </button>
                ))}
              </div>
              <p className="mt-5 text-xs text-gray-400">
                小提示：输入「我要退款」等操作类请求，可体验人工审核流程
              </p>
            </div>
          ) : (
            <>
              {messages.map((msg, idx) =>
                msg.role === 'user' ? (
                  <UserBubble key={msg._uid} content={msg.content} />
                ) : (
                  <AssistantBubble
                    key={msg._uid}
                    content={msg.content}
                    streaming={streaming && idx === messages.length - 1}
                  />
                ),
              )}
              {streaming && !review && <ProgressCard progress={progress} />}
            </>
          )}
          <div ref={bottomRef} />
        </div>

        {/* 输入区 */}
        <div className="border-t border-pink-100 bg-white p-3">
          {/* 宠物档案 / 拍照：让商品推荐能"因宠而异" */}
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <select
              value={profileId}
              onChange={(e) => setProfileId(e.target.value)}
              disabled={streaming}
              className="rounded-lg border border-pink-200 bg-white px-2 py-1 text-xs text-gray-600 outline-none transition focus:border-pink-400 disabled:opacity-50"
            >
              <option value="">不带宠物档案</option>
              {pets.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}（{p.species}）
                </option>
              ))}
            </select>

            <input
              ref={photoRef}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif"
              className="hidden"
              onChange={(e) => {
                const picked = e.target.files?.[0]
                if (!picked) return
                setImageFile(picked)
                setImagePreview(URL.createObjectURL(picked))
              }}
            />
            <button
              type="button"
              onClick={() => photoRef.current?.click()}
              disabled={streaming}
              className="rounded-lg border border-pink-200 bg-pink-50/60 px-2.5 py-1 text-xs text-gray-600 transition hover:border-pink-400 disabled:opacity-50"
            >
              📷 发张照片
            </button>

            {pets.length === 0 && (
              <span className="text-xs text-gray-400">
                还没有宠物档案，可到「我的宠物」建档
              </span>
            )}
          </div>

          {imagePreview && (
            <div className="mb-2 flex items-center gap-2">
              <img
                src={imagePreview}
                alt="待发送照片"
                className="h-12 w-12 rounded-lg object-cover ring-1 ring-pink-200"
              />
              <span className="text-xs text-gray-500">发送时会先识别这张照片</span>
              <button
                onClick={clearPhoto}
                className="text-xs text-gray-400 transition hover:text-rose-500"
              >
                移除
              </button>
            </div>
          )}

          {messages.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {QUICK_QUESTIONS.slice(0, 2).map((q) => (
                <button
                  key={q}
                  onClick={() => sendMessage(q)}
                  disabled={streaming}
                  className="rounded-full border border-pink-200 bg-pink-50/60 px-3 py-1 text-xs text-gray-600 transition hover:border-pink-400 hover:bg-pink-100/70 disabled:opacity-50"
                >
                  {q}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder={streaming ? '助手正在回复，请稍候…' : '输入你的问题，回车发送'}
              disabled={streaming}
              className="flex-1 rounded-xl border border-pink-200 bg-white px-4 py-2.5 text-sm outline-none transition focus:border-pink-400 focus:ring-2 focus:ring-pink-100 disabled:bg-gray-50 disabled:text-gray-400"
            />
            <button
              onClick={() => sendMessage()}
              disabled={streaming || (!input.trim() && !imageFile)}
              className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-pink-500 to-rose-400 px-6 py-2.5 text-sm font-medium text-white shadow-sm transition hover:from-pink-600 hover:to-rose-500 disabled:from-gray-300 disabled:to-gray-300"
            >
              发送
              <span>➤</span>
            </button>
          </div>
        </div>
      </section>

      {/* 人工审核弹窗 */}
      <ReviewModal review={review} onDecide={handleDecide} deciding={deciding} />
    </div>
  )
}
