/**
 * 版本 API
 *
 * 功能：
 * 1. 获取系统当前版本号
 */
import { get } from '@/utils/request'
import type { ApiResponse } from '@/types'

const PREFIX = '/api/v1/version'

/** 当前版本信息 */
export interface CurrentVersion {
  version: string
}

/** 获取当前版本号 */
export const getCurrentVersion = async (): Promise<
  ApiResponse & { data?: CurrentVersion }
> => {
  return get(`${PREFIX}/current`)
}
