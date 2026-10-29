import json, re, urllib.request
from typing import List
from server.app.application.dto import AnswerDraft, CitationDTO, EvidenceItem
from server.app.application.ports import AnswerProviderPort

class GroqAnswerProvider(AnswerProviderPort):
    def __init__(self, api_key, model="openai/gpt-oss-120b"):
        self.api_key=api_key; self.model=model
    def _call(self,prompt):
        body=json.dumps({"model":self.model,"messages":[{"role":"user","content":prompt}],"temperature":0.1,"response_format":{"type":"json_object"}}).encode()
        req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=body,headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read())["choices"][0]["message"]["content"]
    def answer(self,question,evidence,contradictions):
        usable=[e for e in evidence if getattr(e,"score",1)>=0.12]
        if not usable: return AnswerDraft(text="Insufficient evidence.",refused=True,refusal_reason="insufficient_evidence")
        allowed={e.target_id for e in usable}
        prompt=("Answer using only provided subgraph. Separate STORED FACTS from INFERENCE. Cite IDs from allowed list. Refuse if insufficient. "
                "Return JSON {refused:bool,refusal_reason:str,facts:[str],inferences:[str],answer:str,cited_ids:[str]}. "
                f"Allowed IDs: {sorted(allowed)}. Question: {question}. Evidence: {json.dumps([getattr(e,'__dict__',{}) for e in usable])}. Contradictions: {contradictions}.")
        raw=self._call(prompt); m=re.search(r"\{.*\}",raw,re.S); data=json.loads(m.group(0) if m else raw)
        if data.get("refused"): return AnswerDraft(text=data.get("answer","Insufficient evidence."),refused=True,refusal_reason=data.get("refusal_reason","insufficient_evidence"))
        if any(i not in allowed for i in data.get("cited_ids",[])): return AnswerDraft(text="Rejected: cited IDs outside subgraph.",refused=True,refusal_reason="invalid_citation")
        cited=[i for i in data.get("cited_ids",[]) if i in allowed]
        return AnswerDraft(text=data.get("answer",""),facts=data.get("facts",[]),inferences=data.get("inferences",[]),contradictions=contradictions,citations=[CitationDTO(id=i,kind="entity",target_id=i,name=i) for i in cited])
