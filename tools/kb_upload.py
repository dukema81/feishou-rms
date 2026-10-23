# -*- coding: utf-8 -*-
"""飞售零售管理系统 · 文档与DEMO批量上传知识库（分类 33 企业管理系统）"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = r"C:/Users/maxl/WorkBuddy/Claw/feishou-rms"
BASE = "http://42.193.158.63"
CAT = 33
PASSWORD = "YCSpyVwt@J2UByom3#n6gb"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
TOKEN = None
REPLACE = "--replace" in sys.argv

DOCS = [
    ("docs/feishou_design_v1.docx", "飞售零售管理系统建设方案",
     "「飞售零售管理系统（RMS）」完整建设方案 V1.0：连锁零售数字化痛点与建设目标、"
     "业务域设计（门店/商品SKU与条码/会员等级折扣 银卡95·金卡9·铂金85/积分与储值/"
     "促销 满减与折扣·最优匹配·时间窗冲突检测/POS销售状态机 cart→paid·促销→会员折扣→FEFO扣库存→积分/"
     "退货回补/批次效期库存/采购入库/供应商应付与欠款上限/四类风险预警 低库存·临期·负毛利·欠款超限）、"
     "计算内核口径（金额以分存储、Decimal HALF_UP、促销与折扣一次量化）、"
     "总体架构与零依赖技术选型（Python 标准库 http.server + SQLite WAL）、"
     "27 表数据模型、6 角色权限矩阵、13 页面功能清单、对外集成方案、部署方案。",
     "飞售,RMS,零售管理,建设方案,POS"),
    ("docs/feishou_api_v1.docx", "飞售零售管理系统 REST 接口契约",
     "~80 端点分组契约：统一响应包 {code,message,data} 与 HTTP 状态一致、鉴权五通道"
     "（Bearer / X-Token / Cookie / ?token= / X-Api-Key，SHA-256 存储）、"
     "Idempotency-Key 幂等、增量同步协议（版本号 + 实体过滤）、列表统一 {items,total,page,size}、"
     "门店/商品条码/会员充值/供应商/促销试算/POS销售/退货/库存批次/采购/财务/风险/平台域 全量接口表、"
     "销售/采购状态机约束、校验规则与错误码表、电商/外卖/支付网关对接示例。",
     "飞售,RMS,API,接口契约,REST,幂等,增量同步,零售对接"),
    ("docs/feishou_test_v1.docx", "飞售零售管理系统测试报告",
     "四道质量门禁全部通过：pytest 53 条（内核 30 例：元转分HALF_UP/明细金额/积分/会员等级折扣/"
     "促销满减折扣与最优匹配/时间窗重叠/销售采购状态机/FEFO批次分配/缺货 shortfall/"
     "低库存临期负毛利欠款规则/权限通配/统计；API 集成 23 例：门店商品会员CRUD/条码查询/"
     "促销试算/POS计价链路手算对照/余额不足422/FEFO扣减核对/退货回补与二次退货422/"
     "采购入库应付/风险扫描处理/财务汇总/幂等/增量同步/CSV导出/RBAC越权）；"
     "UI 巡检 Playwright 登录+13 页面 0 控制台异常；冒烟 57 项全通过（幂等化连跑2次）。"
     "测试中发现并修复多项缺陷（风险扫描SQL列名、种子序号未初始化、用户删除路由缺失等）。",
     "飞售,RMS,测试报告,pytest,Playwright,质量门禁"),
    ("docs/feishou_manual_v1.docx", "飞售零售管理系统使用手册",
     "面向全部 6 角色的操作手册：系统定位与账号表（admin/123456 等）、13 页面逐页说明"
     "（工作台 KPI、门店管理、商品条码、会员等级储值充值、促销满减折扣、POS 收银计价链路、"
     "销售退货、批次效期库存、采购入库、供应商应付、财务流水、风险四类扫描、系统管理密钥同步）、"
     "收银/补货/退货三大典型流程、金额分口径说明、电商/外卖/支付网关对接指引、部署运维。",
     "飞售,RMS,使用手册,操作指南,零售管理"),
    ("demo/飞售零售管理系统Demo.zip", "飞售零售管理系统离线演示（DEMO）",
     "单文件离线演示（zip 内为 HTML，解压后双击即可用浏览器打开，无需服务与网络）。"
     "数据取自演示实例真实快照：6 用户 / 3 门店 / 8 商品 / 4 会员 / 2 供应商 / 2 促销 / "
     "批次库存（含临期与低库存样例）/ 完整销售链路 / 采购单 / 财务流水 / 风险记录。"
     "13 个页签覆盖工作台、门店管理、商品管理、会员管理、促销活动、POS 收银、销售单据、"
     "库存管理、采购管理、供应商、财务流水、风险预警、系统管理。"
     "支持顶部切换 4 个真实视角（管理员 / 店长 / 会员管理 / 只读）。只读快照，写操作不会真正执行。",
     "飞售,RMS,DEMO,离线演示,零售管理"),
]


def req(path, method="GET", data=None, token=None):
    r = urllib.request.Request(BASE + path, method=method)
    if data is not None:
        r.data = json.dumps(data).encode("utf-8")
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with OP.open(r, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                     # noqa: BLE001
            return e.code, {}


def curl_upload(path, title, desc, tags):
    full = os.path.join(ROOT, path)
    if full.endswith(".docx"):
        mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        mime = "application/zip"
    cmd = ["curl", "-s", "--noproxy", "*",
           "-H", "Authorization: Bearer " + TOKEN,
           "-F", "file=@%s;type=%s" % (full, mime),
           "-F", "title=" + title,
           "-F", "description=" + desc,
           "-F", "categoryId=%d" % CAT,
           "-F", "tags=" + tags,
           BASE + "/api/documents/upload"]
    out = subprocess.run(cmd, capture_output=True, timeout=300)
    try:
        return json.loads(out.stdout.decode("utf-8", "ignore"))
    except Exception:                                         # noqa: BLE001
        return {"code": -1, "raw": out.stdout.decode("utf-8", "ignore")[:400],
                "err": out.stderr.decode("utf-8", "ignore")[:200]}


def existing(cat=CAT):
    st, j = req("/api/documents?categoryId=%d&pageNum=1&pageSize=200" % cat, token=TOKEN)
    data = j.get("data") or {}
    if isinstance(data, list):
        return data
    return data.get("records") or data.get("list") or []


def delete_doc(doc_id):
    return req("/api/documents/%s" % doc_id, "DELETE", token=TOKEN)


def main():
    global TOKEN
    st, j = req("/api/auth/login", "POST", {"username": "admin", "password": PASSWORD})
    assert j.get("code") == 200, j
    TOKEN = j["data"]["token"]
    print("login ok")

    if REPLACE:
        want = {t for _, t, _, _ in DOCS}
        for r in existing():
            if r.get("title") in want:
                st, j = delete_doc(r.get("id"))
                print("删除旧文档 %s id=%s -> %s" % (r.get("title"), r.get("id"), st))
                time.sleep(0.4)

    results = []
    for path, title, desc, tags in DOCS:
        j = curl_upload(path, title, desc, tags)
        code = j.get("code")
        doc_id = (j.get("data") or {}).get("id") if isinstance(j.get("data"), dict) else j.get("data")
        size = os.path.getsize(os.path.join(ROOT, path))
        print("%-32s code=%s id=%s %.1fKB" % (os.path.basename(path), code, doc_id, size / 1024.0))
        if code != 200:
            print("   !!", str(j)[:300])
        results.append((path, title, code, doc_id))
        time.sleep(1.2)

    ok = [r for r in results if r[2] == 200]
    print("\n上传成功 %d / %d" % (len(ok), len(results)))
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "kb_upload_result.json"), "w", encoding="utf-8") as f:
        json.dump([{"file": r[0], "title": r[1], "code": r[2], "id": r[3]} for r in results],
                  f, ensure_ascii=False, indent=2)
    return results


if __name__ == "__main__":
    main()
