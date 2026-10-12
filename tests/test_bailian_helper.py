"""bailian_helper 单测（车道 B）：纯函数 + 假对象，无 webview、无网络、无真实凭据。

覆盖：命令 JSON 解析校验、gateway_post 同构表单体构造（引 gw 常量对比结构）、
登录态子串分类器、LOGIN_SELECTORS 降级逻辑（假 window）、单实例锁死 PID 接管、
save_creds 明文纪律、status/BAD_CMD/shutdown 响应。
运行：python -m pytest tests/test_bailian_helper.py -v
安全：全部用 tmp_path；绝不写 local/、绝不触碰真实凭据（store_login_creds 打桩）。
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import types
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import bailian_helper as bh                      # noqa: E402
from src.sources import bailian_gateway as gw             # noqa: E402


# ================================================================ 命令解析

class TestParseCommand:
    def test_valid_poll(self):
        assert bh.parse_command('{"cmd":"poll","id":1}') == {"cmd": "poll", "id": 1}

    def test_valid_save_creds_passthrough(self):
        obj = bh.parse_command('{"cmd":"save_creds","id":2,"username":"u","password":"p"}')
        assert obj is not None and obj["username"] == "u"

    def test_blank_line_skipped(self):
        assert bh.parse_command("") is None
        assert bh.parse_command("   \n") is None

    def test_not_json_raises(self):
        with pytest.raises(bh.CommandError):
            bh.parse_command("hello world")

    def test_json_array_raises(self):
        with pytest.raises(bh.CommandError):
            bh.parse_command('[1,2]')

    def test_missing_cmd_raises(self):
        with pytest.raises(bh.CommandError):
            bh.parse_command('{"id":1}')

    def test_nonstring_cmd_raises(self):
        with pytest.raises(bh.CommandError):
            bh.parse_command('{"cmd":123}')

    def test_known_cmds_cover_protocol(self):
        # reauth：2026-10-12 M26 增补（协议 §2，交互重登/换账号，跳过 live 短路）
        assert bh.KNOWN_CMDS == {"poll", "login_interactive", "reauth",
                                "status", "shutdown", "save_creds"}


class TestResponses:
    def test_error_response_detail_truncated(self):
        r = bh.error_response(5, "HELPER_ERROR", "x" * 999)
        assert r["id"] == 5 and r["ok"] is False and r["error"] == "HELPER_ERROR"
        assert len(r["detail"]) <= bh.DETAIL_MAX

    def test_safe_detail_collapses_newlines(self):
        assert bh.safe_detail("a\n b\r\nc") == "a b c"


# ================================================================ 请求构造 vs gateway_post

def _reference_construction(api: str, sec_token: str, data_extra: dict | None,
                            trace_id: str, x_anon: str = ""):
    """gateway_post 的表单体/URL 构造逐字段复刻（作为对照基准，不 import 其网络部分）。"""
    cornerstone = {
        "feTraceId": f"helper|{trace_id}",
        "feURL": gw.DASHBOARD_URL,
        "protocol": "V2",
        "console": "ONE_CONSOLE",
        "productCode": "p_efm",
        "switchUserType": 3,
        "domain": "bailian.console.aliyun.com",
        "consoleSite": "BAILIAN_ALIYUN",
        "userNickName": "",
        "userPrincipalName": "",
        "xsp_lang": "zh-CN",
    }
    if x_anon:
        cornerstone["X-Anonymous-Id"] = x_anon
    data = {"commodityCode": gw.COMMODITY, **(data_extra or {}),
            "cornerstoneParam": cornerstone}
    params = {"Api": api, "V": "1.0", "Data": data}
    body = {
        "product": gw.PRODUCT, "action": gw.ACTION, "region": gw.REGION,
        "language": "zh-CN",
        "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
    }
    if sec_token:
        body["sec_token"] = sec_token
    url = (f"{gw.QUOTA_ORIGIN}/data/api.json?" + urllib.parse.urlencode(
        {"action": gw.ACTION, "product": gw.PRODUCT, "api": api,
         "_v": "undefined"}))
    return url, body


class TestBuildRequest:
    API = f"{gw.API_PREFIX}/usage"

    def test_url_and_body_equal_reference(self):
        url, body = bh.build_request(self.API, "", None, trace_id="abc123")
        rurl, rbody = _reference_construction(self.API, "", None, "abc123")
        assert url == rurl
        assert body == rbody
        assert list(body.keys()) == list(rbody.keys())       # 字段序同 gateway
        # params 内嵌 JSON 字符串逐字节一致（覆盖 Data/cornerstone 结构与顺序）
        assert body["params"] == rbody["params"]

    def test_sec_token_omitted_when_empty(self):
        _u, body = bh.build_request(self.API, "", None, trace_id="t")
        assert "sec_token" not in body

    def test_sec_token_present_when_given(self):
        _u, body = bh.build_request(self.API, "tok123", None, trace_id="t")
        assert body["sec_token"] == "tok123"
        _u2, ref = _reference_construction(self.API, "tok123", None, "t")
        assert body == ref

    def test_cornerstone_fields_match_gateway_semantics(self):
        _u, body = bh.build_request(self.API, "", None, trace_id="t")
        cs = json.loads(body["params"])["Data"]["cornerstoneParam"]
        # 规格硬禁令：不得带硬编码 switchAgent
        assert "switchAgent" not in cs
        assert cs["switchUserType"] == 3
        assert cs["protocol"] == "V2"
        assert cs["feURL"] == gw.DASHBOARD_URL
        # X-Anonymous-Id 仅在取到值时附带（gateway 的 cna 分支同构）
        assert "X-Anonymous-Id" not in cs
        _u2, body2 = bh.build_request(self.API, "", None, trace_id="t",
                                      x_anon_id="cnaXYZ")
        cs2 = json.loads(body2["params"])["Data"]["cornerstoneParam"]
        assert cs2["X-Anonymous-Id"] == "cnaXYZ"

    def test_trace_id_random_and_prefixed(self):
        _u, b1 = bh.build_request(self.API)
        _u, b2 = bh.build_request(self.API)
        cs1 = json.loads(b1["params"])["Data"]["cornerstoneParam"]
        cs2 = json.loads(b2["params"])["Data"]["cornerstoneParam"]
        assert cs1["feTraceId"].startswith("helper|")
        assert cs1["feTraceId"] != cs2["feTraceId"]

    def test_data_merge_rule_gateway_identical(self):
        """Data = {commodityCode, **data_extra, cornerstoneParam}（addon 覆盖）。"""
        _u, body = bh.build_request(f"{gw.API_PREFIX}/addon/list", "",
                                    bh.API_ENDPOINTS["addon"][1], trace_id="t")
        data = json.loads(body["params"])["Data"]
        assert list(data.keys())[:5] == ["commodityCode", "status", "pageNum",
                                         "pageSize", "cornerstoneParam"]
        assert data["commodityCode"] == gw.ADDON_COMMODITY   # data_extra 覆盖基线
        assert data["status"] == ["ACTIVE"]
        assert data["pageNum"] == 1 and data["pageSize"] == 10

    def test_api_endpoints_cover_four_apis(self):
        assert set(bh.API_ENDPOINTS) == {"subscription", "quota_config",
                                         "usage", "addon"}
        assert bh.API_ENDPOINTS["subscription"][0] == f"{gw.API_PREFIX}/subscription"
        assert bh.API_ENDPOINTS["quota_config"][0] == f"{gw.API_PREFIX}/quota-config"
        assert bh.API_ENDPOINTS["usage"][0] == f"{gw.API_PREFIX}/usage"
        assert bh.API_ENDPOINTS["addon"][0] == f"{gw.API_PREFIX}/addon/list"


class TestBuildFetchJs:
    def test_contains_protocol_options(self):
        url, body = bh.build_request(f"{gw.API_PREFIX}/usage", "tok", None,
                                     trace_id="t")
        js = bh.build_fetch_js("usage", url, body)
        assert "credentials:'include'" in js
        assert "method:'POST'" in js
        assert "'Content-Type':'application/x-www-form-urlencoded'" in js
        assert "'X-Requested-With':'XMLHttpRequest'" in js
        assert json.dumps(url) in js
        assert json.dumps(urllib.parse.urlencode(body)) in js
        assert "window.pywebview.api.report" in js

    def test_report_carries_status_and_text(self):
        url, body = bh.build_request(f"{gw.API_PREFIX}/usage", "", None, trace_id="t")
        js = bh.build_fetch_js("usage", url, body)
        assert "status:r.status" in js and "text:t" in js


# ================================================================ report 解析

class TestParseReport:
    def test_ok_payload(self):
        d = bh.parse_report(json.dumps({"status": 200, "text": '{"code":"SUCCESS"}'}))
        assert d["status"] == 200
        assert "SUCCESS" in d["text"]
        assert d["err"] is None

    def test_fetch_err(self):
        d = bh.parse_report(json.dumps({"fetch_err": "TypeError: Failed to fetch"}))
        assert d["err"] and d["text"] is None

    def test_none_is_error(self):
        assert bh.parse_report(None)["err"] == "no report"

    def test_plain_string_treated_as_text(self):
        d = bh.parse_report("not-json-envelope")
        assert d["text"] == "not-json-envelope" and d["err"] is None


# ================================================================ 登录态分类器

class TestClassifyEnvelope:
    def test_success_marker(self):
        assert bh.classify_envelope('{"code":"SUCCESS","data":{}}') == "live"

    def test_success_case_insensitive(self):
        assert bh.classify_envelope('{"Code":"success"}') == "live"

    def test_notlogined_variants(self):
        assert bh.classify_envelope('{"code":"Login.NotLogined"}') == "need_login"
        assert bh.classify_envelope('...needlogin...') == "need_login"
        assert bh.classify_envelope('NEEDLOGIN') == "need_login"

    def test_needlogin_beats_success_when_both(self):
        t = '{"ret":["SUCCESS"],"code":"NotLogined"}'
        assert bh.classify_envelope(t) == "need_login"

    def test_empty_and_none_error(self):
        assert bh.classify_envelope(None) == "error"
        assert bh.classify_envelope("") == "error"

    def test_other_unrelated_html(self):
        assert bh.classify_envelope("<html>captcha wall</html>") == "other"


_OK = '{"code":"SUCCESS"}'
_BAD = '{"code":"Login.NotLogined"}'


class TestRoundState:
    def _res(self, sub=_OK, qc=_OK, us=_OK, ad=_OK):
        return {"subscription": sub, "quota_config": qc, "usage": us, "addon": ad}

    def test_all_live(self):
        assert bh.round_state(self._res()) == "live"

    def test_any_login_gate_need_login(self):
        assert bh.round_state(self._res(us=_BAD)) == "need_login"
        assert bh.round_state(self._res(sub=_BAD)) == "need_login"

    def test_addon_not_in_login_gate(self):
        assert bh.round_state(self._res(ad=_BAD)) == "live"

    def test_all_missing_error(self):
        assert bh.round_state({"subscription": None, "quota_config": None,
                               "usage": None, "addon": None}) == "error"

    def test_other_when_no_marker(self):
        assert bh.round_state(self._res(us="<html>oops</html>",
                                        sub="<html>oops</html>",
                                        qc="<html>oops</html>",
                                        ad="<html>oops</html>")) == "other"


class TestExtractSecToken:
    def test_json_style(self):
        assert bh.extract_sec_token('{"data":{"sec_token":"abc123"}}') == "abc123"

    def test_camel_style(self):
        assert bh.extract_sec_token('{"data":{"secToken":"Xy_9"}}') == "Xy_9"

    def test_absent_returns_empty(self):
        assert bh.extract_sec_token('{"data":{}}') == ""
        assert bh.extract_sec_token(None) == ""


# ================================================================ 选择器降级（假 window）

def _spawn_dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.1)"])
    p.wait(timeout=15)
    return p.pid


class FakeWindow:
    """假 JS 桥：按脚本形态识别 可见性探针 / tab 点击 / 填充 / 提交 / 提交后
    只读诊断 五类调用并记录有序 calls 轨迹，供 autofill 时序断言
    （tab 在探针前、提交仅在填充 OK 后、诊断仅在提交后）。

    present        —— "可见"选择器集合（驱动 _VISIBLE_PROBE_JS 返回）
    fill_ok        —— 填充回读校验结果（False 时绝不允许出现提交脚本）
    tab_clicked    —— tab 脚本返回值（True 触发 TAB_SETTLE sleep）
    verify_result  —— 提交后探针返回值（dict 或 JSON 字符串；默认"已清栏"）
    verify_raise   —— 探针 evaluate_js 抛异常（吞异常路径）
    """

    _VIS_TAIL = re.compile(r'\}\)\((".*")\)\s*$', re.S)
    _SUB_RE = re.compile(r'querySelector\((".*?")\)')

    DEFAULT_VERIFY = {"inputs_cleared": True,
                      "url": "https://passport.aliyun.com/havanaone"
                             "/login/login.htm",
                      "err_text": ""}

    def __init__(self, present=(), raise_probe=False, fill_ok=True,
                 tab_clicked=False, verify_result=None, verify_raise=False):
        self.present = set(present)
        self.raise_probe = raise_probe
        self.fill_ok = fill_ok
        self.tab_clicked = tab_clicked
        self.verify_result = (dict(self.DEFAULT_VERIFY) if verify_result is None
                              else verify_result)
        self.verify_raise = verify_raise
        self.scripts: list[str] = []
        self.calls: list[tuple] = []

    def evaluate_js(self, script):
        self.scripts.append(script)
        if self.raise_probe:
            raise RuntimeError("evaluate_js boom")
        s = script.lstrip()
        if s.startswith("(function (sel)"):
            m = self._VIS_TAIL.search(script)
            sel = json.loads(m.group(1))
            self.calls.append(("vis", sel))
            return sel in self.present
        if s.startswith("(function (sels, texts)"):
            self.calls.append(("tab",))
            return self.tab_clicked
        if s.startswith("(function (uSel, uVal"):
            self.calls.append(("fill",))
            return "OK" if self.fill_ok else "FAIL"
        if s.startswith("(function ()"):                  # submit-verify 只读探针
            self.calls.append(("verify",))
            if self.verify_raise:
                raise RuntimeError("probe bridge boom")
            r = self.verify_result
            return dict(r) if isinstance(r, dict) else r
        if "b.click()" in s:
            m = self._SUB_RE.search(script)
            self.calls.append(("submit", json.loads(m.group(1))))
            return None
        return False


class TestLoginSelectorsTable:
    """表结构与 2026-10-10 local/selector_probe2.json 实测对齐。"""

    def test_probe_verified_entries(self):
        assert "#fm-login-id" in bh.LOGIN_SELECTORS["username"]
        assert "#fm-login-password" in bh.LOGIN_SELECTORS["password"]
        assert "form#login-form button[type=\"submit\"]" in bh.LOGIN_SELECTORS["submit"]
        assert "#fm-login-checkcode" in bh.LOGIN_SELECTORS["checkcode"]
        assert ".tabs-nav-item" in bh.LOGIN_SELECTORS["tab"]

    def test_each_step_nonempty_string_candidates(self):
        for key in ("tab", "username", "password", "submit", "checkcode"):
            lst = bh.LOGIN_SELECTORS[key]
            assert isinstance(lst, list) and lst, key        # 每步候选非空
            assert all(isinstance(x, str) and x.strip() for x in lst), key

    def test_tab_texts_present(self):
        assert "账密登录" in bh.LOGIN_TAB_TEXTS
        assert all(isinstance(t, str) and t for t in bh.LOGIN_TAB_TEXTS)

    def test_pwd_login_url_shape(self):
        assert bh.PWD_LOGIN_URL.startswith(
            "https://passport.aliyun.com/havanaone/login/login.htm")
        assert "appEntrance=aliyun_pc_pwd" in bh.PWD_LOGIN_URL   # 账密 entrance
        assert "returnUrl=https%3A%2F%2Faccount.aliyun.com" in bh.PWD_LOGIN_URL
        assert bh.PWD_LOGIN_HOST in bh.LOGIN_WAIT_HOSTS           # 泊航豁免覆盖


class TestAutofillFallback:
    def test_first_visible_candidate_preferred(self):
        w = FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                "button.fm-submit"))
        assert bh.first_visible(w, "username") == "#fm-login-id"
        assert bh.first_visible(w, "submit") == "button.fm-submit"   # 兜底候选

    def test_missing_required_selector_returns_false(self):
        w = FakeWindow()                          # 什么都不存在
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=0.05) == \
            {"submitted": False, "verify": "prefail"}
        # 关键：绝不发出含账密值的填充脚本、绝不提交
        assert all("pw-secret" not in s for s in w.scripts)
        assert "setVal" not in "".join(w.scripts)
        assert not [c for c in w.calls if c[0] in ("fill", "submit", "verify")]

    def test_ordered_sequence_tab_probe_fill_submit(self):
        """时序契约：tab(前) → 可见性探针 → 填充(回读OK) → 提交 → 只读诊断探针。"""
        w = FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                "form#login-form button[type=\"submit\"]"))
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=1.0, verify_wait=0.0) == \
            {"submitted": True, "verify": "cleared"}      # 默认探针=已清栏
        kinds = [c[0] for c in w.calls]
        assert kinds[0] == "tab"                              # tab 最先（no-op 也算调用过）
        assert "vis" in kinds
        assert kinds.index("fill") > kinds.index("vis")       # 探针确认后才填充
        assert kinds[-2:] == ["submit", "verify"]             # 提交后紧跟诊断
        assert w.calls[kinds.index("submit")] == \
            ("submit", "form#login-form button[type=\"submit\"]")
        # 凭据明文只进填充脚本，不进探针/tab/提交/诊断脚本
        cred_scripts = [s for s in w.scripts
                        if "user@x.com" in s or "pw-secret" in s]
        assert len(cred_scripts) == 1 and "setVal" in cred_scripts[0]

    def test_fill_verification_fail_never_submits(self):
        """回读校验 FAIL → 立即弃权，绝不发提交脚本、绝不跑提交后诊断。"""
        w = FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                "form#login-form button[type=\"submit\"]"),
                       fill_ok=False)
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0) == \
            {"submitted": False, "verify": "prefail"}
        assert not [c for c in w.calls if c[0] in ("submit", "verify")]

    def test_captcha_visible_abstains_without_creds(self):
        """风控验证码可见 → L2 弃权：账密不进任何脚本、不提交。"""
        w = FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                "form#login-form button[type=\"submit\"]",
                                 "#fm-login-checkcode"))
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=1.0) == \
            {"submitted": False, "verify": "prefail"}
        assert all("pw-secret" not in s for s in w.scripts)
        assert not [c for c in w.calls if c[0] in ("fill", "submit", "verify")]

    def test_hidden_checkcode_does_not_block(self):
        """常态验证码不可见（present 不含它）→ 正常走完提交 + 提交后诊断。"""
        w = FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                "button.fm-submit"))
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0,
                                 verify_wait=0.0) == \
            {"submitted": True, "verify": "cleared"}
        sub = [c for c in w.calls if c[0] == "submit"]
        assert sub and sub[-1][1] == "button.fm-submit"
        assert w.calls[-1][0] == "verify"

    def test_evaluate_js_exception_degrades_false(self):
        w = FakeWindow(raise_probe=True)
        assert bh.autofill_login(w, "u", "p", inputs_budget=0.05) == \
            {"submitted": False, "verify": "prefail"}


# ================================================================ save_creds（打桩 auth）

class TestStoreLoginCreds:
    def test_missing_lane_helper_error(self, monkeypatch):
        monkeypatch.setattr(bh, "_auth", None)
        r = bh.store_login_creds("u", "p")
        assert r["ok"] is False and r["error"] == "HELPER_ERROR"

    def test_saves_via_contract(self, monkeypatch):
        seen = {}

        class FakeAuth:
            @staticmethod
            def save_bailian_login(u, p):
                seen["creds"] = (u, p)

        monkeypatch.setattr(bh, "_auth", FakeAuth)
        assert bh.store_login_creds("u1", "p1")["ok"] is True
        assert seen["creds"] == ("u1", "p1")

    def test_valueerror_detail_never_leaks_secret(self, monkeypatch):
        class FakeAuth:
            @staticmethod
            def save_bailian_login(u, p):
                raise ValueError(f"blob too long for password {p}")

        monkeypatch.setattr(bh, "_auth", FakeAuth)
        r = bh.store_login_creds("u", "TOPSECRET")
        assert r["ok"] is False and r["error"] == "HELPER_ERROR"
        assert "TOPSECRET" not in json.dumps(r, ensure_ascii=False)

    def test_empty_payload_rejected_without_auth_call(self, monkeypatch):
        called = []

        class FakeAuth:
            @staticmethod
            def save_bailian_login(u, p):
                called.append(1)

        monkeypatch.setattr(bh, "_auth", FakeAuth)
        r = bh.store_login_creds("", "x")
        assert r["ok"] is False and not called


class TestLoadLoginCredsTolerance:
    def test_missing_function_returns_none(self, monkeypatch):
        class NoLane:
            pass

        monkeypatch.setattr(bh, "_auth", NoLane())
        assert bh.load_login_creds() is None

    def test_exception_swallowed(self, monkeypatch):
        class Boom:
            @staticmethod
            def load_bailian_login():
                raise OSError("CM unreadable")

        monkeypatch.setattr(bh, "_auth", Boom())
        assert bh.load_login_creds() is None


# ================================================================ 单实例锁

class TestInstanceLock:
    def test_acquire_write_pid_and_release_cleans(self, tmp_path):
        fd, path = bh.acquire_instance_lock(tmp_path)
        try:
            assert path == tmp_path / "helper.lock"
            assert int(path.read_text().strip()) == os.getpid()
        finally:
            bh.release_instance_lock(fd, path)
        assert not path.exists()

    def test_live_pid_lock_blocks_second_acquire(self, tmp_path):
        fd, _path = bh.acquire_instance_lock(tmp_path)
        try:
            with pytest.raises(bh.AlreadyLocked):
                bh.acquire_instance_lock(tmp_path)
        finally:
            bh.release_instance_lock(fd, _path)

    def test_dead_pid_takeover(self, tmp_path):
        dead = _spawn_dead_pid()
        assert not bh.pid_alive(dead)
        lock = tmp_path / "helper.lock"
        lock.write_text(f"{dead}\n", encoding="ascii")
        fd, path = bh.acquire_instance_lock(tmp_path)       # 接管陈旧锁
        try:
            assert int(path.read_text().strip()) == os.getpid()
        finally:
            bh.release_instance_lock(fd, path)

    def test_garbage_pid_treated_stale(self, tmp_path):
        lock = tmp_path / "helper.lock"
        lock.write_text("not-a-pid", encoding="ascii")
        fd, path = bh.acquire_instance_lock(tmp_path)       # 判不了 PID → 接管
        try:
            assert int(path.read_text().strip()) == os.getpid()
        finally:
            bh.release_instance_lock(fd, path)

    def test_creates_profile_dir(self, tmp_path):
        target = tmp_path / "nested" / "webview_profile"
        fd, path = bh.acquire_instance_lock(target)
        bh.release_instance_lock(fd, path)
        assert target.is_dir()

    def test_pid_alive_self(self):
        assert bh.pid_alive(os.getpid()) is True
        assert bh.pid_alive(0) is False
        assert bh.pid_alive(-1) is False


# ================================================================ 命令分发（status/BAD_CMD/shutdown）

def _mk_st(**over):
    st = {"window": None, "api": None, "stop": None, "state": "live",
          "hidden": True, "login_phase": None, "sec_box": [],
          "start_ts": time.time() - 12, "bye_emitted": False}
    st.update(over)
    return st


class TestHandleCommandSimple:
    def test_unknown_cmd_bad_cmd(self, capsys):
        assert bh.handle_command(_mk_st(), {"cmd": "bogus", "id": 9}) is False
        line = json.loads(capsys.readouterr().out.strip())
        assert line == {"id": 9, "ok": False, "error": "BAD_CMD"}

    def test_status_response_shape(self, capsys):
        assert bh.handle_command(_mk_st(), {"cmd": "status", "id": 3}) is False
        line = json.loads(capsys.readouterr().out.strip())
        assert line["id"] == 3
        assert line["state"] == "live"
        assert line["hidden"] is True
        assert isinstance(line["uptime_s"], int) and line["uptime_s"] >= 12

    def test_shutdown_requests_exit(self, capsys):
        assert bh.handle_command(_mk_st(), {"cmd": "shutdown"}) is True

    def test_worker_bad_line_then_shutdown(self, capsys):
        import queue as _q
        import threading as _th
        st = _mk_st(stop=_th.Event())
        q: _q.Queue = _q.Queue()
        q.put("this is not json\n")
        q.put('{"cmd":"shutdown"}\n')
        bh._worker(st, q)                       # 首眠 1s 后串行处理直至 shutdown
        out = [json.loads(x) for x in
               capsys.readouterr().out.splitlines() if x.strip()]
        assert {"id": None, "ok": False, "error": "BAD_CMD"} in out
        assert {"event": "bye"} in out
        assert st["stop"].is_set()


class TestEmit:
    def test_compact_single_line_json(self):
        buf = io.StringIO()
        bh.emit({"event": "login_done", "method": "silent", "cred_saved": False},
                stream=buf)
        s = buf.getvalue()
        assert s.endswith("\n") and s.count("\n") == 1
        assert ", " not in s                       # 无 pretty print
        assert json.loads(s) == {"event": "login_done", "method": "silent",
                                 "cred_saved": False}

    def test_unicode_envelope_roundtrip(self):
        buf = io.StringIO()
        bh.emit({"data": {"usage": '{"msg":"额度"}'}}, stream=buf)
        assert json.loads(buf.getvalue())["data"]["usage"] == '{"msg":"额度"}'


# ================================================================ §6 修订（2026-10-10）
# Bug I-1：静默 poll 绝不导航登录页；evaluate_js 异常必被捕获并 <15s 回包；
# 交互路径任何出口先落稳定页。假 window + 注入预算（快时钟），无 webview/网络。

_BAD_ENV = '{"code":"Login.NotLogined"}'
_OK_ENV = '{"code":"SUCCESS"}'


class _CredsAuth:
    @staticmethod
    def load_bailian_login():
        return ("user@example.com", "pw-not-secret")


class _NoCredsAuth:
    @staticmethod
    def load_bailian_login():
        return None


class PageWindow:
    """替身页面：fetch/info 脚本 → 立即按脚本里的 report 键回投 report；
    可选模拟 evaluate_js 卡死（hang 秒）或抛 WebViewException（raise_eval）。
    记录 load_url/show/restore/hide/on_top，全部可断言。"""

    _REPORT_RE = re.compile(r'pywebview\.api\.report\("([^"]+)"')

    def __init__(self, api, envelope=_BAD_ENV, hang=0.0, raise_eval=False,
                 switch_on_login=None):
        self.api = api
        self.envelope = envelope
        self.hang = hang
        self.raise_eval = raise_eval
        self.switch_on_login = switch_on_login   # 导航登录页后信封换成该值
        self.scripts: list[str] = []
        self.load_urls: list[str] = []
        self.win_ops: list[str] = []
        self.on_top_log: list[bool] = []
        self._on_top = False

    def evaluate_js(self, script):
        self.scripts.append(script)
        if self.raise_eval and self._REPORT_RE.search(script):
            raise RuntimeError("Main window failed to start")   # 替身 WebViewException
        if self.hang:
            time.sleep(self.hang)
        m = self._REPORT_RE.search(script)
        if not m:
            return False                          # 选择器探测 / SEC_TOKEN_JS
        key = m.group(1)
        if key.startswith("info"):
            self.api.report(key, '{"data":{}}')
        else:
            self.api.report(key, {"status": 200, "text": self.envelope})
        return None

    def load_url(self, url):
        self.load_urls.append(url)
        if url == bh.LOGIN_URL and self.switch_on_login is not None:
            self.envelope = self.switch_on_login

    def show(self):
        self.win_ops.append("show")

    def hide(self):
        self.win_ops.append("hide")

    def restore(self):
        self.win_ops.append("restore")

    @property
    def on_top(self):
        return self._on_top

    @on_top.setter
    def on_top(self, value):
        self.on_top_log.append(bool(value))
        self._on_top = bool(value)


def _round_st(window, **over):
    """默认快时钟注入：tick/等待全在毫秒级，POLL_DEADLINE 可测。"""
    st = {"window": window, "api": window.api, "stop": threading.Event(),
          "state": "unknown", "hidden": True, "login_phase": None,
          "sec_box": [], "start_ts": time.time(), "bye_emitted": False,
          "page_poisoned": False, "round_seq": 0,
          "poll_interval": 0.05, "await_recheck": 0.05,
          "manual_budget": 0.2, "silent_retry_wait": 0.05,
          "autofill_inputs_budget": 0.05}
    st.update(over)
    return st


def _traced_emit(monkeypatch, window):
    """emit 与 load_url 汇入同一条 trace（断言落地先于事件/响应）。"""
    trace = []
    real_emit = bh.emit

    def spy(obj, stream=None):
        trace.append(("emit", obj.get("event", "resp")))
        return real_emit(obj, stream=stream)

    monkeypatch.setattr(bh, "emit", spy)
    real_load = window.load_url

    def load(url):
        trace.append(("load", url))
        return real_load(url)

    window.load_url = load
    return trace


def _stdout_json(capsys) -> list[dict]:
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.strip()]


class TestProtocol6SilentPoll:
    def test_poll_deadline_leaves_margin_under_watchdog(self):
        # 13→20（2026-10-10 16:46 实证：console 重载后首轮页面重，13s 烧一轮）；
        # 仍须为 45s 看门狗留足余量（deadline 硬护栏 + 回包开销）。
        assert bh.POLL_DEADLINE == 20.0
        assert bh.POLL_DEADLINE + 15.0 < 45.0     # §6 修订：必回，看门狗无把柄

    def test_eval_exception_answers_error_within_deadline(self, capsys):
        w = PageWindow(bh.Api(), raise_eval=True)
        st = _round_st(w)
        t0 = time.monotonic()
        bh.handle_command(st, {"cmd": "poll", "id": 7})
        elapsed = time.monotonic() - t0
        line = _stdout_json(capsys)[-1]
        assert elapsed < 15.0                      # 实际为毫秒级（异常即被捕获）
        assert line["id"] == 7 and line["state"] == "error"
        assert line["error"] == "HELPER_ERROR" and line["detail"] == "fetch-timeout"
        assert st["page_poisoned"] is True         # 下轮 poll 重载 console 自愈
        assert bh.LOGIN_URL not in w.load_urls     # 绝不导航登录页

    def test_hang_abandoned_at_budget_not_83s(self, capsys):
        """注入 poll_deadline=0.5（替身 13s）：卡死的 evaluate_js 被弃轮，
        响应在预算处返回——不再是旧行为（每接口 20s×4≈83s 挂死）。"""
        w = PageWindow(bh.Api(), hang=2.0)
        st = _round_st(w, poll_deadline=0.5)
        t0 = time.monotonic()
        bh.handle_command(st, {"cmd": "poll", "id": 8})
        elapsed = time.monotonic() - t0
        line = _stdout_json(capsys)[-1]
        assert 0.5 <= elapsed < 15.0
        assert line["state"] == "error" and line["detail"] == "fetch-timeout"
        assert bh.LOGIN_URL not in w.load_urls

    def test_silent_never_navigates_login_console_reload_once(self, monkeypatch, capsys):
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w)
        bh.handle_command(st, {"cmd": "poll", "id": 9})
        line = _stdout_json(capsys)[-1]
        assert line["state"] == "need_login" and line["error"] == "LOGIN_EXPIRED"
        assert w.load_urls == [bh.CONSOLE_URL]     # 仅允许这一次 console 重载

    def test_silent_without_credential_zero_navigation(self, monkeypatch, capsys):
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w)
        bh.handle_command(st, {"cmd": "poll", "id": 10})
        line = _stdout_json(capsys)[-1]
        assert line["state"] == "no_credential" and line["error"] == "NO_CREDENTIAL"
        assert w.load_urls == []

    def test_report_keys_unique_per_round(self):
        """弃轮僵尸的迟到 report 不能串进新一轮：report 键按 round_seq 隔离。"""
        w = PageWindow(bh.Api())
        st = _round_st(w)
        bh._guarded_round(st, 5.0)
        bh._guarded_round(st, 5.0)
        keys = [m.group(1) for s in w.scripts if (m := PageWindow._REPORT_RE.search(s))]
        assert any(k.endswith("@1") for k in keys) and any(k.endswith("@2") for k in keys)


class TestProtocol6Interactive:
    def test_success_lands_console_before_login_done(self, monkeypatch, capsys):
        """登录页 SPA 静默续登成功：先导航回 console 并落稳，才发 login_done/响应。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        w = PageWindow(bh.Api(), envelope=_BAD_ENV, switch_on_login=_OK_ENV)
        st = _round_st(w)
        trace = _traced_emit(monkeypatch, w)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 11})
        assert ("load", bh.LOGIN_URL) in trace                 # 交互路径允许导航
        i_console = trace.index(("load", bh.CONSOLE_URL))
        i_done = trace.index(("emit", "login_done"))
        assert i_console < i_done                              # §6 红线：先落稳再事件
        assert trace[-1] == ("emit", "resp")
        assert _stdout_json(capsys)[-1]["state"] == "live"
        assert st["page_poisoned"] is False

    def test_l3_popup_pulse_and_fail_exit_lands_stable(self, monkeypatch, capsys):
        """L3：restore+show+on_top 脉冲 → login_required；全链失败：
        落 console 稳定页 → 隐藏 → 才 login_failed → 响应。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: False)  # 逼 .NET 兜底
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: False)     # 假桌面未命中→桥兜底（假对象，不动真窗口）
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)            # 选择器缺失 → autofill 降级
        st = _round_st(w, manual_budget=0.2)
        trace = _traced_emit(monkeypatch, w)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 12})
        assert w.win_ops[:2] == ["restore", "show"]            # 弹窗脉冲
        assert w.on_top_log == [True, False]
        assert ("emit", "login_required") in trace
        i_console = trace.index(("load", bh.CONSOLE_URL))
        i_fail = trace.index(("emit", "login_failed"))
        assert i_console < i_fail                              # 失败出口同样先落稳
        t_deadline = time.monotonic() + 2.0                    # hide 走异步线程，轮询等落
        while "hide" not in w.win_ops and time.monotonic() < t_deadline:
            time.sleep(0.02)
        assert "hide" in w.win_ops
        out = _stdout_json(capsys)
        assert out[-1]["id"] == 12 and out[-1]["state"] == "need_login"

    def test_l3_popup_prefers_pure_win32(self, monkeypatch, capsys):
        """Lane I 取证：WinForms Invoke 可攥着 GIL 冻整个解释器——
        桌面命中 helper 窗口时脉冲必须走纯 ctypes，完全不碰 .NET 桥方法。"""
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        hits = []
        monkeypatch.setattr(bh, "_win32_show_topmost",
                            lambda *a, **k: hits.append(1) or True)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=0.1)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 14})
        assert hits                                    # 走了 Win32 路径
        assert w.win_ops[:2] != ["restore", "show"]    # 且未经 .NET 桥弹窗
        assert {"event": "login_required"} in _stdout_json(capsys)

    def test_l3_wait_no_fetch_storm(self):
        """人工等待期间 fetch 至多每 await_recheck 秒一轮（默认 20s）。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=1.0, poll_interval=0.02,
                       await_recheck=100.0)                    # 窗口内仅允许首 probes
        bh._await_live(st, 1.0)
        rounds = max(int(st["round_seq"]), 0)
        assert rounds <= 2                                     # 1s 等待 + recheck 间隔

    def test_l3_popup_ui_hang_still_emits_event(self, monkeypatch, capsys):
        """Lane I 实证回归：WinForms Invoke/TopMost 可无限卡死 UI 线程。
        弹窗每步限时弃线程；login_required 必须照发、响应不吞、命令线程不陪葬。"""
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: False)  # 逼 .NET 兜底
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)      # 绝不动真桌面窗口

        class HangWindow(PageWindow):
            def restore(self):
                self.win_ops.append("restore")
                time.sleep(30)

            def show(self):
                self.win_ops.append("show")
                time.sleep(30)

            @property
            def on_top(self):
                return self._on_top

            @on_top.setter
            def on_top(self, value):                # 卡死在 TopMost 赋值
                time.sleep(30)
                self._on_top = bool(value)

        w = HangWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=0.2, popup_step_budget=0.05)
        t0 = time.monotonic()
        bh.handle_command(st, {"cmd": "login_interactive", "id": 13})
        assert time.monotonic() - t0 < 15.0
        out = _stdout_json(capsys)
        assert {"event": "login_required"} in out              # 事件未被卡死的 UI 调用吞掉
        assert out[-1]["id"] == 13 and out[-1]["ok"] is False
        assert w.win_ops[:2] == ["restore", "show"]            # 确实发起过脉冲


class TestProtocol6Reauth:
    """M26 增补（2026-10-12）：reauth = login_interactive + force——会话健康也
    不走「已 live 立即回包」短路，必须导航登录页并抵达 L2/L3 交互面。"""

    def _st(self, monkeypatch, envelope, auth_cls=None):
        """默认无 CM 凭据（L2 弃权直入 L3）+ 指定信封的假窗快时钟 st。"""
        monkeypatch.setattr(bh, "_auth", auth_cls or _NoCredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: False)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: False)
        w = PageWindow(bh.Api(), envelope=envelope)
        return w, _round_st(w, manual_budget=0.15)

    def test_reauth_skips_live_shortcut_reaches_popup(self, monkeypatch, capsys):
        """桥全程 live：login_interactive 会秒回；reauth 仍导航登录页 →
        L3 弹窗 → login_required → 人工等待后回包（响应形状同 login）。"""
        w, st = self._st(monkeypatch, _OK_ENV)
        trace = _traced_emit(monkeypatch, w)
        assert bh.handle_command(st, {"cmd": "reauth", "id": 90}) is False
        assert bh.LOGIN_URL in w.load_urls                 # 绝不静默秒回
        assert ("emit", "login_required") in trace         # 弹窗路径抵达
        out = _stdout_json(capsys)
        resp = out[-1]
        assert resp["id"] == 90 and resp["ok"] is True and resp["state"] == "live"
        assert set(resp["data"]) == set(bh.KINDS)

    def test_login_interactive_live_shortcut_unchanged(self, monkeypatch, capsys):
        """对照红线：桥全程 live 时 login_interactive 仍第 1 步秒回、零导航。"""
        w, st = self._st(monkeypatch, _OK_ENV)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 91})
        assert w.load_urls == []
        resp = _stdout_json(capsys)[-1]
        assert resp["id"] == 91 and resp["ok"] is True and resp["state"] == "live"

    def test_reauth_response_shape_parity_with_login(self, monkeypatch, capsys):
        """响应键集与 login_interactive 完全同形（协议 §3；id/ok/state + data|detail）。"""
        w1, st1 = self._st(monkeypatch, _BAD_ENV, auth_cls=_CredsAuth)
        bh.handle_command(st1, {"cmd": "login_interactive", "id": 92})
        a = _stdout_json(capsys)[-1]
        w2, st2 = self._st(monkeypatch, _BAD_ENV, auth_cls=_CredsAuth)
        bh.handle_command(st2, {"cmd": "reauth", "id": 93})
        b = _stdout_json(capsys)[-1]
        assert set(a) == set(b) and a["ok"] == b["ok"] == False
        assert a["state"] == b["state"] == "need_login"    # 无凭据全链失败
        assert a["error"] == b["error"] == "LOGIN_EXPIRED"

    def test_reauth_stop_cancels(self, monkeypatch, capsys):
        """stop 置位（shutdown 在 reader 侧 set）→ reauth 等待被打断，
        必回 error/cancelled 响应，绝不吞回包喂 45s 看门狗。"""
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, silent_retry_wait=30.0, poll_interval=0.02)
        st["stop"].set()                                    # 模拟 shutdown/EOF
        assert bh.handle_command(st, {"cmd": "reauth", "id": 94}) is False
        resp = _stdout_json(capsys)[-1]
        assert resp["id"] == 94 and resp["ok"] is False
        assert resp["state"] == "error" and resp["error"] == "HELPER_ERROR"
        assert "cancelled" in resp["detail"]

    def test_reauth_not_bad_cmd(self, monkeypatch, capsys):
        w = PageWindow(bh.Api(), envelope=_OK_ENV)
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        st = _round_st(w, manual_budget=0.05)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: False)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: False)
        bh.handle_command(st, {"cmd": "reauth", "id": 95})
        assert all(r.get("error") != "BAD_CMD" for r in _stdout_json(capsys))
        bh.handle_command(st, {"cmd": "no_such", "id": 96})
        bad = _stdout_json(capsys)[-1]
        assert bad["id"] == 96 and bad["error"] == "BAD_CMD"


class _NeverReadyEvent:
    """替身就绪事件：永远 False——模拟 load_url 清空 _pywebviewready 后、
    L3 重定向链期间数分钟不置位的真实形态。"""

    def is_set(self):
        return False

    def wait(self, timeout=None):
        return False


class _NeverReadyEvents:
    _pywebviewready = _NeverReadyEvent()


class TestAwaitLiveUnblocked20261010:
    """2026-10-10 py-spy 取证回归：旧 _await_live 把 fetch 轮硬门控在
    _page_ready_now 之后，登录链期间就绪标志永不置位 → 等待循环只 sleep、
    从不重新 fetch，用户 14:51 完成登录后仍烧满 600s budget 报 login_failed。
    修复后：每 recheck 无条件跑一轮 _guarded_round，每轮恰一行 INFO 日志。"""

    def test_never_ready_flag_still_refetches_to_live(self, monkeypatch):
        """(a) 就绪事件恒 unset + 假轮 need_login×3→live：4 轮内返回 live。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        w.events = _NeverReadyEvents()           # type: ignore[attr-defined]
        assert bh._page_ready_now(w) is False        # 前提：旧门控下必死等
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        seq = iter(["need_login", "need_login", "need_login", "live"])
        seen = []

        def fake_round(_st, budget):
            rs = next(seq)
            seen.append(rs)
            return rs, ({"subscription": {}} if rs == "live" else None), None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, results, detail = bh._await_live(st, 5.0)
        assert rs == "live" and detail is None
        assert seen == ["need_login"] * 3 + ["live"]
        assert results == {"subscription": {}}

    def test_fetch_cadence_one_round_per_recheck(self, monkeypatch):
        """(b) 无 fetch 风暴：1s budget / 0.3s recheck → ≈4 轮，间隔 ≥ recheck。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.02, await_recheck=0.3)
        stamps = []

        def fake_round(_st, budget):
            stamps.append(time.monotonic())
            return "need_login", None, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, _res, _d = bh._await_live(st, 1.0)
        assert rs == "timeout"
        assert 3 <= len(stamps) <= 5
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        assert all(g >= 0.28 for g in gaps)

    def test_each_round_logs_exactly_one_info_line(self, monkeypatch, capsys):
        """(c) 每轮恰一行 INFO：含轮号/rs/evalfail，无凭据明文；
        eval_failed 标记进日志行。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.02, await_recheck=0.1)
        calls = []

        def fake_round(_st, budget):
            calls.append(1)
            if len(calls) == 1:
                return "need_login", {"subscription": {"eval_failed": True}}, None
            return "need_login", None, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        bh._await_live(st, 0.5)
        lines = [l for l in capsys.readouterr().err.splitlines()
                 if "await round" in l]
        assert len(lines) == len(calls) and len(calls) >= 2
        assert lines[0].split("INFO ", 1)[1].startswith("await round 1:")
        assert "evalfail=True" in lines[0]
        for i, l in enumerate(lines[1:], start=2):
            assert f"await round {i}:" in l and "INFO" in l
            assert "evalfail=False" in l

    def test_stop_flag_still_cancels(self, monkeypatch):
        """(d) 预设 stop → 零轮立即取消；等待中途置位 → 下一轮检查即撤。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        st["stop"].set()
        assert bh._await_live(st, 30.0) == ("error", None, "cancelled")
        assert st["round_seq"] == 0

        st2 = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        calls = []

        def fake_round(_st, budget):
            calls.append(1)
            if len(calls) == 2:
                st2["stop"].set()
            return "need_login", None, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        t0 = time.monotonic()
        rs, res, detail = bh._await_live(st2, 30.0)
        assert rs == "error" and detail == "cancelled"
        assert len(calls) == 2
        assert time.monotonic() - t0 < 5.0

    def test_raising_round_maps_error_and_loop_continues(self, monkeypatch, capsys):
        """(e) _guarded_round 本身抛异常：本轮映射为 rs=error、补一行 WARN，
        循环不死——后续轮照常，live 仍能返回。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        seq = iter(["boom", "boom", "live"])
        n = []

        def fake_round(_st, budget):
            s = next(seq)
            n.append(s)
            if s == "boom":
                raise RuntimeError("round exploded")
            return "live", {"usage": {}}, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, results, _d = bh._await_live(st, 5.0)
        assert rs == "live" and len(n) == 3 and results == {"usage": {}}
        err = capsys.readouterr().err
        assert "WARN await round 1 raised: RuntimeError" in err
        assert "INFO await round 1: rs=error evalfail=False" in err
        assert "INFO await round 3: rs=live" in err

    def test_url_for_log_strips_query_and_never_raises(self):
        """日志用 URL 探针：剥 query/fragment（防重定向 token 入日志）、
        无 get_current_url → ''、内部异常 → ''，绝不透进等待循环。"""
        w_ok = types.SimpleNamespace(
            get_current_url=lambda:
                "https://account.aliyun.com/login/login.htm?token=SECRET#frag")
        got = bh._url_for_log(w_ok)
        assert got == "https://account.aliyun.com/login/login.htm"
        assert "SECRET" not in got

        def boom():
            raise RuntimeError("stuck")

        assert bh._url_for_log(types.SimpleNamespace(get_current_url=boom)) == ""
        assert bh._url_for_log(PageWindow(bh.Api())) == ""


class TestSettingsBailianEntryRouting:
    """设置面板百炼入口 → NoteApp._bailian_cred_click 同一路径；无钩子回落粘贴面板。"""

    def _open(self, app, name):
        from src import settings_panel as sp
        panel = sp.SettingsPanel.__new__(sp.SettingsPanel)   # 绕开 Tk 构造，只借方法
        panel.app = app
        panel._open_bind_panel(name)

    def test_prefers_cred_click_hook(self):
        calls = []
        app = types.SimpleNamespace(
            _bailian_cred_click=lambda: calls.append("click"),
            open_credentials=lambda: calls.append("paste"),
            open_key_panel=lambda n: calls.append(("key", n)))
        self._open(app, "bailian")
        assert calls == ["click"]

    def test_falls_back_to_paste_panel_without_hook(self):
        calls = []
        app = types.SimpleNamespace(
            open_credentials=lambda: calls.append("paste"))
        self._open(app, "bailian")
        assert calls == ["paste"]

    def test_other_provider_still_key_panel(self):
        calls = []
        app = types.SimpleNamespace(
            _bailian_cred_click=lambda: calls.append("click"),
            open_key_panel=lambda n: calls.append(("key", n)))
        self._open(app, "codex")
        assert calls == [("key", "codex")]


# ================================================================ Fix 1/2/3（2026-10-10 §7 取证）
# lane-J 实证：L3 登录完成后 passport 链把窗口落在 home.console origin，
# 页内 fetch 跨源被 CORS 永拒（evalfail=False、rs=error 无限循环）。
# origin 护栏：非 bailian(.cs).console host 的 fetch 轮先回跳 CONSOLE_URL 一次
# （15s 冷却）；登录页（account/passport）为用户输入区，护栏刻意豁免不打断。

_HOME_CONSOLE = "https://home.console.aliyun.com/home/dashboard/ProductAndService"
_LOGIN_PAGE = "https://account.aliyun.com/login/login.htm"


class UrlWindow(PageWindow):
    """PageWindow + get_current_url 探针（origin 护栏的判定输入）。
    url="" 模拟探针取不到 URL（未知 origin）。"""

    def __init__(self, api, url="", **kw):
        super().__init__(api, **kw)
        self._probe_url = url

    def get_current_url(self):
        return self._probe_url


class TitleWindow(UrlWindow):
    """带可读写 title 属性的替身（pywebview Window.title 同形）。"""

    def __init__(self, api, url="", title=None, **kw):
        super().__init__(api, url=url, **kw)
        self.title = title if title is not None else bh.WINDOW_TITLE


class TestEnsureConsoleOrigin:
    def test_home_console_navigates_once(self):
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE)
        st = _round_st(w)
        assert bh._ensure_console_origin(w, st) is True
        assert w.load_urls == [bh.CONSOLE_URL]

    def test_console_hosts_skipped(self):
        for url in ("https://bailian.console.aliyun.com/",
                    "https://bailian-cs.console.aliyun.com/data/api.json"):
            w = UrlWindow(bh.Api(), url=url)
            st = _round_st(w)
            assert bh._ensure_console_origin(w, st) is False, url
            assert w.load_urls == [], url

    def test_login_page_exempt_not_interrupted(self):
        """登录页=L2 自动提交/L3 人工输入区：导航打断=瀑布不可用（偏离
        任务书"account 也回跳"一处，理由与回归测试见此类 docstring）。"""
        w = UrlWindow(bh.Api(), url=_LOGIN_PAGE)
        st = _round_st(w)
        assert bh._ensure_console_origin(w, st) is False
        assert w.load_urls == []
        assert "account.aliyun.com" in bh.LOGIN_WAIT_HOSTS

    def test_about_blank_treated_as_wrong_origin(self):
        w = UrlWindow(bh.Api(), url="about:blank")
        st = _round_st(w)
        assert bh._ensure_console_origin(w, st) is True
        assert w.load_urls == [bh.CONSOLE_URL]

    def test_unknown_probe_is_noop(self):
        """无 get_current_url / 探针返回 ''：未知 origin → 不导航（假 window
        与卡死 UI 保持良性；既有 80 测全部走这条豁免）。"""
        st = _round_st(PageWindow(bh.Api()))
        assert bh._ensure_console_origin(st["window"], st) is False
        w = UrlWindow(bh.Api(), url="")
        st2 = _round_st(w)
        assert bh._ensure_console_origin(w, st2) is False
        assert w.load_urls == []

    def test_cooldown_one_nav_per_window(self):
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE)
        st = _round_st(w)                          # 默认 15s 冷却
        assert bh._ensure_console_origin(w, st) is True
        assert bh._ensure_console_origin(w, st) is False
        assert bh._ensure_console_origin(w, st) is False
        assert w.load_urls == [bh.CONSOLE_URL]     # 窗口内只导航一次
        assert bh.ORIGIN_GUARD_COOLDOWN == 15.0

    def test_cooldown_expiry_allows_next_nav(self):
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE)
        st = _round_st(w, origin_guard_cooldown=0.05)
        assert bh._ensure_console_origin(w, st) is True
        assert bh._ensure_console_origin(w, st) is False    # 冷却内
        time.sleep(0.06)
        assert bh._ensure_console_origin(w, st) is True     # 冷却过后可再来
        assert w.load_urls == [bh.CONSOLE_URL, bh.CONSOLE_URL]

    def test_origin_guard_logs_info_line(self, capsys):
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE)
        st = _round_st(w)
        bh._ensure_console_origin(w, st)
        err = capsys.readouterr().err
        assert "INFO origin-guard: return to console from home.console.aliyun.com" in err


class TestAwaitLiveOriginGuard:
    def test_wrong_origin_returns_console_before_first_round(self, monkeypatch):
        """Fix 1 核心回归：home.console 泊窗 → 回跳一次 → 轮在 console 上跑；
        后续轮受冷却约束不再反复导航（防 ping-pong）。"""
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        navs_at_round = []

        def fake_round(_st, budget):
            navs_at_round.append(len(w.load_urls))
            if len(navs_at_round) < 3:
                return "need_login", None, None       # 模拟证据里的 error 轮
            return "live", {"usage": {}}, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, results, _d = bh._await_live(st, 5.0)
        assert rs == "live" and results == {"usage": {}}
        assert navs_at_round and navs_at_round[0] == 1     # 首轮已在回跳之后
        assert w.load_urls == [bh.CONSOLE_URL]             # 冷却生效：仅一次
        assert st["og_last_nav"] is not None

    def test_console_origin_zero_navigation(self, monkeypatch):
        w = UrlWindow(bh.Api(), url=bh.CONSOLE_URL, envelope=_OK_ENV)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, budget: ("live", {"usage": {}}, None))
        rs, _res, _d = bh._await_live(st, 5.0)
        assert rs == "live"
        assert w.load_urls == []                           # 正确 origin 不打扰


class TestSilentPollOriginGuard:
    def test_entry_guard_returns_console_before_round(self, capsys):
        """Fix 1：交互绕行后窗口泊在 home.console → 静默 poll 入场先回跳。"""
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE, envelope=_OK_ENV)
        st = _round_st(w)
        bh.handle_command(st, {"cmd": "poll", "id": 21})
        assert w.load_urls == [bh.CONSOLE_URL]
        assert bh.LOGIN_URL not in w.load_urls             # 绝不导航登录页
        out = _stdout_json(capsys)[-1]
        assert out["id"] == 21 and out["state"] == "live"

    def test_console_origin_no_extra_navigation(self, capsys):
        w = UrlWindow(bh.Api(), url=bh.CONSOLE_URL, envelope=_OK_ENV)
        st = _round_st(w)
        bh.handle_command(st, {"cmd": "poll", "id": 22})
        assert w.load_urls == []
        assert _stdout_json(capsys)[-1]["state"] == "live"

    def test_login_page_poll_not_interrupted(self, monkeypatch, capsys):
        """静默 poll 停在登录页（page_poisoned 已清）：护栏不打断输入；
        且静默路径依旧零导航（无凭据）。"""
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        w = UrlWindow(bh.Api(), url=_LOGIN_PAGE, envelope=_BAD_ENV)
        st = _round_st(w)
        bh.handle_command(st, {"cmd": "poll", "id": 23})
        assert w.load_urls == []
        assert _stdout_json(capsys)[-1]["state"] == "no_credential"

    def test_post_interactive_home_console_forced_back(self, monkeypatch, capsys):
        """Fix 3：交互命令结束（_land_stable 已清 page_poisoned）但窗口实际
        泊在 home.console → 下一次静默 poll 由 origin 护栏强制回 console；
        全程绝不导航登录页。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        w = UrlWindow(bh.Api(), url=_HOME_CONSOLE, envelope=_BAD_ENV)
        st = _round_st(w, page_poisoned=False)             # _land_stable 后的状态
        bh.handle_command(st, {"cmd": "poll", "id": 24})
        out = _stdout_json(capsys)[-1]
        assert out["state"] == "need_login"
        assert bh.LOGIN_URL not in w.load_urls
        # 入场护栏 1 次 + need_login 凭据重载 1 次，两次都必须是 CONSOLE_URL
        assert w.load_urls == [bh.CONSOLE_URL, bh.CONSOLE_URL]


class TestL3CloseSemantics:
    def test_l3_sets_manual_title_and_restores(self, monkeypatch, capsys):
        """Fix 2(a)：manual 阶段窗口标题改为"别关"提示，任一路径退出都恢复。"""
        monkeypatch.setattr(bh, "_auth", _NoCredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: True)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        w = TitleWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=0.2)
        seen = []
        real_await = bh._await_live

        def spy(_st, budget, recheck=None):
            seen.append((_st["login_phase"], _st["window"].title))
            return real_await(_st, budget, recheck=recheck)

        monkeypatch.setattr(bh, "_await_live", spy)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 25})
        assert seen and seen[0] == ("manual", bh.MANUAL_LOGIN_TITLE)
        assert w.title == bh.WINDOW_TITLE                  # 超时出口已恢复
        assert "orig_title" not in st                      # 不留残留键
        assert {"event": "login_required"} in _stdout_json(capsys)

    def test_manual_title_constant(self):
        assert bh.MANUAL_LOGIN_TITLE == \
            "阿里云登录窗口 — 登录成功后会自动隐藏，请不要关闭！"

    def test_window_closed_during_manual_emits_login_failed(self, capsys):
        """Fix 2(b)：manual 期间用户关窗 → webview.start() 返回 ≠ 成功，
        main() 出口必须补发 login_failed(window_closed)。"""
        bh._notify_login_window_closed(_mk_st(login_phase="manual"))
        assert _stdout_json(capsys) == [
            {"event": "login_failed", "reason": "window_closed"}]

    def test_window_closed_notify_silent_when_not_manual(self, capsys):
        for phase in (None, "hidden"):
            bh._notify_login_window_closed(_mk_st(login_phase=phase))
        bh._notify_login_window_closed({})                 # 键缺失也不炸
        assert capsys.readouterr().out == ""

    def test_main_calls_notify_after_start_returns(self, monkeypatch, tmp_path):
        """main() 接线：webview.start 正常返回后走 window_closed 通知路径。"""
        calls = []
        ev = threading.Event()

        def fake_start(func=None, args=(), **kw):
            ev.set()
            return None

        fake_webview = types.SimpleNamespace(
            create_window=lambda *a, **k: types.SimpleNamespace(
                get_current_url=lambda: "", events=None,
                destroy=lambda: None, title=""),
            start=fake_start)
        monkeypatch.setitem(sys.modules, "webview", fake_webview)
        monkeypatch.setattr(bh, "emit",
                            lambda obj, stream=None: calls.append(obj))
        st_box = {}

        def hook(st):
            st_box["st"] = st
            st["login_phase"] = "manual"       # 模拟 start 返回时仍在人工登录

        rc = bh.main(tmp_path, pre_window_hook=hook)
        assert rc == 0 and ev.is_set()
        # start 正常返回 + 仍处 manual → 关窗通知必须是 login_failed，绝非成功
        assert {"event": "login_failed", "reason": "window_closed"} in calls
        assert not [c for c in calls if c.get("event") == "login_done"]


# ================================================================ 泊航跳过 + L2 passport 提升
# （2026-10-10 selector_probe/2 实证 + helper.log 16:20 fetch 风暴）：
# ① account 登录页表单在跨源 iframe，顶层零输入——L2 必须先导航
#    passport 账密 entrance 顶层页（fm-* 选择器实证命中），填充失败回 account 页交 L3；
# ② _await_live 泊在 LOGIN_WAIT_HOSTS 时 fetch 轮必 CORS error——整轮跳过，
#    只按 recheck 节奏廉价重探 URL，离开登录 host 后照常恢复 fetch。

class SeqUrlWindow(UrlWindow):
    """get_current_url 按脚本序返回（越界重复末项）——模拟泊航后重定向离开。"""

    def __init__(self, api, urls, **kw):
        super().__init__(api, url=urls[0], **kw)
        self._urls = list(urls)
        self._i = 0

    def get_current_url(self):
        u = self._urls[min(self._i, len(self._urls) - 1)]
        self._i += 1
        return u


class NavWindow(UrlWindow):
    """get_current_url 返回最近一次 load_url 的地址（近似真实导航）。"""

    def get_current_url(self):
        return self.load_urls[-1] if self.load_urls else self._probe_url


class TestAwaitLiveParkedOnLoginHost:
    PARK_MSG = "await: parked on login host, round skipped"

    def test_parked_zero_rounds_info_logged_once_per_60s(self, monkeypatch, capsys):
        """泊 account 登录页：fetch 轮全跳过；默认节流下 INFO 恰一行。"""
        w = SeqUrlWindow(bh.Api(), [_LOGIN_PAGE])          # 永远泊着
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        calls = []
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, budget: calls.append(1)
                            or ("need_login", None, None))
        t0 = time.monotonic()
        rs, _res, _d = bh._await_live(st, 0.5)
        assert time.monotonic() - t0 < 5.0
        assert rs == "timeout"
        assert calls == [1]          # 泊航期间零 fetch；预算耗尽仅 final-check 一轮
        assert w.load_urls == [bh.CONSOLE_URL]   # final-check 强制回跳 console
        assert st["round_seq"] == 0
        lines = [l for l in capsys.readouterr().err.splitlines()
                 if self.PARK_MSG in l]
        assert len(lines) == 1                              # ≤1 次/60s
        assert "account.aliyun.com" in lines[0]

    def test_parked_on_passport_host_also_skipped(self, monkeypatch):
        """L2 提交后停在 passport.aliyun.com 等待重定向：同样跳过。"""
        w = SeqUrlWindow(bh.Api(), ["https://passport.aliyun.com/havanaone/x"])
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        calls = []
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, budget: calls.append(1)
                            or ("error", None, None))
        rs, _res, _d = bh._await_live(st, 0.2)
        assert rs == "timeout" and calls == [1]   # 泊航跳过全部常规轮，final-check 1 轮

    def test_resumes_after_url_leaves_login_host(self, monkeypatch, capsys):
        """离开登录 host 后立即恢复 fetch：每 recheck ≥1 轮，live 即返。"""
        w = SeqUrlWindow(bh.Api(), [_LOGIN_PAGE, _LOGIN_PAGE, bh.CONSOLE_URL])
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        calls = []

        def fake_round(_st, budget):
            calls.append(1)
            return "live", {"usage": {}}, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, results, _d = bh._await_live(st, 3.0)
        assert rs == "live" and results == {"usage": {}}
        assert len(calls) == 1                              # 泊航轮不计数
        err = capsys.readouterr().err
        assert self.PARK_MSG in err
        assert "await round 1: rs=live" in err

    def test_park_log_throttle_interval_configurable(self, monkeypatch, capsys):
        """park_log_interval 注入：每次跳过都可记（节流边界可测）。"""
        w = SeqUrlWindow(bh.Api(), [_LOGIN_PAGE])
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05,
                       park_log_interval=0.0)
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, budget: ("need_login", None, None))
        bh._await_live(st, 0.3)
        lines = [l for l in capsys.readouterr().err.splitlines()
                 if self.PARK_MSG in l]
        assert len(lines) >= 2                              # 无节流时逐轮记录
        assert bh.PARK_LOG_INTERVAL == 60.0                 # 默认 60s 节流


class TestL2PassportPromotion:
    def test_navigates_passport_before_autofill_and_degrades(self, monkeypatch, capsys):
        """瀑布实况：account 页(表单跨源不可填) → L2 先导航 PWD_LOGIN_URL →
        假桥下选择器永不现形 → 弃权 → 回 account 页 → L3 弹窗 → 超时出口。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: True)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        w = NavWindow(bh.Api(), url=_LOGIN_PAGE, envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=0.1)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 31})
        assert w.load_urls[0] == bh.LOGIN_URL               # SPA 续登导航
        assert bh.PWD_LOGIN_URL in w.load_urls              # L2 提升
        i_pwd = w.load_urls.index(bh.PWD_LOGIN_URL)
        i_back = w.load_urls.index(bh.LOGIN_URL, i_pwd)     # 失败回 account
        assert i_pwd < i_back
        assert "L2: promote passport pwd entrance" in (cap := capsys.readouterr()).err
        out = [json.loads(x) for x in cap.out.splitlines() if x.strip()]
        assert {"event": "login_required"} in out
        assert out[-1]["id"] == 31 and out[-1]["state"] == "need_login"

    def test_autofill_success_path_promotes_and_reports_live(self, monkeypatch, capsys):
        """autofill=True（假桥）：提升导航发生、_await_live 以 L2 recheck 启动、
        成功出口 login_done(method=autofill)。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        seen = {}

        def fake_autofill(window, u, p, inputs_budget=None, verify_wait=None):
            seen["autofill"] = (u, p, inputs_budget)
            seen["verify_wait"] = verify_wait
            return True

        def fake_await(_st, budget, recheck=None):
            seen["await"] = (budget, recheck)
            return "live", {"usage": {}}, None

        monkeypatch.setattr(bh, "autofill_login", fake_autofill)
        monkeypatch.setattr(bh, "_await_live", fake_await)
        w = NavWindow(bh.Api(), url=_LOGIN_PAGE, envelope=_BAD_ENV)
        st = _round_st(w, submit_verify_wait=0.05)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 32})
        assert bh.PWD_LOGIN_URL in w.load_urls
        assert seen["autofill"] == ("user@example.com", "pw-not-secret", 0.05)
        assert seen["verify_wait"] == 0.05          # st 注入贯通 autofill 诊断等待
        assert seen["await"] == (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS)
        out = _stdout_json(capsys)
        done = [o for o in out if o.get("event") == "login_done"]
        assert done and done[0]["method"] == "autofill"
        assert out[-1]["state"] == "live"


# ================================================================ submit-verify / final-check / 预算（2026-10-10 16:46 实证）
# ①提交后零可观测（错密码/风控静默拦截/stale entrance 无法区分）→ 只读诊断探针；
# ②L2 预算在泊航中烧光、fallback 起步瞬间其实已登录（16:55:54 类检测滞后假阴性）
#   → timeout 前 final-check（强制回 console + 单轮）；
# ③AUTOFILL_BUDGET 45→90、POLL_DEADLINE 13→20（console 重载后首轮超重），
#   静默 poll 最坏路径由 deadline 硬护栏约束，仍 ≪ 45s 看门狗。

_PWDS_PAGE = ("https://passport.aliyun.com/havanaone/login/login.htm"
              "?appEntrance=aliyun_pc_pwd&returnUrl=SECRET_TOKEN")
_SSO_PAGE = "https://account.aliyun.com/login/login_aliyun.htm?token=ONETIME"


class TestSubmitVerifyProbe:
    """autofill 提交后的只读诊断：每次成功提交必执行、必留 INFO 日志，
    绝不含账密明文； inconclusive 分支只在"未清栏 + 仍泊 pwd 页 + 无可见报错"。"""

    def _full(self, **over):
        return FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                   "form#login-form button[type=\"submit\"]"),
                          **over)

    def test_probe_executed_after_every_successful_submit(self, capsys):
        w = self._full()
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=1.0, verify_wait=0.0) == \
            {"submitted": True, "verify": "cleared"}
        assert [c[0] for c in w.calls].count("verify") == 1
        assert w.calls[-1] == ("verify",)                    # 紧跟提交
        err = capsys.readouterr().err
        assert 'submit-verify: {"inputs_cleared":true,' in err
        assert "passport.aliyun.com/havanaone/login/login.htm" in err

    def test_probe_script_is_readonly_and_credential_free(self):
        w = self._full()
        bh.autofill_login(w, "user@x.com", "pw-secret",
                          inputs_budget=1.0, verify_wait=0.0)
        probe_scripts = [s for s in w.scripts
                         if s.lstrip().startswith("(function ()")]
        assert len(probe_scripts) == 1
        p = probe_scripts[0]
        # 只读：不 click、不改 value、不发 fetch/report
        assert ".click()" not in p and "fetch(" not in p
        assert "report" not in p and "setVal" not in p and ".value =" not in p
        # 明文纪律：账密不进探针；诊断项选择器候选序全嵌入（JSON 转义形态）
        assert "pw-secret" not in p and "user@x.com" not in p
        for sel in bh.SUBMIT_VERIFY_TIP_SELECTORS:
            assert json.dumps(sel) in p
        assert bh.SUBMIT_VERIFY_TIP_SELECTORS[:2] == [".fm-tips",
                                                      ".password-login .error"]

    def test_wrong_password_mode_visible_err_text_no_inconclusive(self, capsys):
        w = self._full(verify_result={"inputs_cleared": False, "url": _PWDS_PAGE,
                                      "err_text": "账号名或密码不正确"})
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=1.0, verify_wait=0.0) == \
            {"submitted": True, "verify": "err"}       # 可见报错=可确证失败形态
        err = capsys.readouterr().err
        assert "账号名或密码不正确" in err
        assert "inconclusive" not in err

    def test_risk_control_silent_block_logs_inconclusive(self, capsys):
        w = self._full(verify_result={"inputs_cleared": False,
                                      "url": _PWDS_PAGE, "err_text": ""})
        assert bh.autofill_login(w, "u@x.com", "p",
                                 inputs_budget=1.0, verify_wait=0.0) == \
            {"submitted": True, "verify": "inconclusive"}
        err = capsys.readouterr().err
        assert ("submit-verify: inconclusive "
                "(likely risk-control silent block)") in err

    def test_cleared_true_never_inconclusive(self, capsys):
        w = self._full(verify_result={"inputs_cleared": True,
                                      "url": _PWDS_PAGE, "err_text": ""})
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        assert "inconclusive" not in capsys.readouterr().err

    def test_left_pwd_page_never_inconclusive(self, capsys):
        """重定向链在途（离开 passport host）：非静默拦截形态，不报 inconclusive。"""
        w = self._full(verify_result={"inputs_cleared": False,
                                      "url": _SSO_PAGE, "err_text": ""})
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        err = capsys.readouterr().err
        assert "inconclusive" not in err
        assert "SECRET_TOKEN" not in err and "ONETIME" not in err  # query 剥净

    def test_username_scrubbed_from_err_text(self, capsys):
        w = self._full(verify_result={"inputs_cleared": False,
                                      "url": _PWDS_PAGE,
                                      "err_text": "user@x.com 不存在"})
        bh.autofill_login(w, "user@x.com", "pw-secret",
                          inputs_budget=1.0, verify_wait=0.0)
        lines = [l for l in capsys.readouterr().err.splitlines()
                 if "submit-verify:" in l]
        assert lines and all("user@x.com" not in l for l in lines)
        assert "<user>" in "".join(lines)

    def test_string_payload_parsed(self, capsys):
        """WebView2 桥把 JS 对象转 dict，也兼容 JSON 字符串返回。"""
        w = self._full(verify_result=json.dumps(
            {"inputs_cleared": False, "url": _PWDS_PAGE, "err_text": "x"}))
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        assert '"err_text":"x"' in capsys.readouterr().err

    def test_bad_payload_warns_without_crash(self, capsys):
        """17:11 修订：不可解析返回值改记 raw= 兜底（脱敏截断原文），
        替代无信息量的 bad probe payload。"""
        w = self._full(verify_result=42)
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0,
                                 verify_wait=0.0) == \
            {"submitted": True, "verify": "inconclusive"}   # 不可解析→不冒认被接受
        err = capsys.readouterr().err
        assert "submit-verify: raw=42" in err
        assert "bad probe payload" not in err

    def test_probe_exception_swallowed(self, capsys):
        w = self._full(verify_raise=True)
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0,
                                 verify_wait=0.0) == \
            {"submitted": True, "verify": "inconclusive"}   # 探针异常→不冒认被接受
        err = capsys.readouterr().err
        assert "submit-verify: probe failed: RuntimeError" in err
        assert "inconclusive" not in err

    def test_wait_constants_and_clamp(self, monkeypatch):
        assert bh.SUBMIT_VERIFY_WAIT == 3.0
        assert bh.SUBMIT_VERIFY_WAIT_MAX == 5.0
        assert bh.SUBMIT_VERIFY_WAIT <= bh.SUBMIT_VERIFY_WAIT_MAX
        slept = []
        monkeypatch.setattr(bh.time, "sleep", lambda s: slept.append(s))
        bh._submit_verify(FakeWindow(), "u", wait=99.0)      # 硬上限 5s
        assert slept[:1] == [5.0]

    def test_stay_in_autofill_budget_after_tuning(self):
        """90s L2 预算覆盖 submit-verify（≤5s）→ _await_live 剩余 ≥ 85s。"""
        assert bh.AUTOFILL_BUDGET - bh.SUBMIT_VERIFY_WAIT_MAX >= 85.0


class TestFinalCheckAfterPark:
    """泊航预算耗尽（从未 fetch 过）→ timeout 前最后一次判活：
    goto CONSOLE_URL + ready ≤10s + 单轮；live 即成功路径（16:55:54 类假阴性）。"""

    def _parked(self):
        w = SeqUrlWindow(bh.Api(), [_LOGIN_PAGE])
        return w, _round_st(w, poll_interval=0.01, await_recheck=0.05)

    def test_parked_expiry_final_round_goes_live(self, monkeypatch, capsys):
        w, st = self._parked()
        calls = []

        def fake_round(_st, budget):
            calls.append(1)
            return "live", {"usage": {}}, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        rs, results, _d = bh._await_live(st, 0.2)
        assert rs == "live" and results == {"usage": {}}
        assert len(calls) == 1                        # 泊航零轮 + final 恰一轮
        assert w.load_urls == [bh.CONSOLE_URL]        # 先回 console 再判活
        err = capsys.readouterr().err
        assert "await: final-check after park (budget expired, never fetched)" in err
        assert "await: final-check live after park" in err

    def test_final_check_not_live_stays_timeout_single_round(self, monkeypatch,
                                                             capsys):
        w, st = self._parked()
        calls = []
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, b: calls.append(1)
                            or ("need_login", None, None))
        rs, _res, _d = bh._await_live(st, 0.2)
        assert rs == "timeout"
        assert len(calls) == 1 and w.load_urls == [bh.CONSOLE_URL]
        err = capsys.readouterr().err
        assert "await: final-check rs=need_login" in err
        assert "final-check live" not in err

    def test_no_final_check_when_rounds_already_ran(self, monkeypatch):
        """已跑常规轮（非纯泊航）→ 预算耗尽直接 timeout，绝不额外导航/补轮。"""
        w = SeqUrlWindow(bh.Api(), [bh.CONSOLE_URL])
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        calls = []
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, b: calls.append(1)
                            or ("need_login", None, None))
        rs, _r, _d = bh._await_live(st, 0.2)
        assert rs == "timeout" and len(calls) >= 1
        assert w.load_urls == []                      # console origin：全程零导航

    def test_no_final_check_when_url_unknown_never_parked(self):
        """URL 探不到（''=未知、非泊航）：常规轮照跑 → timeout 无补导航。"""
        w = PageWindow(bh.Api(), envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05)
        rs, _r, _d = bh._await_live(st, 0.2)          # 真实轮：即时 need_login
        assert rs == "timeout" and w.load_urls == []

    def test_final_check_respects_stop(self):
        w = UrlWindow(bh.Api(), url=_LOGIN_PAGE)
        st = _round_st(w)
        st["stop"].set()
        assert bh._final_check_after_park(st) is None
        assert w.load_urls == []                      # stop 置位绝不导航

    def test_final_check_round_exception_swallowed(self, monkeypatch, capsys):
        w = UrlWindow(bh.Api(), url=_LOGIN_PAGE)
        st = _round_st(w)

        def boom(_st, budget):
            raise RuntimeError("round exploded")

        monkeypatch.setattr(bh, "_guarded_round", boom)
        assert bh._final_check_after_park(st) is None
        assert "await final-check raised: RuntimeError" in capsys.readouterr().err

    def test_l2_parked_expiry_final_live_skips_l3(self, monkeypatch, capsys):
        """端到端（假桥）：autofill 提交成功 → L2 await 全程泊 passport →
        预算耗尽 → final-check 回 console 判活 live → login_done(autofill)，
        绝不弹 L3（16:47:27→16:55:54 假阴性的机制回归）。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        monkeypatch.setattr(bh, "AUTOFILL_BUDGET", 0.15)   # 快时钟替身

        def fake_autofill(window, u, p, inputs_budget=None, verify_wait=None):
            return True

        monkeypatch.setattr(bh, "autofill_login", fake_autofill)
        w = NavWindow(bh.Api(), url=_LOGIN_PAGE, envelope=_BAD_ENV)
        st = _round_st(w, poll_interval=0.01, await_recheck=0.05,
                       submit_verify_wait=0.0)

        def fake_round(_st, budget):
            # 仅当窗口已回 console（final-check 导航后）才判活
            if bh._url_host(bh._url_for_log(w)) in bh.CONSOLE_ALLOWED_HOSTS:
                return "live", {"usage": {}}, None
            return "need_login", None, None

        monkeypatch.setattr(bh, "_guarded_round", fake_round)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 41})
        out = _stdout_json(capsys)
        done = [o for o in out if o.get("event") == "login_done"]
        assert done and done[0]["method"] == "autofill"
        assert not [o for o in out if o.get("event") == "login_required"]
        assert out[-1]["id"] == 41 and out[-1]["state"] == "live"
        assert bh.PWD_LOGIN_URL in w.load_urls        # L2 提升照常发生


class TestBudgetTuning20261010:
    def test_autofill_budget_90s(self):
        assert bh.AUTOFILL_BUDGET == 90.0

    def test_poll_deadline_20s(self):
        assert bh.POLL_DEADLINE == 20.0

    def test_silent_worst_case_mechanism_and_constants_bound(self, capsys):
        """机制证：卡死注入下轮在注入 deadline 处即弃、响应紧接返回；
        常量证：真实最坏路径 = POLL_DEADLINE(20) + 回包/事件开销 ≪ 45s 看门狗
        （导航/ready 均从 start 计时、remaining() 收窄轮预算，不叠加超支）。"""
        w = PageWindow(bh.Api(), hang=0.6)           # 每接口挂 0.6s（模拟 13s 烧穿）
        st = _round_st(w, poll_deadline=0.4)
        t0 = time.monotonic()
        bh.handle_command(st, {"cmd": "poll", "id": 42})
        elapsed = time.monotonic() - t0
        assert 0.4 <= elapsed < 3.0                   # deadline 即弃，不随 hang 放大
        out = _stdout_json(capsys)[-1]
        assert out["state"] == "error" and out["detail"] == "fetch-timeout"
        assert bh.POLL_DEADLINE + 15.0 < 45.0         # 20 + 15s 余量仍压看门狗
        assert bh.GOTO_TIMEOUT + bh.RELOAD_SETTLE_BUDGET <= bh.POLL_DEADLINE


# ================================================================ 17:11 实证修复（2026-10-10）
# ①helper.log 17:11-17:13：submit 已执行但窗口全程泊 passport（parked x1→x6），
#   90s 预算烧光、从未进入 login_aliyun.htm 握手——静态 PWD_LOGIN_URL 的
#   returnUrl/rnd 探针时刻快照过期，重定向链死胡同。L2 提升改为：account 页
#   实时抓取 #alibaba-login-box iframe src → 顶层导航；抓取失败才兜底静态 URL。
# ②submit-verify: bad probe payload——真桥 return 契约与 fake-bridge 不符，
#   err_text 诊断丢失。探针 JS 改为 JSON.stringify 单表达式返回（旧模板结尾
#   是从未被调用的裸函数表达式——"stray statement" 即根因）；Python 侧兼容
#   dict/JSON 字符串/双重编码，不可解析记 raw=<200 字符脱敏原文>。
# ③泊航期间 host 变化单记一行 INFO：区分"从未离开 entrance"与"握手了但没会话"。

_FRESH_ENTRANCE = ("https://passport.aliyun.com/havanaone/login/login.htm"
                   "?lang=zh_CN&appEntrance=aliyun_pc_pwd&returnUrl="
                   "https%3A%2F%2Faccount.aliyun.com%2Flogin%2Flogin_aliyun.htm"
                   "%3Ftoken%3DFRESHTOK&rnd=0.123")


class ScrapeWindow(NavWindow):
    """NavWindow + entrance 抓取脚本（(() => 前缀）拦截：返回 scrape（任意值），
    scrape_raise=True 时抛异常；其余脚本走 PageWindow 原逻辑。
    load_urls 天然记录 goto 顺序。"""

    def __init__(self, api, scrape=None, scrape_raise=False, **kw):
        super().__init__(api, **kw)
        self._scrape = scrape
        self._scrape_raise = scrape_raise
        self.evaluated: list[str] = []

    def evaluate_js(self, script):
        self.evaluated.append(script)
        if script.lstrip().startswith("(() =>"):
            if self._scrape_raise:
                raise RuntimeError("bridge boom")
            return self._scrape
        return super().evaluate_js(script)


class TestL2FreshEntrance:
    """Fix 1：提升步骤的抓取成功/失败/兜底时序（假桥记录 goto 顺序）。"""

    def _win(self, **over):
        return ScrapeWindow(bh.Api(), envelope=_BAD_ENV, url=_LOGIN_PAGE, **over)

    def test_scrape_success_goto_order_no_static(self, capsys):
        w = self._win(scrape=_FRESH_ENTRANCE)
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == [bh.LOGIN_URL, _FRESH_ENTRANCE]   # account→新鲜页
        err = capsys.readouterr().err
        assert "L2: promote passport pwd entrance" in err
        assert "L2: fresh entrance from iframe" in err
        assert "static entrance fallback" not in err

    def test_scrape_empty_string_static_fallback(self, capsys):
        w = self._win(scrape="")
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == [bh.LOGIN_URL, bh.PWD_LOGIN_URL]
        err = capsys.readouterr().err
        assert "L2: iframe src unavailable, static entrance fallback" in err
        assert "fresh entrance" not in err

    def test_scrape_bridge_false_static_fallback(self, capsys):
        """假桥无元素形态返回 False（非字符串）→ 等同抓取失败。"""
        w = self._win(scrape=None)                    # evaluate_js → False
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == [bh.LOGIN_URL, bh.PWD_LOGIN_URL]
        assert "static entrance fallback" in capsys.readouterr().err

    def test_scrape_exception_static_fallback(self, capsys):
        w = self._win(scrape_raise=True)
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == [bh.LOGIN_URL, bh.PWD_LOGIN_URL]
        err = capsys.readouterr().err
        assert "L2: entrance scrape raised: RuntimeError" in err
        assert "static entrance fallback" in err

    def test_scrape_foreign_host_rejected_falls_back(self, capsys):
        """iframe src 非 passport host → 拒绝顶层导航（防注入），走静态兜底。"""
        w = self._win(scrape="https://evil.example.com/havanaone/login.htm")
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == [bh.LOGIN_URL, bh.PWD_LOGIN_URL]
        err = capsys.readouterr().err
        assert "L2: scraped entrance rejected" in err
        assert "static entrance fallback" in err

    def test_already_on_passport_zero_navigation(self, capsys):
        """守卫保留：已在 passport 顶层页（如上一轮提升后重入）→ no-op 不打断。"""
        w = ScrapeWindow(bh.Api(), envelope=_BAD_ENV, url=bh.PWD_LOGIN_URL,
                         scrape=_FRESH_ENTRANCE)
        bh._promote_to_pwd_entrance(w)
        assert w.load_urls == []
        assert "promote" not in capsys.readouterr().err

    def test_scrape_js_is_readonly_single_expression(self):
        js = bh._ENTRANCE_SCRAPE_JS
        assert js.lstrip().startswith("(() =>") and js.rstrip().endswith("()")
        assert "#alibaba-login-box" in js
        assert "passport.aliyun.com/havanaone" in js          # iframe 兜底候选
        for bad in (".click()", "fetch(", "report", ".value =", "setAttribute"):
            assert bad not in js, bad                          # 纯读取

    def test_waterfall_end_to_end_fresh_entrance(self, monkeypatch, capsys):
        """集成（假桥记录 goto 顺序）：瀑布 L2 导航新鲜 iframe src 而非静态 URL，
        autofill 在新鲜页上执行。"""
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: True)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        seen = {}

        def fake_autofill(window, u, p, inputs_budget=None, verify_wait=None):
            seen["host_at_autofill"] = bh._url_host(bh._url_for_log(window))
            return False

        monkeypatch.setattr(bh, "autofill_login", fake_autofill)
        w = ScrapeWindow(bh.Api(), envelope=_BAD_ENV, url=_LOGIN_PAGE,
                         scrape=_FRESH_ENTRANCE)
        st = _round_st(w, manual_budget=0.1)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 51})
        # 步2 SPA 续登 → 提升回 account → 新鲜 entrance（绝不静态兜底）
        assert w.load_urls[:3] == [bh.LOGIN_URL, bh.LOGIN_URL, _FRESH_ENTRANCE]
        assert bh.PWD_LOGIN_URL not in w.load_urls
        assert seen["host_at_autofill"] == bh.PWD_LOGIN_HOST
        err = capsys.readouterr().err
        assert "L2: fresh entrance from iframe" in err
        assert "FRESHTOK" not in err                       # query 不入日志


class TestSubmitVerifyContract:
    """Fix 2：真桥 return 形态兼容（dict/JSON 字符串/双重编码）+ raw 兜底日志。"""

    def _full(self, **over):
        return FakeWindow(present=("#fm-login-id", "#fm-login-password",
                                   "form#login-form button[type=\"submit\"]"),
                          **over)

    def test_probe_js_ends_with_stringified_single_expression(self):
        """根因回归：旧模板结尾是从未被调用的裸 `(function(){...})`——真桥下
        探针根本没执行。现必须是 `})()` 立即调用 + JSON.stringify 返回。"""
        w = self._full()
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        p = [s for s in w.scripts if s.lstrip().startswith("(function ()")][0]
        assert p.rstrip().endswith("})()")
        assert "return JSON.stringify(out);" in p
        assert "return out;" not in p

    def test_dict_payload_parsed(self, capsys):
        w = self._full(verify_result={"inputs_cleared": False, "url": _PWDS_PAGE,
                                      "err_text": "账号名或密码不正确"})
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0,
                                 verify_wait=0.0) == \
            {"submitted": True, "verify": "err"}
        assert "账号名或密码不正确" in capsys.readouterr().err

    def test_double_encoded_string_parsed(self, capsys):
        payload = json.dumps({"inputs_cleared": False, "url": _PWDS_PAGE,
                              "err_text": "密码错误"})
        w = self._full(verify_result=json.dumps(payload))   # 字符串再编码一层
        assert bh.autofill_login(w, "u", "p", inputs_budget=1.0,
                                 verify_wait=0.0) == \
            {"submitted": True, "verify": "err"}
        err = capsys.readouterr().err
        assert '"err_text":"密码错误"' in err
        assert "raw=" not in err

    def test_garbage_payload_logs_scrubbed_raw(self, capsys):
        w = self._full(verify_result="bridge said no user@x.com at "
                       "https://passport.aliyun.com/havanaone/login.htm"
                       "?tok=SECRETTOK")
        assert bh.autofill_login(w, "user@x.com", "pw-secret",
                                 inputs_budget=1.0, verify_wait=0.0) == \
            {"submitted": True, "verify": "inconclusive"}
        lines = [l for l in capsys.readouterr().err.splitlines()
                 if "submit-verify:" in l]
        assert lines and any("raw=" in l for l in lines)
        joined = "".join(lines)
        assert "<user>" in joined and "user@x.com" not in joined
        assert "SECRETTOK" not in joined                    # URL query 剥净
        assert "bad probe payload" not in joined

    def test_numeric_payload_raw_line(self, capsys):
        w = self._full(verify_result=7)
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        assert "submit-verify: raw=7" in capsys.readouterr().err

    def test_raw_truncated_to_200_chars(self, capsys):
        w = self._full(verify_result="x" * 500)
        bh.autofill_login(w, "u", "p", inputs_budget=1.0, verify_wait=0.0)
        line = [l for l in capsys.readouterr().err.splitlines()
                if "submit-verify:" in l][0]
        assert len(line.split("raw=", 1)[1]) <= 200


class TestAwaitLiveHostTransition:
    """Fix 3：泊航期间 host 变化单记一行 INFO（每次变化恰一行，不受节流抑制）。"""

    TRANS = "await: host transition"

    def _st(self, w):
        return _round_st(w, poll_interval=0.01, await_recheck=0.05,
                         park_log_interval=1000.0)      # park 行节流，transition 独立

    def test_passport_to_account_transition_logged_once(self, monkeypatch, capsys):
        """提交后握手链：泊 passport → 移入 login_aliyun.htm（account）→ 泊住
        （无会话）——一行 transition 区分于"从未离开 entrance"。"""
        w = SeqUrlWindow(bh.Api(), [_PWDS_PAGE, _SSO_PAGE, _SSO_PAGE])
        st = self._st(w)
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, b: ("need_login", None, None))
        rs, _r, _d = bh._await_live(st, 0.3)
        assert rs == "timeout"
        err = capsys.readouterr().err
        trans = [l for l in err.splitlines() if self.TRANS in l]
        assert len(trans) == 1
        assert "passport.aliyun.com→account.aliyun.com" in trans[0]
        assert "SECRET_TOKEN" not in err and "ONETIME" not in err  # host-only

    def test_same_host_parked_emits_no_transition(self, monkeypatch, capsys):
        """全程泊 passport（17:11 形态：从未离开 entrance）→ 零 transition 行。"""
        w = SeqUrlWindow(bh.Api(), [_PWDS_PAGE])
        st = self._st(w)
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, b: ("need_login", None, None))
        bh._await_live(st, 0.2)
        err = capsys.readouterr().err
        assert self.TRANS not in err
        assert "passport.aliyun.com, x" in err             # park 计数行仍带 host

    def test_transition_lines_follow_each_change(self, monkeypatch, capsys):
        """host 每变一次记一行（passport→account→passport 两行、方向正确）。"""
        w = SeqUrlWindow(bh.Api(), [_PWDS_PAGE, _SSO_PAGE, _PWDS_PAGE,
                                    _PWDS_PAGE])
        st = self._st(w)
        monkeypatch.setattr(bh, "_guarded_round",
                            lambda _st, b: ("need_login", None, None))
        bh._await_live(st, 0.25)
        trans = [l for l in capsys.readouterr().err.splitlines()
                 if self.TRANS in l]
        assert len(trans) == 2
        assert "passport.aliyun.com→account.aliyun.com" in trans[0]
        assert "account.aliyun.com→passport.aliyun.com" in trans[1]


# ================================================================ L2 fast-escalate（2026-10-10 17:25 实证）
# 证据（helper.log 17:25:20-23）：submit-verify 判定"风控静默拦截"（inputs_cleared=false
# + err_text 空 + 仍泊 passport）后，代码却仍烧满 AUTOFILL_BUDGET=90s 的泊航轮
# （parked x1…）才升级 L3。静默拦截=提交被吞（程序化不可信事件），等待绝无回报。
# 新行为：非 cleared / 非握手在途形态 → 10s 宽限窗（~5s/~10s 两次廉价 URL 重探）
# 仍泊登录 host → 跳过剩余 AUTOFILL park 预算直入 L3；离登录 host=真在途 → 回全量 await。

class TestL2FastGraceProbe:
    """`_l2_fast_grace` 机制：宽限窗内仅按 probe 节奏廉价重探 URL（不 fetch/不导航），
    返回 parked | left | cancelled。全程用注入的小窗（毫秒级）验证节奏与判定。"""

    def _st(self, window, grace=0.2, probe=0.05):
        return {"window": window, "stop": threading.Event(),
                "poll_interval": 0.01, "l2_grace_seconds": grace,
                "l2_grace_probe_interval": probe}

    def test_parked_still_on_login_host_all_probes(self):
        """全程泊 passport：每次探针都留在窗内 → 'parked'，且不提前 return。"""
        w = UrlWindow(bh.Api(), url=_PWDS_PAGE)   # get_current_url 恒返 _PWDS_PAGE
        st = self._st(w)
        assert bh._l2_fast_grace(st) == "parked"

    def test_host_leaves_login_window_returns_left(self):
        """慢 redirect 离开登录 host=真握手在途 → 'left'（首个探针后即返）。"""
        w = UrlWindow(bh.Api(), url=bh.CONSOLE_URL)
        st = self._st(w)
        assert bh._l2_fast_grace(st) == "left"

    def test_transition_mid_window_returns_left(self):
        """泊 passport 起步、窗内某刻移入 console → 'left'（SeqUrl 逐次推进）。"""
        w = SeqUrlWindow(bh.Api(), [_PWDS_PAGE, _PWDS_PAGE, bh.CONSOLE_URL])
        st = self._st(w, grace=0.2, probe=0.05)   # 探针 ~4 次：0.05/0.1/0.15/0.2
        assert bh._l2_fast_grace(st) == "left"

    def test_url_unknown_treated_as_left(self):
        """URL 探不到（''）按在途处理 → 'left'（宁可多 await 不误杀握手）。"""
        w = UrlWindow(bh.Api(), url="")
        st = self._st(w)
        assert bh._l2_fast_grace(st) == "left"

    def test_stop_flag_during_window_cancels(self):
        """宽限途中 stop 置位 → 'cancelled'（提前结束、绝不耗尽窗）。"""
        w = UrlWindow(bh.Api(), url=_PWDS_PAGE)
        st = self._st(w, grace=0.2, probe=0.05)
        st["stop"].set()                            # 预置：_sleep_until 立即 False
        assert bh._l2_fast_grace(st) == "cancelled"

    def test_account_host_also_counts_as_parked(self):
        """account 登录 host 同样属 LOGIN_WAIT_HOSTS 泊航集 → 'parked'。"""
        w = UrlWindow(bh.Api(), url=_SSO_PAGE)     # account 握手页
        st = self._st(w)
        assert bh._l2_fast_grace(st) == "parked"

    def test_probe_budget_uses_last_checkpoint(self):
        """窗尾必探一次（checkpoints 含 grace 值本身）——grace 恰为 probe 倍数时不重复。"""
        # grace=10, probe=5（默认）→ checkpoints [5,10]，共 2 次；此处以注入窗断言末点存在。
        assert bh.L2_FAST_GRACE_SECONDS == 10.0
        assert bh.L2_FAST_GRACE_PROBE_INTERVAL == 5.0
        assert bh.L2_FAST_GRACE_SECONDS < bh.AUTOFILL_BUDGET   # 快速升级 ≪ 90s


class TestL2FastEscalateWiring:
    """`_interactive_login` L2 相按 autofill verify 分派：
    cleared → 全量 AUTOFILL_BUDGET await（不变）；
    inconclusive/err → 宽限窗 parked 即**跳过** L2 await 直入 L3；
    宽限 left → 回全量 await；宽限 cancelled → 干净取消。"""

    def _drive(self, monkeypatch, verify, grace_ret, await_ret="timeout"):
        monkeypatch.setattr(bh, "_auth", _CredsAuth)
        monkeypatch.setattr(bh, "_win32_show_topmost", lambda *a, **k: True)
        monkeypatch.setattr(bh, "_win32_show_hide", lambda *a, **k: True)
        seen = {"await_budgets": [], "grace_called": 0}

        def fake_autofill(window, u, p, inputs_budget=None, verify_wait=None):
            return {"submitted": True, "verify": verify}

        def fake_grace(_st):
            seen["grace_called"] += 1
            return grace_ret

        def fake_await(_st, budget, recheck=None):
            seen["await_budgets"].append((budget, recheck))
            return await_ret, {"usage": {}}, None

        monkeypatch.setattr(bh, "autofill_login", fake_autofill)
        monkeypatch.setattr(bh, "_l2_fast_grace", fake_grace)
        monkeypatch.setattr(bh, "_await_live", fake_await)
        # 窗口泊 passport 顶层：宽限判定 parked 后仍满足 bounce→account 前置导航
        w = NavWindow(bh.Api(), url=_PWDS_PAGE, envelope=_BAD_ENV)
        st = _round_st(w, manual_budget=0.1, submit_verify_wait=0.0)
        bh.handle_command(st, {"cmd": "login_interactive", "id": 70})
        return w, st, seen

    def test_inconclusive_parked_skips_l2_await_and_reaches_l3(self, monkeypatch,
                                                                capsys):
        """风控静默拦截（inconclusive）+ 宽限仍泊 → 绝不调用 AUTOFILL_BUDGET await，
        L3 login_required 正常发出（不等 90s）。"""
        _w, _st, seen = self._drive(monkeypatch, "inconclusive", "parked")
        l2_budget = (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS)
        assert l2_budget not in seen["await_budgets"]         # 剩余 90s park 预算被跳过
        assert seen["grace_called"] == 1
        out = _stdout_json(capsys)
        assert {"event": "login_required"} in out             # 直入 L3 人工
        assert out[-1]["id"] == 70 and out[-1]["state"] in ("need_login", "no_credential")

    def test_err_text_parked_skips_l2_await(self, monkeypatch, capsys):
        """错密码（err_text 非空）→ 同快速路径：不烧 90s，交 L3 让用户修正。"""
        _w, _st, seen = self._drive(monkeypatch, "err", "parked")
        l2_budget = (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS)
        assert l2_budget not in seen["await_budgets"]
        assert seen["grace_called"] == 1
        assert {"event": "login_required"} in _stdout_json(capsys)

    def test_cleared_keeps_full_autofill_budget_await(self, monkeypatch, capsys):
        """inputs_cleared=true（submit 被接受、握手在途）→ 维持全量 await（不变）；
        此处 live 早退，不进 L3，宽限绝不被调用。"""
        _w, _st, seen = self._drive(monkeypatch, "cleared", "parked",
                                     await_ret="live")
        assert (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS) in seen["await_budgets"]
        assert seen["grace_called"] == 0                       # cleared 直接 await
        out = _stdout_json(capsys)
        done = [o for o in out if o.get("event") == "login_done"]
        assert done and done[0]["method"] == "autofill"
        assert out[-1]["state"] == "live"

    def test_grace_left_falls_back_to_full_await(self, monkeypatch, capsys):
        """宽限窗内 host 离开登录页（真在途）→ 回全量 AUTOFILL_BUDGET await。"""
        _w, _st, seen = self._drive(monkeypatch, "inconclusive", "left",
                                      await_ret="timeout")
        assert (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS) in seen["await_budgets"]
        assert seen["grace_called"] == 1

    def test_grace_cancelled_returns_error_cleanly(self, monkeypatch, capsys):
        """宽限途中 stop → 干净 error/cancelled，不发起 L2 await、不发 login_required。"""
        _w, _st, seen = self._drive(monkeypatch, "inconclusive", "cancelled")
        l2_budget = (bh.AUTOFILL_BUDGET, bh.L2_RECHECK_SECONDS)
        assert l2_budget not in seen["await_budgets"]
        out = _stdout_json(capsys)
        assert not [o for o in out if o.get("event") == "login_required"]
        assert out[-1]["state"] == "error" and out[-1]["detail"] == "cancelled"


class TestNormalizeAutofillResult:
    """bool→dict 向后兼容：旧 False→prefail、旧 True→cleared（维持原全量 await）。"""

    def test_bool_true_maps_cleared(self):
        assert bh._normalize_autofill_result(True) == \
            {"submitted": True, "verify": "cleared"}

    def test_bool_false_maps_prefail(self):
        assert bh._normalize_autofill_result(False) == \
            {"submitted": False, "verify": "prefail"}

    def test_dict_passed_through(self):
        d = {"submitted": True, "verify": "inconclusive"}
        assert bh._normalize_autofill_result(d) == d

    def test_dict_submitted_missing_verify_falls_back(self):
        assert bh._normalize_autofill_result({"submitted": True}) == \
            {"submitted": True, "verify": "inconclusive"}
        assert bh._normalize_autofill_result({"submitted": False}) == \
            {"submitted": False, "verify": "prefail"}
