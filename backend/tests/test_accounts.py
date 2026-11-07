"""Tes NIP otomatis (ADM-/TKS-/VST-) dan penjagaan peran pada pembuatan akun.

Dijalankan dari folder backend:

    .venv/Scripts/python.exe -m unittest discover -s tests -v

Tidak menyentuh Firebase: ``accounts._ref`` dan ``accounts._app`` diganti
dengan penyimpanan di memori, ``firebase_admin.auth.create_user`` di-mock.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import accounts


class _FakeRef:
    """Pengganti ``firebase_admin.db.Reference`` untuk satu node."""

    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self):
        return dict(self._data) if self._data else None

    def set(self, value) -> None:
        self._data.clear()
        self._data.update(value)

    def delete(self) -> None:
        self._data.clear()


class AccountNipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tree: dict = {"akun": {}}
        for patcher in (
            mock.patch.object(accounts, "_app", return_value=None),
            mock.patch.object(accounts, "_ref", side_effect=self._ref),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ref(self, *parts: str) -> _FakeRef:
        node = self.tree
        for part in parts:
            node = node.setdefault(part, {})
        return _FakeRef(node)

    def _seed(self, uid: str, **profile) -> None:
        self.tree["akun"][uid] = {
            "nama": "Petugas",
            "nip": "",
            "username": uid,
            "email": f"{uid}@uji.test",
            "peran": "visitor",
            "created_at": "",
            "updated_at": "",
            **profile,
        }

    def _create(self, uid: str = "u-baru", **payload):
        body = {"nama": "Petugas", "email": f"{uid}@uji.test", "password": "rahasia123"}
        body.update(payload)
        with mock.patch(
            "firebase_admin.auth.create_user", return_value=SimpleNamespace(uid=uid)
        ):
            return accounts.create_account(body)

    # --- pembuatan -----------------------------------------------------

    def test_nip_mengikuti_peran_saat_dibuat(self) -> None:
        self.assertEqual(self._create("u-admin", peran="admin")["nip"], "ADM-001")
        self.assertEqual(self._create("u-tek", peran="teknisi")["nip"], "TKS-001")
        self.assertEqual(self._create("u-vis", peran="visitor")["nip"], "VST-001")

    def test_nomor_urut_terpisah_per_awalan(self) -> None:
        self._seed("a", nip="ADM-004", peran="admin", username="a")
        self._seed("b", nip="VST-009", peran="visitor", username="b")
        self.assertEqual(self._create("u-tek", peran="teknisi")["nip"], "TKS-001")
        self.assertEqual(self._create("u-tek2", peran="teknisi")["nip"], "TKS-002")
        self.assertEqual(self._create("u-admin", peran="admin")["nip"], "ADM-005")

    def test_nip_di_body_diabaikan(self) -> None:
        self.assertEqual(self._create("u-admin", peran="admin", nip="ADM-777")["nip"], "ADM-001")
        self.assertEqual(self._create("u-vis", peran="visitor", nip="NIP-LIAR")["nip"], "VST-001")

    def test_nip_tidak_pernah_duplikat(self) -> None:
        self.assertEqual(self._create("u1", peran="admin")["nip"], "ADM-001")
        self.assertEqual(self._create("u2", peran="admin")["nip"], "ADM-002")
        self.assertEqual(self._create("u3", peran="admin")["nip"], "ADM-003")

    def test_penjaga_unik_nip_menolak_duplikat(self) -> None:
        accounts_list = [{"uid": "a", "nip": "ADM-001"}]
        with self.assertRaises(accounts.AccountError) as ctx:
            accounts._unique(accounts_list, "nip", "adm-001")
        self.assertEqual(ctx.exception.status, 409)

    def test_nip_otomatis_tidak_pernah_bentrok(self) -> None:
        self._seed("a", nip="VST-001")
        self._seed("b", nip="VST-002")
        self.assertEqual(self._create("u-vis", peran="visitor")["nip"], "VST-003")

    # --- pendaftaran mandiri -------------------------------------------

    def test_pendaftaran_selalu_visitor(self) -> None:
        profile = accounts.ensure_self_profile(
            "u-vis", "vis@uji.test", {"nama": "Vis", "peran": "admin", "nip": "ADM-999"}
        )
        self.assertEqual(profile["peran"], "visitor")
        self.assertEqual(profile["nip"], "VST-001")

    # --- perubahan peran ------------------------------------------------

    def test_peran_berubah_mengganti_awalan_nip(self) -> None:
        self._seed("u1", nip="VST-003")
        profile = accounts.update_account("u1", {"nama": "Petugas", "peran": "teknisi"})
        self.assertEqual(profile["peran"], "teknisi")
        self.assertEqual(profile["nip"], "TKS-001")

    def test_nip_lama_ikut_diganti_saat_peran_berubah(self) -> None:
        self._seed("u1", nip="19850712 201001 1 002")
        profile = accounts.update_account("u1", {"nama": "Petugas", "peran": "teknisi"})
        self.assertEqual(profile["nip"], "TKS-001")

    def test_akun_lama_tanpa_nip_dilengkapi_saat_diedit(self) -> None:
        self._seed("u1", nip="")
        profile = accounts.update_account("u1", {"nama": "Petugas"})
        self.assertEqual(profile["nip"], "VST-001")

    def test_nip_tidak_berubah_saat_nama_diedit(self) -> None:
        self._seed("u1", nip="VST-007")
        profile = accounts.update_account("u1", {"nama": "Nama Baru"})
        self.assertEqual(profile["nip"], "VST-007")


if __name__ == "__main__":
    unittest.main()
