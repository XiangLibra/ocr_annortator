
# llm_processor.py ── 本地 Ollama LLM 呼叫工具
import ollama

def process_with_llm(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
) -> str:
    """
    透過本地 Ollama 模型執行對話  
    Parameters
    ----------
    model : str
        模型名稱，例："llama3"、"gemma:2b" …
    system_prompt : str
        Agent 的角色 / 指令（system role）
    user_prompt : str
        真正要餵給模型的文字（OCR 結果或其他）
    temperature : float
        生成溫度
    Returns
    -------
    str : LLM 輸出文字
    """
    # 確保所有參數都是字符串
    if not isinstance(system_prompt, str):
        system_prompt = str(system_prompt)
    if not isinstance(user_prompt, str):
        user_prompt = str(user_prompt)
    
    msgs = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_prompt},
    ]
    
    # 調試信息
    print(f"DEBUG: model={model}")
    print(f"DEBUG: system_prompt type={type(system_prompt)}, content={system_prompt[:100]}...")
    print(f"DEBUG: user_prompt type={type(user_prompt)}, content={user_prompt[:100]}...")
    print(f"DEBUG: msgs={msgs}")
    
    resp = ollama.chat(
        model=model,
        messages=msgs,
        options={"temperature": temperature},
    )
    return resp["message"]["content"]
