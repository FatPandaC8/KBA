import json, os, re, urllib.request
from typing import List
from server.app.application.dto import ExtractionResult
from server.app.application.ports import KnowledgeExtractionPort
from server.app.domain.entities import ExtractedEntity, KnowledgeItemEntity, RelationshipEntity, normalize_key
from server.app.domain.value_objects import Certainty, EntityType, RelationStatus, RelationType
from server.app.domain.errors import ValidationError
import uuid

def _id(*p): return str(uuid.uuid5(uuid.NAMESPACE_URL, "echo:" + ":".join(p)))

class GroqExtractionAdapter(KnowledgeExtractionPort):
    def __init__(self, api_key, model="openai/gpt-oss-120b", pipeline_version="groq"):
        self.api_key=api_key; self.model=model; self.pipeline_version=pipeline_version
    def _call(self,prompt):
        body=json.dumps({"model":self.model,"messages":[{"role":"user","content":prompt}],"temperature":0.1,"response_format":{"type":"json_object"}}).encode()
        req=urllib.request.Request("https://api.groq.com/openai/v1/chat/completions",data=body,headers={"Authorization":f"Bearer {self.api_key}","Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=60) as r: return json.loads(r.read())["choices"][0]["message"]["content"]
    def extract(self,transcript,capture_id,user_id=""):
        return self.extract_graph(transcript,capture_id,user_id).knowledge_item
    def extract_graph(self,transcript,capture_id,user_id=""):
        clean=" ".join((transcript or "").split())
        if not clean: raise ValidationError("empty transcript")
        prompt=("Extract entities and directed relationships. Return JSON {title,core_idea,entities:[{name,type,confidence}],relationships:[{source,target,relation_type,confidence}]. "
               "Types: person,project,tool,concept,place. Relations: related_to,depends_on,supports,example_of,constrained_by,contradicts. Transcript: "+clean)
        data=None; last=None
        for _ in range(3):
            try:
                raw=self._call(prompt)
                m=re.search(r"\{.*\}",raw,re.S)
                data=json.loads(m.group(0) if m else raw)
                assert isinstance(data.get("entities"),list) and isinstance(data.get("relationships"),list)
                break
            except Exception as e:
                last=e; data=None
        if data is None: raise ValidationError(f"groq extraction failed: {last}")
        entities=[]
        for e in data.get("entities",[]):
            entities.append(ExtractedEntity.create(id=_id(user_id,capture_id,e["type"],normalize_key(e["name"])),capture_id=capture_id,name=e["name"],user_id=user_id,entity_type=e["type"],description="",confidence=float(e.get("confidence",0.7)),certainty=Certainty.CONFIRMED,provenance="groq",provider_id="extraction_groq",model_version=self.pipeline_version))
        by={normalize_key(e.name):e for e in entities}
        rels=[]
        for r in data.get("relationships",[]):
            s=by.get(normalize_key(r["source"])); t=by.get(normalize_key(r["target"]))
            if not s or not t or s.id==t.id: continue
            rels.append(RelationshipEntity.create(id=_id(user_id,capture_id,s.id,t.id,r["relation_type"]),from_id=s.id,to_id=t.id,user_id=user_id,relation_type=r["relation_type"],status=RelationStatus.SUGGESTED,certainty=Certainty.CONFIRMED,confidence=float(r.get("confidence",0.7)),source_capture_id=capture_id,provenance="groq"))
        item=KnowledgeItemEntity.create(id=_id(user_id,capture_id,"knowledge_item"),capture_id=capture_id,title=data.get("title",clean[:80]),core_idea=data.get("core_idea",clean[:200]),user_id=user_id,details="",transcript=clean,concepts=sorted({e.name for e in entities}),tags=sorted({e.entity_type for e in entities}),open_questions=[],candidate_relations=[],provenance="groq",provider_id="extraction_groq",model_version=self.pipeline_version)
        return ExtractionResult(knowledge_item=item,entities=entities,relationships=rels)
