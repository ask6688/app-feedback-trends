# 使用指南

[返回项目首页](../README.md) · [导入数据](#导入自己的数据) · [自定义 Topic](#自定义-topic) · [指标与结果](#指标与结果)

以下命令在仓库根目录、已激活的 Python 环境中运行。初次安装与人工 Demo 见首页的「运行与配置」。每组数据使用独立的 `--data-dir`；不传 `--profile` 时使用默认媒体 preset。

## 导入自己的数据

市场反馈最小表头（[完整人工示例](../examples/media-ios.csv)）：

```csv
comment_date,star,content,author
2025-01-01,5,视频播放很流畅,synthetic-a
2025-01-02,2,视频无法播放,synthetic-b
```

日期使用 `YYYY-MM-DD`；星级 1–5 或留空；`content` 是实际分类正文。作者可省略，有作者时能更准确识别同一评论的平台删除标记或开发者回复变体。标题不会参与分类。支持常见中文表头及 `date/rating/text/author` 等别名，字段解析见 [importer](../trendlib/importer.py)。不支持旧 `.xls`，请另存为 XLSX 或 CSV。

```sh
python trends.py preview --data-dir outputs/my-app \
  --ios inputs/ios.csv --android inputs/OPPO.csv
# 阅读 outputs/my-app/preview.json：新增、已有、变更、歧义和解析告警
python trends.py apply --data-dir outputs/my-app
python trends.py serve --data-dir outputs/my-app
```

`inputs/` 和 `outputs/` 均不进入版本控制。Android 当前沿用常见媒体 preset 的市场识别：OPPO、VIVO、华为、小米、魅族，可从 `channel` 列、文件名或表名识别。其他 Android 来源按未指定渠道归集；平台维度为 IOS / AND，不是任意数据源适配器。

客服可选，表头 `period,conversation`；区间写为 `2025-01-01~2025-01-07`，完整示例见 [support.csv](../examples/support.csv)。有角色前缀时提取 `用户：` 发言，无该前缀时使用整段对话。

```sh
python trends.py preview --data-dir outputs/my-app --cs inputs/support.csv \
  --cs-time-mode overlap
python trends.py apply --data-dir outputs/my-app
```

`--cs-time-mode auto` 保留旧规则：输入仅一个日期区间时按批次截止标签识别，匹配忽略时间；多个区间则要求时间重叠。确定区间表示实际发生时间时显式用 `overlap`。

### 增量与安全提交

- 先预览，再执行 `apply`。已有记录不重分类；变更候选与有损导出的歧义记录留在预览中，**不会自动覆盖或累计**，需要人工处理源数据。
- 去重沿用多重集逻辑，不是简单 `set(text)`：匿名同文多条仍可保留，显式同作者的平台文本变体有单独规则。
- 两类历史统一写入 `history.json`，报告成功后才原子提交。失败保留原历史与既有报告；过期预览拒绝提交。
- 每个数据目录只能有一个写入进程。异常退出遗留 `.lock` 时，确认进程已停止再移除锁文件。
- Profile 在首批数据后固定：修改名称、顺序、规则或启用状态时用新的 `--data-dir`，避免历史前后口径混用。不会静默重算历史。

## 自定义 Topic

[commerce.json](../profiles/commerce.json) 是简单电商例子。运行：

```sh
python trends.py preview --data-dir outputs/commerce \
  --profile profiles/commerce.json --ios examples/commerce.csv
python trends.py apply --data-dir outputs/commerce --profile profiles/commerce.json
python trends.py serve --data-dir outputs/commerce --profile profiles/commerce.json
```

它将“支付 / 物流 / 性能”分类并进入月度、周度、近七天与 HTML，看板不依赖五类固定 Topic。

```json
{
  "schema_version": 1,
  "id": "my-product",
  "topics": [
    {
      "key": "payment",
      "name": "支付",
      "matcher": "simple",
      "keywords": ["支付", "扣款"],
      "requires": ["订单"],
      "excludes": ["演示"],
      "enabled": true,
      "order": 0
    }
  ]
}
```

| 字段 | 含义 |
| --- | --- |
| `key` | 唯一内部标识，字母、数字、下划线或连字符 |
| `name` | 展示名与保存的历史标签；唯一纯文本，最长 60 字符 |
| `keywords` | 至少命中一个词 |
| `requires` | 非空时，另需至少命中一个上下文词 |
| `excludes` | 命中任一排除词就排除整条反馈 |
| `enabled` / `order` | 默认启用；控制参与分类与看板排列 |

简单匹配是不区分大小写的子串判断，不使用正则，不推断否定或同义改写；一条反馈可以命中多个 Topic。正面反馈也可以命中。先在小样例验证自己的规则。

复杂规则继续由 Python 内置 matcher 处理，`simple` 与 `builtin` 可在同一 profile 共存。例如 `{"key":"player","name":"播放","matcher":"builtin","builtin":"播放"}`。当前注册的内置 matcher 只有默认五个；添加其他复杂规则需改 Python，不执行配置中的任意代码。

### 默认媒体 preset 与历史兼容

[media.json](../profiles/media.json) 保留五类的中文名称、标签和顺序：**播放 → 风控 → 广告 → 下载 → 网页浏览与搜索**。这只是一个 profile，不是产品能力的固定边界。

[legacy_rules.py](../trendlib/legacy_rules.py) 保留成熟的字符串、正则和上下文排除规则，包括客服与市场的差异。召回只提供线索，最终判断逐个 Topic 执行；不要求负面反馈。此 preset 保持已有标签、去重与指标口径，兼容范围见 [公开范围说明](PUBLIC_SCOPE.md)。

可将自己的旧格式 `classification.json` / `classification_cs.json` 导入**新目录**：

```sh
python trends.py adopt-history --data-dir outputs/migrated \
  --market inputs/classification.json --cs inputs/classification_cs.json
```

此命令验证结构并保留原记录、标签、ID，不重分类，不改变源文件。仅接受选定 profile 内的标签。不要将真实历史库放进仓库。

## 指标与结果

- 市场 Topic 反馈占比 = 命中该 Topic 的评论数 / 同期全量市场评论数。
- Topic 差评反馈占比 = 命中该 Topic 且星级 ≤ 3 的评论数 / 同期全量市场评论数；不是 Topic 内部差评比例。
- 全市场差评率 = 同期星级 ≤ 3 的评论数 / 同期全量评论数。无星级记录保留在全量分母中。
- IOS / AND 合并先加分子分母，再计算比例；不平均两端比例。多标签 Topic 的占比相加可超过 100%。
- 月度覆盖完整历史；周度沿用最新日期往前三个日历月的周一至周日窗口，首周从窗口起点所在周的周一开始，可能早于窗口起点；近七天截至**数据最新日期**，不是系统今天。
- “完整周期”依据数据的首尾日期边界判断，不保证每天均有观测或来源覆盖。部分周期会标记。客服按 `(文件名, 起始日, 结束日)` 批次聚合，重叠批次不折算自然周。

`outputs/<dataset>/history.json` 是累计历史；`preview.json` 是本次增量候选。每次报告存到 `reports/<revision>-<id>/`，包含：

```text
report.html + assets/details.js + assets/details_cs.js
classification.json + classification_cs.json
monthly_metrics.json / .csv + weekly_metrics.json / .csv
audit.json + profile.json
scripts/{metrics_meta,cs_metrics,star_metrics,audit_raw,raw_records}.json
```

真正给人看的成果是 `report.html`。复制或分享报告时需带上 `assets/`。看板的“已解决”标记只保存在当前浏览器 localStorage，按 dataset 隔离；没有多人同步或写回分析库。

