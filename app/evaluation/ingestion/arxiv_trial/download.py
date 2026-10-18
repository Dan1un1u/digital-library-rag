"""Download ten public arXiv PDFs and their citation metadata for a local trial."""
import json
import re
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

IDS=['2005.11401','2004.04906','2104.08663','2004.12832','2107.05720','2112.09118','1908.10084','2210.07316','2212.10496','2307.03172']
class Meta(HTMLParser):
    def __init__(self):
        super().__init__(); self.values={}
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='meta' and attrs.get('name','').startswith('citation_'):
            self.values.setdefault(attrs['name'],[]).append(attrs.get('content',''))

def fetch(url):
    request=urllib.request.Request(url,headers={'User-Agent':'LibraryCourseTrial/1.0'})
    with urllib.request.urlopen(request,timeout=90) as response:
        return response.read()

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True)
    output=Path(parser.parse_args().output).resolve(); output.mkdir(parents=True,exist_ok=True)
    manifest=[]
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    for aid in IDS:
        target=output/(aid+'.pdf')
        try:
            html=fetch('https://arxiv.org/abs/'+aid).decode()
            meta=Meta(); meta.feed(html)
            title=meta.values['citation_title'][0]
            date=meta.values.get('citation_date',[''])[0]
            pdf_url=meta.values.get('citation_pdf_url',['https://arxiv.org/pdf/'+aid])[0]
            licenses=re.findall(r'https?://(?:creativecommons.org|arxiv.org/licenses)/[^"<>\s]+',html)
            if not target.exists():
                time.sleep(3)
                data=fetch(pdf_url)
                if not data.startswith(b'%PDF'): raise ValueError('Response is not PDF')
                target.write_bytes(data)
            metadata={'title':title,'authors':meta.values.get('citation_author',[]),'year':int(date[:4]) if date else None,
                      'topics':['arXiv实验'],'language':'en','source_url':'https://arxiv.org/abs/'+aid,
                      'rights_note':'arXiv公开下载，仅用于本地解析实验；再分发权限待核验。页面许可：'+(', '.join(sorted(set(licenses))) or '未提取')}
            manifest.append({'file':aid+'.pdf','metadata':metadata})
            print(aid,title,target.stat().st_size,flush=True)
        except Exception as exc:
            print('FAILED',aid,str(exc),flush=True)
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        time.sleep(3)
    if len(manifest)!=10: raise SystemExit('Downloaded '+str(len(manifest))+'/10')
