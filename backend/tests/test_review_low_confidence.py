# -*- coding: utf-8 -*-
"""低置信识别 → 人工审核的测试（HITL 换个场景用）。

要点：复用既有的 interrupt/resume 机制，图结构一行不用改。
"""
from agents import graph as graph_module
from agents import nodes

IMG = "data:image/jpeg;base64,AA"


def _payload(confidence, **over):
    base = {
        "species": "猫",
        "species_code": "cat",
        "breed": "英短",
        "size": "中型",
        "size_code": "medium",
        "body_condition": "正常",
        "coat_condition": "毛发枯燥",
        "health_notes": "多喝水",
        "confidence": confidence,
        "_mode": "vlm",
    }
    base.update(over)
    return base


def _run(question="推荐几款猫粮", image_data_url=IMG):
    """跑一遍工作流，返回 (thread_id, interrupt payload)。"""
    tid, payload = None, None
    for event, data in graph_module.stream_workflow(
        question, user_id=1, image_data_url=image_data_url
    ):
        if event == "thread_id":
            tid = data
        elif event == "interrupt":
            payload = data
    return tid, payload


# ------------------------------------------------------------------
# analysis 规则本身
# ------------------------------------------------------------------
class Test审核规则:
    def test_低置信识别触发审核(self):
        out = nodes.analysis_node(
            {"question": "推荐猫粮", "pet_profile": {"confidence": 0.2},
             "confidence_grade": "low"}
        )
        assert out["needs_review"] is True
        assert any("识别" in r for r in out["review_reasons"])

    def test_中高档识别不触发(self):
        for grade in ("medium", "high"):
            out = nodes.analysis_node(
                {"question": "推荐猫粮", "pet_profile": {"confidence": 0.9},
                 "confidence_grade": grade}
            )
            assert out["needs_review"] is False, grade

    def test_没带图不受影响(self):
        out = nodes.analysis_node({"question": "推荐猫粮"})
        assert out["needs_review"] is False

    def test_原有两条规则仍然有效(self):
        out = nodes.analysis_node(
            {"question": "我要退款", "intent": "order", "total": 600.0}
        )
        assert out["needs_review"] is True
        assert len(out["review_reasons"]) == 2


# ------------------------------------------------------------------
# 端到端：interrupt → resume
# ------------------------------------------------------------------
class Test端到端审核:
    def test_低置信会停在人工审核(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", lambda url: _payload(0.3)
        )
        _, payload = _run()
        assert payload is not None, "低置信没有触发人工审核"
        assert any("识别" in r for r in payload["reasons"])
        # 审核 payload 里带上了识别结果，审核人能看到
        assert payload["pet_profile"]["confidence"] == 0.3

    def test_高置信不触发审核直接出结果(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", lambda url: _payload(0.9)
        )
        _, payload = _run()
        assert payload is None

    def test_审核通过后正常给推荐(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", lambda url: _payload(0.3)
        )
        tid, payload = _run()
        assert payload is not None

        answer = ""
        for event, data in graph_module.resume_workflow(tid, "approved"):
            if event == "answer":
                answer = data
        assert answer and "识别结果未通过" not in answer

    def test_审核驳回后说明不采信识别(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", lambda url: _payload(0.3)
        )
        tid, payload = _run()
        assert payload is not None

        answer = ""
        for event, data in graph_module.resume_workflow(tid, "rejected"):
            if event == "answer":
                answer = data
        assert "识别结果未通过人工确认" in answer
