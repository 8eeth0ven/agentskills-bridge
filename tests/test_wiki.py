"""llm-wiki 只读资产校验(无条件可跑,零第三方依赖)。

wiki 由其它线程产出。校验分级:
- llm-wiki 尚无任何 markdown(未交付)→ 内容级用例 skip;
- 已有 markdown → 每个 *.md 非空、以 # 开头、不含 TODO/FIXME 占位标记
  (行首独立词或后跟冒号;正文词汇性提及不算),严格校验;
- INDEX.md 链接:草稿期(INDEX 含"待编写"章节且无 MANIFEST)允许计划章节
  暂未落盘 → skip;定稿(MANIFEST.sha256 存在或无待编写标记)后严格校验;
- MANIFEST.sha256(若存在)逐行 sha256 校验,不匹配即 fail。
"""

import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "llm-wiki"

LINK_RE = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")
# TODO/FIXME 只按"占位标记"查:行首独立词,或后跟半/全角冒号。
# 正文词汇性提及(如 langchain 章映射表描述 stub 的"函数体 TODO")不算残留。
MARKER_RE = re.compile(r"(?im)^[ \t>-]*(TODO|FIXME)\b|\b(?:TODO|FIXME)\s*[：:]")


def _md_files() -> list:
    if not WIKI.is_dir():
        return []
    return sorted(p for p in WIKI.rglob("*.md") if p.is_file())


class TestWiki(unittest.TestCase):
    def test_wiki_dir_exists(self):
        self.assertTrue(WIKI.is_dir(), "llm-wiki/ 目录应存在")

    def test_markdown_files_wellformed(self):
        files = _md_files()
        if not files:
            self.skipTest("llm-wiki not yet populated")
        for path in files:
            with self.subTest(file=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.strip(), f"{path} 不应为空文件")
                self.assertTrue(
                    text.lstrip().startswith("#"),
                    f"{path} 应以 # 标题开头",
                )
                self.assertIsNone(
                    MARKER_RE.search(text),
                    f"{path} 含 TODO/FIXME 占位标记",
                )

    def test_index_exists_and_links_resolve(self):
        files = _md_files()
        indexes = sorted(WIKI.rglob("INDEX.md")) if WIKI.is_dir() else []
        if not files and not indexes:
            self.skipTest("llm-wiki not yet populated")
        self.assertTrue(indexes, "wiki 有内容时 INDEX.md 必须存在")
        index = indexes[0]
        text = index.read_text(encoding="utf-8")
        manifests = sorted(WIKI.rglob("MANIFEST.sha256"))
        # 草稿期(INDEX 仍含"待编写"章节且无 MANIFEST 清单)允许指向尚未落盘的
        # 计划章节;wiki 定稿(MANIFEST 存在或无待编写标记)后链接必须全部可达。
        draft = ("待编写" in text) and (not manifests)
        if draft:
            missing = [
                m.group(1)
                for m in LINK_RE.finditer(text)
                if "http" not in m.group(1)
                and not m.group(1).startswith(("#", "mailto:"))
                and not (index.parent / m.group(1)).resolve().exists()
            ]
            self.skipTest(
                f"wiki draft (待编写章节未落盘,无 MANIFEST): {len(missing)} 个链接暂不可达"
            )
        for match in LINK_RE.finditer(text):
            target = match.group(1)
            if "http" in target or target.startswith("#") or target.startswith("mailto:"):
                continue
            resolved = (index.parent / target).resolve()
            self.assertTrue(
                resolved.exists(),
                f"INDEX.md 链接目标不存在: {target}",
            )

    def test_manifest_sha256_if_present(self):
        manifests = sorted(WIKI.rglob("MANIFEST.sha256")) if WIKI.is_dir() else []
        if not manifests:
            self.skipTest("MANIFEST.sha256 not present")
        manifest = manifests[0]
        base = manifest.parent
        for lineno, line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(), start=1
        ):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            digest, sep, rel = line.partition("  ")
            self.assertTrue(sep == "  " and digest and rel, f"第 {lineno} 行格式应为 '<sha256>␣␣<相对路径>'")
            path = (base / rel).resolve()
            self.assertTrue(path.is_file(), f"MANIFEST 条目文件不存在: {rel}")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(
                actual,
                digest,
                f"sha256 不匹配: {rel}",
            )


if __name__ == "__main__":
    unittest.main()
