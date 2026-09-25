/**
 * 账号权限检测弹窗
 *
 * 只读展示：哪个账号持有「鱼小铺专业卖家工作台（COMMONPRO）」商业身份、卖家等级多少。
 * 该权限由闲鱼按账号发放，本系统无法开通，只能读出来给你看。
 */
import { useCallback, useEffect, useState } from 'react'
import { X, Loader2, RefreshCw, ShieldCheck, ShieldAlert } from 'lucide-react'
import { checkAccountPermissions, type AccountPermissionItem } from '@/api/accounts'
import { getApiErrorMessage } from '@/utils/request'
import { useUIStore } from '@/store/uiStore'

interface Props {
  onClose: () => void
}

export function PermissionCheckModal({ onClose }: Props) {
  const { addToast } = useUIStore()
  const [rows, setRows] = useState<AccountPermissionItem[]>([])
  const [loading, setLoading] = useState(false)
  const [checkedAt, setCheckedAt] = useState<string>('')

  const runCheck = useCallback(async () => {
    setLoading(true)
    try {
      const result = await checkAccountPermissions()
      if (result.success) {
        setRows(result.data || [])
        setCheckedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }))
      } else {
        addToast({ type: 'error', message: result.message || '权限检测失败' })
      }
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '权限检测失败') })
    } finally {
      setLoading(false)
    }
  }, [addToast])

  useEffect(() => {
    runCheck()
  }, [runCheck])

  const granted = rows.filter((r) => r.workbench_enabled).length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-3xl max-h-[85vh] overflow-hidden flex flex-col bg-white dark:bg-slate-800 rounded-xl shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 dark:border-slate-700">
          <div>
            <h3 className="text-base font-semibold text-gray-800 dark:text-gray-200">账号权限检测</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
              读取闲鱼侧的「鱼小铺专业卖家工作台」商业身份。没有该身份的账号无法下架商品、也取不到数据罗盘；该身份只能由闲鱼开通。
            </p>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-md hover:bg-gray-100 dark:hover:bg-slate-700 text-gray-500">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3">
          <table className="table-ios table-fixed w-full">
            <thead>
              <tr>
                <th className="w-[30%]">账号</th>
                <th className="w-[92px] whitespace-nowrap">工作台</th>
                <th className="w-[26%]">商业身份</th>
                <th className="w-[70px] whitespace-nowrap">卖家等级</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.pk}-${row.account_id}`}>
                  <td>
                    <div className="font-mono text-xs text-gray-700 dark:text-gray-300 truncate" title={row.account_id}>
                      {row.account_id || '--'}
                    </div>
                    <div className="text-xs text-gray-400 truncate">{row.note || '无备注'}</div>
                  </td>
                  <td>
                    {row.error ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-gray-100 text-gray-500 dark:bg-slate-700 dark:text-gray-400 whitespace-nowrap">
                        未检出
                      </span>
                    ) : row.workbench_enabled ? (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-green-50 text-green-700 dark:bg-green-900/30 dark:text-green-400 whitespace-nowrap">
                        <ShieldCheck className="w-3 h-3" />
                        可进入
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 whitespace-nowrap">
                        <ShieldAlert className="w-3 h-3" />
                        无权限
                      </span>
                    )}
                  </td>
                  <td className="text-xs text-gray-600 dark:text-gray-400">
                    {(row.identities || []).length
                      ? (row.identities || []).map((i) => i.bizName || i.bizCode).join('、')
                      : '--'}
                  </td>
                  <td className="text-xs text-gray-600 dark:text-gray-400 whitespace-nowrap">
                    {row.seller_level || '--'}
                  </td>
                  <td className="text-xs text-gray-500 dark:text-gray-400">
                    {row.error || (row.workbench_enabled
                      ? '可调用下架、数据罗盘等工作台接口'
                      : 'seller.pc 类接口不可用（下架 / 数据罗盘），需该账号自行取得鱼小铺专业卖家身份')}
                  </td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-center text-sm text-gray-400 py-6">
                    没有可检测的账号
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          {loading && (
            <div className="flex items-center justify-center gap-2 py-6 text-sm text-gray-500">
              <Loader2 className="w-4 h-4 animate-spin" />
              正在逐个账号检测权限…
            </div>
          )}
        </div>

        <div className="flex items-center justify-center gap-3 px-5 py-3 border-t border-gray-100 dark:border-slate-700">
          {checkedAt && !loading && (
            <span className="text-xs text-gray-400">
              {checkedAt} 检测 · {granted}/{rows.length} 个账号有工作台权限
            </span>
          )}
          <button
            onClick={runCheck}
            disabled={loading}
            className="btn-ios-secondary btn-sm flex items-center gap-1 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            重新检测
          </button>
          <button onClick={onClose} className="btn-ios-primary btn-sm">
            关闭
          </button>
        </div>
      </div>
    </div>
  )
}
