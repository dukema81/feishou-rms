# 飞售零售管理系统（RMS）建设方案

版本：v1.0 ｜ 密级：内部

## 1. 项目概述

飞售零售管理系统（FeiShou RMS）面向连锁零售/便利店/精品店，提供门店管理、商品（SKU/条码）、会员体系、促销活动、POS 收银、库存与批次效期、采购补货、供应商结算、财务流水、风险扫描等一体化业务能力，并预留标准化 API 供第三方系统（电商平台、外卖平台、支付网关、ERP/WMS、企业 OA 等）对接。

### 1.1 设计目标
- **零依赖部署**：Python 标准库 + SQLite（WAL），单机即可运行，无第三方包。
- **对外友好**：统一 REST 风格、统一响应包、Bearer/ApiKey/Cookie 五通道鉴权、幂等键、增量同步。
- **金额精确**：所有金额以「分」（cents）为单位，Decimal HALF_UP，杜绝浮点误差。
- **风控前置**：低库存、临期、负毛利销售、供应商欠款超限自动扫描告警。

### 1.2 与「飞」系列体系的关系
沿用集团「飞」系列管理系统架构范式（飞运/飞餐/飞医），端口 **8029**、路由前缀 `/retail/`，与 nginx 网关统一托管。

## 2. 总体架构

```
浏览器 SPA (原生JS)
    │ /retail/
nginx (80) ── proxy_pass http://127.0.0.1:8029/ (剥前缀)
    │
ThreadingHTTPServer (8029)
    ├── server.py  路由层（~80 路由）
    ├── ret.py     纯函数业务内核（无IO可单测）
    ├── seed.py    演示数据
    └── db.py      sqlite3 WAL + execute 重试/回滚
            └── feishou.db（27 表）
```

分层职责：
- **路由层**：鉴权、参数校验、调用内核、统一响应包 `{code, message, data}`。
- **业务内核**：促销计算（满减/折扣）、会员折扣与积分、销售金额、FEFO 扣减、毛利校验、风险扫描——纯函数，可独立单测。
- **数据层**：`execute()` 带 30 次锁重试，统一捕获 `OperationalError`/`IntegrityError` 并回滚。

## 3. 业务域设计

### 3.1 基础主数据
| 域 | 表 | 说明 |
|---|---|---|
| 门店 | stores | 门店编码、地址、电话、状态 |
| 商品 | commodities | SKU 编码、条码（EAN-13 唯一）、单位、售价/进价（分）、保质期、安全库存 |
| 会员 | members | 会员码、等级（normal/silver/gold/platinum）→折扣 1.00/0.95/0.90/0.85、积分、余额、手机号 |
| 供应商 | suppliers | 资质、应付余额、账期、欠款上限 |

### 3.2 促销促销 promotions
- 类型 `full_off`（满减：满 threshold_cents 减 off_cents）与 `discount`（折扣 rate，如 88 → ×0.88）。
- 时间窗 start_date~end_date、适用门店（store_id 空=全门店）。
- 结算时自动匹配最优促销（先折扣后满减，多重叠加取优惠最大组合）。

### 3.3 POS 销售 sales + sale_items
- 购物车→结算：`cart→paid`；单号 `XSyyyymmdd-xxx`。
- 计价链路：明细小计 → 促销优惠（行内分摊）→ 会员折扣 → 实付；积分 = 实付/10 取整；支持现金/微信/支付宝/储值余额支付；储值余额不足 422。
- 退货 sales 返向单，走负流水。
- **负毛利校验**：折后行单价低于进价不阻断但生成 risk。

### 3.4 库存与采购
- **inventory**：门店×商品批次（batch_no、效期、数量）；`store_id+commodity_id+batch_no` 唯一。
- **POS 出库**：paid 时按 **FEFO（效期近先出）** 扣批次；不足整体失败 422 回滚。
- **采购 purchases + purchase_items**：draft→submitted→received；receive 入批次库存 + 应付流水（含可填门店）。
- **盘点**：库存只读，入/出库唯一通道为采购 receive 与销售 paid/退货。

### 3.5 会员
- 消费累计积分、积分可抵现（本期预留接口）；等级折扣自动套用；储值余额充值/扣减留痕（member_txns）。

### 3.6 风险中心 risks
| 类型 | 规则 | 等级 |
|---|---|---|
| stock_low | 门店商品可用量 ≤ 安全库存 | 30 warn |
| expiry_near | 效期 ≤ 90 天 | 25 warn |
| negative_margin | 折后售价 < 进价销售 | 35 warn |
| supplier_overdue | 供应商应付 > 欠款上限 | 20 risk |

### 3.7 平台域
users/tokens/api_keys/notices/logs/idem_keys/sync_state/ret_rules/seq，与飞医同构：角色 admin/manager/cashier/warehouse/member_admin/reader，权限通配 `*`、前缀 `retail.*`、写含读。

## 4. 数据模型（27 表）

stores, commodities, members, member_txns, promotions, sales, sale_items, inventory, purchases, purchase_items, suppliers, transactions, risks, users, tokens, api_keys, notices, logs, idem_keys, sync_state, ret_rules, seq 等

关键约束：
- 单号统一 `seq` 表发号（XS 销售、CG 采购、TH 退货）。
- `inventory(store_id, commodity_id, batch_no)` 唯一；`commodities.barcode` 唯一。
- 金额字段一律 `*_cents`（INTEGER）。

## 5. 安全与鉴权

- 密码 SHA-256 存储；登录签发 token（tokens 表，7 天过期）。
- 五通道鉴权：`Authorization: Bearer` / `X-Token` / `Cookie(retail_token|token)` / `?token=` / `X-Api-Key`（SHA-256 存储，默认 perms `retail.*`）。
- 幂等：`Idempotency-Key` 头 → idem_keys，写接口重复请求返回首次结果。
- 全量审计 logs 表（user/action/detail/ip）。

## 6. 非功能要求

- 性能：SQLite WAL 并发读写，接口 P95 < 100ms（单机百店规模）。
- 可用性：systemd 守护 + nginx 反代；数据文件日备。
- 可扩展：电商/外卖/支付网关对接仅需按 `docs/api.md` 契约调用，Token/ApiKey 均支持。

## 7. 交付物

| 交付物 | 位置 |
|---|---|
| 设计/API/测试/操作手册（md + docx） | docs/ |
| DEMO 单文件 HTML（zip） | demo/ |
| 后端 + 前端 + 测试 | backend/ frontend/ tests/ |
| 部署 | systemd feishou-rms (8029) + nginx /retail/ |
| 源码 | github.com/dukema81/feishou-rms |
