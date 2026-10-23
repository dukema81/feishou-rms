/* 飞售零售管理系统 · 页面层 */
var PAGES = {};

/* ---------- 工作台 ---------- */
PAGES.dash = function (main) {
  return GET('/api/dashboard').then(function (r) {
    var d = r.data || {};
    main.innerHTML =
      '<h2>工作台</h2>' +
      '<div class="kpis">' +
      kpi(d.sales_today, '今日销售单') +
      kpi(fmtCents(d.income_cents), '今日营收', 'ok') +
      kpi(d.members, '会员总数') +
      kpi(d.active_promotions, '进行中促销', 'pri') +
      kpi(d.pending_purchase, '待收货采购', d.pending_purchase ? 'warn' : '') +
      kpi(d.low_stock, '低库存告警', d.low_stock ? 'warn' : '') +
      kpi(d.near_expiry, '临期批次', d.near_expiry ? 'warn' : '') +
      kpi(d.open_risks, '未处理风险', d.open_risks ? 'err' : '') +
      '</div>' +
      '<div class="grid2">' +
      '<div class="card"><h3>快捷操作</h3><div class="quick">' +
      (perm('retail.sales.write') ? '<a class="btn" href="#/pos">POS 收银</a>' : '') +
      (perm('retail.members.write') ? '<a class="btn ghost" href="#/member">会员登记</a>' : '') +
      (perm('retail.purchases.write') ? '<a class="btn ghost" href="#/purchase">采购入库</a>' : '') +
      (perm('retail.promotions.write') ? '<a class="btn ghost" href="#/promotion">创建促销</a>' : '') +
      '</div></div>' +
      '<div class="card"><h3>最新销售</h3><div id="dash-sales">加载中…</div></div></div>';
    return GET('/api/sales').then(function (r2) {
      var el = document.getElementById('dash-sales');
      if (el) el.innerHTML = table(['单号', '~实收', '支付', '状态'], (r2.data.items || []).slice(0, 8), function (x) {
        return '<tr><td>' + esc(x.no) + '</td><td class="num">' + fmtCents(x.paid_cents) + '</td>' +
          '<td>' + payTag(x.pay_method) + '</td><td>' + saleTag(x.status) + '</td></tr>';
      }, '暂无销售记录');
    });
  });
};

/* ---------- 门店管理 ---------- */
PAGES.store = function (main) {
  main.innerHTML = '<h2>门店管理</h2><div class="toolbar">' +
    (perm('retail.stores.write') ? '<button class="btn" id="btn-new">新增门店</button>' : '') +
    '<input id="f-kw" placeholder="名称/编码/地址" class="inp">' +
    '<button class="btn ghost" id="btn-search">搜索</button></div><div id="list"></div>';
  function load(kw) {
    GET('/api/stores' + qs({keyword: kw})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['编码', '名称', '地址', '电话', '状态'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.code || '—') + '</td><td>' + esc(x.name) + '</td>' +
            '<td>' + esc(x.address || '—') + '</td><td>' + esc(x.phone || '—') + '</td>' +
            '<td>' + tag(x.status === 'active' ? '营业中' : '停用', x.status === 'active' ? 'ok' : 'err') + '</td></tr>';
        });
    });
  }
  document.getElementById('btn-search').onclick = function () { load(document.getElementById('f-kw').value.trim()); };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>新增门店</h3>' +
        field('门店编码', '<input id="f-code" placeholder="如 S004">') +
        field('名称', '<input id="f-name">') +
        field('地址', '<input id="f-addr">') +
        field('电话', '<input id="f-phone">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/stores', {
          code: document.getElementById('f-code').value.trim(),
          name: document.getElementById('f-name').value.trim(),
          address: document.getElementById('f-addr').value.trim(),
          phone: document.getElementById('f-phone').value.trim()
        }).then(function () { toast('已保存'); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 商品管理 ---------- */
PAGES.commodity = function (main) {
  main.innerHTML = '<h2>商品管理</h2><div class="toolbar">' +
    (perm('retail.commodities.write') ? '<button class="btn" id="btn-new">新增商品</button>' : '') +
    '<input id="f-kw" placeholder="名称/SKU" class="inp">' +
    '<input id="f-bc" placeholder="条码" class="inp" style="width:150px">' +
    '<button class="btn ghost" id="btn-search">搜索</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/commodities', 'commodities.csv'); };
  function load(kw, bc) {
    GET('/api/commodities' + qs({keyword: kw, barcode: bc})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['SKU', '条码', '名称', '分类', '~售价', '~进价', '~库存', '~安全库存'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.sku || '') + '</td><td>' + esc(x.barcode || '—') + '</td><td>' + esc(x.name) + '</td>' +
            '<td>' + esc(x.category || '—') + '</td><td class="num">' + fmtCents(x.price_cents) + '</td>' +
            '<td class="num">' + fmtCents(x.cost_cents) + '</td>' +
            '<td class="num">' + (x.stock <= x.safe_stock ? tag(x.stock, 'err') : x.stock) + '</td>' +
            '<td class="num">' + x.safe_stock + '</td></tr>';
        });
    });
  }
  document.getElementById('btn-search').onclick = function () {
    load(document.getElementById('f-kw').value.trim(), document.getElementById('f-bc').value.trim());
  };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>新增商品</h3>' +
        field('名称', '<input id="f-name">') +
        field('条码(EAN)', '<input id="f-bc" placeholder="6901234500000">') +
        field('单位', '<input id="f-unit" value="件">') +
        field('分类', '<input id="f-cat" placeholder="饮料/零食/日化…">') +
        field('售价(元)', '<input id="f-price" type="number" step="0.01">') +
        field('进价(元)', '<input id="f-cost" type="number" step="0.01">') +
        field('保质期(天)', '<input id="f-shelf" type="number" value="365">') +
        field('安全库存', '<input id="f-safe" type="number" value="10">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>', true);
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/commodities', {
          name: document.getElementById('f-name').value.trim(),
          barcode: document.getElementById('f-bc').value.trim(),
          unit: document.getElementById('f-unit').value.trim(),
          category: document.getElementById('f-cat').value.trim(),
          price: Number(document.getElementById('f-price').value || 0),
          cost: Number(document.getElementById('f-cost').value || 0),
          shelf_life_days: Number(document.getElementById('f-shelf').value || 365),
          safe_stock: Number(document.getElementById('f-safe').value || 10)
        }).then(function (r2) { toast('已保存：' + r2.data.sku); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 会员管理 ---------- */
PAGES.member = function (main) {
  main.innerHTML = '<h2>会员管理</h2><div class="toolbar">' +
    (perm('retail.members.write') ? '<button class="btn" id="btn-new">登记会员</button>' : '') +
    '<input id="f-kw" placeholder="姓名/会员码/手机号" class="inp">' +
    '<select id="f-level"><option value="">全部等级</option><option value="normal">普通</option>' +
    '<option value="silver">银卡</option><option value="gold">金卡</option><option value="platinum">铂金</option></select>' +
    '<button class="btn ghost" id="btn-search">搜索</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/members', 'members.csv'); };
  function ops(x) {
    if (!perm('retail.members.write')) return '—';
    return '<button class="btn sm ghost" data-rc="' + x.id + '">充值</button>';
  }
  function load(kw, lv) {
    GET('/api/members' + qs({keyword: kw, level: lv})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['会员码', '姓名', '手机号', '等级', '~积分', '~余额', '操作'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.code) + '</td><td>' + esc(x.name) + '</td><td>' + esc(x.phone || '—') + '</td>' +
            '<td>' + memberTag(x.level) + '</td><td class="num">' + x.points + '</td>' +
            '<td class="num">' + fmtCents(x.balance_cents) + '</td><td class="ops">' + ops(x) + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-rc')) return;
        var id = b.getAttribute('data-rc');
        modal('<h3>会员充值</h3>' +
          field('充值金额(元)', '<input id="f-amt" type="number" step="0.01" value="100">') +
          field('备注', '<input id="f-note" placeholder="现金/微信…">') +
          '<div class="m-foot"><button class="btn" id="btn-ok">确认充值</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
        document.getElementById('btn-ok').onclick = function () {
          POST('/api/members/' + id + '/recharge', {
            amount_cents: Math.round(Number(document.getElementById('f-amt').value || 0) * 100),
            note: document.getElementById('f-note').value.trim()
          }).then(function (r2) {
            toast('充值成功，余额 ' + fmtCents(r2.data.balance_cents));
            closeModal(); load();
          }).catch(function (e2) { toast(e2.message, true); });
        };
      };
    });
  }
  document.getElementById('btn-search').onclick = function () {
    load(document.getElementById('f-kw').value.trim(), document.getElementById('f-level').value);
  };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>登记会员</h3>' +
        field('姓名', '<input id="f-name">') +
        field('手机号', '<input id="f-phone">') +
        field('等级', '<select id="f-level"><option value="normal">普通</option><option value="silver">银卡（95折）</option>' +
          '<option value="gold">金卡（9折）</option><option value="platinum">铂金（85折）</option></select>') +
        field('初始储值(元)', '<input id="f-bal" type="number" step="0.01" value="0">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/members', {
          name: document.getElementById('f-name').value.trim(),
          phone: document.getElementById('f-phone').value.trim(),
          level: document.getElementById('f-level').value,
          balance: Number(document.getElementById('f-bal').value || 0)
        }).then(function (r2) { toast('登记成功：' + r2.data.code); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 促销活动 ---------- */
PAGES.promotion = function (main) {
  main.innerHTML = '<h2>促销活动</h2><div class="toolbar">' +
    (perm('retail.promotions.write') ? '<button class="btn" id="btn-new">新建促销</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/promotions').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['名称', '类型', '规则', '时间窗', '适用门店', '状态'], r.data.items, function (x) {
          var rule = x.ptype === 'full_off'
            ? '满 ' + fmtCents(x.threshold_cents) + ' 减 ' + fmtCents(x.off_cents)
            : (x.rate / 10).toFixed(1) + ' 折';
          var store = x.store_id ? ('门店 #' + x.store_id) : '全部门店';
          return '<tr><td>' + esc(x.name) + '</td>' +
            '<td>' + tag(x.ptype === 'full_off' ? '满减' : '折扣', x.ptype === 'full_off' ? 'pri' : 'ok') + '</td>' +
            '<td>' + esc(rule) + '</td><td>' + esc(x.start_date) + ' ~ ' + esc(x.end_date) + '</td>' +
            '<td>' + esc(store) + '</td>' +
            '<td>' + tag(x.status === 'active' ? '进行中' : '已停用', x.status === 'active' ? 'ok' : '') + '</td></tr>';
        });
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>新建促销</h3>' +
        field('名称', '<input id="f-name">') +
        field('类型', '<select id="f-type"><option value="full_off">满减</option><option value="discount">折扣</option></select>') +
        field('满减门槛(分)', '<input id="f-th" type="number" value="3000">') +
        field('满减金额(分)', '<input id="f-off" type="number" value="500">') +
        field('折扣率(1-99)', '<input id="f-rate" type="number" value="88">') +
        field('开始日期', '<input id="f-sd" type="date" value="' + todayStr() + '">') +
        field('结束日期', '<input id="f-ed" type="date" value="2027-12-31">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>', true);
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/promotions', {
          name: document.getElementById('f-name').value.trim(),
          ptype: document.getElementById('f-type').value,
          threshold_cents: Number(document.getElementById('f-th').value || 0),
          off_cents: Number(document.getElementById('f-off').value || 0),
          rate: Number(document.getElementById('f-rate').value || 100),
          start_date: document.getElementById('f-sd').value,
          end_date: document.getElementById('f-ed').value
        }).then(function () { toast('促销已创建'); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- POS 收银 ---------- */
PAGES.pos = function (main) {
  main.innerHTML = '<h2>POS 收银</h2><div class="grid2">' +
    '<div class="card"><h3>购物车</h3>' +
    '<div class="toolbar"><select id="f-store"></select>' +
    '<select id="f-member"><option value="">散客（无会员）</option></select></div>' +
    '<div id="cart-items"></div>' +
    '<div class="toolbar"><button class="btn sm ghost" id="btn-add">＋ 扫码/选商品</button>' +
    '<button class="btn" id="btn-pay">结账</button></div>' +
    '<div id="cart-sum" class="pos-sum"></div></div>' +
    '<div class="card"><h3>最近销售</h3><div id="recent">加载中…</div></div></div>';
  Promise.all([GET('/api/stores'), GET('/api/members'), GET('/api/commodities')]).then(function (rs) {
    document.getElementById('f-store').innerHTML = rs[0].data.items.map(function (s) {
      return '<option value="' + s.id + '">' + esc(s.name) + '</option>';
    }).join('');
    document.getElementById('f-member').innerHTML += rs[1].data.items.map(function (m) {
      return '<option value="' + m.id + '">' + esc(m.name) + '（' + esc(m.code) + ' ' + (LEVEL_TAG[m.level] || [m.level])[0] + '）</option>';
    }).join('');
    window._POS_COMMODITIES = rs[2].data.items || [];
    var n = 0;
    function addRow(pre) {
      n++;
      document.getElementById('cart-items').insertAdjacentHTML('beforeend',
        '<div class="fld-row" data-row="' + n + '">' +
        '<select class="i-comm">' + _POS_COMMODITIES.map(function (c) {
          return '<option value="' + c.id + '" data-price="' + c.price_cents + '">' +
            esc(c.name) + ' ' + fmtCents(c.price_cents) + '</option>';
        }).join('') + '</select>' +
        '<input class="i-qty" type="number" value="' + (pre && pre.qty || 1) + '" min="1" style="width:70px">' +
        '<button class="btn sm ghost" onclick="this.parentNode.remove()">✕</button></div>');
    }
    addRow();
    window._posAddRow = addRow;
    document.getElementById('btn-add').onclick = function () { addRow(); };
    document.getElementById('btn-pay').onclick = function () {
      var items = [];
      document.querySelectorAll('#cart-items .fld-row').forEach(function (row) {
        items.push({
          commodity_id: Number(row.querySelector('.i-comm').value),
          qty: Number(row.querySelector('.i-qty').value || 1)
        });
      });
      if (!items.length) return toast('购物车为空', true);
      var mv = document.getElementById('f-member').value;
      modal('<h3>结账</h3>' +
        field('支付方式', '<select id="f-pay"><option value="cash">现金</option><option value="wechat">微信</option>' +
          '<option value="alipay">支付宝</option><option value="balance">储值余额</option></select>') +
        field('实收金额(元)', '<input id="f-recv" type="number" step="0.01" placeholder="现金收的可填收款额">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">确认收款</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        var recv = document.getElementById('f-recv').value;
        POST('/api/sales', {
          store_id: Number(document.getElementById('f-store').value),
          member_id: mv ? Number(mv) : null,
          items: items,
          pay_method: document.getElementById('f-pay').value,
          received_cents: recv ? Math.round(Number(recv) * 100) : undefined
        }).then(function (r2) {
          var d = r2.data;
          toast('收款成功 ' + d.no + '，实收 ' + fmtCents(d.paid_cents) +
            (d.points_earned ? '，积分 +' + d.points_earned : '') +
            (d.change_cents ? '，找零 ' + fmtCents(d.change_cents) : ''));
          closeModal();
          document.getElementById('cart-items').innerHTML = '';
          n = 0; addRow();
          go('pos');
        }).catch(function (e) { toast(e.message, true); });
      };
    };
    return GET('/api/sales').then(function (r3) {
      document.getElementById('recent').innerHTML = table(
        ['单号', '~实收', '支付', '状态'], (r3.data.items || []).slice(0, 6), function (x) {
          return '<tr><td>' + esc(x.no) + '</td><td class="num">' + fmtCents(x.paid_cents) + '</td>' +
            '<td>' + payTag(x.pay_method) + '</td><td>' + saleTag(x.status) + '</td></tr>';
        });
    });
  });
};

/* ---------- 销售单据 ---------- */
PAGES.sales = function (main) {
  main.innerHTML = '<h2>销售单据</h2><div class="toolbar">' +
    '<select id="f-status"><option value="">全部状态</option><option value="paid">已支付</option><option value="refunded">已退货</option></select>' +
    '<button class="btn ghost" id="btn-filter">筛选</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/sales', 'sales.csv'); };
  function load(st) {
    GET('/api/sales' + qs({status: st})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['单号', '时间', '~小计', '~促销优惠', '~会员优惠', '~实收', '支付', '状态', '操作'], r.data.items, function (x) {
          var ops = (perm('retail.sales.write') && x.status === 'paid')
            ? '<button class="btn sm ghost" data-ref="' + x.id + '">退货</button>' : '—';
          return '<tr><td>' + esc(x.no) + '</td><td>' + esc(x.created_at) + '</td>' +
            '<td class="num">' + fmtCents(x.subtotal_cents) + '</td>' +
            '<td class="num">' + (x.promo_off_cents ? '−' + fmtCents(x.promo_off_cents) : '—') + '</td>' +
            '<td class="num">' + (x.member_off_cents ? '−' + fmtCents(x.member_off_cents) : '—') + '</td>' +
            '<td class="num"><b>' + fmtCents(x.paid_cents) + '</b></td>' +
            '<td>' + payTag(x.pay_method) + '</td><td>' + saleTag(x.status) + '</td>' +
            '<td class="ops">' + ops + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-ref')) return;
        var id = b.getAttribute('data-ref');
        if (!confirm('确认退货？库存回补、积分冲减、退款走负流水。')) return;
        POST('/api/sales/' + id + '/refund', {}).then(function (r2) {
          toast('退货成功：' + r2.data.refund_no + '，退款 ' + fmtCents(r2.data.refund_cents));
          load(document.getElementById('f-status').value);
        }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  document.getElementById('btn-filter').onclick = function () { load(document.getElementById('f-status').value); };
  load();
};

/* ---------- 库存管理 ---------- */
PAGES.inventory = function (main) {
  main.innerHTML = '<h2>库存管理</h2><div class="toolbar">' +
    '<select id="f-store"><option value="">全部门店</option></select>' +
    '<input id="f-kw" placeholder="商品名称" class="inp">' +
    '<button class="btn ghost" id="btn-search">搜索</button>' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/inventory', 'inventory.csv'); };
  GET('/api/stores').then(function (r) {
    document.getElementById('f-store').innerHTML += r.data.items.map(function (s) {
      return '<option value="' + s.id + '">' + esc(s.name) + '</option>';
    }).join('');
  });
  function load(sid, kw) {
    GET('/api/inventory' + qs({store_id: sid, keyword: kw})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['商品', 'SKU', '门店', '批次', '~数量', '效期', '状态'], r.data.items, function (x) {
          var expSoon = x.expire_at && (new Date(x.expire_at) - new Date()) < 90 * 86400000;
          return '<tr><td>' + esc(x.commodity_name || x.commodity_id) + '</td><td>' + esc(x.sku || '') + '</td>' +
            '<td>' + tag('门店 #' + x.store_id, '') + '</td><td>' + esc(x.batch_no) + '</td>' +
            '<td class="num">' + x.qty + '</td><td>' + esc(x.expire_at || '—') + '</td>' +
            '<td>' + (expSoon ? tag('临期', 'warn') : tag('正常', 'ok')) + '</td></tr>';
        });
    });
  }
  document.getElementById('btn-search').onclick = function () {
    load(document.getElementById('f-store').value, document.getElementById('f-kw').value.trim());
  };
  load();
};

/* ---------- 采购管理 ---------- */
PAGES.purchase = function (main) {
  main.innerHTML = '<h2>采购管理</h2><div class="toolbar">' +
    (perm('retail.purchases.write') ? '<button class="btn" id="btn-new">新建采购单</button>' : '') +
    '<select id="f-status"><option value="">全部状态</option><option value="draft">草稿</option>' +
    '<option value="submitted">已提交</option><option value="received">已入库</option></select>' +
    '<button class="btn ghost" id="btn-filter">筛选</button></div><div id="list"></div>';
  function actBtn(x) {
    if (!perm('retail.purchases.write')) return '—';
    var m = {'draft': [['to_submitted', '提交']],
             'submitted': [['to_received', '入库确认']]};
    return (m[x.status] || []).map(function (a) {
      return '<button class="btn sm ghost" data-id="' + x.id + '" data-act="' + a[0] + '">' + a[1] + '</button>';
    }).join(' ') || '—';
  }
  function load(st) {
    GET('/api/purchases' + qs({status: st})).then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['采购单号', '时间', '供应商', '~金额', '状态', '操作'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.no) + '</td><td>' + esc(x.created_at) + '</td>' +
            '<td>' + esc((x.supplier || {}).name || '') + '</td>' +
            '<td class="num">' + fmtCents(x.total_cents) + '</td><td>' + poTag(x.status) + '</td>' +
            '<td class="ops">' + actBtn(x) + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b) return;
        POST('/api/purchases/' + b.getAttribute('data-id') + '/transition', {action: b.getAttribute('data-act')})
          .then(function (r2) {
            toast(r2.data.status === 'received' ? '入库成功，库存与应付已更新' : '操作成功');
            load(document.getElementById('f-status').value);
          }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  document.getElementById('btn-filter').onclick = function () { load(document.getElementById('f-status').value); };
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      Promise.all([GET('/api/suppliers'), GET('/api/stores'), GET('/api/commodities')]).then(function (rs) {
        var comms = rs[2].data.items;
        modal('<h3>新建采购单</h3>' +
          field('供应商', '<select id="f-sup">' + rs[0].data.items.map(function (s) {
            return '<option value="' + s.id + '">' + esc(s.name) + '</option>';
          }).join('') + '</select>') +
          field('入库门店', '<select id="f-store">' + rs[1].data.items.map(function (s) {
            return '<option value="' + s.id + '">' + esc(s.name) + '</option>';
          }).join('') + '</select>') +
          '<div id="po-items"></div>' +
          '<div class="toolbar"><button class="btn sm ghost" id="btn-add-item">＋ 添加明细</button></div>' +
          '<div class="m-foot"><button class="btn" id="btn-ok">保存采购单</button>' +
          '<button class="btn ghost" onclick="closeModal()">取消</button></div>', true);
        var n = 0;
        function addItem() {
          n++;
          document.getElementById('po-items').insertAdjacentHTML('beforeend',
            '<div class="fld-row" data-row="' + n + '">' +
            '<select class="i-comm">' + comms.map(function (c) {
              return '<option value="' + c.id + '">' + esc(c.name) + '</option>';
            }).join('') + '</select>' +
            '<input class="i-qty" type="number" value="10" min="1" placeholder="数量" style="width:70px">' +
            '<input class="i-cost" type="number" placeholder="进价(分)" style="width:90px">' +
            '<input class="i-batch" placeholder="批次" style="width:110px">' +
            '<input class="i-exp" type="date" style="width:140px">' +
            '</div>');
        }
        addItem();
        document.getElementById('btn-add-item').onclick = addItem;
        document.getElementById('btn-ok').onclick = function () {
          var items = [];
          document.querySelectorAll('#po-items .fld-row').forEach(function (row) {
            items.push({
              commodity_id: Number(row.querySelector('.i-comm').value),
              qty: Number(row.querySelector('.i-qty').value || 1),
              cost_cents: Number(row.querySelector('.i-cost').value || 0),
              batch_no: row.querySelector('.i-batch').value.trim() || null,
              expiry: row.querySelector('.i-exp').value || null
            });
          });
          POST('/api/purchases', {
            supplier_id: Number(document.getElementById('f-sup').value),
            store_id: Number(document.getElementById('f-store').value),
            items: items
          }).then(function (r2) {
            toast('采购单已创建：' + r2.data.no);
            closeModal(); load();
          }).catch(function (e) { toast(e.message, true); });
        };
      });
    };
  load();
};

/* ---------- 供应商 ---------- */
PAGES.supplier = function (main) {
  main.innerHTML = '<h2>供应商管理</h2><div class="toolbar">' +
    (perm('retail.suppliers.write') ? '<button class="btn" id="btn-new">新增供应商</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/suppliers').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['名称', '联系人', '电话', '~账期(天)', '~应付金额', '~欠款上限'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.contact || '—') + '</td>' +
            '<td>' + esc(x.phone || '—') + '</td><td class="num">' + x.credit_days + '</td>' +
            '<td class="num">' + fmtCents(x.payable_cents) + '</td>' +
            '<td class="num">' + fmtCents(x.debt_limit_cents) + '</td></tr>';
        });
    });
  }
  if (document.getElementById('btn-new'))
    document.getElementById('btn-new').onclick = function () {
      modal('<h3>新增供应商</h3>' +
        field('名称', '<input id="f-name">') +
        field('联系人', '<input id="f-contact">') +
        field('电话', '<input id="f-phone">') +
        field('账期(天)', '<input id="f-days" type="number" value="30">') +
        field('欠款上限(元)', '<input id="f-debt" type="number" value="50000">') +
        '<div class="m-foot"><button class="btn" id="btn-ok">保存</button>' +
        '<button class="btn ghost" onclick="closeModal()">取消</button></div>');
      document.getElementById('btn-ok').onclick = function () {
        POST('/api/suppliers', {
          name: document.getElementById('f-name').value.trim(),
          contact: document.getElementById('f-contact').value.trim(),
          phone: document.getElementById('f-phone').value.trim(),
          credit_days: Number(document.getElementById('f-days').value || 30),
          debt_limit_cents: Math.round(Number(document.getElementById('f-debt').value || 0) * 100)
        }).then(function () { toast('已保存'); closeModal(); load(); })
          .catch(function (e) { toast(e.message, true); });
      };
    };
  load();
};

/* ---------- 财务流水 ---------- */
PAGES.finance = function (main) {
  main.innerHTML = '<h2>财务流水</h2><div class="toolbar">' +
    '<button class="btn ghost" id="btn-export">导出 CSV</button></div><div id="sum"></div><div id="list"></div>';
  document.getElementById('btn-export').onclick = function () { dl('/api/export/transactions', 'transactions.csv'); };
  Promise.all([GET('/api/finance/summary'), GET('/api/transactions')]).then(function (rs) {
    var s = rs[0].data, items = rs[1].data.items;
    var methods = Object.keys(s.by_method || {}).map(function (m) {
      return kpi(fmtCents(s.by_method[m]), '今日·' + m);
    }).join('');
    document.getElementById('sum').innerHTML = '<div class="kpis">' +
      kpi(fmtCents(s.income_cents), '今日收入', 'ok') +
      kpi(fmtCents(s.refund_cents), '今日退款', 'err') +
      kpi(s.sale_count, '销售单') +
      kpi(s.member_new, '新增会员') + methods + '</div>';
    var TT = {'income': ['收入', 'ok'], 'expense': ['采购', 'warn'], 'refund': ['退款', 'err']};
    document.getElementById('list').innerHTML = table(
      ['时间', '类型', '~金额', '方式', '备注'], items, function (x) {
        var t = TT[x.ttype] || [x.ttype, ''];
        return '<tr><td>' + esc(x.created_at) + '</td><td>' + tag(t[0], t[1]) + '</td>' +
          '<td class="num">' + fmtCents(x.amount_cents) + '</td><td>' + esc(x.pay_method || '—') + '</td>' +
          '<td>' + esc(x.note || '') + '</td></tr>';
      });
  });
};

/* ---------- 风险预警 ---------- */
PAGES.risk = function (main) {
  main.innerHTML = '<h2>风险预警</h2><div class="toolbar">' +
    (perm('retail.risk.write') ? '<button class="btn" id="btn-scan">立即扫描</button>' : '') +
    '</div><div id="list"></div>';
  function load() {
    GET('/api/risks').then(function (r) {
      document.getElementById('list').innerHTML = table(
        ['类型', '标题', '详情', '~评分', '等级', '状态', '操作'], r.data.items, function (x) {
          var ops = '';
          if (perm('retail.risk.write') && x.status === 'open')
            ops = '<button class="btn sm ghost" data-res="' + x.id + '">处理</button>';
          var rt = {'stock_low': '商品低库存', 'expiry_near': '效期预警', 'negative_margin': '负毛利',
                    'supplier_overdue': '欠款超限'}[x.rtype] || x.rtype;
          return '<tr><td>' + esc(rt) + '</td><td>' + esc(x.title) + '</td><td>' + esc(x.detail || '') + '</td>' +
            '<td class="num">' + x.score + '</td><td>' + levelTag(x.grade) + '</td>' +
            '<td>' + tag(x.status === 'open' ? '未处理' : '已处理', x.status === 'open' ? 'err' : 'ok') + '</td>' +
            '<td class="ops">' + (ops || '—') + '</td></tr>';
        });
      document.getElementById('list').onclick = function (e) {
        var b = e.target.closest('button'); if (!b || !b.getAttribute('data-res')) return;
        PUT('/api/risks/' + b.getAttribute('data-res') + '/resolve', {note: '已人工处理'})
          .then(function () { toast('已处理'); load(); }).catch(function (e2) { toast(e2.message, true); });
      };
    });
  }
  if (document.getElementById('btn-scan'))
    document.getElementById('btn-scan').onclick = function () {
      POST('/api/risks/scan', {}).then(function (r) {
        toast('扫描完成，新增 ' + r.data.created + ' 条'); load();
      }).catch(function (e) { toast(e.message, true); });
    };
  load();
};

/* ---------- 系统管理 ---------- */
PAGES.system = function (main) {
  main.innerHTML = '<h2>系统管理</h2><div class="grid2">' +
    '<div class="card"><h3>用户</h3><div id="users">加载中…</div></div>' +
    '<div class="card"><h3>公告</h3><div id="notices">加载中…</div></div>' +
    (perm('*') ? '<div class="card"><h3>API Key（对接外部系统）</h3><div id="keys">加载中…</div></div>' +
      '<div class="card"><h3>增量同步状态</h3><div id="sync">加载中…</div></div>' : '') +
    '</div>';
  GET('/api/users').then(function (r) {
    document.getElementById('users').innerHTML = table(
      ['用户名', '姓名', '角色'], r.data.items, function (x) {
        return '<tr><td>' + esc(x.username) + '</td><td>' + esc(x.name || '') + '</td><td>' + esc(x.role) + '</td></tr>';
      });
  }).catch(function () { document.getElementById('users').innerHTML = '<div class="empty">无权限</div>'; });
  GET('/api/notices').then(function (r) {
    document.getElementById('notices').innerHTML = (r.data.items || []).map(function (n) {
      return '<p><b>' + esc(n.title) + '</b><br>' + esc(n.content || '') + '</p>';
    }).join('') || '<div class="empty">暂无</div>';
  });
  if (perm('*')) {
    GET('/api/api-keys').then(function (r) {
      document.getElementById('keys').innerHTML =
        '<div class="toolbar"><button class="btn sm" id="btn-key">生成 Key</button></div>' +
        table(['名称', '前缀', '权限', '最近使用'], r.data.items, function (x) {
          return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.prefix || '') + '</td>' +
            '<td>' + esc(x.perms) + '</td><td>' + esc(x.last_used || '—') + '</td></tr>';
        });
      document.getElementById('btn-key').onclick = function () {
        POST('/api/api-keys', {name: '外部对接-' + Date.now() % 10000}).then(function (r2) {
          modal('<h3>API Key 已生成（仅显示一次）</h3><p class="key-line">' + esc(r2.data.key) + '</p>' +
            '<div class="m-foot"><button class="btn" onclick="closeModal()">我已保存</button></div>');
        });
      };
    });
    GET('/api/sync?since=0&entities=commodities').then(function (r) {
      var d = r.data || {};
      document.getElementById('sync').innerHTML =
        '<p>同步版本：<b>' + (d.version || 0) + '</b>，本轮变更 <b>' + (d.changes || []).length + '</b> 条</p>' +
        '<p>支持实体：stores / commodities / members / promotions / sales / inventory / purchases / risks</p>';
    });
  }
};
