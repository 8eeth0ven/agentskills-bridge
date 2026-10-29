# 参与贡献

欢迎中英文 Issue 与 PR。Python ≥3.10，转换引擎无强制第三方依赖；格式转换无需 API key。

## 验证转换

```bash
python3 cli.py --help
python3 cli.py wiki verify
python3 cli.py skill2agent examples/agent-fullcycle-engineering --target generic --out out/generic
python3 cli.py agent2skill out/generic --from generic --out out/restored
python3 cli.py verify out/generic
```

比较原始 skill 与恢复目录中的普通文件路径、字节和权限。验证产物能独立迁移后，再检查目标框架实际读取的指令、工具与资源；完整 capsule 回读不能替代原生格式验证。

## 添加格式

实现一对原生 parser / emitter，注册到两侧的 `PARSERS` / `EMITTERS` 和 `TARGET_FORMATS`，CLI 自动使用注册格式。公开契约见 [INTERFACE.md](INTERFACE.md)。

分别检查原生字段映射与完整 IR、原始资源恢复，确认损坏或陈旧 capsule 会明确失败。生成的 Python 应通过 AST 等静态方式解析；直接导入外部源文件会执行其中的代码。

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

确认文档承诺与实际能力一致。密钥只通过环境变量注入，不读取固定本地密钥文件；临时产物自动回收，共享文件不记录本机绝对路径。提交内容应只包含产品代码、使用示例、文档及图片。
