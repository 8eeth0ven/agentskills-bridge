# 独立往返保真审计

本轮将两个契约分开验证：**原始资产的可恢复性**与**框架原生产物的实际字段映射**。capsule 可以保存框架无法表达的信息，但不能据此声称某框架原生支持全部工具契约、任意工作流或相同的运行行为。

## 输入与证据

- 审计测试：[tests/test_fidelity_adversarial.py](../tests/test_fidelity_adversarial.py)。所有样本在临时目录生成，不依赖网络或 API key。
- 资产样本包含 11 个文件：CRLF/无末尾换行、未知及嵌套 frontmatter、两份不同子目录的同名 Markdown、JSON reference、嵌套二进制脚本、可执行 shell、二进制 asset、空文件、自定义 agents YAML、根目录 LICENSE。每份恢复结果逐文件比较原始 bytes 与 executable bits。
- 先删除原 skill 源目录，再运行恢复链；跨格式测试甚至先删除源目录才进行第一次 emit，排除依赖原路径补拷文件的假通过。
- 精确保留的比较排除协议目录 `.agentskills-bridge/`；目录中的 manifest/IR 有独立完整性测试。目录自身、时间戳、owner 与 ACL 不在本测试的保留承诺内。
- 固定 seed `0xB21D6E` 生成 1,000 份 Python 字符串，涵盖 NUL、CR/LF、单双引号、反斜杠、中文与 emoji。每份直接 `ast.literal_eval` 解码 emitter 的字符串字面量并与源字符串比较。

## 发现和修复

| 缺陷 | 本轮处理 | 验证路径 |
| --- | --- | --- |
| skill loader 只登记脚本路径、只读一级 Markdown reference，无法独立带走完整技能包 | 原始普通文件 bytes、路径和 mode 进入便携 IR/capsule | load → 删除源目录 → emit → parse → write_skill |
| write_skill 会归一换行、丢未知 frontmatter/资源，扁平化嵌套 reference | 完整包恢复走原始文件契约 | 原树 11 文件与恢复树逐项比较 |
| CrewAI parser 根据 `#` 推测产物来源，headingless prompt 被包装，原生 Markdown backstory 会吞掉 role/goal | emitter 写明确标记；只有标记存在时，backstory 才作为完整指令 | **直接**模块 emitter/parser；无 capsule |
| LangChain 正则截断转义三引号、无法识别普通/带类型注解的字符串常量，错误采信注释或 f-string | AST 只解码模块顶层 literal，保留引号与空字符串；不执行模块 | 原生文件包含顶层 raise，读取仍成功；注释/动态值不冒充 literal |
| Python 字面量未正确处理 NUL、CR 与任意引号组合；展示名可破坏生成的模块语法 | 安全生成字面量，标题/名称/描述安全编码 | AST 语法检查及 1,000 固定随机输入 |
| LangChain 工具 docstring 限制为 2 KB，长 schema 被静默丢弃 | AST 无窗口读取，解码原始 docstring | 600 枚 enum 的 schema 完整回读 |
| 工具/参数名称归一后冲突，布尔 property schema 导致异常 | 确定性去重 Python 标识符，外部工具名保留在 `@tool(name)`，兼容布尔 schema | AST 检查函数及参数无重名，完整 tools 回读 |

原生投影测试导入 `converter.emitters.langchain` / `converter.parsers.langchain` / CrewAI 对应模块函数，**不经过注册表的保真包装器**。因此新增 capsule 不会掩盖这些 native 修复是否有效。

## 复现与结果

```bash
python3 -m unittest tests.test_fidelity_adversarial -v
python3 -m unittest discover tests -q
python3 evaluation/run_native_audit.py --baseline 21ad414 --out evaluation/fidelity-baseline-native.json
```

当前审计含 15 个测试方法。资产层覆盖直写 1 链、11 个单格式链、121 个有序格式对，合计 **133 链**；完整性层覆盖 **44 个** native 文件修改/新增/删除/权限变化组合，以及 IR 损坏、未知协议版本、重算 checksum 后的路径穿越、显式 `native_only=True` 导入。独立 native 层含 1,000 个固定 seed 字符串与额外边界输入。

本轮最终全套结果：**171 个测试方法，170 通过，1 跳过，0 失败**。跳过项来自既有测试的条件分支，不能计为已验证的运行时能力。具体结果应在自己的环境重新运行确认。

基线 `21ad41450556aca49a25870292e4f33ca89e764c` 通过 `git archive` 解包到独立临时目录，只替换测试文件，转换器保持原样。在相同 8 个 native 测试方法下，旧版出现 **66 个失败 subcase 与 895 个错误 subcase**，当前为 0/0；这不是 961 个独立生产故障，主要数量来自同一字符串生成缺陷在固定 fuzz 语料中的重复触发。摘要见 [fidelity-baseline-native.json](fidelity-baseline-native.json)，复现脚本会重新计算两侧结果。

## 适用边界

这些结果证明该语料及测试覆盖中的完整普通文件可恢复、损坏/陈旧 capsule 会被拒绝，以及特定 native 字段映射已修复。它们不证明所有第三方工程都能完整导入，也不证明转换后的工具 stub 具有真实后端、所有工作流都可在目标引擎等价运行，或真实模型输出恒等。SHA-256 用于完整性检查，不能认证来源；完整包包含技能原始文件，分享前应按原始资料的可分享范围处理。

本报告没有测量所有开源转换器，不能据此宣称“开源第一”。可对外突出已复现的 **11 格式、多跳、源目录删除后仍可恢复的逐字节资产往返**，同时保留上述契约边界。
