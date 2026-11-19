"""模块契约用例：幂等 / 状态机 / 错误码三件事，每个新模块都照这套断言。"""


def test_create_then_duplicate_conflicts(client):
    body = {"biz_key": "k-1", "title": "t"}
    assert client.post("/example", json=body).status_code == 201
    r = client.post("/example", json=body)
    assert r.status_code == 409
    assert r.json()["code"] == "CONFLICT"      # 幂等：重复提交不落两条


def test_illegal_transition_rejected(client):
    r = client.post("/example/draft/transition", json={"target": "approved"})
    assert r.status_code == 412
    assert r.json()["code"] == "PRECONDITION"  # 状态机：非法流转拒绝，而非静默


def test_unknown_state_rejected(client):
    r = client.post("/example/ghost/transition", json={"target": "approved"})
    assert r.status_code == 412


def test_validation_error_is_4xx_not_500(client):
    r = client.post("/example", json={"biz_key": "", "title": ""})
    assert 400 <= r.status_code < 500          # 参数校验不泄成 500
