"""
Нагрузочное тестирование Chat API (FastAPI + vLLM + PostgreSQL).

Режимы:
1) Поиск точки поломки (рекомендуется): нагрузка растёт до первой деградации.
   locust -f locustfile.py --host=http://localhost:8080 --headless -t 30m --html=report.html --csv=report
   $env:FIND_BREAKING_POINT="1"

2) Обычный: останов при >= 20 ошибок или медиана > 20 с.
   locust -f locustfile.py --host=http://localhost:8080 --headless --html=report.html --csv=report

Переменные окружения:
  FIND_BREAKING_POINT=1         — режим «найти точку поломки» (p95 > 5 с, 10 users/step, 10 s step, max 400 users)
  FAILURE_THRESHOLD             — останов при числе ошибок >= (по умолч. 20; в режиме breaking point = 1)
  RESPONSE_TIME_THRESHOLD_SEC   — останов при задержке > N с (по умолч. 20; в режиме breaking point = 5)
  RESPONSE_TIME_USE_P95=1       — использовать p95 вместо медианы
  STEP_DURATION                 — секунд между шагами (в режиме breaking point = 10)
  USERS_PER_STEP                — пользователей за шаг (в режиме breaking point = 10)
  MAX_USERS                     — макс. пользователей (в режиме breaking point = 400)
"""

import os
from locust import HttpUser, LoadTestShape, task, between
from locust import events

# Тексты из сценариев (как в test_scenarios.py)
REQUEST_CHOOSE_TOPIC = "Хочу выучить что-нибудь новое. Предложи тему: математика или история."
USER_CHOOSE_MATH = "объясни дискриминант квадратного уравнения кратко"
USER_CHOOSE_HISTORY = "расскажи исторический факт кратко"


class ChatAPIUser(HttpUser):
    """Пользователь, имитирующий сценарии 1, 2 и 3 (ветки математика/история)."""

    wait_time = between(1, 3)
    connection_timeout = 10
    # Таймаут на запрос задаём в каждом request (vLLM может отвечать долго)
    CHAT_TIMEOUT = 120

    @task(weight=1)
    def scenario_1_linear_simple_question(self):
        """Сценарий 1: один вопрос «2+2?», затем чтение истории по session_id."""
        with self.client.post(
            "/chat",
            json={"content": "Сколько будет 2 + 2?"},
            name="POST /chat [scenario_1]",
            catch_response=True,
            timeout=self.CHAT_TIMEOUT,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            try:
                data = r.json()
                session_id = data.get("session_id")
                if not session_id:
                    r.failure("no session_id")
                    return
            except Exception as e:
                r.failure(str(e))
                return

        self.client.get(
            f"/chat/{session_id}",
            name="GET /chat/{id} [scenario_1]",
        )

    @task(weight=1)
    def scenario_2_linear_several_messages(self):
        """Сценарий 2: «Привет!» → «Как тебя зовут?» в одной сессии, затем история."""
        with self.client.post(
            "/chat",
            json={"content": "Привет!"},
            name="POST /chat [scenario_2 msg1]",
            catch_response=True,
            timeout=self.CHAT_TIMEOUT,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            try:
                session_id = r.json().get("session_id")
                if not session_id:
                    r.failure("no session_id")
                    return
            except Exception as e:
                r.failure(str(e))
                return

        self.client.post(
            "/chat",
            json={"content": "Как тебя зовут?", "session_id": session_id},
            name="POST /chat [scenario_2 msg2]",
            timeout=self.CHAT_TIMEOUT,
        )
        self.client.get(
            f"/chat/{session_id}",
            name="GET /chat/{id} [scenario_2]",
        )

    @task(weight=1)
    def scenario_3_branch_mathematics(self):
        """Сценарий 3 (ветка А): выбор темы → запрос про дискриминант."""
        with self.client.post(
            "/chat",
            json={"content": REQUEST_CHOOSE_TOPIC},
            name="POST /chat [scenario_3 topic]",
            catch_response=True,
            timeout=self.CHAT_TIMEOUT,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            try:
                session_id = r.json().get("session_id")
                if not session_id:
                    r.failure("no session_id")
                    return
            except Exception as e:
                r.failure(str(e))
                return

        self.client.post(
            "/chat",
            json={"content": USER_CHOOSE_MATH, "session_id": session_id},
            name="POST /chat [scenario_3 math]",
            timeout=self.CHAT_TIMEOUT,
        )
        self.client.get(
            f"/chat/{session_id}",
            name="GET /chat/{id} [scenario_3 math]",
        )

    @task(weight=1)
    def scenario_3_branch_history(self):
        """Сценарий 3 (ветка Б): выбор темы → запрос про исторический факт."""
        with self.client.post(
            "/chat",
            json={"content": REQUEST_CHOOSE_TOPIC},
            name="POST /chat [scenario_3 topic]",
            catch_response=True,
            timeout=self.CHAT_TIMEOUT,
        ) as r:
            if r.status_code != 200:
                r.failure(f"status {r.status_code}")
                return
            try:
                session_id = r.json().get("session_id")
                if not session_id:
                    r.failure("no session_id")
                    return
            except Exception as e:
                r.failure(str(e))
                return

        self.client.post(
            "/chat",
            json={"content": USER_CHOOSE_HISTORY, "session_id": session_id},
            name="POST /chat [scenario_3 history]",
            timeout=self.CHAT_TIMEOUT,
        )
        self.client.get(
            f"/chat/{session_id}",
            name="GET /chat/{id} [scenario_3 history]",
        )


# --- Step load: add users over time, stop when failures or response time exceed threshold ---

def _env_bool(key: str, default: str = "0") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes")

FIND_BREAKING_POINT = _env_bool("FIND_BREAKING_POINT")

if FIND_BREAKING_POINT:
    FAILURE_THRESHOLD = int(os.environ.get("FAILURE_THRESHOLD", "1"))
    RESPONSE_TIME_THRESHOLD_SEC = float(os.environ.get("RESPONSE_TIME_THRESHOLD_SEC", "5"))
    RESPONSE_TIME_USE_P95 = _env_bool("RESPONSE_TIME_USE_P95", "1")
    STEP_DURATION = int(os.environ.get("STEP_DURATION", "10"))
    USERS_PER_STEP = int(os.environ.get("USERS_PER_STEP", "10"))
    MAX_USERS = int(os.environ.get("MAX_USERS", "400"))
else:
    FAILURE_THRESHOLD = int(os.environ.get("FAILURE_THRESHOLD", "20"))
    RESPONSE_TIME_THRESHOLD_SEC = float(os.environ.get("RESPONSE_TIME_THRESHOLD_SEC", "20"))
    RESPONSE_TIME_USE_P95 = _env_bool("RESPONSE_TIME_USE_P95", "0")
    STEP_DURATION = int(os.environ.get("STEP_DURATION", "10"))
    USERS_PER_STEP = int(os.environ.get("USERS_PER_STEP", "2"))
    MAX_USERS = int(os.environ.get("MAX_USERS", "50"))


class StepLoadStopOnThreshold(LoadTestShape):
    """
    Пошаговый рост нагрузки. Останов при:
    - числу ошибок >= FAILURE_THRESHOLD,
    - медиана или p95 времени ответа > RESPONSE_TIME_THRESHOLD_SEC.
    Режим FIND_BREAKING_POINT=1 — агрессивнее рост и останов на первой деградации.
    """

    def tick(self):
        run_time = self.get_run_time()
        if run_time is None:
            return None

        step_index = int(run_time // STEP_DURATION)
        user_count = min(MAX_USERS, USERS_PER_STEP * max(1, step_index + 1))
        spawn_rate = USERS_PER_STEP

        env = getattr(self, "environment", None)
        runner = getattr(env, "runner", None) if env else None
        if runner and getattr(runner, "stats", None):
            total = runner.stats.total
            num_failures = total.num_failures
            if num_failures >= FAILURE_THRESHOLD:
                return None
            threshold_ms = RESPONSE_TIME_THRESHOLD_SEC * 1000
            if RESPONSE_TIME_USE_P95:
                get_p95 = getattr(total, "get_response_time_percentile", None)
                p95 = get_p95(0.95) if get_p95 else None
                if p95 is not None and p95 > threshold_ms:
                    return None
            else:
                median_ms = total.median_response_time
                if median_ms is not None and median_ms > threshold_ms:
                    return None

        return (user_count, spawn_rate)


# --- Final "bottleneck found under these rules" message to console and HTML ---

def _bottleneck_summary(environment) -> tuple[str, dict]:
    """Build message and key stats. Returns (message_line, stats_dict)."""
    runner = getattr(environment, "runner", None)
    stats_dict = {
        "failures": 0,
        "median_ms": None,
        "p95_ms": None,
        "user_count": 0,
        "total_requests": 0,
    }
    if runner and getattr(runner, "stats", None):
        total = runner.stats.total
        stats_dict["failures"] = total.num_failures
        stats_dict["median_ms"] = total.median_response_time
        get_p95 = getattr(total, "get_response_time_percentile", None)
        stats_dict["p95_ms"] = get_p95(0.95) if get_p95 else None
        stats_dict["total_requests"] = total.num_requests
        stats_dict["user_count"] = getattr(runner, "user_count", 0) or 0
    rules = (
        f"p95<={RESPONSE_TIME_THRESHOLD_SEC}s, failures<{FAILURE_THRESHOLD}, "
        f"step={STEP_DURATION}s, +{USERS_PER_STEP} users/step, max_users={MAX_USERS}"
    )
    if stats_dict["failures"] >= FAILURE_THRESHOLD:
        msg = f"Bottleneck found under these rules (failures >= {FAILURE_THRESHOLD}). Rules: {rules}"
    elif RESPONSE_TIME_USE_P95 and stats_dict["p95_ms"] and stats_dict["p95_ms"] > RESPONSE_TIME_THRESHOLD_SEC * 1000:
        msg = f"Bottleneck found under these rules (p95 > {RESPONSE_TIME_THRESHOLD_SEC}s). Rules: {rules}"
    else:
        msg = f"Test passed. Bottleneck not reached under these rules. Rules: {rules}"
    return msg, stats_dict


def _inject_banner_into_html(report_path: str, banner_html: str) -> None:
    """Insert banner right after <body> or before </body> in report.html."""
    try:
        with open(report_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "</body>" in content and banner_html not in content:
            content = content.replace("</body>", f"{banner_html}</body>", 1)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(content)
    except Exception:
        pass


@events.quitting.add_listener
def _on_quitting(environment, **kwargs):
    msg, stats = _bottleneck_summary(environment)
    print("\n" + "=" * 72)
    print("LOCUST RESULT: " + msg)
    print("  failures=%s, median_ms=%s, p95_ms=%s, user_count=%s, total_requests=%s" % (
        stats["failures"], stats["median_ms"], stats["p95_ms"], stats["user_count"], stats["total_requests"]))
    print("  (Same message written to report_bottleneck.html)")
    print("=" * 72 + "\n")

    banner = (
        '<div style="margin:12px;padding:12px;background:#1a237e;color:#fff;font-family:sans-serif;border-radius:8px;">'
        "<strong>LOCUST RESULT:</strong> %s<br>"
        "failures=%s, median_ms=%s, p95_ms=%s, user_count=%s, total_requests=%s"
        "</div>"
    ) % (msg.replace("<", "&lt;"), stats["failures"], stats["median_ms"], stats["p95_ms"], stats["user_count"], stats["total_requests"])

    with open("report_bottleneck.html", "w", encoding="utf-8") as f:
        f.write(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Bottleneck</title></head><body>%s</body></html>"
            % banner
        )
    report_path = getattr(getattr(environment, "parsed_options", None), "html", None)
    if report_path and os.path.isfile(report_path):
        _inject_banner_into_html(report_path, banner)
    elif os.path.isfile("report.html"):
        _inject_banner_into_html("report.html", banner)
