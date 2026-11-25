"""Build-time only. Extract the tested, transport-independent v3.3 Gemini/Responses codecs."""
from hashlib import sha256
from pathlib import Path
import sys

UPSTREAM_HASH = "2bb1af12ea7418580bba1720e17ca2335e9bda373e8151097921f0a69c0d4b7f"

def prepare(source, target):
    raw=Path(source).read_bytes()
    if sha256(raw).hexdigest()!=UPSTREAM_HASH:
        raise ValueError("The frozen v3.3 Responses codec has a different hash")
    text=raw.decode("utf-8")
    start=text.index("import { createHash }")
    end=text.index("export function createCodexBackend(")
    output=text[start:end]+"\nexport { events, chunk, finish, outputParts };\n"
    dest=Path(target)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(output,encoding="utf-8",newline="\n")

if __name__=="__main__":
    prepare(*sys.argv[1:])

