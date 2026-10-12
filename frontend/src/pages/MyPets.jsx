import { useEffect, useRef, useState } from 'react'
import api from '../api/client.js'

// 三档的展示样式与含义说明——把"可信度分级"这件事直接摊给用户看
const GRADE = {
  high: {
    label: '高',
    cls: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    tip: '识别可信，推荐会按品种、体型与毛发状况精确筛选',
  },
  medium: {
    label: '中',
    cls: 'bg-amber-100 text-amber-700 border-amber-200',
    tip: '只能确定猫/狗大类，推荐只按物种走，不区分具体品种',
  },
  low: {
    label: '低',
    cls: 'bg-rose-100 text-rose-700 border-rose-200',
    tip: '识别不够可信，档案将标记为待人工确认，暂不用于推荐',
  },
}

const MODE_TIP = {
  local_fallback: '未配置视觉模型，当前为本地降级结果（并未真正读图）',
  vlm_error: '视觉模型调用失败，已降级为本地结果',
}

export default function MyPets() {
  const [pets, setPets] = useState([])
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState('')
  const [result, setResult] = useState(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const fileRef = useRef(null)

  const loadPets = async () => {
    try {
      const { data } = await api.get('/pets')
      setPets(data)
    } catch (err) {
      setMsg(err.response?.data?.detail || '加载档案失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPets()
  }, [])

  const handlePick = async (file) => {
    if (!file) return
    setMsg('')
    setResult(null)
    setName('')
    setPreview(URL.createObjectURL(file))
    setBusy(true)
    const fd = new FormData()
    fd.append('file', file)
    try {
      const { data } = await api.post('/vision/classify', fd)
      setResult(data)
      setName(file.name.replace(/\.[^.]+$/, '').slice(0, 20) || '我的宠物')
    } catch (err) {
      setMsg(err.response?.data?.detail || '识别失败，请重试')
    } finally {
      setBusy(false)
    }
  }

  const reset = () => {
    setResult(null)
    setPreview('')
    setName('')
    if (fileRef.current) fileRef.current.value = ''
  }

  const handleSave = async () => {
    if (!result || busy) return
    setBusy(true)
    setMsg('')
    try {
      await api.post('/pets', {
        name: name || '我的宠物',
        species: result.species,
        breed: result.breed,
        size: result.size,
        body_condition: result.body_condition,
        coat_condition: result.coat_condition,
        health_notes: result.health_notes,
        confidence: result.confidence,
        image_path: result.image_path,
      })
      reset()
      setMsg('建档成功，可以去「智能助手」里选它来推荐商品了')
      await loadPets()
    } catch (err) {
      setMsg(err.response?.data?.detail || '建档失败')
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm('确定删除这条宠物档案吗？')) return
    try {
      await api.delete(`/pets/${id}`)
      await loadPets()
    } catch (err) {
      setMsg(err.response?.data?.detail || '删除失败')
    }
  }

  const grade = result ? GRADE[result.grade] : null

  return (
    <div className="mx-auto max-w-5xl">
      <header className="mb-5">
        <h1 className="text-xl font-bold text-gray-800">🐾 我的宠物</h1>
        <p className="mt-1 text-sm text-gray-500">
          上传一张正面清晰的照片，自动识别品种、体型与毛发状况，建档后可在智能助手里获得针对性推荐。
        </p>
      </header>

      {msg && (
        <div className="mb-4 rounded-xl border border-pink-200 bg-pink-50 px-4 py-2.5 text-sm text-pink-700">
          {msg}
        </div>
      )}

      <div className="grid gap-5 md:grid-cols-2">
        {/* ===== 左栏：上传与识别结果 ===== */}
        <section className="rounded-2xl bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-bold text-gray-700">① 上传照片</h2>

          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif"
            onChange={(e) => handlePick(e.target.files?.[0])}
            className="w-full text-sm text-gray-500 file:mr-3 file:rounded-lg file:border-0 file:bg-pink-100 file:px-4 file:py-2 file:text-sm file:font-medium file:text-pink-700 hover:file:bg-pink-200"
          />

          {preview && (
            <img
              src={preview}
              alt="待识别照片"
              className="mt-4 max-h-64 w-full rounded-xl object-contain ring-1 ring-pink-100"
            />
          )}

          {busy && (
            <p className="mt-4 text-sm text-gray-500">
              <span className="mr-2 inline-block animate-spin">⏳</span>
              正在识别…
            </p>
          )}

          {result && (
            <div className="mt-4 rounded-xl border border-gray-100 bg-gray-50/70 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-bold text-gray-700">② 识别结果</h3>
                {grade && (
                  <span className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${grade.cls}`}>
                    可信度 {grade.label}
                  </span>
                )}
              </div>

              <dl className="space-y-1.5 text-sm">
                {[
                  ['物种', result.species],
                  ['品种', result.breed],
                  ['体型', result.size],
                  ['体态', result.body_condition],
                  ['毛发', result.coat_condition],
                  ['健康建议', result.health_notes],
                ].map(([k, v]) => (
                  <div key={k} className="flex gap-2">
                    <dt className="w-16 shrink-0 text-gray-400">{k}</dt>
                    <dd className="flex-1 text-gray-700">{v || '——'}</dd>
                  </div>
                ))}
                <div className="flex gap-2">
                  <dt className="w-16 shrink-0 text-gray-400">置信度</dt>
                  <dd className="flex-1 text-gray-700">
                    {(result.confidence * 100).toFixed(0)}%
                  </dd>
                </div>
              </dl>

              {grade && (
                <p className="mt-3 rounded-lg bg-white px-3 py-2 text-xs leading-relaxed text-gray-500">
                  {grade.tip}
                </p>
              )}
              {MODE_TIP[result.mode] && (
                <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700">
                  ⚠️ {MODE_TIP[result.mode]}
                </p>
              )}

              {result.rejected && (
                <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">
                  {result.reject_reason || '识别结果不可用，请换一张照片'}
                </p>
              )}

              <div className="mt-4 space-y-2">
                <label className="block text-xs text-gray-500">给它起个名字</label>
                <input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={20}
                  className="w-full rounded-lg border border-pink-200 px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-100"
                  placeholder="例如：小黑"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleSave}
                    disabled={busy}
                    className="flex-1 rounded-lg bg-gradient-to-r from-pink-500 to-rose-500 px-4 py-2 text-sm font-medium text-white transition hover:from-pink-400 hover:to-rose-400 disabled:from-gray-300 disabled:to-gray-300"
                  >
                    ③ 确认建档
                  </button>
                  <button
                    onClick={reset}
                    className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-500 transition hover:bg-gray-50"
                  >
                    重来
                  </button>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* ===== 右栏：档案列表 ===== */}
        <section className="rounded-2xl bg-white p-5 shadow-sm">
          <h2 className="mb-3 text-sm font-bold text-gray-700">
            我的档案
            <span className="ml-2 text-xs font-normal text-gray-400">
              共 {pets.length} 只
            </span>
          </h2>

          {loading ? (
            <p className="py-8 text-center text-sm text-gray-400">加载中…</p>
          ) : pets.length === 0 ? (
            <p className="py-8 text-center text-sm text-gray-400">
              还没有档案，上传一张照片试试
            </p>
          ) : (
            <ul className="space-y-3">
              {pets.map((p) => {
                const g = GRADE[p.confidence_grade] || GRADE.low
                return (
                  <li
                    key={p.id}
                    className="rounded-xl border border-pink-100 bg-pink-50/40 p-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 truncate text-sm font-bold text-gray-800">
                          {p.name}
                          <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${g.cls}`}>
                            {g.label}
                          </span>
                          {p.review_status === 'pending' && (
                            <span className="rounded-full bg-gray-200 px-2 py-0.5 text-[10px] text-gray-600">
                              待人工确认
                            </span>
                          )}
                        </p>
                        <p className="mt-1 text-xs text-gray-500">
                          {p.species} · {p.breed} · 置信度{' '}
                          {(p.confidence * 100).toFixed(0)}%
                        </p>
                        <p className="mt-1 line-clamp-2 text-xs text-gray-500">
                          毛发：{p.coat_condition}
                        </p>
                      </div>
                      <button
                        onClick={() => handleDelete(p.id)}
                        className="shrink-0 rounded-lg px-2 py-1 text-xs text-gray-400 transition hover:bg-rose-50 hover:text-rose-500"
                      >
                        删除
                      </button>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
