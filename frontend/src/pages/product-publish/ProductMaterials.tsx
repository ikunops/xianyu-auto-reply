/**
 * 商品素材库页面
 *
 * 功能：
 * 1. 分页展示所有商品素材
 * 2. 新建/编辑/删除素材
 * 3. 筛选（标题、分类、成色）
 * 4. 勾选批量删除
 * 5. 素材用于单品发布和批量发布
 */
import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { Plus, Pencil, Trash2, RefreshCw, Image, ChevronLeft, ChevronRight, Search, X } from 'lucide-react'
import { useUIStore } from '@/store/uiStore'
import { useAuthStore } from '@/store/authStore'
import { getMaterials, deleteMaterial, batchDeleteMaterials, type ProductMaterial } from '@/api/productPublish'
import { PageLoading } from '@/components/common/Loading'
import { ConfirmModal } from '@/components/common/ConfirmModal'
import { MaterialFormModal } from './MaterialFormModal'
import { mediaUrl } from '@/utils/mediaUrl'

const CATEGORIES = ['数码家电', '服饰鞋包', '家居日用', '图书音像', '美妆个护', '母婴用品', '运动户外', '食品生鲜', '虚拟商品', '其他']
const CONDITIONS = ['全新', '99新', '95新', '9成新', '8成新', '7成新以下']

/** 链接状态标签：库里 link_status 目前只有 alive / unknown，其余值给以后巡检写入时用 */
const LINK_LABEL: Record<string, { label: string; cls: string }> = {
  alive: { label: '链接有效', cls: 'text-green-600 dark:text-green-400' },
  unknown: { label: '未巡检', cls: 'text-slate-400' },
  invalid: { label: '已失效', cls: 'text-red-500 dark:text-red-400' },
  dead: { label: '已失效', cls: 'text-red-500 dark:text-red-400' },
  needs_code: { label: '需提取码', cls: 'text-amber-600 dark:text-amber-400' },
}

export function ProductMaterials() {
  const { addToast } = useUIStore()
  const { user } = useAuthStore()
  const isAdmin = Boolean(user?.is_admin)
  const [loading, setLoading] = useState(true)
  const [tableLoading, setTableLoading] = useState(false)
  const [materials, setMaterials] = useState<ProductMaterial[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [totalPages, setTotalPages] = useState(0)
  const [showModal, setShowModal] = useState(false)
  const [editTarget, setEditTarget] = useState<ProductMaterial | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<{ open: boolean; item: ProductMaterial | null }>({ open: false, item: null })
  const [deleting, setDeleting] = useState(false)

  // 筛选状态
  const [filterTitle, setFilterTitle] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterCondition, setFilterCondition] = useState('')

  // 批量选择状态
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [batchDeleteConfirm, setBatchDeleteConfirm] = useState(false)
  const [batchDeleting, setBatchDeleting] = useState(false)

  /** 加载素材列表 */
  const load = async (p = page, size = pageSize) => {
    setTableLoading(true)
    try {
      const filters: { title?: string; category?: string; condition?: string } = {}
      if (filterTitle.trim()) filters.title = filterTitle.trim()
      if (filterCategory) filters.category = filterCategory
      if (filterCondition) filters.condition = filterCondition
      const res = await getMaterials(p, size, Object.keys(filters).length > 0 ? filters : undefined)
      if (res.success) {
        setMaterials(res.data.list)
        setTotal(res.data.total)
        setTotalPages(res.data.total_pages)
        // 清除不在当前页的选中项
        const currentIds = new Set(res.data.list.map(m => m.id))
        setSelectedIds(prev => prev.filter(id => currentIds.has(id)))
      } else {
        addToast({ type: 'error', message: res.message || '加载失败' })
      }
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setLoading(false)
      setTableLoading(false)
    }
  }

  useEffect(() => { load(page, pageSize) }, [page, pageSize])

  /** 执行筛选 */
  const handleFilter = () => {
    setPage(1)
    setSelectedIds([])
    load(1, pageSize)
  }

  /** 重置筛选 */
  const handleResetFilter = () => {
    setFilterTitle('')
    setFilterCategory('')
    setFilterCondition('')
    setPage(1)
    setSelectedIds([])
    // 直接用空筛选加载
    setTableLoading(true)
    getMaterials(1, pageSize).then(res => {
      if (res.success) {
        setMaterials(res.data.list)
        setTotal(res.data.total)
        setTotalPages(res.data.total_pages)
        setSelectedIds([])
      }
    }).catch(() => {
      addToast({ type: 'error', message: '加载失败' })
    }).finally(() => {
      setLoading(false)
      setTableLoading(false)
    })
  }

  /** 确认删除单条 */
  const handleConfirmDelete = async () => {
    if (!deleteConfirm.item) return
    setDeleting(true)
    try {
      const res = await deleteMaterial(deleteConfirm.item.id)
      if (res.success) {
        addToast({ type: 'success', message: '删除成功' })
        setDeleteConfirm({ open: false, item: null })
        setSelectedIds(prev => prev.filter(id => id !== deleteConfirm.item!.id))
        load(page, pageSize)
      } else {
        addToast({ type: 'error', message: res.message || '删除失败' })
      }
    } catch {
      addToast({ type: 'error', message: '删除失败，请重试' })
    } finally {
      setDeleting(false)
    }
  }

  /** 批量删除 */
  const handleBatchDelete = async () => {
    if (selectedIds.length === 0) return
    setBatchDeleting(true)
    try {
      const res = await batchDeleteMaterials(selectedIds)
      if (res.success) {
        addToast({ type: 'success', message: res.message || `成功删除 ${selectedIds.length} 条素材` })
        setBatchDeleteConfirm(false)
        setSelectedIds([])
        load(page, pageSize)
      } else {
        addToast({ type: 'error', message: res.message || '批量删除失败' })
      }
    } catch {
      addToast({ type: 'error', message: '批量删除失败，请重试' })
    } finally {
      setBatchDeleting(false)
    }
  }

  /** 全选/取消全选当前页 */
  const handleSelectAll = () => {
    if (materials.length === 0) return
    const currentPageIds = materials.map(m => m.id)
    const allSelected = currentPageIds.every(id => selectedIds.includes(id))
    if (allSelected) {
      setSelectedIds(prev => prev.filter(id => !currentPageIds.includes(id)))
    } else {
      setSelectedIds(prev => [...new Set([...prev, ...currentPageIds])])
    }
  }

  /** 切换单条选中 */
  const toggleSelect = (id: number) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(i => i !== id) : [...prev, id]
    )
  }

  const allCurrentSelected = materials.length > 0 && materials.every(m => selectedIds.includes(m.id))

  const handlePageSizeChange = (size: number) => { setPageSize(size); setPage(1) }

  if (loading) return <PageLoading />

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">商品素材库</h1>
          <p className="page-description">管理商品素材，用于单品发布和批量发布</p>
        </div>
        <div className="flex gap-2">
          {selectedIds.length > 0 && (
            <button className="btn-ios-danger" onClick={() => setBatchDeleteConfirm(true)}>
              <Trash2 className="w-4 h-4" />批量删除 ({selectedIds.length})
            </button>
          )}
          <button className="btn-ios-secondary" onClick={() => load(page, pageSize)} disabled={tableLoading}>
            <RefreshCw className={`w-4 h-4 ${tableLoading ? 'animate-spin' : ''}`} />刷新
          </button>
          <button className="btn-ios-primary" onClick={() => { setEditTarget(null); setShowModal(true) }}>
            <Plus className="w-4 h-4" />新建素材
          </button>
        </div>
      </div>

      {/* 筛选栏 */}
      <div className="vben-card">
        <div className="vben-card-body py-3 px-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2">
              <input
                className="input-ios w-48"
                placeholder="搜索标题..."
                value={filterTitle}
                onChange={e => setFilterTitle(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleFilter()}
              />
            </div>
            <select
              className="input-ios w-32"
              value={filterCategory}
              onChange={e => { setFilterCategory(e.target.value); }}
            >
              <option value="">全部分类</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select
              className="input-ios w-28"
              value={filterCondition}
              onChange={e => { setFilterCondition(e.target.value); }}
            >
              <option value="">全部成色</option>
              {CONDITIONS.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <button className="btn-ios-primary btn-sm" onClick={handleFilter}>
              <Search className="w-3.5 h-3.5" />筛选
            </button>
            {(filterTitle || filterCategory || filterCondition) && (
              <button className="btn-ios-secondary btn-sm" onClick={handleResetFilter}>
                <X className="w-3.5 h-3.5" />重置
              </button>
            )}
          </div>
        </div>
      </div>

      {/* 表格卡片 */}
      <motion.div
        initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}
        className="vben-card flex flex-col"
        style={{ height: 'calc(100vh - 280px)', minHeight: '400px' }}
      >
        <div className="vben-card-header">
          <h2 className="vben-card-title"><Image className="w-4 h-4" />素材列表</h2>
          <span className="badge-primary">共 {total} 条</span>
        </div>
        <div className="flex-1 overflow-x-auto overflow-y-auto">
          <table className="table-ios table-fixed">
            <thead className="sticky top-0 bg-white dark:bg-slate-800 z-10">
              <tr>
                <th className="w-10">
                  <input
                    type="checkbox"
                    checked={allCurrentSelected}
                    onChange={handleSelectAll}
                    className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  />
                </th>
                {isAdmin && <th className="w-[88px] whitespace-nowrap">所属用户</th>}
                <th className="w-[22%]">标题</th>
                <th className="w-[27%]">来源</th>
                <th className="w-[80px] whitespace-nowrap">价格</th>
                <th className="w-[96px] whitespace-nowrap">分类</th>
                <th className="w-[72px] whitespace-nowrap">成色</th>
                <th className="w-[140px] whitespace-nowrap">图片</th>
                <th className="w-[152px] whitespace-nowrap">创建时间</th>
                <th className="w-[96px] whitespace-nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              {tableLoading ? (
                <tr><td colSpan={isAdmin ? 10 : 9} className="text-center py-12">
                  <RefreshCw className="w-6 h-6 animate-spin text-blue-500 mx-auto" />
                </td></tr>
              ) : materials.length === 0 ? (
                <tr><td colSpan={isAdmin ? 10 : 9} className="text-center py-12 text-slate-400">
                  <div className="flex flex-col items-center gap-2">
                    <Image className="w-12 h-12 text-slate-300" />
                    <p>暂无素材，点击「新建素材」添加</p>
                  </div>
                </td></tr>
              ) : materials.map(m => (
                <tr key={m.id} className={selectedIds.includes(m.id) ? 'bg-blue-50 dark:bg-blue-900/10' : ''}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(m.id)}
                      onChange={() => toggleSelect(m.id)}
                      className="w-4 h-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                    />
                  </td>
                  {isAdmin && (
                    <td className="text-sm text-slate-600 dark:text-slate-400 whitespace-nowrap">
                      {m.username || '-'}
                    </td>
                  )}
                  <td className="align-top">
                    <span className="truncate block font-medium text-slate-800 dark:text-slate-100" title={m.title}>{m.title}</span>
                  </td>
                  <td className="align-top">
                    {(m.sources || []).length === 0 ? (
                      <span className="text-xs text-amber-600 dark:text-amber-400">未登记来源</span>
                    ) : (
                      <div className="flex flex-col gap-0.5">
                        {(m.sources || []).slice(0, 1).map(s => (
                          <div key={s.share_url || s.source_path}>
                            <span
                              className="truncate block text-xs text-slate-600 dark:text-slate-300"
                              title={s.source_path || '（无目录，仅分享链接）'}
                            >
                              {s.source_path || '（无目录，仅分享链接）'}
                            </span>
                            <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
                              <span className={LINK_LABEL[s.link_status]?.cls || 'text-slate-400'}>
                                {LINK_LABEL[s.link_status]?.label
                                  || (s.link_status ? '状态：' + s.link_status : '未巡检')}
                              </span>
                              {s.extract_code && <span>提取码 {s.extract_code}</span>}
                              {s.last_check_at && <span>{new Date(s.last_check_at).toLocaleDateString('zh-CN')}</span>}
                              <a
                                href={s.share_url}
                                target="_blank"
                                rel="noreferrer"
                                className="text-blue-500 hover:underline"
                                onClick={e => e.stopPropagation()}
                              >链接</a>
                            </span>
                          </div>
                        ))}
                        {(m.sources || []).length > 1 && (
                          <span className="text-[11px] text-amber-600 dark:text-amber-400">
                            共 {(m.sources || []).length} 条来源（异常，应只有 1 条）
                          </span>
                        )}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap">
                    <span className="text-amber-600 font-medium">{m.price}</span>
                    {m.original_price && (
                      <span className="text-xs text-slate-400 line-through ml-1">{m.original_price}</span>
                    )}
                  </td>
                  <td className="text-slate-500 whitespace-nowrap">{m.category || '-'}</td>
                  <td className="whitespace-nowrap"><span className="badge-gray">{m.condition}</span></td>
                  <td className="whitespace-nowrap">{(m.images || []).slice(0, 3).map((u, i) => (<a key={i} href={mediaUrl(u)} target="_blank" rel="noreferrer"><img src={mediaUrl(u)} alt="" className="w-9 h-9 object-cover rounded-md inline-block mr-1 border border-slate-200 dark:border-slate-600 hover:opacity-80" /></a>))}{(m.images || []).length > 3 && <span className="text-xs text-slate-400">+{(m.images || []).length - 3}</span>}{!(m.images || []).length && <span className="text-xs text-slate-400">无图</span>}</td>
                  <td className="text-sm text-slate-500 whitespace-nowrap">
                    {m.created_at ? new Date(m.created_at).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-'}
                  </td>
                  <td>
                    <div className="table-actions">
                      <button className="table-action-btn" title="编辑"
                        onClick={() => { setEditTarget(m); setShowModal(true) }}>
                        <Pencil className="w-4 h-4 text-blue-500" />
                      </button>
                      <button className="table-action-btn" title="删除"
                        onClick={() => setDeleteConfirm({ open: true, item: m })}>
                        <Trash2 className="w-4 h-4 text-red-500" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* 分页 */}
        {total > 0 && (
          <div className="flex-shrink-0 flex flex-col sm:flex-row items-center justify-between px-4 py-3 border-t border-slate-200 dark:border-slate-700 gap-3">
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <span>每页</span>
              <select value={pageSize} onChange={e => handlePageSizeChange(Number(e.target.value))}
                className="px-2 py-1 border border-slate-300 dark:border-slate-600 rounded-md bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value={10}>10 条</option>
                <option value={20}>20 条</option>
                <option value={50}>50 条</option>
                <option value={100}>100 条</option>
              </select>
              <span>共 {total} 条</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-slate-500">第 {page} / {totalPages} 页</span>
              <button onClick={() => setPage(p => p - 1)} disabled={page <= 1 || tableLoading}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                <ChevronLeft className="w-4 h-4" />
              </button>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages || tableLoading}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </motion.div>

      {/* 新建/编辑弹窗 */}
      {showModal && (
        <MaterialFormModal
          initial={editTarget}
          onClose={() => setShowModal(false)}
          onSaved={() => { setShowModal(false); load(page, pageSize) }}
        />
      )}

      {/* 删除确认弹窗 */}
      <ConfirmModal
        isOpen={deleteConfirm.open}
        title="确认删除"
        message={`确认删除素材「${deleteConfirm.item?.title ?? ''}」？此操作不可撤销。`}
        confirmText="删除"
        type="danger"
        loading={deleting}
        onConfirm={handleConfirmDelete}
        onCancel={() => setDeleteConfirm({ open: false, item: null })}
      />

      {/* 批量删除确认弹窗 */}
      <ConfirmModal
        isOpen={batchDeleteConfirm}
        title="确认批量删除"
        message={`确认删除选中的 ${selectedIds.length} 条素材？此操作不可撤销。`}
        confirmText={`删除 ${selectedIds.length} 条`}
        type="danger"
        loading={batchDeleting}
        onConfirm={handleBatchDelete}
        onCancel={() => setBatchDeleteConfirm(false)}
      />
    </div>
  )
}

export default ProductMaterials
