"""
Сценарии диалогов: тесты вызывают только API по реальному HTTP (POST/GET).

Перед запуском тестов обязательно поднять сервер в другом терминале:
  uvicorn main:app --reload --port 8080
  (порт 8080, т.к. vLLM занимает 8000; URL в .env: api_base_url)
Затем: pytest tests/test_scenarios.py -v
Чтобы видеть session_id и ссылку на историю: pytest tests/test_scenarios.py -v -s
"""

import httpx
import pytest


def test_scenario_1_linear_simple_question(client: httpx.Client):
    """
    Сценарий 1: Линейный — простой вопрос.
    1. Пользователь: «Сколько будет 2 + 2?»
    2. Ожидание: ответ модели содержит «4» (или эквивалент).
    3. Проверка: сообщения сохранены в БД, история доступна по session_id.
    """
    # 1. Отправляем сообщение через API
    response = client.post(
        "/chat",
        json={"content": "Сколько будет 2 + 2?"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "session_id" in data
    assert "message" in data
    session_id = data["session_id"]
    answer = data["message"].strip().lower()

    # 2. Ожидание: в ответе есть 4 (число или слово)
    assert "4" in answer or "четыре" in answer, (
        f"Ожидалось, что в ответе модели есть '4' или 'четыре', получено: {data['message']!r}"
    )

    # 3. Проверка: в БД по session_id сохранены оба сообщения (читаем через API)
    history_response = client.get(f"/chat/{session_id}")
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()
    assert history["session_id"] == session_id
    messages = history["messages"]
    assert len(messages) == 2, "В истории должны быть 2 сообщения: пользователь и модель"
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Сколько будет 2 + 2?"
    assert messages[1]["role"] == "assistant"
    assert "4" in messages[1]["content"] or "четыре" in messages[1]["content"].lower()
    # Вывод для проверки по session_id вручную
    link = f"{client.base_url}/chat/{session_id}"
    print(f"\n  [Сценарий 1] session_id: {session_id}\n  История в БД: {link}")


def test_scenario_2_linear_several_messages(client: httpx.Client):
    """
    Сценарий 2: Линейный — несколько сообщений подряд.
    1. Пользователь: «Привет!»
    2. Модель отвечает.
    3. Пользователь: «Как тебя зовут?» (та же сессия)
    4. Модель отвечает.
    5. Проверка: в БД по session_id в истории 4 сообщения (2 user, 2 assistant).
    """
    # 1–2. Первое сообщение, получаем session_id (в БД сохраняется автоматически)
    r1 = client.post("/chat", json={"content": "Привет!"})
    assert r1.status_code == 200, r1.text
    data1 = r1.json()
    session_id = data1["session_id"]
    assert session_id, "API должен вернуть session_id"

    # 3–4. Второе сообщение в ту же сессию
    r2 = client.post("/chat", json={"content": "Как тебя зовут?", "session_id": session_id})
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["session_id"] == session_id
    assert data2.get("message") is not None, "Модель должна ответить"

    # 5. Проверка: в БД по session_id ровно 4 сообщения (2 user, 2 assistant)
    history_response = client.get(f"/chat/{session_id}")
    assert history_response.status_code == 200, history_response.text
    history = history_response.json()
    assert history["session_id"] == session_id, "История должна быть привязана к тому же session_id"
    messages = history["messages"]
    assert len(messages) == 4, (
        f"В БД по session_id должно быть 4 сообщения (2 user, 2 assistant), получено: {len(messages)}"
    )
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant", "user", "assistant"], (
        f"Ожидался порядок user, assistant, user, assistant; получено: {roles}"
    )
    assert messages[0]["content"] == "Привет!"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["content"] == "Как тебя зовут?"
    assert messages[3]["role"] == "assistant"
    # Вывод для проверки по session_id вручную
    link = f"{client.base_url}/chat/{session_id}"
    print(f"\n  [Сценарий 2] session_id: {session_id}\n  История в БД: {link}")


REQUEST_CHOOSE_TOPIC = (
    "Хочу выучить что-нибудь новое. Предложи тему: математика или история."
)


USER_CHOOSE_MATH = "объясни дискриминант квадратного уравнения кратко"
USER_CHOOSE_HISTORY = "расскажи исторический факт кратко"


def test_scenario_3_branch_mathematics(client: httpx.Client):
    """
    Сценарий 3 (ветка А): пользователь выбирает математику — тема «дискриминант».
    1. Пользователь просит предложить тему: математика или история.
    2. Модель предлагает темы.
    3. Пользователь: «объясни дискриминант квадратного уравнения кратко» → модель отвечает; проверка: 4 сообщения в истории.
    """
    r1 = client.post("/chat", json={"content": REQUEST_CHOOSE_TOPIC})
    assert r1.status_code == 200, r1.text
    session_id = r1.json()["session_id"]

    r2 = client.post("/chat", json={"content": USER_CHOOSE_MATH, "session_id": session_id})
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["session_id"] == session_id
    assert data2.get("message"), f"Модель должна ответить на запрос: {USER_CHOOSE_MATH!r}"

    hist = client.get(f"/chat/{session_id}")
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert len(messages) == 4
    link = f"{client.base_url}/chat/{session_id}"
    print(f"\n  [Сценарий 3 — математика] session_id: {session_id}\n  История в БД: {link}")


def test_scenario_3_branch_history(client: httpx.Client):
    """
    Сценарий 3 (ветка Б): пользователь выбирает историю — тема «исторический факт».
    1. Пользователь просит предложить тему: математика или история.
    2. Модель предлагает темы.
    3. Пользователь: «расскажи исторический факт кратко» → модель отвечает; проверка: 4 сообщения в истории.
    """
    r1 = client.post("/chat", json={"content": REQUEST_CHOOSE_TOPIC})
    assert r1.status_code == 200, r1.text
    session_id = r1.json()["session_id"]

    r2 = client.post("/chat", json={"content": USER_CHOOSE_HISTORY, "session_id": session_id})
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["session_id"] == session_id
    assert data2.get("message"), f"Модель должна ответить на запрос: {USER_CHOOSE_HISTORY!r}"

    hist = client.get(f"/chat/{session_id}")
    assert hist.status_code == 200
    messages = hist.json()["messages"]
    assert len(messages) == 4
    link = f"{client.base_url}/chat/{session_id}"
    print(f"\n  [Сценарий 3 — история] session_id: {session_id}\n  История в БД: {link}")
