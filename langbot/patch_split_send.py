# SPDX-License-Identifier: Apache-2.0
"""Optional LangBot 4.11.4 split-send patch.

Blank paragraphs are split, long paragraphs grouped into up to two sentences.
Replies are sent sequentially, three seconds apart. Only the first quotes the
original message. The adapter call fragment is from LangBot (Apache-2.0).
This public edition requires an explicit target and --apply; it never searches
other installations. Make changes only while the selected LangBot is stopped.
"""
import pathlib
import sys
import argparse

V3_MARK_LINE = "    # === langbot split-send patch v3 (sentence split) ===\n"
MARK3 = "# === langbot split-send patch v4 (sentence split) ==="
V1_MARK_LINE = "    # === langbot split-send patch ===\n"
V2_MARK_LINE = "    # === langbot split-send patch v2 (sentence split) ===\n"
# Only a file explicitly selected by the operator may be patched.

OLD_ELSE = """            else:
                await query.adapter.reply_message(
                    message_source=query.message_event,
                    message=message_chain,
                    quote_origin=quote_origin,
                )
"""

NEW_ELSE = """            else:
                await self._send_segmented(
                    query=query,
                    message_chain=message_chain,
                    quote_origin=quote_origin,
                )
"""

HELPER3 = '''    # === langbot split-send patch v4 (sentence split) ===
    # Pure splitter: never deletes text. Blank paragraphs first, then any
    # paragraph longer than 30 chars with >=2 sentences is split into <=2-sentence
    # messages.
    SPLIT_MIN_CHARS = 30
    SPLIT_MAX_SENTENCES = 2

    @staticmethod
    def _plain_text(message_chain):
        texts = []
        for me in message_chain:
            if isinstance(me, platform_message.Plain):
                texts.append(me.text)
            else:
                return None
        return "".join(texts)

    @staticmethod
    def _sentence_chunks(text):
        import re as _re
        pat = _re.compile(r"[^。！？!?…]*[。！？!?…]+[”’」』]?")
        chunks = []
        start = 0
        for m in pat.finditer(text):
            chunks.append(text[start:m.end()])
            start = m.end()
        if start < len(text):
            if chunks:
                chunks[-1] += text[start:]
            else:
                chunks = [text]
        return chunks

    @classmethod
    def _subsplit_block(cls, block):
        if len(block) <= cls.SPLIT_MIN_CHARS:
            return [block]
        chunks = cls._sentence_chunks(block)
        if len(chunks) < 2:
            return [block]
        groups = []
        current = []
        for chunk in chunks:
            current.append(chunk)
            if len(current) >= cls.SPLIT_MAX_SENTENCES:
                groups.append("".join(current))
                current = []
        if current:
            groups.append("".join(current))
        return groups if groups else [block]

    async def _send_segmented(self, query, message_chain, quote_origin):
        text = self._plain_text(message_chain)
        if text is None or not text.strip():
            await query.adapter.reply_message(
                message_source=query.message_event,
                message=message_chain,
                quote_origin=quote_origin,
            )
            return
        import re as _re
        blocks = [b.strip() for b in _re.split(r"\\n[ \\t]*\\n", text) if b.strip()]
        if not blocks:
            blocks = [text.strip()]
        segments = []
        for block in blocks:
            segments.extend(self._subsplit_block(block))
        for index, segment in enumerate(segments):
            seg_chain = platform_message.MessageChain(
                [platform_message.Plain(text=segment)])
            await query.adapter.reply_message(
                message_source=query.message_event,
                message=seg_chain,
                quote_origin=(quote_origin if index == 0 else False),
            )
            if index < len(segments) - 1:
                await asyncio.sleep(3.0)
'''

ANCHOR = "    async def process(self, query: pipeline_query.Query, stage_inst_name: str) -> entities.StageProcessResult:"


def _strip_old_blocks(src: str) -> str:
    # Remove any previously injected helper block (v1/v2) sitting before ANCHOR.
    for mark_line in (V1_MARK_LINE, V2_MARK_LINE, V3_MARK_LINE):
        pos = src.find(mark_line)
        anchor = src.find(ANCHOR)
        if pos != -1 and anchor != -1 and pos < anchor:
            src = src[:pos] + src[anchor:]
    return src


def patch_file(path: pathlib.Path) -> str:
    src = path.read_text(encoding="utf-8")
    if MARK3 in src:
        return "skip(already-v4)"
    anchor = src.find(ANCHOR)
    if anchor == -1:
        return "skip(anchor-not-found)"
    new_src = _strip_old_blocks(src)
    if OLD_ELSE in new_src:
        new_src = new_src.replace(OLD_ELSE, NEW_ELSE, 1)
    elif NEW_ELSE not in new_src:
        return "skip(old-snippet-not-found)"
    if new_src.find(ANCHOR) == -1:
        return "skip(anchor-lost)"
    new_src = new_src.replace(ANCHOR, HELPER3 + "\n" + ANCHOR, 1)
    if new_src == src:
        return "skip(unchanged)"
    path.write_text(new_src, encoding="utf-8")
    return "patched-v4"


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional split-send patch for LangBot 4.11.4")
    parser.add_argument("--target", type=pathlib.Path, required=True, help="Explicit respback.py file")
    parser.add_argument("--apply", action="store_true", help="Write changes (default: inspect only)")
    args = parser.parse_args()
    target = args.target.resolve()
    if not target.is_file() or target.name != "respback.py":
        parser.error("target must be an existing respback.py")
    if not args.apply:
        print("Inspection only; no file changed. Use --apply after backing up the selected file.")
        return 0
    backup = target.with_name(target.name + ".before-public-split.bak")
    if not backup.exists():
        backup.write_bytes(target.read_bytes())
    print(patch_file(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
