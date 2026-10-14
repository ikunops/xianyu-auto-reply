/**
 * 滑块冷却设置卡片（自包含：直接读写 system_settings 的三个键）
 *
 * 背景：滑块验证连续失败会触发大量重试，进而加深平台风控。这里提供：
 *  - 总开关：是否在连续失败达到阈值后进入冷却
 *  - 失败阈值：连续失败多少次进入冷却
 *  - 冷却时长：冷却多少分钟（冷却期内不再尝试刷新 Token；默认 180）
 * 冷却状态落库在 xy_accounts.captcha_cooldown_until / captcha_fail_count，
 * 账号列表会展示"冷却中"徽标，并可手动解除。
 */
import { useEffect, useState } from 'react'
import { ShieldCheck, Save } from 'lucide-react'

import { updateSystemSettings } from '@/api/settings'
import { useUIStore } from '@/store/uiStore'
import { getApiErrorMessage } from '@/utils/apiError'
import type { SystemSettings } from '@/types'

interface Props {
  settings: SystemSettings | null
}

export function CaptchaCooldownSettingsCard({ settings }: Props) {
  const { addToast } = useUIStore()
  const [enabled, setEnabled] = useState(true)
  const [minutes, setMinutes] = useState('180')
  const [threshold, setThreshold] = useState('5')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!settings) return
    const e = settings['captcha.cooldown_enabled'] as unknown
    const m = settings['captcha.cooldown_minutes']
    const t = settings['captcha.fail_threshold']
    if (e !== undefined) setEnabled(e === true || e === 'true')
    if (m !== undefined && m !== null && String(m) !== '') setMinutes(String(m))
    if (t !== undefined && t !== null && String(t) !== '') setThreshold(String(t))
  }, [settings])

  const handleSave = async () => {
    const m = Number(minutes)
    const t = Number(threshold)
    if (!Number.isFinite(m) || m < 1) {
      addToast({ type: 'error', message: '冷却时长需为不小于 1 的分钟数' })
      return
    }
    if (!Number.isFinite(t) || t < 1) {
      addToast({ type: 'error', message: '失败阈值需为不小于 1 的整数' })
      return
    }
    try {
      setSaving(true)
      const result = await updateSystemSettings({
        'captcha.cooldown_enabled': enabled,
        'captcha.cooldown_minutes': Math.floor(m),
        'captcha.fail_threshold': Math.floor(t),
      })
      if (result.success) {
        addToast({ type: 'success', message: result.message || '滑块冷却设置已保存' })
      } else {
        addToast({ type: 'error', message: result.message || '保存失败' })
      }
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '保存失败') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="vben-card">
      <div className="vben-card-header flex items-center justify-between gap-3">
        <h2 className="vben-card-title">
          <ShieldCheck className="w-4 h-4 text-blue-500" />
          滑块冷却（防触发平台风控）
        </h2>
        <button onClick={handleSave} disabled={saving} className="btn-ios-primary">
          <Save className="w-4 h-4" />
          {saving ? '保存中...' : '保存'}
        </button>
      </div>
      <div className="vben-card-body space-y-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          滑块验证在 10 分钟内失败达到阈值即触发大量重试并加深平台风控。开启后：达到阈值即进入冷却，
          冷却期内不再尝试刷新 Token；账号列表会显示"冷却中"并可手动解除。
        </p>
        <div className="flex items-center gap-3">
          <label className="input-label w-32">启用冷却</label>
          <button
            type="button"
            onClick={() => setEnabled((v) => !v)}
            className={`inline-flex items-center gap-1 px-3 py-1.5 text-xs rounded-full border transition-colors ${
              enabled
                ? 'bg-green-100 text-green-700 border-green-300 dark:bg-green-900/30 dark:text-green-300 dark:border-green-700'
                : 'bg-slate-100 text-slate-500 border-slate-300 dark:bg-slate-700 dark:text-slate-300 dark:border-slate-600'
            }`}
          >
            {enabled ? '已开启' : '已关闭'}
          </button>
        </div>
        <div className="flex items-center gap-3">
          <label className="input-label w-32">失败次数阈值</label>
          <input
            className="input-ios w-28"
            type="number"
            min={1}
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
          <span className="text-xs text-slate-500 dark:text-slate-400">次 / 10 分钟内（默认 5）</span>
        </div>
        <div className="flex items-center gap-3">
          <label className="input-label w-32">冷却时长</label>
          <input
            className="input-ios w-28"
            type="number"
            min={1}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
          <span className="text-xs text-slate-500 dark:text-slate-400">分钟（默认 180）</span>
        </div>
      </div>
    </div>
  )
}
