# 参与贡献

欢迎 Issue、Discussion 和 PR,中英文都可以。小改动不需要完美——测试全绿就发上来,格式细节可以在 review 里一起磨。

## 环境

Python ≥3.10,零强制依赖。clone 后直接:

```bash
python3 -m unittest discover tests    # 70 用例应全绿
python3 evaluation/run_eval.py        # 27 链评测应为全 1.0000
```

## 加一个新框架 target(最小路径)

转换引擎以 `converter/ir.py` 的 **AgentIR** 为枢纽,新增一个框架只需要一对函数(契约详见 [INTERFACE.md](INTERFACE.md)):

1. `converter/emitters/<fmt>.py` — `emit_<fmt>(ir: AgentIR, out_dir) -> Path`,IR → 框架格式;
2. `converter/parsers/<fmt>.py` — `parse_<fmt>(path) -> AgentIR`,框架格式 → IR(best-effort,容错第三方真实输入);
3. 在 `emitters/__init__.py`、`parsers/__init__.py` 注册,`ir.py` 的 `TARGET_FORMATS` 加名字;
4. `tests/` 加用例:产物断言 + emit→parse→write_skill→load_skill roundtrip(knowledge 文件名与内容一致);
5. (欢迎)`llm-wiki/03-frameworks/<fmt>.md` 写一章:最小示例 / 字段表 / IR 映射 / 有损点。

roundtrip 保真是硬约束:新链路的 name / description / system_prompt / knowledge 应做到归一化后一致(参考 `evaluation/run_eval.py` 的指标)。

## llm-wiki 维护

wiki 是只读知识库(MANIFEST.sha256 保护)。修改三步:

```bash
chmod -R u+w llm-wiki/
# …编辑章节…
python3 -c "from converter.wiki import Wiki; from pathlib import Path; Path('llm-wiki/MANIFEST.sha256').write_text(Wiki('llm-wiki').build_manifest(), encoding='utf-8')"
chmod -R a-w llm-wiki/ && python3 cli.py wiki verify
```

## PR 自检清单

- [ ] `python3 -m unittest discover tests` 全绿
- [ ] `python3 evaluation/run_eval.py` 无回归(新增格式需纳入矩阵)
- [ ] `python3 cli.py wiki verify` 通过(若改了 wiki)
- [ ] 密钥/本机路径不入库(测试只读环境变量)
