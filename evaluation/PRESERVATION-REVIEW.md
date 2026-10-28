# Preservation Capsule 独立审查

日期：2026-10-29。范围：`converter/preservation.py`、`skill_loader.py`、`skill_writer.py`、CLI 与两侧 registry wrappers。审查不使用外部模型、密钥或真实服务；测试对原生文件和 `native_only=True` 回读断言，避免只读取 capsule 而掩盖运行时投影差异。

**最终结果：本次发现的缺陷全部修复，独立回归 16/16 通过；仓库完整套件运行 171 个测试，结果 OK，1 项 skip。**

## 发现与修复

| 已复现问题 | 最终处理与验证 |
| --- | --- |
| 修改活跃 prompt/name/description 后，旧 source snapshot 覆盖原生 SKILL.md，capsule 却保存新值 | 恢复资源后按活跃字段更新原生投影。三个 skill 目录格式均验证原生字段一致，未知 frontmatter 保留。 |
| 不存在的入口文件被祖先 capsule 掩盖 | 发现 capsule 前校验输入存在；错误入口拒绝。 |
| 缺少 SKILL.md 的 source snapshot 可发布为 skill | 原生 skill 投影明确要求 SKILL.md，缺失时拒绝。 |
| agents/a.yaml 比新生成 openai.yaml 优先，interface 编辑未生效 | 更新 loader 实际读取的来源；清空字段时同时处理后续来源，防止旧值重新出现。 |
| interface 编辑删除 short_description、图标、依赖与扩展配置 | 在原文件中更新对应字段，保留无关配置。 |
| tools 编辑后原生 frontmatter 仍含旧工具契约 | 更新可解析 metadata 的 tools；不透明 metadata 使用显式契约 override，保留原始配置。 |
| knowledge 删除后旧 references 文档重新出现 | 从活跃原生投影移除被明确删除的已识别知识文档，保留原始 provenance。 |
| 0444 只读源文件阻止合法编辑 | 暂存区原子替换内容，并保留原模式；只读 SKILL 合法编辑通过。 |

## 回归覆盖

`tests/test_preservation_edits.py` 使用 stdlib unittest 与临时目录，覆盖：

- `skill`、`crewai-skills`、`deepagents` 的原生 prompt/name/description、interface、知识内容及工具契约编辑；知识删除；多来源 interface 清空。
- 未编辑输入的完整文件集合、原始字节及权限保留。fixture 含 CRLF SKILL/知识文档、unknown frontmatter、二进制 assets 与 0751 脚本；删除源目录后仍可输出。活跃 IR 被明确编辑时，原生投影应用这些编辑，原始 source archive 仍保留 provenance。
- interface 修改保留 short_description、图标与依赖；只读 SKILL 更新后仍为 0444。
- 非空输出目录拒绝且保留原内容；输出 symlink 拒绝且不触及目标；staging 失败保留原有空目录且不留下部分输出。
- capsule 格式不符拒绝；新增 native symlink 拒绝；不存在的入口拒绝。

另独立验证了 generic/n8n 包移动并删除原始 source 后的解析与 verify。原有对抗测试继续覆盖全格式多跳、内容改动、未来 schema 与路径越界。

## 最终复现

```bash
# 独立编辑、目录与符号链接边界：16 个测试通过
python3 -m unittest tests.test_preservation_edits -q

# 完整套件：171 个测试，OK，1 skip
python3 -m unittest discover -s tests -q
```

两张 README SVG 已重新渲染并核对：原生投影与 capsule 并行、完整性验证后回程、显式 native-only 的描述与当前实现一致。SHA-256 的作用是完整性校验，未描述为身份签名或对恶意重写 manifest 的认证保证。
