from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import ollama
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pymongo import MongoClient

import llm_processor
sys.path.append(os.path.join(os.path.dirname(__file__), "backend"))
from ocr_core import run_ocr_on_file  # type: ignore

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FRONT_AGENTS_DIR = os.path.join(APP_DIR, "frontend-agents")
FRONT_OCR_DIR = os.path.join(APP_DIR, "frontend-vue")
OUTPUT_DIR = os.path.join(APP_DIR, "output")
OCR_IMAGE_DIR = os.path.join(OUTPUT_DIR, "ocr_images")
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(OCR_IMAGE_DIR, exist_ok=True)
LANG_MAP = {"繁體中文": "chi_tra", "English": "eng"}
STORE: Dict[str, Any] = {}
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "ocr_insight")
MONGO_COL = os.getenv("MONGO_COL", "ocr_records")
MONGO_BATCH_COL = os.getenv("MONGO_BATCH_COL", "ocr_batches")
mongo_client = MongoClient(MONGO_URL)
ocr_collection = mongo_client[MONGO_DB][MONGO_COL]
ocr_batch_collection = mongo_client[MONGO_DB][MONGO_BATCH_COL]


# ═══════════════════════════════════════════════════════════════
#                      Multi-Agent Framework
# ═══════════════════════════════════════════════════════════════


class Agent:
    """單一 Agent 類別"""

    def __init__(self, name: str, system_prompt: str, model: str, temperature: float = 0.0):
        self.name = name
        self.system_prompt = system_prompt
        self.model = model
        self.temperature = temperature
        self.id = str(uuid.uuid4())

    def execute(self, input_text: str, context: Dict | None = None) -> str:
        """執行 Agent 任務"""
        try:
            if context:
                context_str = f"\n\n=== 上下文資訊 ===\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
                input_text = context_str + input_text

            response = llm_processor.process_with_llm(
                model=self.model,
                system_prompt=self.system_prompt,
                user_prompt=input_text,
                temperature=self.temperature,
            )
            return response
        except Exception as e:  # pragma: no cover - 外部 LLM 例外
            return f"Agent {self.name} 執行錯誤: {str(e)}"


class RouterAgent:
    """路由 Agent - 決定使用哪個 Agent 或執行流程"""

    def __init__(self, model: str = "llama3.2:3b"):
        self.model = model
        self.system_prompt = (
            "你是一個智能路由助理，負責分析用戶的文件比對需求並決定最適合的處理方式。\n\n"
            "回傳 JSON：{\n"
            '  "strategy": "single|parallel|sequential",\n'
            '  "agents": ["agent1", ...],\n'
            '  "reasoning": "決策理由"\n'
            "}"
        )

    def route(self, input_text: str, available_agents: List[str]) -> Dict:
        prompt = f"""
可用的 Agent: {', '.join(available_agents)}

輸入內容：
{input_text}

請分析並決定最佳的處理策略。
"""
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                options={"temperature": 0.1},
            )
            result = response["message"]["content"]
            try:
                return json.loads(result)
            except Exception:
                return {
                    "strategy": "single",
                    "agents": [available_agents[0]] if available_agents else [],
                    "reasoning": "自動選擇單一 Agent 處理",
                }
        except Exception as e:  # pragma: no cover - 外部 LLM 例外
            return {
                "strategy": "single",
                "agents": [available_agents[0]] if available_agents else [],
                "reasoning": f"路由錯誤，使用預設策略: {str(e)}",
            }


class MultiAgentChain:
    """Multi-Agent 執行鏈"""

    def __init__(self):
        self.agents: Dict[str, Agent] = {}
        self.router = RouterAgent()
        self.execution_history: List[Dict[str, Any]] = []
        self.evaluator_prompt = (
            "你是結果評估整合專家。請分析多個 Agent 的處理結果，整合出最佳的綜合回答。\n\n"
            "請考慮：\n1. 各個結果的準確性和完整性\n2. 不同觀點的互補性\n3. 整合後的邏輯一致性\n\n"
            "最終提供一個統一、完整的答案。"
        )

    def add_agent(self, agent: Agent):
        self.agents[agent.name] = agent

    def remove_agent(self, name: str):
        if name in self.agents:
            del self.agents[name]

    def execute_single(self, agent_name: str, input_text: str, context=None) -> Dict[str, Any]:
        if agent_name not in self.agents:
            raise ValueError(f"Agent {agent_name} 不存在")
        result = self.agents[agent_name].execute(input_text, context)
        payload = {
            "strategy": "single",
            "agent": agent_name,
            "result": result,
            "context": context,
        }
        self.execution_history.append(payload)
        return payload

    def execute_parallel(self, agent_names: List[str], input_text: str, context=None) -> Dict[str, Any]:
        results: Dict[str, str] = {}
        for name in agent_names:
            if name in self.agents:
                results[name] = self.agents[name].execute(input_text, context)

        evaluation_input = f"原始輸入：\n{input_text}\n\n各 Agent 結果：\n"
        for name, result in results.items():
            evaluation_input += f"\n=== {name} ===\n{result}\n"

        final_result = llm_processor.process_with_llm(
            model="llama3.2:3b",
            system_prompt=self.evaluator_prompt,
            user_prompt=evaluation_input,
            temperature=0.1,
        )

        payload = {
            "strategy": "parallel",
            "agents": agent_names,
            "individual_results": results,
            "final_result": final_result,
        }
        self.execution_history.append(payload)
        return payload

    def execute_sequential(self, agent_names: List[str], input_text: str, context=None) -> Dict[str, Any]:
        current_input = input_text
        steps: List[Dict[str, Any]] = []

        for name in agent_names:
            if name not in self.agents:
                continue
            result = self.agents[name].execute(current_input, context)
            steps.append({"agent": name, "input": current_input, "output": result})
            current_input = result

        payload = {
            "strategy": "sequential",
            "agents": agent_names,
            "steps": steps,
            "final_result": current_input,
        }
        self.execution_history.append(payload)
        return payload

    def execute_branched(self, dag: DAGConfig, input_text: str, context=None) -> Dict[str, Any]:
        """
        簡化版 DAG 執行：依拓撲順序一次跑每個節點，輸入共用 input_text，
        並附上各節點輸出與拓撲順序，方便前端配合圖形顯示。
        """
        # 建立圖
        edges = [(e[0], e[1]) for e in dag.edges if len(e) == 2]
        indeg: Dict[str, int] = {}
        adj: Dict[str, List[str]] = {}
        for s, t in edges:
            adj.setdefault(s, []).append(t)
            indeg[t] = indeg.get(t, 0) + 1
            indeg.setdefault(s, 0)

        # 入口：若未指定，選 indeg=0 的節點
        entry = dag.entry or [n for n, d in indeg.items() if d == 0]
        order: List[str] = []
        outputs: Dict[str, str] = {}

        # 簡易拓撲排序（Kahn）
        from collections import deque
        q = deque(entry)
        seen = set()
        while q:
            n = q.popleft()
            if n in seen:
                continue
            seen.add(n)
            order.append(n)
            for nxt in adj.get(n, []):
                indeg[nxt] -= 1
                if indeg[nxt] <= 0:
                    q.append(nxt)
        # 若有孤立節點
        for n in adj.keys():
            if n not in seen:
                order.append(n)

        # 執行
        for name in order:
            if name not in self.agents:
                outputs[name] = f"(skipped, agent not found: {name})"
                continue
            outputs[name] = self.agents[name].execute(input_text, context)

        final_out = {k: outputs[k] for k in dag.outputs} if dag.outputs else outputs
        payload = {
            "strategy": "branched",
            "topo_order": order,
            "edges": edges,
            "entry": entry,
            "outputs": outputs,
            "final_result": final_out,
        }
        self.execution_history.append(payload)
        return payload


# ═══════════════════════════════════════════════════════════════
#                      FastAPI Schemas
# ═══════════════════════════════════════════════════════════════


class AgentCreate(BaseModel):
    name: str
    system_prompt: str
    model: str = "llama3.2:3b"
    temperature: float = 0.0


class AgentUpdate(BaseModel):
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0, le=1.2)


class RunRequest(BaseModel):
    input_text: str
    strategy: Optional[str] = Field(default="auto", description="auto|single|parallel|sequential|branched")
    agents: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None
    batchId: Optional[str] = None


class RunResponse(BaseModel):
    strategy_used: str
    decision: Dict[str, Any]
    payload: Dict[str, Any]

class CompareOverride(BaseModel):
    fileId: str
    filename: Optional[str] = None
    text: str


class CompareOCRRequest(BaseModel):
    fileIds: List[str] = Field(..., min_items=2, description="至少兩個 fileId")
    overrides: Optional[List[CompareOverride]] = None
    strategy: Optional[str] = Field(default="auto", description="auto|single|parallel|sequential")
    agents: Optional[List[str]] = None
    batchId: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
#                      DAG 支援 (分支策略)
# ═══════════════════════════════════════════════════════════════


class DAGConfig(BaseModel):
    edges: List[List[str]] = Field(default_factory=list, description="[[src, dst], ...]")
    entry: List[str] = Field(default_factory=list, description="入口 Agent 清單")
    outputs: List[str] = Field(default_factory=list, description="出口 Agent 清單")


def dag_to_mermaid(cfg: DAGConfig) -> str:
    """產出 mermaid flowchart 文字，方便前端預覽。"""
    lines = ["flowchart LR"]
    if cfg.entry:
        lines.append("  START([入口])")
        for e in cfg.entry:
            lines.append(f"  START --> {e}")
    if cfg.outputs:
        lines.append("  END([出口])")
    for src, dst in cfg.edges:
        lines.append(f"  {src} --> {dst}")
    for o in cfg.outputs:
        lines.append(f"  {o} --> END")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#                      FastAPI Application
# ═══════════════════════════════════════════════════════════════


app = FastAPI(title="Multi-Agent OCR Backend (FastAPI)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if os.path.isdir(FRONT_OCR_DIR):
    app.mount("/static", StaticFiles(directory=FRONT_OCR_DIR), name="static")
    app.mount("/ocr-files", StaticFiles(directory=OCR_IMAGE_DIR), name="ocr-files")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONT_OCR_DIR, "index.html"))


if os.path.isdir(FRONT_AGENTS_DIR):
    # 簡單提供 /agents 下的前端檔案（Vue CDN，無額外靜態需求）
    app.mount("/agents", StaticFiles(directory=FRONT_AGENTS_DIR), name="agents")


# 初始化 Multi-Agent Chain 與預設 Agents
chain = MultiAgentChain()

default_agents = [
    Agent("文件摘要專家", "你是專業的文件摘要專家，擅長提取關鍵資訊並產生簡潔有用的摘要。", "llama3.2:3b", 0.1),
    Agent("差異分析專家", "你是文件比對專家，擅長分析兩份文件的差異、相似點和關鍵變化。", "llama3.2:3b", 0.1),
    Agent("結構化分析專家", "你擅長將文件內容進行結構化分析，包括分類、標籤和組織資訊。", "llama3.2:3b", 0.1),
    Agent(
        "評價專家",
        "你是結果評估專家。收到多個不同專家（Agent）的回覆，請評分、指出最佳 Agent，並提供理由。\n"
        '{ "scores": { AgentName: int }, "best_agent": "...", "reasoning": "..." }',
        "llama3.2:3b",
        0.0,
    ),
]
for agent in default_agents:
    chain.add_agent(agent)

CURRENT_DAG = DAGConfig()


def save_image_from_data_url(file_id: str, page_index: int, data_url: str) -> Dict[str, str]:
    if not data_url:
        return {"imageFile": "", "imagePath": ""}
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError:
        encoded = data_url
    image_bytes = base64.b64decode(encoded)
    image_file = f"{file_id}_p{page_index}.png"
    image_path = os.path.join(OCR_IMAGE_DIR, image_file)
    with open(image_path, "wb") as f:
        f.write(image_bytes)
    return {"imageFile": image_file, "imagePath": image_path}


def doc_to_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    item = {k: v for k, v in doc.items() if k != "_id"}
    item["fileId"] = doc.get("fileId") or str(doc.get("_id"))
    pages = []
    for p in doc.get("pages", []):
        page = dict(p)
        image_file = page.get("imageFile")
        if image_file:
            page["imageUrl"] = f"/ocr-files/{image_file}"
        pages.append(page)
    item["pages"] = pages
    created_at = item.get("createdAt")
    if isinstance(created_at, datetime):
        item["createdAt"] = created_at.isoformat()
    return item


def batch_doc_to_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    created_at = doc.get("createdAt")
    files = doc.get("files", []) or []
    return {
        "batchId": doc.get("batchId") or str(doc.get("_id")),
        "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
        "fileCount": len(files),
        "files": files,
        "filenames": [f.get("filename") for f in files],
        "kind": "batch",
    }


def iso_dt(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def batch_doc_to_detail(doc: Dict[str, Any]) -> Dict[str, Any]:
    item = batch_doc_to_item(doc)
    item["compareResults"] = [
        {**c, "createdAt": iso_dt(c.get("createdAt"))} for c in (doc.get("compareResults") or [])
    ]
    item["chatLogs"] = [
        {**c, "createdAt": iso_dt(c.get("createdAt"))} for c in (doc.get("chatLogs") or [])
    ]
    return item


def delete_record(file_id: str) -> None:
    doc = ocr_collection.find_one({"_id": file_id})
    if doc:
        for p in doc.get("pages", []):
            image_path = p.get("imagePath")
            if image_path and os.path.isfile(image_path):
                try:
                    os.remove(image_path)
                except OSError:
                    pass
        ocr_collection.delete_one({"_id": file_id})
    STORE.pop(file_id, None)


def get_record_by_id(file_id: str) -> Optional[Dict[str, Any]]:
    record = STORE.get(file_id)
    if record:
        return record
    doc = ocr_collection.find_one({"_id": file_id})
    if doc:
        return doc_to_item(doc)
    return None

# ═══════════════════════════════════════════════════════════════
#                       API Endpoints
# ═══════════════════════════════════════════════════════════════


@app.get("/api/agents")
def list_agents():
    return [
        {
            "name": a.name,
            "system_prompt": a.system_prompt,
            "model": a.model,
            "temperature": a.temperature,
        }
        for a in chain.agents.values()
    ]


@app.post("/api/agents")
def create_agent(agent: AgentCreate):
    if agent.name in chain.agents:
        raise HTTPException(status_code=400, detail="Agent 已存在")
    chain.add_agent(Agent(agent.name, agent.system_prompt, agent.model, agent.temperature))
    return {"ok": True}


@app.put("/api/agents/{name}")
def update_agent(name: str, data: AgentUpdate):
    if name not in chain.agents:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    ag = chain.agents[name]
    if data.system_prompt is not None:
        ag.system_prompt = data.system_prompt
    if data.model is not None:
        ag.model = data.model
    if data.temperature is not None:
        ag.temperature = data.temperature
    return {"ok": True}


@app.delete("/api/agents/{name}")
def delete_agent(name: str):
    if name not in chain.agents:
        raise HTTPException(status_code=404, detail="Agent 不存在")
    chain.remove_agent(name)
    return {"ok": True}


@app.get("/api/router_prompt")
def get_router_prompt():
    return {"router_prompt": chain.router.system_prompt, "evaluator_prompt": chain.evaluator_prompt}


@app.put("/api/router_prompt")
def update_router_prompt(payload: Dict[str, str]):
    if "router_prompt" in payload:
        chain.router.system_prompt = payload["router_prompt"]
    if "evaluator_prompt" in payload:
        chain.evaluator_prompt = payload["evaluator_prompt"]
    return {"ok": True}


@app.get("/api/dag")
def get_dag():
    """取得目前的 DAG 邊、入口、出口與 mermaid 預覽。"""
    return {
        "edges": CURRENT_DAG.edges,
        "entry": CURRENT_DAG.entry,
        "outputs": CURRENT_DAG.outputs,
        "mermaid": dag_to_mermaid(CURRENT_DAG),
    }


@app.get("/api/ocr/history")
def list_ocr_history():
    batches: List[Dict[str, Any]] = []
    try:
        cursor = ocr_batch_collection.find({}, {"_id": 1, "batchId": 1, "createdAt": 1, "files": 1}).sort(
            "createdAt", -1
        )
        batches = [batch_doc_to_item(doc) for doc in cursor]
    except Exception:
        batches = []

    # 若沒有任何 batch，回退成以單檔案為主的列表
    if batches:
        return {"items": batches}

    items_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        cursor = ocr_collection.find(
            {},
            {"_id": 1, "fileId": 1, "filename": 1, "createdAt": 1, "pageCount": 1},
        ).sort("createdAt", -1)
        for doc in cursor:
            created_at = doc.get("createdAt")
            file_id = doc.get("fileId") or str(doc.get("_id"))
            items_by_id[file_id] = {
                "fileId": file_id,
                "filename": doc.get("filename"),
                "pageCount": doc.get("pageCount"),
                "createdAt": created_at.isoformat() if isinstance(created_at, datetime) else created_at,
                "kind": "file",
            }
    except Exception:
        items_by_id = {}

    for fid, record in STORE.items():
        if fid in items_by_id:
            continue
        items_by_id[fid] = {
            "fileId": fid,
            "filename": record.get("filename"),
            "pageCount": len(record.get("pages", [])),
            "createdAt": record.get("createdAt"),
            "kind": "file",
        }

    def sort_key(item: Dict[str, Any]):
        val = item.get("createdAt") or ""
        return val

    items = sorted(items_by_id.values(), key=sort_key, reverse=True)
    return {"items": items}


@app.get("/api/ocr/history/file/{file_id}")
def get_ocr_history_file(file_id: str):
    record = get_record_by_id(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="record not found")
    return {"item": record}


@app.get("/api/ocr/history/batch/{batch_id}")
def get_ocr_history_batch(batch_id: str):
    doc = ocr_batch_collection.find_one({"_id": batch_id})
    if not doc:
        raise HTTPException(status_code=404, detail="batch not found")
    return {"batch": batch_doc_to_detail(doc)}


@app.delete("/api/ocr/history/file/{file_id}")
def delete_ocr_history_file(file_id: str):
    doc = ocr_collection.find_one({"_id": file_id})
    if not doc:
        raise HTTPException(status_code=404, detail="record not found")
    delete_record(file_id)
    return {"ok": True}


@app.delete("/api/ocr/history/batch/{batch_id}")
def delete_ocr_history_batch(batch_id: str):
    doc = ocr_batch_collection.find_one({"_id": batch_id})
    if not doc:
        raise HTTPException(status_code=404, detail="batch not found")
    for f in doc.get("files", []):
        fid = f.get("fileId")
        if fid:
            delete_record(fid)
    ocr_batch_collection.delete_one({"_id": batch_id})
    return {"ok": True}


@app.put("/api/dag")
def set_dag(cfg: DAGConfig):
    """設定 DAG。前端可存取/載入並預覽 mermaid。"""
    CURRENT_DAG.edges = cfg.edges
    CURRENT_DAG.entry = cfg.entry
    CURRENT_DAG.outputs = cfg.outputs
    return {
        "ok": True,
        "edges": CURRENT_DAG.edges,
        "entry": CURRENT_DAG.entry,
        "outputs": CURRENT_DAG.outputs,
        "mermaid": dag_to_mermaid(CURRENT_DAG),
    }


@app.post("/api/run", response_model=RunResponse)
def run_chain(req: RunRequest):
    available_agents = list(chain.agents.keys())
    decision = {"strategy": req.strategy or "auto", "agents": req.agents or []}

    if (req.strategy or "auto") == "auto":
        decision = chain.router.route(req.input_text, available_agents)

    strategy = (decision.get("strategy") or req.strategy or "single").lower()
    agent_names = req.agents or decision.get("agents") or available_agents
    if not agent_names:
        raise HTTPException(status_code=400, detail="沒有可用的 Agent")

    if strategy == "single":
        target = agent_names[0]
        payload = chain.execute_single(target, req.input_text, req.context)
    elif strategy == "parallel":
        payload = chain.execute_parallel(agent_names, req.input_text, req.context)
    elif strategy == "sequential":
        payload = chain.execute_sequential(agent_names, req.input_text, req.context)
    elif strategy == "branched":
        payload = chain.execute_branched(CURRENT_DAG, req.input_text, req.context)
    else:
        raise HTTPException(status_code=400, detail="策略必須為 single/parallel/sequential/branched/auto")

    if req.batchId:
        final_text = payload.get("final_result") or payload.get("result") or ""
        chat_entries = [
            {"role": "user", "text": req.input_text, "createdAt": datetime.utcnow()},
            {"role": "ai", "text": final_text, "createdAt": datetime.utcnow()},
        ]
        ocr_batch_collection.update_one(
            {"_id": req.batchId},
            {"$push": {"chatLogs": {"$each": chat_entries}}},
        )

    return RunResponse(strategy_used=strategy, decision=decision, payload=payload)


@app.get("/api/history")
def history():
    return {"history": chain.execution_history}


@app.post("/api/compare_ocr", response_model=RunResponse)
def compare_ocr(req: CompareOCRRequest):
    # 收集 OCR 文字
    override_map = {o.fileId: o for o in (req.overrides or [])}
    compare_files: List[Dict[str, Any]] = []
    for fid in req.fileIds:
        if fid in override_map:
            o = override_map[fid]
            compare_files.append({"fileId": fid, "filename": o.filename or fid, "text": o.text})
            continue
        record = STORE.get(fid)
        if not record:
            doc = ocr_collection.find_one({"_id": fid})
            record = doc_to_item(doc) if doc else None
        if not record:
            raise HTTPException(status_code=404, detail=f"fileId {fid} not found")
        txt = record.get("correctedFullText") or record.get("fullText") or ""
        compare_files.append({"fileId": fid, "filename": record.get("filename", fid), "text": txt})

    # 組合 prompt：要求同時提供 Markdown 表格摘要差異/相似
    input_text = (
        "請比較以下文件的差異與相似之處，並列出主要差異點。\n"
        "請用 Markdown 表格摘要：欄位包含「項目」「文件1」「文件2」「差異/說明」。\n\n"
    )
    for idx, item in enumerate(compare_files, 1):
        input_text += f"--- 文件{idx}: {item['filename']} ---\n{item['text']}\n\n"

    # 呼叫 multi-agent 決策
    available_agents = list(chain.agents.keys())
    decision = {"strategy": req.strategy or "auto", "agents": req.agents or []}
    if (req.strategy or "auto") == "auto":
        decision = chain.router.route(input_text, available_agents)

    strategy = (decision.get("strategy") or req.strategy or "single").lower()
    agent_names = req.agents or decision.get("agents") or available_agents
    if not agent_names:
        raise HTTPException(status_code=400, detail="沒有可用的 Agent")

    if strategy == "single":
        payload = chain.execute_single(agent_names[0], input_text, None)
    elif strategy == "parallel":
        payload = chain.execute_parallel(agent_names, input_text, None)
    elif strategy == "sequential":
        payload = chain.execute_sequential(agent_names, input_text, None)
    elif strategy == "branched":
        payload = chain.execute_branched(CURRENT_DAG, input_text, None)
    else:
        raise HTTPException(status_code=400, detail="策略必須為 single/parallel/sequential/branched/auto")

    if req.batchId:
        compare_entry = {
            "compareId": str(uuid.uuid4()),
            "createdAt": datetime.utcnow(),
            "fileIds": [c.get("fileId") for c in compare_files],
            "files": compare_files,
            "strategy_used": strategy,
            "decision": decision,
            "payload": payload,
        }
        ocr_batch_collection.update_one(
            {"_id": req.batchId},
            {"$push": {"compareResults": compare_entry}},
        )

    return RunResponse(strategy_used=strategy, decision=decision, payload=payload)


# ═══════════════════════════════════════════════════════════════
#                       OCR Endpoints
# ═══════════════════════════════════════════════════════════════


@app.post("/api/ocr")
async def ocr(files: List[UploadFile] = File(...), language: str = Form("繁體中文")):
    """
    上傳多檔進行 OCR，回傳 pages/words 結構（供前端標註器使用）
    """
    lang_code = LANG_MAP.get(language, "chi_tra")
    results = []
    batch_id = str(uuid.uuid4())
    created_at = datetime.utcnow()
    batch_files = []
    for f in files:
        file_id = str(uuid.uuid4())
        content = await f.read()
        ocr_result = run_ocr_on_file(content, f.filename, lang_code)
        db_pages = []
        for page in ocr_result.get("pages", []):
            saved = save_image_from_data_url(file_id, page.get("pageIndex", 0), page.get("imageDataUrl", ""))
            page["imageUrl"] = f"/ocr-files/{saved['imageFile']}" if saved.get("imageFile") else ""
            db_pages.append(
                {
                    "pageIndex": page.get("pageIndex"),
                    "width": page.get("width"),
                    "height": page.get("height"),
                    "imageFile": saved.get("imageFile"),
                    "imagePath": saved.get("imagePath"),
                    "words": page.get("words", []),
                }
            )
        payload = {
            "fileId": file_id,
            "filename": f.filename,
            "createdAt": created_at.isoformat(),
            "batchId": batch_id,
            **ocr_result,
        }
        STORE[file_id] = payload
        record = {
            "_id": file_id,
            "fileId": file_id,
            "filename": f.filename,
            "batchId": batch_id,
            "pages": db_pages,
            "fullText": ocr_result.get("fullText", ""),
            "correctedFullText": None,
            "pageCount": len(db_pages),
            "createdAt": created_at,
        }
        result = ocr_collection.replace_one({"_id": file_id}, record, upsert=True)
        print(
            "[OCR][DB] upserted file_id=%s filename=%s pages=%s acknowledged=%s upserted_id=%s matched=%s"
            % (
                file_id,
                f.filename,
                len(db_pages),
                result.acknowledged,
                result.upserted_id,
                result.matched_count,
            )
        )
        batch_files.append(
            {"fileId": file_id, "filename": f.filename, "pageCount": len(db_pages)}
        )
        results.append(payload)
    batch_record = {
        "_id": batch_id,
        "batchId": batch_id,
        "files": batch_files,
        "createdAt": created_at,
    }
    ocr_batch_collection.replace_one({"_id": batch_id}, batch_record, upsert=True)
    return {"items": results, "batchId": batch_id}


@app.post("/api/save")
async def save(
    fileId: str = Form(...),
    correctedFullText: str = Form(None),
    wordEdits: str = Form(None),
    pageWords: str = Form(None),
):
    """
    儲存前端標註後的內容；wordEdits 為 JSON 字串:
      [{"wordId":"w12","newText":"臺灣"}]
    """
    record = STORE.get(fileId)
    db_doc = ocr_collection.find_one({"_id": fileId})
    if not record and not db_doc:
        return {"ok": False, "msg": "fileId not found"}
    if not record and db_doc:
        record = doc_to_item(db_doc)

    if correctedFullText is not None:
        record["correctedFullText"] = correctedFullText

    if pageWords:
        try:
            pages_payload = json.loads(pageWords)
        except json.JSONDecodeError:
            pages_payload = []
        page_map = {p.get("pageIndex"): p for p in record.get("pages", [])}
        for p in pages_payload:
            idx = p.get("pageIndex")
            if idx in page_map:
                page_map[idx]["words"] = p.get("words", [])

    if wordEdits:
        edits = json.loads(wordEdits)
        word_map = {w["id"]: w for p in record["pages"] for w in p["words"]}
        for e in edits:
            wid = e.get("wordId")
            new_text = e.get("newText", "")
            if wid in word_map:
                word_map[wid]["text"] = new_text

    out_path = os.path.join(OUTPUT_DIR, f"{fileId}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    if db_doc:
        db_doc["correctedFullText"] = record.get("correctedFullText")
        db_doc["fullText"] = record.get("fullText")
        existing_pages = {p.get("pageIndex"): p for p in db_doc.get("pages", [])}
        db_doc["pages"] = [
            {
                "pageIndex": p.get("pageIndex"),
                "width": p.get("width"),
                "height": p.get("height"),
                "imageFile": p.get("imageFile") or existing_pages.get(p.get("pageIndex"), {}).get("imageFile"),
                "imagePath": p.get("imagePath") or existing_pages.get(p.get("pageIndex"), {}).get("imagePath"),
                "words": p.get("words", []),
            }
            for p in record.get("pages", [])
        ]
        ocr_collection.replace_one({"_id": fileId}, db_doc, upsert=True)
    STORE[fileId] = record

    return {"ok": True, "path": out_path}
