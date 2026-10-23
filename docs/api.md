# 飞售零售管理系统（RMS）API 接口契约

Base URL：`http://<host>/retail/api`（生产经 nginx，本地直连 8029 端口根路径 `/api`）
版本：v1.0

## 1. 通用约定

### 1.1 响应包
所有接口返回统一 JSON：
```json
{"code": 200, "message": "ok", "data": { ... }}
```
`code` 与 HTTP 状态码一致：200 成功、400 参数错、401 未认证、403 无权限、404 不存在、409 冲突、422 业务规则拒绝、423 幂等冲突、500 服务器错误、501 未实现（预留接口）。

### 1.2 列表响应
```json
{"code":200,"message":"ok","data":{"items":[...],"total":57,"page":1,"size":20}}
```
通用查询参数：`page`(默认1)、`size`(默认20, ≤200)、`keyword`、`sort`、`order`、`store_id` 等业务过滤。

### 1.3 鉴权（五通道，任选其一）
| 通道 | 示例 |
|---|---|
| Bearer | `Authorization: Bearer <token>` |
| 头 | `X-Token: <token>` |
| Cookie | `Cookie: retail_token=<token>` 或 `token=<token>` |
| 查询 | `?token=<token>` |
| ApiKey | `X-Api-Key: <key>`（服务器存 SHA-256，默认 perms `retail.*`） |

Token 登录签发，7 天有效。无凭证访问需鉴权接口返回 401。

### 1.4 幂等
写接口（POST/PUT/DELETE）支持请求头 `Idempotency-Key: <uuid>`；同一 key 重复请求返回首次结果（idem_keys 表）。

### 1.5 增量同步（供外部系统对接）
```
GET /api/sync?since=<version>&entities=commodities,sales,inventory
→ {"code":200,"data":{"version":123,"changes":[{"entity":"commodities","op":"upsert","row":{...}}, ...]}}
```
`since=0` 为全量快照；省略 `entities` 返回全部实体。

### 1.6 导出
`GET /api/export/<entity>?format=csv` → `text/csv`（UTF-8 BOM）。支持 commodities/members/sales/inventory/transactions。

## 2. 认证与系统

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/login | `{username,password}` → `{token,user}` |
| POST | /api/logout | 注销当前 token |
| GET | /api/me | 当前用户信息+权限 |
| GET | /api/health | 健康检查（免鉴权）`{"status":"ok"}` |
| GET | /api/notices | 公告列表 |
| POST | /api/notices | 新建公告（admin） |
| GET | /api/logs | 审计日志（admin） |
| GET/PUT | /api/rules | 业务参数（积分比例、临期天数等） |

## 3. 基础主数据

### 3.1 门店 /api/stores
- `GET /?keyword=&status=`；`POST /` `{code, name, address, phone}`
- `GET|PUT|DELETE /{id}`（有关联销售/库存时删除 409）

### 3.2 商品 /api/commodities
- `GET /?keyword=&barcode=&category=&store_id=`；`POST /` `{name, sku, barcode, unit, category, price_cents, cost_cents, shelf_life_days, safe_stock}`
- `GET|PUT|DELETE /{id}`；条码重复 409
- `GET /api/commodities/barcode/{code}` 扫码查询（POS 用）

### 3.3 会员 /api/members
- `GET /?keyword=&level=&phone=`；`POST /` `{name, phone, level(normal|silver|gold|platinum), balance_cents}` → 会员码 `M+seq`
- `GET|PUT|DELETE /{id}`；等级折扣：normal 1.00 / silver 0.95 / gold 0.90 / platinum 0.85
- `GET /{id}/txns` 储值/积分流水；`POST /{id}/recharge {amount_cents}` 充值
- `GET /{id}/sales` 消费记录

### 3.4 供应商 /api/suppliers
- `GET /?keyword=`；`POST /` `{name, contact, phone, credit_days, debt_limit_cents}`
- `GET|PUT|DELETE /{id}`；应付余额见 `payable_cents`

## 4. 促销 /api/promotions
- `GET /?status=&store_id=&date_from=&date_to=`
- `POST /` `{name, type(full_off|discount), threshold_cents?, off_cents?, rate?, start_date, end_date, store_id?}`
- `GET|PUT|DELETE /{id}`；时间窗冲突同门店同类型重叠 422
- 优惠计算规则：`full_off` 满减整单；`discount` rate 两位整数（88→×0.88）作用于小计；多促销自动取优惠最大者

## 5. POS 销售 /api/sales

### 5.1 结账
- `POST /` `{store_id, member_id?, items:[{commodity_id, qty, unit_price_cents?}], promotion_id?, pay_method:cash|wechat|alipay|balance, received_cents}`
- 计价链路：小计 → 促销优惠 → 会员等级折扣 → `paid_cents`（Decimal HALF_UP 到分）；积分 = `paid_cents / 10` 取整入账；balance 支付校验余额不足 422
- 库存按 **FEFO** 扣批次，不足整体失败 422 回滚
- 折后行价低于成本 → 负毛利风险不阻断
- 返回单号 `XSyyyymmdd-xxx`、明细、优惠分解 `{promo_off_cents, member_off_cents}`、积分、找零

### 5.2 查询与退货
- `GET /?store_id=&member_id=&status=&date_from=&date_to=`；`GET /{id}`（含 items）
- `POST /{id}/refund {reason}` → 生成退货单（TH 单号）、库存回补、会员积分/余额回冲、负流水

### 5.3 日报
- `GET /api/finance/summary?date=&store_id=` → `{income_cents, refund_cents, by_method:{...}, sale_count, member_new}`

## 6. 库存与采购

### 6.1 库存 /api/inventory
- `GET /?store_id=&commodity_id=&keyword=&near_expiry_days=`（默认按效期升序）
- `GET /api/inventory/summary?store_id=&commodity_id=` 汇总可用量

### 6.2 采购 /api/purchases
- `GET /?status=&supplier_id=&store_id=`；`POST /` `{supplier_id, store_id, items:[{commodity_id, qty, cost_cents, batch_no, expiry}]}` → `CGyyyymmdd-xxx`
- 状态流转 `POST /{id}/transition {to}`：`draft→submitted`、`submitted→received`（入批次库存 + 应付流水累加供应商余额）；`draft→cancelled`

## 7. 风险中心
- `POST /api/risk/scan` → 执行四类扫描，返回 `{created, by_type:{...}}`
- `GET /api/risk?status=&level=&type=`；`POST /api/risk/{id}/resolve {note}` 关闭风险

## 8. 用户与系统管理（admin）
- `GET|POST /api/users`，`PUT|DELETE /api/users/{id}`；`PUT /api/users/{id}/password {password}` 改密
- `GET|POST /api/api-keys`，`DELETE /api/api-keys/{id}` —— 返回明文仅一次
- `GET /api/dashboard` → 今日销售/笔数/客流、待收货、低库存数、临期数、活跃促销
- `GET /api/sync?since=&entities=`（见 1.5）

## 9. 错误码示例
```json
// 422 库存不足
{"code":422,"message":"库存不足：可口可乐330ml 需 10 缺 3","data":{"commodity_id":3,"short":3}}
// 422 余额不足
{"code":422,"message":"储值余额不足","data":{"balance_cents":5000,"need_cents":12800}}
```
