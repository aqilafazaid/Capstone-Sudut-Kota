"""Tes CRUD node dan pembatasan akses API.

Dijalankan dari folder backend:

    .venv/Scripts/python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

# Harus diset sebelum app diimpor: app = create_app() berjalan saat import.
_TMP = tempfile.mkdtemp(prefix="sudutkota-test-")
os.environ["NODE_DB"] = os.path.join(_TMP, "nodes.db")
os.environ["STREAM_AUTOSTART"] = "false"
os.environ["ALLOW_TEST_SOURCES"] = "false"
os.environ["RTDB_ROOT"] = "cctv_data"

import app as app_module  # noqa: E402
import auth  # noqa: E402
import nodes as node_store  # noqa: E402


def _fake_verifier(token: str) -> dict:
    """Token uji: nama peran itu sendiri (admin / teknisi / visitor)."""
    return {"uid": f"u-{token}", "email": f"{token}@uji.test"}


def _fake_role(uid: str) -> str:
    return uid.split("-", 1)[1]


ADMIN = {"Authorization": "Bearer admin"}
TEKNISI = {"Authorization": "Bearer teknisi"}
VISITOR = {"Authorization": "Bearer visitor"}
TOKEN = TEKNISI  # peran default untuk tes tulis


class NodeApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        auth.set_verifier(_fake_verifier)
        auth.set_role_resolver(_fake_role)

    @classmethod
    def tearDownClass(cls) -> None:
        auth.set_verifier(None)
        auth.set_role_resolver(None)

    def setUp(self) -> None:
        node_store.reset_nodes(seed_demo=False)
        self.client = app_module.app.test_client()

    def create(self, **overrides):
        payload = {
            "nama": "Simpang Uji",
            "zona": "Kota Uji",
            "jalan": "Jl. Uji",
            "channel": "99",
            "rtsp": "rtsp://127.0.0.1:8554/uji",
            "aktif": False,
        }
        payload.update(overrides)
        return self.client.post("/api/nodes", json=payload, headers=TOKEN)

    # --- baca ------------------------------------------------------------
    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_list_seeds_three_nodes_without_rtsp(self):
        response = self.client.get("/api/nodes")
        self.assertEqual(response.status_code, 200)
        rows = response.get_json()
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertNotIn("rtsp", row)
            self.assertTrue(row["hls_url"].startswith("/hls/"))

    def test_detail_requires_operator_and_returns_rtsp(self):
        self.assertEqual(self.client.get("/api/nodes/cam_29").status_code, 401)
        self.assertEqual(
            self.client.get("/api/nodes/cam_29", headers=VISITOR).status_code, 403
        )
        response = self.client.get("/api/nodes/cam_29", headers=TOKEN)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["rtsp"].startswith("rtsp://"))

    # --- tulisan ----------------------------------------------------------
    def test_write_requires_bearer_header(self):
        payload = {"nama": "X", "zona": "Y", "rtsp": "rtsp://127.0.0.1/x"}
        self.assertEqual(self.client.post("/api/nodes", json=payload).status_code, 401)
        self.assertEqual(
            self.client.post("/api/nodes", json=payload, headers={"X-SK-Token": "salah"}).status_code,
            401,
        )

    def test_visitor_cannot_write(self):
        payload = {"nama": "X", "zona": "Y", "rtsp": "rtsp://127.0.0.1/x"}
        self.assertEqual(
            self.client.post("/api/nodes", json=payload, headers=VISITOR).status_code, 403
        )

    def test_create_list_detail_update_delete(self):
        response = self.create()
        self.assertEqual(response.status_code, 201, response.get_json())
        node = response.get_json()
        self.assertEqual(node["id"], "cam_99")
        self.assertNotIn("rtsp", node)

        listed = self.client.get("/api/nodes").get_json()
        self.assertIn("cam_99", [row["id"] for row in listed])

        detail = self.client.get("/api/nodes/cam_99", headers=TOKEN).get_json()
        self.assertEqual(detail["rtsp"], "rtsp://127.0.0.1:8554/uji")

        updated = self.client.put(
            "/api/nodes/cam_99", json={"nama": "Nama Baru"}, headers=TOKEN
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.get_json()["nama"], "Nama Baru")

        deleted = self.client.delete("/api/nodes/cam_99", headers=TOKEN)
        self.assertEqual(deleted.status_code, 200)
        self.assertNotIn("cam_99", [row["id"] for row in self.client.get("/api/nodes").get_json()])

    def test_duplicate_channel_is_rejected(self):
        response = self.create(channel="29")
        self.assertEqual(response.status_code, 409)

    def test_validation(self):
        cases = [
            {"nama": "", "zona": "Z", "rtsp": "rtsp://127.0.0.1/x"},
            {"nama": "X", "zona": "", "rtsp": "rtsp://127.0.0.1/x"},
            {"nama": "X", "zona": "Z", "rtsp": ""},
            {"nama": "X", "zona": "Z", "rtsp": "http://127.0.0.1/x"},
        ]
        for payload in cases:
            response = self.client.post("/api/nodes", json=payload, headers=TOKEN)
            self.assertEqual(response.status_code, 400, payload)

    def test_http_source_only_when_test_sources_enabled(self):
        with mock.patch.dict(os.environ, {"ALLOW_TEST_SOURCES": "true"}):
            response = self.create(rtsp="https://example.com/test.m3u8", channel="98")
            self.assertEqual(response.status_code, 201, response.get_json())
        with mock.patch.dict(os.environ, {"ALLOW_TEST_SOURCES": "false"}):
            response = self.create(rtsp="https://example.com/test.m3u8", channel="97")
            self.assertEqual(response.status_code, 400)

    def test_persists_across_app_instances(self):
        self.assertEqual(self.create(channel="96").status_code, 201)
        second = app_module.create_app().test_client()
        ids = [row["id"] for row in second.get("/api/nodes").get_json()]
        self.assertIn("cam_96", ids)

    def test_reset_is_admin_only(self):
        self.assertEqual(self.create(channel="95").status_code, 201)
        self.assertEqual(
            self.client.post("/api/nodes/reset", headers=TOKEN).status_code, 403
        )
        response = self.client.post("/api/nodes/reset", headers=ADMIN)
        self.assertEqual(response.status_code, 200)
        ids = [row["id"] for row in response.get_json()["nodes"]]
        self.assertEqual(sorted(ids), ["cam_29", "cam_35", "cam_43"])

    def test_status_is_operator_only(self):
        self.assertEqual(self.client.get("/api/status").status_code, 401)
        self.assertEqual(self.client.get("/api/status", headers=VISITOR).status_code, 403)
        response = self.client.get("/api/status", headers=TOKEN)
        self.assertEqual(response.status_code, 200)

    def test_proxy_endpoint_removed(self):
        self.assertEqual(self.client.get("/api/proxy?url=http://127.0.0.1/x").status_code, 404)

    def test_config_reports_public_flags(self):
        data = self.client.get("/api/config").get_json()
        self.assertIn("auth_configured", data)
        self.assertNotIn("write_token_required", data)
        self.assertFalse(data["allow_test_sources"])
        self.assertNotIn("test-token", str(data))


if __name__ == "__main__":
    unittest.main()
