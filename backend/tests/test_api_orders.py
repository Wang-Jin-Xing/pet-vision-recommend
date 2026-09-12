"""订单接口集成测试：下单、库存扣减、越权防护、状态流转。"""


def test_下单_未登录返回401(client, make_product):
    product = make_product()
    resp = client.post(
        "/api/orders", json={"items": [{"product_id": product.id, "quantity": 2}]}
    )
    assert resp.status_code == 401


def test_下单成功_扣减库存并计算总价(client, auth_headers, make_product, db):
    p1 = make_product(name="狗粮", price=100.0, stock=10)
    p2 = make_product(name="猫砂", price=50.0, stock=5)

    resp = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "items": [
                {"product_id": p1.id, "quantity": 2},
                {"product_id": p2.id, "quantity": 1},
            ]
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "pending"
    assert data["total"] == 250.0
    assert len(data["items"]) == 2

    db.refresh(p1)
    db.refresh(p2)
    assert p1.stock == 8
    assert p2.stock == 4


def test_下单_商品不存在返回404(client, auth_headers):
    resp = client.post(
        "/api/orders",
        headers=auth_headers,
        json={"items": [{"product_id": 99999, "quantity": 1}]},
    )
    assert resp.status_code == 404


def test_下单_库存不足返回400且不扣库存(client, auth_headers, make_product, db):
    product = make_product(stock=3)
    resp = client.post(
        "/api/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product.id, "quantity": 5}]},
    )
    assert resp.status_code == 400
    db.refresh(product)
    assert product.stock == 3  # 失败回滚，库存不变


def test_订单列表_仅返回本人订单(client, make_user, make_product, db):
    owner, pwd = make_user(email="owner@test.com", username="卖家")
    other, _ = make_user(email="other@test.com", username="别人")
    product = make_product()

    from auth import create_access_token

    def headers_for(user):
        return {
            "Authorization": f"Bearer {create_access_token(subject=str(user.id))}"
        }

    # owner 下一单
    r = client.post(
        "/api/orders",
        headers=headers_for(owner),
        json={"items": [{"product_id": product.id, "quantity": 1}]},
    )
    assert r.status_code == 201

    # other 看不到 owner 的订单
    r = client.get("/api/orders", headers=headers_for(other))
    assert r.status_code == 200
    assert r.json() == []


def test_订单详情_非本人返回403(client, make_user, make_product, db):
    owner, _ = make_user(email="owner2@test.com")
    intruder, intruder_pwd = make_user(email="intruder@test.com")
    product = make_product()

    from auth import create_access_token

    order = models_order(db, owner, product)
    intruder_token = create_access_token(subject=str(intruder.id))

    resp = client.get(
        f"/api/orders/{order.id}",
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert resp.status_code == 403


def test_订单状态_正常流转(client, auth_headers, make_product):
    product = make_product()
    order_id = client.post(
        "/api/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product.id, "quantity": 1}]},
    ).json()["id"]

    resp = client.patch(
        f"/api/orders/{order_id}/status",
        headers=auth_headers,
        json={"status": "paid"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


def test_订单状态_非法值返回422(client, auth_headers, make_product):
    product = make_product()
    order_id = client.post(
        "/api/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product.id, "quantity": 1}]},
    ).json()["id"]

    resp = client.patch(
        f"/api/orders/{order_id}/status",
        headers=auth_headers,
        json={"status": "exploded"},
    )
    assert resp.status_code == 422


def test_订单状态_重复设置相同状态返回400(client, auth_headers, make_product):
    product = make_product()
    order_id = client.post(
        "/api/orders",
        headers=auth_headers,
        json={"items": [{"product_id": product.id, "quantity": 1}]},
    ).json()["id"]

    # 新建订单默认 pending，再设为 pending 应被业务规则拒绝
    resp = client.patch(
        f"/api/orders/{order_id}/status",
        headers=auth_headers,
        json={"status": "pending"},
    )
    assert resp.status_code == 400


def test_更新不存在的订单返回404(client, auth_headers):
    resp = client.patch(
        "/api/orders/99999/status",
        headers=auth_headers,
        json={"status": "paid"},
    )
    assert resp.status_code == 404


def models_order(db, user, product):
    """直接构造一条订单（绕过 HTTP），供越权类测试使用。"""
    import models

    order = models.Order(user_id=user.id, status="pending", total=product.price)
    order.items.append(
        models.OrderItem(
            product_id=product.id, quantity=1, price=product.price
        )
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order
