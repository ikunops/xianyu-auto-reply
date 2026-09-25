/**
 * 素材图片在库里存的是后端容器内的绝对路径（/app/static/course-images/x.png），
 * 而浏览器要经 nginx 的 /static 代理才能取到。直接把绝对路径当 src 会命中
 * SPA 兜底路由拿到一坨 HTML，表现为破图 + 显示 alt 文字。
 * 只用于显示；发布/入库仍用原始绝对路径。
 */
export function mediaUrl(path?: string | null): string {
  if (!path) return ''
  if (/^(https?:|data:|blob:|\/\/)/.test(path)) return path
  return path.replace(/^\/?app\/static\//, '/static/')
}
