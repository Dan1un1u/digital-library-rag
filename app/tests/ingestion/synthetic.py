"""Generate three clearly labelled synthetic PDFs, never academic sources."""
import json
from pathlib import Path
import fitz


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    specs = [
        ('single.pdf',['Keyword retrieval uses exact terms. Evidence citations need a document and a page.']),
        ('multi.pdf',['Semantic retrieval uses vectors. This sentence continues on the next',
                      'page without merging pages. Hybrid retrieval combines independent rankings.']),
        ('long.pdf',['Long paragraphs require overlapping chunks. ' * 100])]
    manifest=[]
    for name,texts in specs:
        pdf=fitz.open()
        for number,text in enumerate(texts,1):
            page=pdf.new_page()
            page.insert_text((50,30),'SYNTHETIC TEST MATERIAL - NOT A RESEARCH PAPER',fontsize=9)
            page.insert_textbox(fitz.Rect(50,100,545,740),text,fontsize=10)
            page.insert_text((50,815),f'Page {number}',fontsize=9)
        pdf.save(directory/name)
        pdf.close()
        metadata={'title':'合成测试资料 '+name,'authors':[],'year':None,'topics':['合成测试'],
                  'language':'en','source_url':None,'rights_note':'本项目生成的合成测试资料'}
        manifest.append({'file':name,'metadata':metadata})
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    generate(args.output)
