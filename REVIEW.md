# 审查报告 — xianyu-auto-reply(基线 c634349,feature/ad-purge)

> 审查小分队六步流程产出。审查对象:`frontend/` + `promotion/frontend/` 源码 + 后端广告/外联面(本仓库无 dist 产物,审查对象即源码,构建验证后置于修复阶段)。
> 机械统计工具:`mech_stats.py`(CSS/TSX 工艺)、`closure_map.py`(闭环映射),脚本经两轮核验修正误报后取数。

## 结论

骨架健康:376 条后端路由与前端 API 层双向闭环仅 2 处悬空且都藏在孤儿死函数里,前端无乱码/无内联硬编码色/无真重复选择器。主要问题集中在三处:**作者商业化基建遍布前后端**(站内广告位买卖系统、remote 官方广告/公告源、激活码引流页、8 个 launcher 文件外联 xy.zhinianboke.com)、**24 个孤儿 API 函数**(死代码)、**CSS 以 !important 对抗 Tailwind**(119 处)。总修复量:广告/招商彻底移除约 30+ 文件,死代码清理可选,工艺问题仅记录不改。

## 广告/招商/引流移除清单(P0,本次必做)

### 前端 frontend/
| # | 位置 | 内容 | 处置 |
|---|---|---|---|
| F1 | `pages/dashboard/Dashboard.tsx:275-419` | 推荐广告轮播+文字广告+"广告位招租"空态 | 删模块 |
| F2 | `pages/advertisements/`(AdApply/AdManage/AdPaymentModal)+ 路由 `App.tsx:351,421` + 菜单 `config/navigation.ts` | 广告位申请/付费(支付宝当面付)/复核 | 删页面+路由+菜单 |
| F3 | `pages/about/About.tsx:7,28-34,104-124,197-350` | 微信群/QQ群/公众号("发送最新源码")/Telegram/赞赏 五卡片区 | 删区块,页面收缩为系统信息 |
| F4 | `pages/about/UpdateModal.tsx:30` + `api/version.ts` | 检查更新弹窗指向 xy-update.zhinianboke.com | 删检查更新,留本地版本号 |
| F5 | `pages/auth/GetSourceCode.tsx` / `GetLocalVersion.tsx` + 路由 `App.tsx:319-320` | "关注公众号'执念商业'发送'最新源码'"引流页 | 删页面+路由 |
| F6 | `components/common/AuthNavbar.tsx:19,22-27,103` | `isOnlineEnv()` 域名判断+受限菜单 | 随 F5 清理 |
| F7 | `pages/personalSettings/PersonalSettings.tsx:725-726` | "秘钥资金流水…请进入 agent.zhinianboke.com…QQ:531779708 微信:zhinian_znbk" | 删文案 |
| F8 | `pages/admin/RiskLogs.tsx:241-242` | 滑块验证码指引指向 xy-api.zhinianboke.com(作者商业服务) | 删指引文案,留输入框 |
| F9 | `pages/accounts/Accounts.tsx:1903-1908` | 抓包工具链接指向 zhinianboke 仓库 | 删链接留说明 |
| F10 | `api/settings.ts:44-46` | 底部广告默认值 hsykj.com | 默认值置空 |
| F11 | `pages/settings/AuthFooterAdSettingsCard.tsx:17-38` + Settings 页挂载点 | 管理员"底部广告设置"卡 | 删卡片 |
| F12 | `api/advertisements.ts` / `api/announcements.ts:21,32` / popupAnnouncements | remote 官方来源合并逻辑(source==='remote') | 删 remote 分支,只留 local |
| F13 | `api/settings.ts:499-515` qrcode 五类型函数 | 社群二维码存取 | 删 |
| F14 | `public/static/{qq-group,wechat,wechat-group,wechat-group1,xianyu-group}.png` | 群二维码占位图 | 删 |
| F15 | `login`/`register` 页 footer_ad_html 渲染点 | 登录页底部广告渲染 | 删渲染 |

### 后端 backend-web/
| # | 位置 | 内容 | 处置 |
|---|---|---|---|
| B1 | `app/api/routes/advertisements.py`(646行)+ `_exports.py:15,141` | 广告买卖全系统(含 remote 合并 :28-31,86-89) | 删路由+注册 |
| B2 | `app/services/remote_content_service.py` + `announcements.py:22-24,89-91` + `popup_announcements.py:26-28,100-102` | 官方远程拉取服务(广告/公告/弹窗公告) | 删服务+三处调用 |
| B3 | `app/api/routes/qrcode.py` + `_exports.py:64,156` | 社群二维码上传/读取(已确认仅此用途) | 删 |
| B4 | `app/api/routes/version.py:36-79` + `app/services/version_service.py:25` | `/version/check` 远程更新代理指向 xy-update.zhinianboke.com | 删 check 端点,留 /current |
| B5 | `app/services/system_setting_service.py:39` | DEFAULT_AUTH_FOOTER_AD_HTML(hsykj) | 置空 |
| B6 | `common/db/init_database.py:132-136` | 种子数据 auth.footer_ad_html(hsykj) | 删种子项 |
| B7 | `app/core/config.py:90-113` + `.env.example:48,55` + `docker-compose.yml:91,95` + `deploy.sh` / `update.sh` / `deploy_remote.sh` | REMOTE_OFFICIAL_BASE_URL/ENABLE_REMOTE_* 配置族 | 删;CARD_DOCK_BASE_URL 默认值改空(分销功能保留,不再默认指作者服务器) |

### 桌面端 launcher/(Windows EXE)
| # | 位置 | 内容 | 处置 |
|---|---|---|---|
| L1 | `updater.py:32` + `config_init.py:28` | 更新服务器 xy-update.zhinianboke.com | 默认值置空 |
| L2 | `gui.py:104,235,247` / `gui_about.py:20` / `gui_dashboard.py:23` / `gui_running.py:270` / `gui_renew.py:168` | 群二维码/激活/续期/主页外联 xy.zhinianboke.com | 置空或删跳转 |

### 文档与杂项
| # | 位置 | 内容 | 处置 |
|---|---|---|---|
| D1 | `README.md:7-29` | 招商接单/夸克网盘引流/五个交流群二维码表 | 删章节 |
| D2 | `README.md:166-175,207-215,437` | curl xy-update.zhinianboke.com 一键脚本指引 | 改为本地脚本指引 |
| D3 | `README.md:180` | clone 地址指向上游 | 改本仓库 |
| D4 | `推荐云服务器CDN-www.hsykj.com.url` | 云服务器广告快捷方式 | 删文件 |
| D5 | `scripts/Pipeline脚本*.groovy` | Jenkins 流水线,仓库地址写死 zhinianboke | 删(作者 CI 残留) |
| D6 | `README.md:467-469` | Star History 图指上游 | 删 |

## P1(应修,机械批量)

1. **24 个孤儿 API 函数**(0 调用者,证据见 `closure_map.py` 输出):`settings.ts` 的 backup 五件套全部无页面调用(getBackupList/downloadDatabaseBackup/uploadDatabaseBackup 端点写法正确但无人用——实际备份 UI 在 admin/DbBackupLogs.tsx 走别的封装;**exportUserBackup/importUserBackup 既孤儿又调不存在的 `/api/v1/backup/*` 端点(后端实际是 `/api/v1/admin/backup/*`),双重死代码**);其余:`accounts.ts::getAvailableDeliveryBlockRules/getAllAIReplySettings/clearProxyConfig`、`cards.ts::getAllCards`、`compass.ts::goofishCompassSearch`、`distribution.ts::cascadeUpdateStatus`、`items.ts::fetchItemsFromAccount`、`keywords.ts::addKeyword/batchAddKeywords/batchDeleteKeywords`、`notifications.ts::deleteAccountNotifications`、`orders.ts::updateOrderStatus`、`productPublish.ts::getMaterial`、`publishAddresses.ts::*2`、`settings.ts::getDefaultDisclaimerSettings/getAISettings/updateAISettings`、`version.ts::getCurrentVersion`。随广告移除顺带清理本次涉及文件内的孤儿,其余不动(避免面扩大)。
2. **119 处 !important**(`frontend/src/styles/theme.css` 79 + `promotion/frontend/src/styles/theme.css` 40):与 Tailwind preflight 对抗,记录不改(改动面大,收益低)。

## P2(可优化,仅记录)

- `frontend/src/styles/globals.css` 等 4 处 rgba 硬编码色(量化:共 4 处,均灰色系辅助色)。
- `frontend/index.html:16-18` Google Fonts 外链,国内环境加载慢,可考虑本地化。
- 隐藏死入口:`search/compass/crawler` 三页有路由无菜单;`online-chat-new` 路由渲染空元素(App.tsx:346 注释自证,KeepAlive 实现在别处,非 bug);EXE 专用菜单开关残留(navigation.ts:40-42)。

## ✅ 保留项(防误伤)

- **distribution/ 分销体系 + promotion/ 返佣子系统**:用户明确保留(代理招商体系≠广告),纳入审查不动代码。
- **激活码功能**(`/get-activation`、`/renew-activation`、`activation.py`):注册流程的一部分,保留;仅删"公众号取源码"引流页(F5)。
- **announcements/popupAnnouncements 本地公告功能**:管理员自建公告是正常运营功能,只删 remote 源。
- **payment.py 充值/支付宝**:服务 AI 秘钥余额充值,非广告,保留(广告付款端点随 B1 一并消失)。
- **免责声明三套展示**:共用一份默认文案,内容中性,非死代码。
- **AGPL-3.0 LICENSE 与上游特别鸣谢**(XianYuApis/XianyuAutoAgent/myfish):许可证要求与开源礼节,保留。

## 落地顺序

1. 前端移除(F1-F15)→ 独立 commit
2. 后端移除(B1-B7)+ launcher(L1-L2)→ 独立 commit
3. README/杂项(D1-D6)→ 独立 commit
4. 验证:双前端 `tsc + vite build`、后端 `py_compile` 全量、闭环复扫(悬空=0、已删符号残留=0)→ 回归结果写回本文件
