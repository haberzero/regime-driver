# 库存 / 定价 / 订单子系统 重构设计定稿

## 0. 结论摘要
- 折扣体系：选「策略函数注入」，否决「数据驱动规则表」。
- 异常集：统一继承 `InventoryError`，含任务要求的四个异常，另新增 `InvalidPriceError`（缺陷 4 需要价格校验，四个既有异常均不适合表达"价格非法"）。
- 原子性：`place_order` 先解析定价与校验全部库存，再统一扣减；扣减中途失败按已扣行回滚 `restock`。
- 有意的语义变更（任务重新定义了 API）：`make_order`/`Inventory.price_of` 等旧名移除；`restock`/`take` 对未知 SKU 抛 `UnknownSKUError`（不再隐式创建）。

## 1. 分层结构
- `errors.py` —— 唯一异常定义处，所有领域异常继承 `InventoryError`，均带 `message` 与结构化字段。
- `inventory.py` —— 库存域：`Inventory` 只负责 SKU 名称与数量，不含价格（价格归属 pricing 域）。
- `pricing.py` —— 定价域：`PriceCatalog` 维护价格表与折扣策略。
- `orders.py` —— 订单域：`OrderLine` / `Order` / `place_order`，依赖 `pricing` + `inventory`，做编排与事务。
- 依赖方向：errors ← inventory / pricing ← orders。inventory 与 pricing 互不依赖。

## 2. 折扣体系选型（必须书面定稿）
### 方案 A：策略函数注入（chosen）
调用方通过 `PriceCatalog.register_coupon(code, strategy)` 注册任意策略函数，`discounted_price(sku, qty, coupon_code)` 按 `strategy(base_subtotal)` 计算折后金额。
- 理由：
  1. 满减 / 打折都可自然表达为"子总金额 → 折后金额"的纯函数（满减=门槛条件减法，打折=乘系数），语义直接。
  2. 折扣本质是业务规则，代码即配置：复杂/非线性/叠加策略无需改动定价模块结构。
  3. 定价域与业务解耦：新增券 = 调用方新增一个函数，无需 schema/枚举/校验扩展。
  4. 可测试性：策略为纯函数，`discounted_price` 结果可精确断言（round 2 位）。
- 被否方案理由（方案 B：数据驱动规则表）：规则表需要为"满减/打折二选一"引入类型枚举、阈值/系数字段与校验逻辑，schema 一旦确定难以覆盖门槛、阶梯、按类目等复杂策略；规则与执行散落两处，新增规则要改表结构或加字段，违背"折扣可配置且由调用方注册"的意图。数据驱动适合静态可穷举的规则集，而本子系统希望策略完全由调用方扩展。

## 3. 异常集
统一基类 `InventoryError(Exception)`。结构化字段：
- `UnknownSKUError(sku)`
- `InsufficientStockError(sku, requested, available)`
- `InvalidQuantityError(sku, quantity)`
- `InvalidCouponError(coupon_code)`
- `InvalidPriceError(sku, price)` —— 新增：缺陷 4 要求价格<=0 或非数字必须抛错；`InvalidQuantityError` 语义指数量，用其表达价格会误导调用方，故新增专门异常（仍继承统一基类）。

## 4. 原子性方案
`place_order(catalog, inventory, lines)`：
1. 逐行 `catalog.price_of(sku)` 取单价并构造 `OrderLine`（未知 SKU → `UnknownSKUError`；非法数量 → `InvalidQuantityError`）。此阶段不触碰库存 → 从根因上消灭"先扣库存再定价导致 None*int 崩溃"的缺陷 2 窗口。
2. 逐行校验 `inventory.stock_level` 充足性（不足 → `InsufficientStockError`），全部通过才进入扣减 → 部分失败时无任何扣减。
3. 统一扣减 `inventory.take`；`take` 内部加锁为原子操作。若因并发竞态中途 `take` 失败，对已扣行按逆序 `restock` 回滚后重新抛出 → 任何失败必回滚，保证原子性。
4. 返回 `Order`，`Order.total` 由行数据求和，绝不再次读取/修改库存（消除缺陷 5 的重复扣减）。

## 5. 并发
`Inventory` 以单把 `threading.Lock` 保护数量读写（restock/take/stock_level 均加锁），保证并发 `restock`/`take` 不丢库存。

## 6. 缺陷修复对照
1. 名称更新：`add_item(sku, name)` 对已存在 SKU 也更新名称（并新增 `name_of`）。
2. 先扣后算崩溃：见第 4 节，定价先于扣减，且扣减失败可回滚。
3. `restock` 负数：抛 `InvalidQuantityError`。
4. 价格/数量校验：`set_price`/`OrderLine` 校验价格，restock/take/OrderLine 校验数量。
5. 重复扣库存：库存只在 `place_order` 阶段扣一次，`Order.total` 纯计算。

## 7. 技术债
- 金额用浮点 + `round(x, 2)`；生产应换 `Decimal`。
- `place_order` 的校验与扣减之间存在竞态窗口（靠回滚兜底），高并发下可用事务锁或 WMS 行锁改进。
- 折扣按"行"计算，未实现"整单级"满减语义；如需整单优惠需在 `Order` 层再做一次聚合。
- `Inventory.add_item(sku, name)` 刻意保持宽松（不校验 sku/name 类型，沿用旧语义"接受任意标识"）；既有异常集无贴合"名称/SKU 格式非法"的异常，若需收紧可新增 `InvalidSKUError` 或改抛 `ValueError`（待决）。
