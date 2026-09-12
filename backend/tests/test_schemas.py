"""Pydantic 契约校验测试：注册/登录/订单/聊天消息的非法输入均应被拒绝。"""
import pytest
from pydantic import ValidationError

import schemas


class TestUserCreate:
    def test_合法数据通过(self):
        u = schemas.UserCreate(
            email="a@b.com", username="小明", password="123456"
        )
        assert u.email == "a@b.com"

    @pytest.mark.parametrize("bad", ["not-an-email", "abc@", "abc@x", "@x.com"])
    def test_非法邮箱拒绝(self, bad):
        with pytest.raises(ValidationError):
            schemas.UserCreate(email=bad, username="u", password="123456")

    def test_密码短于6位拒绝(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(email="a@b.com", username="u", password="12345")

    def test_密码超过72字符拒绝(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(
                email="a@b.com", username="u", password="x" * 73
            )

    def test_用户名空白拒绝(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(email="a@b.com", username="   ", password="123456")


class TestOrderSchema:
    def test_空订单拒绝(self):
        with pytest.raises(ValidationError):
            schemas.OrderCreate(items=[])

    def test_数量必须为正数(self):
        with pytest.raises(ValidationError):
            schemas.OrderCreate(
                items=[{"product_id": 1, "quantity": 0}]
            )

    def test_数量上限999(self):
        with pytest.raises(ValidationError):
            schemas.OrderCreate(
                items=[{"product_id": 1, "quantity": 1000}]
            )

    def test_商品id必须大于0(self):
        with pytest.raises(ValidationError):
            schemas.OrderCreate(items=[{"product_id": 0, "quantity": 1}])

    def test_订单状态白名单(self):
        assert schemas.OrderStatusUpdate(status="paid").status == "paid"
        with pytest.raises(ValidationError):
            schemas.OrderStatusUpdate(status="destroyed")


class TestChatSchema:
    def test_空白消息拒绝(self):
        with pytest.raises(ValidationError):
            schemas.ChatRequest(message="   ")

    def test_超长消息拒绝(self):
        with pytest.raises(ValidationError):
            schemas.ChatRequest(message="好" * 2001)

    def test_合法消息通过(self):
        req = schemas.ChatRequest(message="  你好  ")
        assert req.message == "你好"  # 两端空白被剥离
