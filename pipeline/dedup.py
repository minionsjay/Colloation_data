"""Near-duplicate detection using MinHash LSH.

Tokens are character trigrams — language-agnostic and handles
minor spelling variations or formatting differences.
"""

from datasketch import MinHash, MinHashLSH

from pipeline.schema import CleanedPost


def text_to_minhash(text: str, num_perm: int = 128) -> MinHash:
    """Convert text to MinHash using character trigrams."""
    m = MinHash(num_perm=num_perm)
    # Character trigrams — works across languages without tokenization
    for i in range(len(text) - 2):
        m.update(text[i : i + 3].encode("utf-8"))
    return m


class DedupIndex:
    """LSH-based near-duplicate index. Thread-safe for single-process use.

    Usage:
        index = DedupIndex()
        for post in posts:
            if index.is_duplicate(post.clean_text):
                post.is_duplicate = True
            else:
                index.add(post)
    """

    def __init__(self, threshold: float = 0.8, num_perm: int = 128):
        self.threshold = threshold
        self.num_perm = num_perm
        self.lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._count = 0

    def _key(self, content_id: str) -> str:
        return content_id

    def is_duplicate(self, text: str) -> bool:
        """Check if text is near-duplicate of any previously added text."""
        if len(text) < 20:
            return False  # too short to meaningfully dedup
        mh = text_to_minhash(text, self.num_perm)
        results = self.lsh.query(mh)
        return len(results) > 0

    def add(self, post: CleanedPost):
        """Add a post to the index."""
        if len(post.clean_text) >= 20:
            mh = text_to_minhash(post.clean_text, self.num_perm)
            self.lsh.insert(self._key(post.content_id), mh)
            self._count += 1

    def dedup_posts(self, posts: list[CleanedPost]) -> list[CleanedPost]:
        """In-place dedup: marks duplicates and returns non-duplicate list."""
        kept = []
        for post in posts:
            if self.is_duplicate(post.clean_text):
                post.is_duplicate = True
            else:
                self.add(post)
                kept.append(post)
        return kept
