# -*- coding: utf-8 -*-
"""工作流接入视觉节点的测试：带图 / 不带图两条路径必须泾渭分明。

核心保证：**不带图时，行为与改造前完全一致**（这是"增量挂载"的安全底线）。
"""
from agents import graph as graph_module
from agents import nodes


def _fake_vision(payload: dict):
    return lambda data_url: dict(payload)


def _cat_payload(**over):
    base = {
        "species": "猫",
        "species_code": "cat",
        "breed": "英短",
        "size": "中型",
        "size_code": "medium",
        "body_condition": "正常",
        "coat_condition": "毛发枯燥",
        "health_notes": "多喝水",
        "confidence": 0.9,
        "_mode": "vlm",
    }
    base.update(over)
    return base


def _node_sequence(question: str, image_data_url=None):
    """跑一遍工作流，收集经过的节点名。"""
    seq = []
    for event, data in graph_module.stream_workflow(
        question, user_id=1, image_data_url=image_data_url
    ):
        if event == "progress":
            seq.append(data)
    return seq


# ------------------------------------------------------------------
# 入口路由
# ------------------------------------------------------------------
class Test入口条件边:
    def test_不带图直接进supervisor(self):
        assert nodes.route_start({"question": "推荐猫粮"}) == "supervisor"

    def test_带图先进视觉节点(self):
        assert nodes.route_start({"image_data_url": "data:image/jpeg;base64,AA"}) == "vision_agent"

    def test_空字符串视为不带图(self):
        assert nodes.route_start({"image_data_url": ""}) == "supervisor"


# ------------------------------------------------------------------
# 视觉节点本身
# ------------------------------------------------------------------
class Test视觉节点:
    def test_写入档案与档位(self, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", _fake_vision(_cat_payload())
        )
        out = nodes.vision_agent_node({"image_data_url": "data:image/jpeg;base64,AA"})
        assert out["confidence_grade"] == "high"
        assert out["pet_profile"]["species_code"] == "cat"
        assert out["pet_profile"]["size_code"] == "medium"

    def test_低置信判低档(self, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url",
            _fake_vision(_cat_payload(confidence=0.3)),
        )
        out = nodes.vision_agent_node({"image_data_url": "data:image/jpeg;base64,AA"})
        assert out["confidence_grade"] == "low"

    def test_识别抛异常不阻断流程(self, monkeypatch):
        def _boom(data_url):
            raise RuntimeError("模型服务挂了")

        monkeypatch.setattr("agents.vision.classify_data_url", _boom)
        out = nodes.vision_agent_node({"image_data_url": "data:image/jpeg;base64,AA"})
        # 仍返回结构完整的兜底结果，不向上抛
        assert out["confidence_grade"] == "low"
        assert out["pet_profile"]["species_code"] == "other"


# ------------------------------------------------------------------
# 整图路径：带图 vs 不带图
# ------------------------------------------------------------------
class Test整图路径:
    def test_图里共有8个业务节点(self):
        names = set(graph_module.get_graph().get_graph().nodes)
        for expected in (
            "vision_agent", "supervisor", "knowledge_agent", "shopping_agent",
            "order_agent", "analysis", "human_review", "writer",
        ):
            assert expected in names, f"缺少节点 {expected}"

    def test_不带图不经过视觉节点(self, offline_llm):
        seq = _node_sequence("推荐几款猫粮")
        assert "vision_agent" not in seq
        assert "supervisor" in seq

    def test_带图先经过视觉节点(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", _fake_vision(_cat_payload())
        )
        seq = _node_sequence("推荐几款猫粮", image_data_url="data:image/jpeg;base64,AA")
        assert seq[0] == "vision_agent"
        assert "supervisor" in seq

    def test_带图与不带图都能跑完拿到回答(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url", _fake_vision(_cat_payload())
        )
        for img in (None, "data:image/jpeg;base64,AA"):
            answer = ""
            for event, data in graph_module.stream_workflow(
                "推荐几款猫粮", user_id=1, image_data_url=img
            ):
                if event == "answer":
                    answer = data
            assert answer, f"image_data_url={img!r} 时没拿到回答"


# ------------------------------------------------------------------
# 档案驱动的推荐（用 conftest 库里的真实种子商品）
# ------------------------------------------------------------------
class Test档案驱动推荐:
    @staticmethod
    def _answer(question, image_data_url=None):
        answer = ""
        for event, data in graph_module.stream_workflow(
            question, user_id=1, image_data_url=image_data_url
        ):
            if event == "answer":
                answer = data
        return answer

    def test_带图推荐会说明用了识别结果(self, offline_llm, monkeypatch):
        monkeypatch.setattr(
            "agents.vision.classify_data_url",
            _fake_vision(_cat_payload(coat_condition="毛发枯燥")),
        )
        answer = self._answer("推荐几款猫粮", "data:image/jpeg;base64,AA")
        assert "📷" in answer, answer

    def test_不带图推荐不会出现筛选说明(self, offline_llm):
        answer = self._answer("推荐几款猫粮")
        assert "📷" not in answer, answer
