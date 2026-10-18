"""中英文共用的确定性分词与 BM25；不做翻译或隐藏查询扩展。"""

import math
import re
import unicodedata
from collections import Counter

TOKENIZER_VERSION = "nfkc-casefold-cjk-bigram-v1"


def tokenize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens = re.findall(r"[a-z0-9]+(?:[._+\-][a-z0-9]+)*", text)
    for segment in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", text):
        if len(segment) == 1:
            tokens.append(segment)
        else:
            tokens.extend(segment[i:i + 2] for i in range(len(segment) - 1))
    return tokens


class BM25:
    def __init__(self, token_lists, k1=1.5, b=0.75):
        self.token_lists = token_lists
        self.k1, self.b = k1, b
        self.lengths = [len(tokens) for tokens in token_lists]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 1.0
        self.average_length = self.average_length or 1.0
        self.frequencies = [Counter(tokens) for tokens in token_lists]
        self.document_frequency = Counter()
        for frequency in self.frequencies:
            self.document_frequency.update(frequency.keys())

    def scores(self, query, eligible):
        terms = set(tokenize(query))
        count = len(self.frequencies)
        scores = {}
        for index in eligible:
            score = 0.0
            frequency = self.frequencies[index]
            length_ratio = self.lengths[index] / self.average_length
            for term in sorted(terms):
                tf = frequency.get(term, 0)
                if not tf:
                    continue
                df = self.document_frequency[term]
                idf = math.log(1 + (count - df + 0.5) / (df + 0.5))
                denominator = tf + self.k1 * (1 - self.b + self.b * length_ratio)
                score += idf * tf * (self.k1 + 1) / denominator
            if score > 0:
                scores[index] = score
        return scores
