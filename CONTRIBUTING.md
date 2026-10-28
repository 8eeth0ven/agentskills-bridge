# 参与贡献

欢迎中英文 Issue 与 PR。Python ≥3.10，转换引擎无强制第三方依赖；静态与保真测试无需 API key。

## 本地验证

```bash
python3 -m unittest discover tests -q
python3 evaluation/run_eval.py
python3 evaluation/benchmark_preservation.py
python3 cli.py wiki verify
```

严格资源评测逐文件检查 SHA-256、字节数与 POSIX mode，执行前删除源目录。基准结果、输入范围和限制见 [开源对照报告](evaluation/ECOSYSTEM-COMPARISON.md)。合法编辑与完整性回归见 `tests/test_preservation_edits.py`、`tests/test_fidelity_adversarial.py`。

## 添加格式

实现一对原生 parser / emitter，注册到两侧的 `PARSERS` / `EMITTERS` 和 `TARGET_FORMATS`，CLI 自动使用注册格式。公开契约见 [INTERFACE.md](INTERFACE.md)。

为两种性质分别加测试：直接调用模块函数，验证目标真实字段映射；通过公开注册表，验证完整 IR、原始资源以及损坏检测。完整 capsule 回读不应替代原生格式或真实引擎验证。生成的 Python 只能用 AST 等静态方式解析，导入外部源文件会执行其代码。

## 知识库维护

`llm-wiki/` 的清单受 SHA-256 校验。维护者更新章节后，重新生成清单并恢复只读权限：

```bash
chmod -R u+w llm-wiki/
# 编辑需要更新的章节
python3 -c "from converter.wiki import Wiki; from pathlib import Path; Path('llm-wiki/MANIFEST.sha256').write_text(Wiki('llm-wiki').build_manifest(), encoding='utf-8')"
chmod -R a-w llm-wiki/
python3 cli.py wiki verify
```

## 提交前

确认测试通过，文档承诺与实测范围一致。密钥只通过环境变量注入，不读取固定本地密钥文件；临时输出用临时目录，持久化报告不记录本机绝对路径。真实框架、模型、网络与外部语料测试单独记录依赖、版本、样本和跳过原因。
