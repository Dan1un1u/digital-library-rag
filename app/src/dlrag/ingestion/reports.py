"""Automated parsing checks and honest annotation templates."""
import csv
import json
from pathlib import Path


def export_reports(store, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    documents = store.list_documents(include_nonready=True)
    fields = ['doc_id','title','authors','year','topics','language','source_url','rights_note','file_sha256','status','error_code','error_message']
    with (output/'catalogue.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for doc in documents:
            row = {k:doc[k] for k in fields}
            for key in ('authors','topics'):
                row[key] = json.dumps(row[key],ensure_ascii=False)
            writer.writerow(row)
    fields = ['doc_id','pdf_page','body_order','header_handling','offset_correctness','issues','result','review_mode']
    all_chunks = store.list_chunks(include_indexing=True)
    with (output/'parsing_quality.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for doc in documents:
            for number in range(1, doc['page_count']+1):
                page = store.get_page(doc['doc_id'],number)
                diagnostics = json.loads(page['diagnostics_json'])
                chunks = [c for c in all_chunks if c['doc_id']==doc['doc_id'] and c['pdf_page']==number]
                valid = all(page['normalized_text'][c['page_char_start']:c['page_char_end']]==c['text'] for c in chunks)
                writer.writerow(dict(doc_id=doc['doc_id'],pdf_page=number,body_order='pending_human_review',
                    header_handling='removed_repeated_margin' if 'REPEATED_MARGIN_REMOVED' in diagnostics else 'not_removed',
                    offset_correctness='pass' if valid else 'fail',issues=';'.join(diagnostics),
                    result='automatic_checks_only',review_mode='automatic'))
    return {'documents':len(documents),'chunks':len(all_chunks),'output_dir':str(output)}


def candidate_templates(output_file):
    prompts = ['馆藏如何定义数字图书馆？','馆藏如何定义信息检索？','关键词检索的基本步骤是什么？',
        '什么是语义检索？','什么是倒排索引？','文献如何解释向量相似度？','文献如何解释检索增强生成？',
        '知识组织包含哪些方法？','如何评估检索结果？','引用定位需要哪些信息？',
        '不同文献如何比较关键词检索与语义检索？','不同文献如何讨论检索质量评估？',
        '不同文献如何描述数字图书馆的挑战？','不同文献如何讨论知识组织与检索的关系？',
        '不同文献如何讨论证据与回答可信度？']
    path = Path(output_file)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8') as f:
        for number, question in enumerate(prompts,1):
            item = dict(question_id=f'A{number:03d}',split='dev',category='exact' if number<=10 else 'multi_document',
                question=question,filters={'year_from':None,'year_to':None,'topics':[]},expected_status='answered',
                reference_points=[],relevant_doc_ids=[],relevant_chunk_ids=[],evidence_groups=[],clarification_expectation=None,
                annotation_status='pending_real_corpus_and_C_review',usable_for_evaluation=False)
            f.write(json.dumps(item,ensure_ascii=False)+'\n')
    return {'templates':15,'annotated_questions':0}
