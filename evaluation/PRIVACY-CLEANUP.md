# 评测脚本隐私与可移植性清理

本次清理范围：`runtime/*.py`、`behavior/probe_behavior.py`、`external/run_external.py`、`schema_diff.py`、`schema_diff_report.md`，以及 `../converter/emitters/langflow.py` 的说明。

- 移除两处自动读取固定密钥文件的实现。真实模型测试只接受调用者明确设置的 `GLM_API_KEY` 等进程环境变量；缺 key 立即 skip。
- 六个 runtime 模块改用每个测试类独立的 `TemporaryDirectory`，通过 class cleanup 回收。GLM LangChain 测试现场生成产物，不再依赖其他本机评测留下的目录。
- 外部语料必须通过 `--corpus-root` 明确指定；临时 subagent 组装写入临时工作区。异常摘要将工程、语料与临时工作区路径替换为通用标签。
- schema 校验不再扫描本机 clone、不指定本机代理。使用 `--official-flow <fixture.json>`、官方 URL 或内置结构摘录；`--offline` 禁止下载。转换产物始终写入临时目录。
- 行为探针临时产物自动清理，API 错误文本中的当前 key 会被遮盖。行为与外部语料脚本支持 `--out-dir`，默认输出到各自的 `latest/`，避免覆盖已有历史证据。
- 历史 schema 报告仅调整本机路径为仓库相对路径或来源描述；历史日期、结果数字没有修改。未保存的历史临时快照明确标为未随仓库提供。

验证结果：

- 12 个相关 Python 文件 `py_compile` 通过。
- 清空 key 环境后，六个 runtime 类均因缺依赖或缺 key skip；没有运行真实模型调用。这些 skip 不代表框架运行时通过。
- 三个 GLM E2E 类在清空进程环境、禁止任何 `Path.read_text` 的条件下立即 skip，确认缺 key 时没有读取本机文件。
- 行为探针无 key 正常 skip；三形态构建离线完成；空外部语料返回 missing-input，未推测本机仓库位置。
- `python3 evaluation/schema_diff.py --offline`：必需级差异 0，仅使用内置结构摘录，未下载官方 fixture。
- `python3 -m unittest discover tests -q`：171 个测试，170 通过、1 跳过、0 失败。

本次没有重跑真实 API 行为评测，也没有据此更新历史行为分数。
