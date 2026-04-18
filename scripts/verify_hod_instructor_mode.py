import json
import re
import urllib.error
import urllib.request
import http.cookiejar

BASE = "http://127.0.0.1:5000"
HEAD_USER = "HEAD-MOHAMED"
HEAD_PASS = "HeadTemp!2026"


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(self, path: str):
        req = urllib.request.Request(BASE + path, method="GET")
        with self.opener.open(req, timeout=20) as r:
            return r.getcode(), r.read().decode("utf-8", errors="replace")

    def post_json(self, path: str, payload: dict, csrf: str = ""):
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRFToken"] = csrf
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=20) as r:
                return r.getcode(), r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def csrf(self) -> str:
        _, html = self.get("/login")
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        return m.group(1) if m else ""


def main():
    cli = Client()
    ok = True

    def check(name: str, condition: bool, details: str = ""):
        nonlocal ok
        if condition:
            print(f"[PASS] {name}")
        else:
            ok = False
            print(f"[FAIL] {name} :: {details}")

    code, body = cli.post_json("/auth/login", {"username": HEAD_USER, "password": HEAD_PASS})
    check("login", code == 200, f"status={code} body={body[:120]}")

    csrf = cli.csrf()
    code, body = cli.post_json("/auth/active_mode", {"mode": "head"}, csrf=csrf)
    check("switch -> head", code == 200, f"status={code} body={body[:120]}")

    code, body = cli.get("/students/attendance_allowed_courses")
    head_count = -1
    if code == 200:
        j = json.loads(body)
        head_count = len(j.get("courses", []))
    check("attendance list in head mode", code == 200 and head_count >= 0, f"status={code} count={head_count}")

    code, body = cli.post_json("/auth/active_mode", {"mode": "instructor"}, csrf=csrf)
    check("switch -> instructor", code == 200, f"status={code} body={body[:120]}")

    code, body = cli.get("/auth/check")
    caps = {}
    if code == 200:
        caps = (json.loads(body) or {}).get("capabilities") or {}
    check(
        "instructor mode cannot manage schedule edit",
        caps.get("can_manage_schedule_edit") is False,
        f"can_manage_schedule_edit={caps.get('can_manage_schedule_edit')}",
    )

    code, body = cli.get("/students/attendance_allowed_courses")
    instructor_count = -1
    if code == 200:
        j = json.loads(body)
        instructor_count = len(j.get("courses", []))
    check(
        "attendance list in instructor mode",
        code == 200 and instructor_count >= 0,
        f"status={code} count={instructor_count}",
    )
    check(
        "instructor attendance is scoped (<= head mode)",
        instructor_count <= head_count if (instructor_count >= 0 and head_count >= 0) else False,
        f"head_count={head_count}, instructor_count={instructor_count}",
    )

    code, body = cli.get("/transcript_page")
    redirected_to_my_courses = ("/my_courses" in body) or ("مقرراتي" in body)
    check("transcript hidden in instructor mode", redirected_to_my_courses, f"status={code}")

    code, body = cli.post_json(
        "/exams/midterm/add_row",
        {
            "course_name": "__probe__",
            "exam_date": "2026-06-01",
            "exam_time": "09:00-12:00",
            "room": "R1",
            "instructor": "Probe",
        },
        csrf=csrf,
    )
    check("midterm edit blocked in instructor mode", code in (401, 403), f"status={code} body={body[:120]}")

    print(f"HEAD_ATTENDANCE_COUNT={head_count}")
    print(f"INSTRUCTOR_ATTENDANCE_COUNT={instructor_count}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
