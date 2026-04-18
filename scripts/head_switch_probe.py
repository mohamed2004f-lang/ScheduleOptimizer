import json
import os
import re
import urllib.request
import urllib.error
import http.cookiejar


BASE = "http://127.0.0.1:5000"
ADMIN_USER = os.environ.get("PROBE_ADMIN_USER", "admin-mohamed")
ADMIN_PASS = os.environ.get("PROBE_ADMIN_PASS", "123456")
HEAD_USER = os.environ.get("PROBE_HEAD_USER", "HEAD-MOHAMED")
HEAD_PASS = os.environ.get("PROBE_HEAD_PASS", "HeadTemp!2026")
HEAD_INSTRUCTOR_ID = int(os.environ.get("PROBE_HEAD_INSTRUCTOR_ID", "2"))


class Client:
    def __init__(self):
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))

    def get(self, path: str) -> str:
        req = urllib.request.Request(BASE + path, method="GET")
        with self.opener.open(req, timeout=15) as r:
            return r.read().decode("utf-8", errors="replace")

    def get_status(self, path: str) -> tuple[int, str]:
        req = urllib.request.Request(BASE + path, method="GET")
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.getcode(), r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def post_json(self, path: str, payload: dict, csrf: str | None = None) -> tuple[int, str]:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-CSRFToken"] = csrf
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method="POST")
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.getcode(), r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", errors="replace")

    def csrf(self) -> str:
        html = self.get("/login")
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        if not m:
            return ""
        return m.group(1)


def main():
    ok = True

    def check(name: str, condition: bool, details: str = ""):
        nonlocal ok
        if condition:
            print(f"[PASS] {name}")
        else:
            ok = False
            msg = f"[FAIL] {name}"
            if details:
                msg += f" :: {details}"
            print(msg)

    admin = Client()
    code, out = admin.post_json("/auth/login", {"username": ADMIN_USER, "password": ADMIN_PASS})
    print("ADMIN_LOGIN", code, out)
    check("admin login", code == 200, out[:200])

    code_u, users_raw = admin.post_json("/auth/check", {})
    print("AUTH_CHECK_AFTER_ADMIN_LOGIN", code_u, users_raw)

    users = admin.get("/users/list")
    print("USERS_LIST", users)

    csrf_admin = admin.csrf()
    code_upd, upd = admin.post_json(
        "/users/add",
        {
            "username": HEAD_USER,
            "password": HEAD_PASS,
            "role": "head_of_department",
            "instructor_id": HEAD_INSTRUCTOR_ID,
            "is_supervisor": True,
            "is_active": True,
        },
        csrf=csrf_admin,
    )
    print("HEAD_UPDATE", code_upd, upd)
    check("head user update", code_upd == 200, upd[:200])

    head = Client()
    code_h, out_h = head.post_json("/auth/login", {"username": HEAD_USER, "password": HEAD_PASS})
    print("HEAD_LOGIN", code_h, out_h)
    check("head login", code_h == 200, out_h[:200])

    print("HEAD_CHECK_1", head.get("/auth/check"))

    code_sw1, sw1 = head.post_json("/auth/active_mode", {"mode": "instructor"}, csrf=head.csrf())
    print("HEAD_SWITCH_TO_INSTRUCTOR", code_sw1, sw1)
    check("switch to instructor", code_sw1 == 200, sw1[:200])
    print("HEAD_CHECK_2", head.get("/auth/check"))
    my_courses_status, my_courses_body = head.get_status("/my_courses")
    print("HEAD_MY_COURSES_PAGE", my_courses_status, my_courses_body[:180].replace("\n", " "))
    check("my_courses page open", my_courses_status == 200, my_courses_body[:120])
    assigned_status, assigned_body = head.get_status("/schedule/my_assigned_sections")
    print("HEAD_ASSIGNED_SECTIONS", assigned_status, assigned_body[:280])
    check("assigned sections api", assigned_status == 200, assigned_body[:180])

    code_sw2, sw2 = head.post_json("/auth/active_mode", {"mode": "supervisor"}, csrf=head.csrf())
    print("HEAD_SWITCH_TO_SUPERVISOR", code_sw2, sw2)
    check("switch to supervisor", code_sw2 == 200, sw2[:200])
    print("HEAD_CHECK_3", head.get("/auth/check"))
    if not ok:
        raise SystemExit(1)
    print("[PASS] probe completed successfully")


if __name__ == "__main__":
    main()
