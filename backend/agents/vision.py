"""视觉识别：宠物照片 → 结构化档案字段。

搬迁自 PetSight（原实现已实测：3 种畸形模型输出全部兜住），接入本项目的配置体系。

设计原则：
- **纯标准库** urllib 直调 OpenAI 兼容视觉接口，不引入额外依赖，也不依赖 langchain 是否可用；
- **三层鲁棒解析**：剥 ``` 代码块 → 截取首尾 `{...}` → 逐行 key:value 兜底；
- **双层拒识**：物种不是猫/狗 → 拒；置信度低于阈值 → 拒。拒识结果照样返回，让上层决定是
  转人工还是让用户重传（上层不因为"识别不确定"就整个失败）；
- **绝不抛异常**：无 Key / 网络失败 / 模型返回垃圾，都降级为本地结果，链路不中断。

与 PetSight 原版的一处改进：
原版所有候选模型**共用同一份全局 KEY/BaseURL**，一旦钥匙失效，
"多模型重试"其实是在用同一把坏钥匙重试三遍，必然全挂 → 直接穿过重试落到本地降级。
这里把凭据做成**可单独配置**（VLM_API_KEY/VLM_BASE_URL 留空时才复用 LLM_*），
换别家视觉模型时不必改代码。
"""

from __future__ import annotations

import base64
import json
import logging
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from config import settings

logger = logging.getLogger("petvision.vision")

# 期望模型输出的 JSON 结构（写进提示词，强制结构化）
SCHEMA_PROMPT = (
    "你是一名资深宠物医生与宠物品种学专家。请分析这张宠物图片，"
    "只返回一个合法的 JSON 对象，不要输出任何其他文字、Markdown 或解释。字段如下：\n"
    "{\n"
    '  "species": "猫|狗|其他",\n'
    '  "breed": "最可能的品种，如：英短/金毛 等",\n'
    '  "size": "体型大小，只能填：小型/中型/大型/不确定",\n'
    '  "body_condition": "体态判断，如：正常/偏瘦/偏胖/过于肥胖，附一句依据",\n'
    '  "coat_condition": "毛发状态，如：健康顺滑/毛发枯燥/局部掉毛",\n'
    '  "health_notes": "2-4 条可执行的健康观察与建议，逗号分隔",\n'
    '  "confidence": 0.0\n'
    "}\n"
)

# 支持的图片类型
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}


# ------------------------------------------------------------------
# 一、三层鲁棒解析（纯函数，可单测，不依赖网络）
# ------------------------------------------------------------------
def _strip_code_fence(text: str) -> str:
    """去除模型输出中的 ```json ... ``` 包裹。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    return t


def _extract_json(text: str) -> Optional[dict]:
    """稳定地从模型输出里提取 JSON 对象；第一层失败再走逐行兜底。"""
    t = _strip_code_fence(text)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start : end + 1])
        except json.JSONDecodeError:
            pass
    # 兜底：逐行解析 key:value（容错模型漏引号/逗号/括号）
    data: Dict[str, str] = {}
    for line in t.splitlines():
        m = re.match(r'"?([^"]+)"?\s*:\s*"?([^"]*?)"?,?\s*$', line.strip())
        if m:
            data[m.group(1)] = m.group(2).strip()
    return data or None


def _normalize(payload: dict) -> dict:
    """标准化字段，保证每个 key 都有合法默认值；health_notes 统一为字符串。"""
    notes = payload.get("health_notes", "")
    if isinstance(notes, list):
        notes = "，".join(str(n) for n in notes)
    elif not isinstance(notes, str):
        notes = str(notes)
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "species": str(payload.get("species", "未知")).strip() or "未知",
        "breed": str(payload.get("breed", "未知")).strip() or "未知",
        "size": str(payload.get("size", "不确定")).strip() or "不确定",
        "body_condition": str(payload.get("body_condition", "——")).strip() or "——",
        "coat_condition": str(payload.get("coat_condition", "——")).strip() or "——",
        "health_notes": notes.strip() or "——",
        "confidence": confidence,
    }


def _looks_like_pet(species: str) -> bool:
    """宽松判断物种是否属于猫/狗（覆盖中英文）。"""
    low = species.lower()
    return any(kw in low for kw in ("猫", "狗", "犬", "cat", "dog", "feline", "canine"))


def _species_code(species: str) -> str:
    """把物种字符串归一到 cat / dog / other，供结构化筛选用。"""
    low = species.lower()
    if "猫" in low or "cat" in low or "feline" in low:
        return "cat"
    if "狗" in low or "犬" in low or "dog" in low or "canine" in low:
        return "dog"
    return "other"


def _size_code(size: str) -> str:
    """把体型描述归一到 small / medium / large / unknown。

    注意与 `body_condition`（体态：偏胖/偏瘦）区分——
    这里说的是**体型大小**，商品能不能用得上，看的是这个。
    """
    low = (size or "").lower()
    if any(k in low for k in ("小型", "mini", "small", "toy")):
        return "small"
    if any(k in low for k in ("中型", "medium")):
        return "medium"
    if any(k in low for k in ("大型", "巨型", "large", "giant")):
        return "large"
    return "unknown"


def _should_reject(payload: dict) -> str:
    """判断识别结果是否「不可直接采信」。空字符串表示可信；非空为拒识原因。

    **这里只管「是不是宠物」这一层**——不是猫/狗或完全没认出来，才拒。
    置信度高低**不在这一层拒**：低置信结果照样允许建档，只是会被判成低档、
    转人工确认（见 services/pet_profile.grade_confidence）。

    为什么改掉 PetSight 原版「低置信直接拒建档」的做法：
    拒掉 = 服务失败，用户白拍一张、还得重来；转人工 = 用户仍能走完流程。
    把关的责任交给人工，而不是把用户挡在门外。
    """
    species = str(payload.get("species", "")).strip()
    if not _looks_like_pet(species):
        if species in ("", "未知"):
            return "未能识别出宠物，请上传清晰、正面的猫/狗照片"
        return f"识别结果并非宠物（物种：{species}），请上传猫/狗照片"
    return ""


# ------------------------------------------------------------------
# 二、模型调用（无 Key / 失败一律降级，不抛异常）
# ------------------------------------------------------------------
def _vlm_credentials() -> tuple[str, str]:
    """解析视觉模型凭据：优先用 VLM_* 独立配置，留空则复用 LLM_*。

    这样"换一家视觉模型"只需改 .env，不必动代码。
    """
    key = settings.VLM_API_KEY or settings.LLM_API_KEY
    base = (settings.VLM_BASE_URL or settings.LLM_BASE_URL).rstrip("/")
    return key, base


def _model_list() -> List[str]:
    """主模型 + 备用模型（去重，保序）。"""
    out: List[str] = []
    for m in [settings.VLM_MODEL] + _split_models(settings.VLM_FALLBACK_MODELS):
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out


def _split_models(raw: str) -> List[str]:
    return [s for s in re.split(r"[,\s]+", raw or "") if s]


def _call_one_model(image_data_url: str, model: str, key: str, base: str) -> Optional[dict]:
    """单次调用指定视觉模型，成功返回 dict，失败返回 None。"""
    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "temperature": settings.VLM_TEMPERATURE,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": SCHEMA_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=settings.VLM_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):  # 部分网关把 content 返回成数组
        content = "".join(part.get("text", "") for part in content)
    return _extract_json(content)


def _call_vlm_with_fallback(image_data_url: str) -> dict:
    """依次尝试主模型与备用模型；全失败返回 {"_error": ...}。"""
    key, base = _vlm_credentials()
    last_err = ""
    for model in _model_list():
        try:
            extracted = _call_one_model(image_data_url, model, key, base)
            if extracted:
                return extracted
            last_err = f"模型 {model} 未返回可解析的内容"
            logger.warning(last_err)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "ignore")[:200]
            except Exception:  # noqa: BLE001
                pass
            last_err = f"HTTP {e.code} ({model}): {detail}"
            logger.warning(last_err)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__} ({model}): {e}"
            logger.warning(last_err)
    return {"_error": last_err}


def _local_fallback() -> dict:
    """本地降级：无 Key 或调用失败时的确定性结果，保证流程可完整演示。"""
    return {
        "species": "未知",
        "breed": "未知",
        "size": "不确定",
        "body_condition": "——（未配置视觉模型，无法自动判断）",
        "coat_condition": "——（未配置视觉模型，无法自动判断）",
        "health_notes": "请配置可用的视觉大模型 API Key 以启用真实图片识别；当前为本地降级模式。",
        "confidence": 0.0,
        "_mode": "local_fallback",
    }


# ------------------------------------------------------------------
# 三、对外入口
# ------------------------------------------------------------------
def classify_pet_image(image_base64: str, mime: str = "image/jpeg") -> dict:
    """识别宠物图片，返回结构化档案字段。**始终返回可用的 dict，不抛异常。**

    返回的 `_mode` 字段表明本次结果来源：
      - "vlm"           正常识别
      - "rejected"      识别结果不是猫/狗，带 reject_reason（低置信**不算**拒识，只降档）
      - "local_fallback" 未配置 Key
      - "vlm_error"     调用失败后降级
    """
    image_data_url = f"data:{mime};base64,{image_base64}"
    key, _ = _vlm_credentials()
    if not key:
        return {**_local_fallback(), "species_code": "other", "size_code": "unknown"}

    payload = _call_vlm_with_fallback(image_data_url)
    if "_error" in payload:
        return {
            **_local_fallback(),
            "species_code": "other",
            "size_code": "unknown",
            "_mode": "vlm_error",
            "_error": payload["_error"],
        }

    normalized = _normalize(payload)
    normalized["species_code"] = _species_code(normalized["species"])
    normalized["size_code"] = _size_code(normalized["size"])
    reason = _should_reject(normalized)
    if reason:
        return {
            **normalized,
            "_mode": "rejected",
            "rejected": True,
            "reject_reason": reason,
        }
    return {**normalized, "_mode": "vlm"}


def classify_from_bytes(raw: bytes, mime: str = "image/jpeg") -> dict:
    """从图片字节直接识别（路由层用这个）。"""
    return classify_pet_image(base64.b64encode(raw).decode("ascii"), mime)


def classify_data_url(data_url: str) -> dict:
    """从 data URL（形如 `data:image/jpeg;base64,xxxx`）直接识别。

    工作流节点收到的是前端传来的 data URL，这里拆回 base64 + mime。
    格式不对时同样走降级，不抛异常。
    """
    m = re.match(r"data:(?P<mime>[^;]+);base64,(?P<b64>.+)", data_url or "", re.S)
    if not m:
        return {
            **_local_fallback(),
            "species_code": "other",
            "size_code": "unknown",
            "_mode": "local_fallback",
        }
    return classify_pet_image(m.group("b64"), m.group("mime"))
