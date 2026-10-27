"""Download-free lexical vector baseline for laptop development, not Titan embeddings."""
import hashlib
import math
import re
DIMENSIONS=1024

def vectorize(text):
    tokens=re.findall(r"[\w-]+",text.lower())
    features=tokens+[a+" "+b for a,b in zip(tokens,tokens[1:])]
    values=[0.0]*DIMENSIONS
    for token in features:
        digest=hashlib.sha256(token.encode()).digest()
        index=int.from_bytes(digest[:4],"big")%DIMENSIONS
        values[index]+=1 if digest[4]%2 else -1
    norm=math.sqrt(sum(x*x for x in values))
    return [x/norm for x in values] if norm else values

def similarity(a,b): return sum(x*y for x,y in zip(a,b))
