import re
import string

_PUNCT = set(string.punctuation)


def normalize_answer(s: str) -> str:
    """MVP 归一化：
    - 去前后空白
    - 统一大小写
    - 将连续空白压缩为单个空格
    - 去除常见标点（保留字母/数字/空格/撇号已统一）

    说明：文档强调“规则优先、完全匹配”，因此这里要稳定、可复现。
    """
    if s is None:
        return ""
    s = s.strip()
    # normalize common apostrophes
    s = s.replace("’", "'").replace("‘", "'").replace("`", "'")
    s = s.lower()

    # remove punctuation except apostrophe and spaces
    cleaned = []
    for ch in s:
        if ch in _PUNCT and ch != "'":
            continue
        cleaned.append(ch)
    s = "".join(cleaned)

    # collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s
