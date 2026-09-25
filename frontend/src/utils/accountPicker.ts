import type { AccountDetail } from '@/types'

/**
 * 数据罗盘类页面（卖家工作台 PC 接口）只有被闲鱼开了权限的账号能取到数，
 * 而后端账号列表按 account_id 升序返回，第一个往往不是可用账号 —— 所以默认账号要单独挑。
 */
const LAST_KEY = 'xy_data_account_last'
const OK_KEY = 'xy_data_account_ok'

/** 下拉展示顺序：启用中的排前面，其余保持后端原序 */
export function sortAccountsForPicker(accounts: AccountDetail[]): AccountDetail[] {
  return [...accounts].sort((a, b) => (a.enabled === b.enabled ? 0 : a.enabled ? -1 : 1))
}

const usable = (accounts: AccountDetail[]) => sortAccountsForPicker(accounts).filter((a) => a.pk != null)

/** 默认账号：上次真取到过数的 > 上次选过的 > 备注里写明主号的 > 第一个启用中的 */
export function pickDefaultAccountId(accounts: AccountDetail[]): number | null {
  const list = usable(accounts)
  if (!list.length) return null
  const remembered = Number(localStorage.getItem(OK_KEY) || localStorage.getItem(LAST_KEY) || 0)
  const hit = list.find((a) => a.pk === remembered)
  if (hit) return hit.pk ?? null
  const marked = list.find((a) => (a.note || a.remark || '').includes('主号'))
  if (marked) return marked.pk ?? null
  return list[0].pk ?? null
}

/** 记住用户手动选过的账号 */
export function rememberAccountChoice(accountId: number): void {
  localStorage.setItem(LAST_KEY, String(accountId))
}

/** 记住"这个账号真能取到罗盘数据"，下次进页面直接落在它上面 */
export function rememberWorkingAccount(accountId: number): void {
  localStorage.setItem(OK_KEY, String(accountId))
}
