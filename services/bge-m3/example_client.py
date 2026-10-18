"""Run with a Python environment containing requests while the service is running."""
import requests

client = requests.Session()
client.trust_env = False
response = client.post('http://127.0.0.1:18080/v1/embeddings', json={
    'model': 'BAAI/bge-m3',
    'input': ['数字图书馆帮助读者检索学术文献。', 'A digital library supports scholarly literature search.'],
    'encoding_format': 'float',
}, timeout=60)
response.raise_for_status()
result = response.json()
left, right = [entry['embedding'] for entry in result['data']]
print({'dimension': len(left), 'cosine_similarity': sum(a * b for a, b in zip(left, right)),
       'tokens': result['usage']['total_tokens']})
