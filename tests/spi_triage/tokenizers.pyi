# Reviewed typed surface for the pinned `tokenizers==0.22.2` library.
# The deployed tokenizer assets are digest-pinned by `local_token_counter.py`;
# this stub declares only the reviewed calls that module makes, and ships no
# runtime code (the native library stays a real runtime dependency).

class Encoding:
    # Reviewed encoding result of the native Qwen tokenizer.
    ids: list[int]

class Tokenizer:
    @classmethod
    def from_file(cls, path: str) -> Tokenizer: ...
    def encode(self, sequence: str, add_special_tokens: bool = True) -> Encoding: ...
