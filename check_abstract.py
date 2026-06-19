import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from docx import Document

doc = Document(r'D:\Workplace\EpiSOA\outputs\manuscript\episoa_full_draft.docx')

issues = []

for i, p in enumerate(doc.paragraphs):
    t = p.text
    
    # Check for internal jargon / informal terms in main text (not code/config sections)
    informal = ['human_gold_v2', 'llm_gold', 'pseudo-gold', 'soe_v3', 'direct_llm', 
                'strict-char', 'semantic@0.5', 'ESR', 'bm25', 'full_soe', 'quality_topk_selector',
                'without_decomposed_verifier', 'without_chain_aware_selection']
    for term in informal:
        if term in t:
            issues.append(f'Para {i}: contains jargon "{term}"')
    
    # Check for English technical terms in Chinese narrative text
    # (excluding proper nouns like LLM, ChatGPT, EpiSOA which are acceptable)
    if re.search(r'[\u4e00-\u9fff].*\b(gold|silver|pipeline|verifier|selector|attributor|tuple)\b', t, re.I):
        issues.append(f'Para {i}: English term in Chinese text: {t[:80]}')

print('=== Issues found ===')
for issue in issues:
    print(issue)

if not issues:
    print('No obvious issues found in automated scan')
