"""Uji otomatis untuk aplikasi investasi.

Cara menjalankan (di Command Prompt, folder proyek, venv aktif):
    python -m unittest -v test_app

Setiap uji memakai database sementara, jadi database.db Anda tidak tersentuh.
"""
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import app as modul

FOLDER = os.path.dirname(os.path.abspath(__file__))


def buat_database(path):
    with open(os.path.join(FOLDER, "schema.sql"), encoding="utf-8") as f:
        skema = f.read()
    db = sqlite3.connect(path)
    db.executescript(skema)
    # Persentase dibuat tetap supaya hasil uji selalu sama
    db.execute("UPDATE produk SET kenaikan_persen = 5.0, aktif = 1 WHERE id = 1")
    db.execute("UPDATE produk SET kenaikan_persen = 6.0, aktif = 1 WHERE id = 2")
    db.execute("UPDATE produk SET kenaikan_persen = 2.0, aktif = 1 WHERE id = 3")
    db.commit()
    db.close()


class Dasar(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.path = os.path.join(self.folder, "uji.db")
        buat_database(self.path)
        modul.DB_PATH = self.path
        modul.app.config["TESTING"] = True
        modul.app.config["CSRF_AKTIF"] = False   # dinyalakan khusus di TestKeamanan
        modul.percobaan_gagal.clear()
        self.klien = modul.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    # ---- alat bantu ----
    def kueri(self, sql, *param):
        db = sqlite3.connect(self.path)
        try:
            return db.execute(sql, param).fetchall()
        finally:
            db.close()

    def daftar(self, klien=None, nama="Uji", email="uji@contoh.com", sandi="rahasia123"):
        klien = klien or self.klien
        r = klien.post("/daftar", data={"nama": nama, "email": email,
                                        "kata_sandi": sandi}, follow_redirects=True)
        return r.get_data(as_text=True)

    def masuk(self, klien, email, sandi):
        r = klien.post("/login", data={"email": email, "kata_sandi": sandi},
                       follow_redirects=True)
        return r.get_data(as_text=True)

    def saldo(self, uid=1):
        return self.kueri("SELECT jumlah FROM saldo WHERE pengguna_id = ?", uid)[0][0]

    def modal(self, uid, produk_id):
        baris = self.kueri("SELECT modal FROM kepemilikan WHERE pengguna_id = ? "
                           "AND produk_id = ?", uid, produk_id)
        return baris[0][0] if baris else 0

    def jumlah_transaksi(self, uid=None):
        if uid is None:
            return self.kueri("SELECT COUNT(*) FROM transaksi")[0][0]
        return self.kueri("SELECT COUNT(*) FROM transaksi WHERE pengguna_id = ?", uid)[0][0]

    def _saldo_aksi(self, aksi, nominal, klien):
        klien = klien or self.klien
        r = klien.post("/saldo", data={"aksi": aksi, "nominal": str(nominal)},
                       follow_redirects=True)
        return r.get_data(as_text=True)

    def setor(self, nominal, klien=None):
        return self._saldo_aksi("SETOR", nominal, klien)

    def tarik(self, nominal, klien=None):
        return self._saldo_aksi("TARIK", nominal, klien)

    def _produk_aksi(self, aksi, produk_id, nominal, klien):
        klien = klien or self.klien
        r = klien.post("/produk/transaksi",
                       data={"produk_id": str(produk_id), "aksi": aksi,
                             "nominal": str(nominal)}, follow_redirects=True)
        return r.get_data(as_text=True)

    def beli(self, produk_id, nominal, klien=None):
        return self._produk_aksi("BELI", produk_id, nominal, klien)

    def jual(self, produk_id, nominal, klien=None):
        return self._produk_aksi("JUAL", produk_id, nominal, klien)

    def ringkasan(self, uid=1):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            return modul.ringkasan_portofolio(db, uid)
        finally:
            db.close()


# ======================================================================
class TestAkun(Dasar):
    def test_daftar_membuat_pengguna_dan_saldo_nol(self):
        self.daftar()
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 1)
        self.assertEqual(self.saldo(), 0)

    def test_kata_sandi_tidak_disimpan_apa_adanya(self):
        self.daftar(sandi="rahasia123")
        tersimpan = self.kueri("SELECT kata_sandi FROM pengguna")[0][0]
        self.assertNotIn("rahasia123", tersimpan)
        self.assertGreater(len(tersimpan), 40)

    def test_email_ganda_ditolak_tanpa_membedakan_huruf_besar(self):
        self.daftar(email="uji@contoh.com")
        lain = modul.app.test_client()
        html = self.daftar(lain, email="UJI@Contoh.com")
        self.assertIn("Email sudah terdaftar", html)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 1)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM saldo")[0][0], 1)

    def test_kata_sandi_pendek_ditolak(self):
        html = self.daftar(sandi="1234567")
        self.assertIn("minimal 8 karakter", html)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 0)

    def test_kolom_kosong_ditolak(self):
        html = self.daftar(nama="   ")
        self.assertIn("Semua kolom wajib diisi", html)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 0)

    def test_login_dengan_sandi_salah_ditolak(self):
        self.daftar()
        lain = modul.app.test_client()
        html = self.masuk(lain, "uji@contoh.com", "salah-salah")
        self.assertIn("Email atau kata sandi salah", html)
        self.assertEqual(lain.get("/").status_code, 302)  # masih terkunci

    def test_login_dengan_sandi_benar_berhasil(self):
        self.daftar()
        lain = modul.app.test_client()
        self.masuk(lain, "uji@contoh.com", "rahasia123")
        self.assertEqual(lain.get("/").status_code, 200)

    def test_pesan_salah_login_sama_untuk_email_tidak_dikenal(self):
        self.daftar()
        lain = modul.app.test_client()
        html = self.masuk(lain, "tidak-ada@contoh.com", "rahasia123")
        self.assertIn("Email atau kata sandi salah", html)

    def test_halaman_terkunci_tanpa_login(self):
        for path in ["/", "/produk", "/saldo", "/riwayat"]:
            r = self.klien.get(path)
            self.assertEqual(r.status_code, 302, path)
            self.assertIn("/login", r.headers["Location"], path)

    def test_aksi_terkunci_tanpa_login(self):
        r = self.klien.post("/saldo", data={"aksi": "SETOR", "nominal": "1000"})
        self.assertEqual(r.status_code, 302)
        r = self.klien.post("/produk/transaksi",
                            data={"produk_id": "1", "aksi": "BELI", "nominal": "1000"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.jumlah_transaksi(), 0)

    def test_keluar_harus_lewat_post(self):
        self.daftar()
        self.assertEqual(self.klien.get("/keluar").status_code, 405)
        self.klien.post("/keluar")
        self.assertEqual(self.klien.get("/").status_code, 302)

    def test_nama_berbahaya_ditampilkan_sebagai_teks_biasa(self):
        html = self.daftar(nama="<script>alert(1)</script>")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_percobaan_sql_injection_ditolak(self):
        self.daftar()
        lain = modul.app.test_client()
        html = self.masuk(lain, "' OR '1'='1", "' OR '1'='1")
        self.assertIn("Email atau kata sandi salah", html)
        self.assertEqual(lain.get("/").status_code, 302)


# ======================================================================
class TestSaldo(Dasar):
    def setUp(self):
        super().setUp()
        self.daftar()

    def test_setor_dan_tarik(self):
        self.setor(5_000_000)
        self.assertEqual(self.saldo(), 5_000_000)
        self.tarik(1_000_000)
        self.assertEqual(self.saldo(), 4_000_000)
        self.assertEqual(self.jumlah_transaksi(), 2)

    def test_tarik_melebihi_saldo_ditolak(self):
        self.setor(1_000_000)
        html = self.tarik(1_000_001)
        self.assertIn("Saldo tidak cukup", html)
        self.assertEqual(self.saldo(), 1_000_000)
        self.assertEqual(self.jumlah_transaksi(), 1)

    def test_tarik_seluruh_saldo_diperbolehkan(self):
        self.setor(1_000_000)
        self.tarik(1_000_000)
        self.assertEqual(self.saldo(), 0)

    def test_tarik_saat_saldo_nol_ditolak(self):
        self.assertIn("Saldo tidak cukup", self.tarik(1))
        self.assertEqual(self.jumlah_transaksi(), 0)

    def test_nominal_tidak_valid_ditolak(self):
        buruk = ["0", "-5", "1.5", "1,5", "abc", "", "   ", "1e3", "+5", "1_000",
                 "5 000", str(10 ** 12 + 1), "9" * 5000]
        for nominal in buruk:
            for aksi in ("SETOR", "TARIK"):
                self._saldo_aksi(aksi, nominal, None)
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(self.jumlah_transaksi(), 0)

    def test_aksi_tidak_dikenal_ditolak(self):
        self._saldo_aksi("HAPUS", 1000, None)
        self.assertEqual(self.jumlah_transaksi(), 0)

    def test_batas_nominal_maksimum_masih_diterima(self):
        self.setor(10 ** 12)
        self.assertEqual(self.saldo(), 10 ** 12)


# ======================================================================
class TestProduk(Dasar):
    def setUp(self):
        super().setUp()
        self.daftar()
        self.setor(5_000_000)

    def test_beli_mengurangi_saldo_dan_menambah_modal(self):
        self.beli(1, 2_000_000)
        self.assertEqual(self.saldo(), 3_000_000)
        self.assertEqual(self.modal(1, 1), 2_000_000)

    def test_beli_dua_kali_modal_ditambahkan(self):
        self.beli(1, 1_000_000)
        self.beli(1, 500_000)
        self.assertEqual(self.modal(1, 1), 1_500_000)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM kepemilikan")[0][0], 1)

    def test_beli_melebihi_saldo_ditolak(self):
        html = self.beli(1, 5_000_001)
        self.assertIn("Saldo tidak cukup", html)
        self.assertEqual(self.saldo(), 5_000_000)
        self.assertEqual(self.modal(1, 1), 0)

    def test_beli_dengan_seluruh_saldo_diperbolehkan(self):
        self.beli(2, 5_000_000)
        self.assertEqual(self.saldo(), 0)

    def test_jual_sebagian_modal_dilepas_proporsional(self):
        self.beli(1, 2_000_000)           # nilai = 2.100.000
        self.jual(1, 1_050_000)           # setengah nilai
        self.assertEqual(self.saldo(), 3_000_000 + 1_050_000)
        self.assertEqual(self.modal(1, 1), 1_000_000)

    def test_jual_melebihi_nilai_ditolak(self):
        self.beli(1, 2_000_000)
        html = self.jual(1, 2_100_001)
        self.assertIn("Nominal melebihi nilai sekarang", html)
        self.assertEqual(self.modal(1, 1), 2_000_000)
        self.assertEqual(self.saldo(), 3_000_000)

    def test_jual_seluruh_nilai_modal_menjadi_nol(self):
        self.beli(1, 2_000_000)
        self.jual(1, 2_100_000)
        self.assertEqual(self.modal(1, 1), 0)
        self.assertEqual(self.saldo(), 3_000_000 + 2_100_000)

    def test_jual_produk_yang_tidak_dimiliki_ditolak(self):
        html = self.jual(2, 1000)
        self.assertIn("belum memiliki produk", html)
        self.assertEqual(self.saldo(), 5_000_000)

    def test_produk_tidak_ada_ditolak(self):
        for produk_id in (99, 0, -1):
            self.beli(produk_id, 1000)
        self._produk_aksi("BELI", "abc", 1000, None)
        self.assertEqual(self.saldo(), 5_000_000)
        self.assertEqual(self.jumlah_transaksi(), 1)  # hanya setor awal

    def test_produk_nonaktif_tidak_bisa_dibeli_tapi_bisa_dijual(self):
        self.beli(3, 1_000_000)
        db = sqlite3.connect(self.path)
        db.execute("UPDATE produk SET aktif = 0 WHERE id = 3")
        db.commit()
        db.close()
        html = self.beli(3, 1_000)
        self.assertIn("tidak tersedia", html)
        self.assertEqual(self.modal(1, 3), 1_000_000)
        self.jual(3, 1_020_000)
        self.assertEqual(self.modal(1, 3), 0)

    def test_aksi_produk_tidak_dikenal_ditolak(self):
        self._produk_aksi("TARIK", 1, 1000, None)
        self.assertEqual(self.jumlah_transaksi(), 1)

    def test_nominal_tidak_valid_ditolak(self):
        for nominal in ["0", "-1", "1.5", "abc", "", "1_000"]:
            self.beli(1, nominal)
        self.assertEqual(self.saldo(), 5_000_000)
        self.assertEqual(self.jumlah_transaksi(), 1)

    def test_pembulatan_nilai(self):
        self.assertEqual(modul.hitung_nilai(95_238, 5.0), 100_000)
        self.assertEqual(modul.hitung_nilai(1_000_000, 2.0), 1_020_000)
        self.assertEqual(modul.hitung_nilai(0, 5.0), 0)
        self.assertEqual(modul.hitung_nilai(100, 0.5), 101)      # 100,5 dibulatkan naik
        self.assertEqual(modul.hitung_nilai(1_000_000, -3.5), 965_000)


# ======================================================================
class TestPerhitungan(Dasar):
    def setUp(self):
        super().setUp()
        self.daftar()

    def test_contoh_tahap_1(self):
        self.setor(5_000_000)
        self.beli(1, 2_000_000)
        self.beli(3, 1_000_000)
        r = self.ringkasan()
        self.assertEqual(r["saldo"], 2_000_000)
        self.assertEqual(r["total_modal"], 3_000_000)
        self.assertEqual(r["total_nilai"], 3_120_000)
        self.assertEqual(r["untung"], 120_000)
        self.assertAlmostEqual(r["persen"], 4.0, places=6)
        self.assertEqual(r["total_aset"], 5_120_000)

    def test_contoh_tahap_2_setelah_jual(self):
        self.setor(5_000_000)
        self.beli(1, 2_000_000)
        self.beli(3, 1_000_000)
        self.jual(1, 1_050_000)
        self.assertEqual(self.saldo(), 3_050_000)
        self.assertEqual(self.modal(1, 1), 1_000_000)
        self.assertEqual(self.modal(1, 3), 1_000_000)

    def test_skenario_dari_percobaan_nyata(self):
        self.setor(5_000_000)
        self.beli(1, 2_000_000)
        self.beli(3, 1_000_000)
        self.jual(1, 1_050_000)
        self.beli(1, 2_000_000)
        self.jual(1, 2_000_000)
        self.jual(1, 1_050_000)
        self.assertEqual(self.saldo(), 4_100_000)
        self.assertEqual(self.modal(1, 1), 95_238)
        r = self.ringkasan()
        self.assertEqual(r["total_modal"], 1_095_238)
        self.assertEqual(r["total_nilai"], 1_120_000)
        self.assertEqual(round(r["persen"], 2), 2.26)

    def test_tanpa_investasi_persen_nol(self):
        r = self.ringkasan()
        self.assertEqual(r["total_modal"], 0)
        self.assertEqual(r["persen"], 0.0)
        self.assertEqual(r["total_aset"], 0)

    def test_perubahan_persentase_produk_mengubah_nilai(self):
        self.setor(1_000_000)
        self.beli(3, 1_000_000)
        db = sqlite3.connect(self.path)
        db.execute("UPDATE produk SET kenaikan_persen = -10 WHERE id = 3")
        db.commit()
        db.close()
        r = self.ringkasan()
        self.assertEqual(r["total_nilai"], 900_000)
        self.assertEqual(r["untung"], -100_000)
        self.assertAlmostEqual(r["persen"], -10.0, places=6)

    def test_tampilan_dashboard_dan_riwayat_terbuka(self):
        self.setor(5_000_000)
        self.beli(1, 2_000_000)
        for path in ["/", "/produk", "/saldo", "/riwayat"]:
            self.assertEqual(self.klien.get(path).status_code, 200, path)


# ======================================================================
class TestKonsistensi(Dasar):
    def jumlah_bertanda(self, uid):
        return self.kueri(
            "SELECT COALESCE(SUM(CASE jenis WHEN 'SETOR' THEN nominal "
            "WHEN 'JUAL' THEN nominal ELSE -nominal END), 0) "
            "FROM transaksi WHERE pengguna_id = ?", uid)[0][0]

    def periksa_aturan_dasar(self):
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM saldo WHERE jumlah < 0")[0][0], 0)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM kepemilikan WHERE modal < 0")[0][0], 0)

    def test_acak_saldo_selalu_cocok_dengan_catatan(self):
        acak = random.Random(2026)
        klien = {1: self.klien, 2: modul.app.test_client()}
        self.daftar(klien[1], nama="A", email="a@contoh.com")
        self.daftar(klien[2], nama="B", email="b@contoh.com")
        pilihan = [1, 999, 123_456, 1_000_000, 7_654_321]

        for _ in range(300):
            u = acak.choice([1, 2])
            aksi = acak.choice(["SETOR", "SETOR", "TARIK", "BELI", "BELI",
                                "JUAL", "JUAL", "JUAL_SEMUA"])
            n = acak.choice(pilihan)
            produk_id = acak.choice([1, 2, 3])
            if aksi in ("SETOR", "TARIK"):
                klien[u].post("/saldo", data={"aksi": aksi, "nominal": n})
            elif aksi == "JUAL_SEMUA":
                persen = self.kueri("SELECT kenaikan_persen FROM produk WHERE id = ?",
                                    produk_id)[0][0]
                nilai = modul.hitung_nilai(self.modal(u, produk_id), persen)
                if nilai > 0:
                    klien[u].post("/produk/transaksi", data={
                        "produk_id": produk_id, "aksi": "JUAL", "nominal": nilai})
            else:
                klien[u].post("/produk/transaksi", data={
                    "produk_id": produk_id, "aksi": aksi, "nominal": n})
            self.periksa_aturan_dasar()

        for uid in (1, 2):
            self.assertEqual(self.saldo(uid), self.jumlah_bertanda(uid), f"pengguna {uid}")
        for jenis in ("SETOR", "TARIK", "BELI", "JUAL"):
            jumlah = self.kueri("SELECT COUNT(*) FROM transaksi WHERE jenis = ?", jenis)[0][0]
            self.assertGreater(jumlah, 0, f"tidak ada transaksi {jenis}: uji kurang bermakna")

    def test_kegagalan_di_tengah_proses_membatalkan_semuanya(self):
        self.daftar()
        self.setor(1_000_000)
        asli = modul.proses_beli

        def rusak(db, pengguna_id, produk, nominal):
            db.execute("UPDATE saldo SET jumlah = jumlah - ? WHERE pengguna_id = ?",
                       (nominal, pengguna_id))
            raise RuntimeError("gagal di tengah proses")

        modul.proses_beli = rusak
        try:
            with self.assertRaises(RuntimeError):
                self.klien.post("/produk/transaksi", data={
                    "produk_id": "1", "aksi": "BELI", "nominal": "400000"})
        finally:
            modul.proses_beli = asli

        self.assertEqual(self.saldo(), 1_000_000)      # saldo kembali utuh
        self.assertEqual(self.modal(1, 1), 0)
        self.assertEqual(self.jumlah_transaksi(), 1)   # hanya setor awal
        # setelah kegagalan, transaksi berikutnya tetap berjalan normal
        self.beli(1, 400_000)
        self.assertEqual(self.saldo(), 600_000)


# ======================================================================
class TestIsolasiPengguna(Dasar):
    def setUp(self):
        super().setUp()
        self.klien_a = self.klien
        self.klien_b = modul.app.test_client()
        self.daftar(self.klien_a, nama="A", email="a@contoh.com")
        self.daftar(self.klien_b, nama="B", email="b@contoh.com")

    def test_saldo_masing_masing(self):
        self.setor(7_654_321, self.klien_a)
        self.assertEqual(self.saldo(1), 7_654_321)
        self.assertEqual(self.saldo(2), 0)

    def test_pengguna_lain_tidak_bisa_menjual_milik_orang(self):
        self.setor(2_000_000, self.klien_a)
        self.beli(1, 2_000_000, self.klien_a)
        html = self.jual(1, 1_000_000, self.klien_b)
        self.assertIn("belum memiliki produk", html)
        self.assertEqual(self.modal(1, 1), 2_000_000)
        self.assertEqual(self.saldo(2), 0)

    def test_riwayat_hanya_milik_sendiri(self):
        self.setor(7_654_321, self.klien_a)
        halaman_a = self.klien_a.get("/riwayat").get_data(as_text=True)
        halaman_b = self.klien_b.get("/riwayat").get_data(as_text=True)
        self.assertIn("7.654.321", halaman_a)
        self.assertNotIn("7.654.321", halaman_b)
        self.assertIn("Belum ada transaksi", halaman_b)

    def test_dashboard_menampilkan_saldo_sendiri(self):
        self.setor(7_654_321, self.klien_a)
        self.assertIn("Rp7.654.321", self.klien_a.get("/").get_data(as_text=True))
        self.assertNotIn("7.654.321", self.klien_b.get("/").get_data(as_text=True))


# ======================================================================
def ambil_token(html):
    cocok = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return cocok.group(1) if cocok else None


class TestKeamanan(Dasar):
    def setUp(self):
        super().setUp()
        modul.app.config["CSRF_AKTIF"] = True

    def tearDown(self):
        modul.app.config["CSRF_AKTIF"] = False
        super().tearDown()

    def daftar_dengan_token(self, klien, email="uji@contoh.com"):
        token = ambil_token(klien.get("/daftar").get_data(as_text=True))
        return klien.post("/daftar", data={
            "csrf_token": token, "nama": "Uji", "email": email,
            "kata_sandi": "rahasia123"}, follow_redirects=True)

    # ---- CSRF ----
    def test_kiriman_tanpa_token_ditolak(self):
        r = self.klien.post("/daftar", data={
            "nama": "Uji", "email": "uji@contoh.com", "kata_sandi": "rahasia123"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 0)

    def test_kiriman_dengan_token_salah_ditolak(self):
        self.klien.get("/daftar")
        r = self.klien.post("/daftar", data={
            "csrf_token": "token-palsu", "nama": "Uji",
            "email": "uji@contoh.com", "kata_sandi": "rahasia123"})
        self.assertEqual(r.status_code, 400)

    def test_kiriman_dengan_token_benar_diterima(self):
        r = self.daftar_dengan_token(self.klien)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 1)

    def test_token_dari_sesi_lain_ditolak(self):
        lain = modul.app.test_client()
        token_lain = ambil_token(lain.get("/daftar").get_data(as_text=True))
        self.klien.get("/daftar")
        r = self.klien.post("/daftar", data={
            "csrf_token": token_lain, "nama": "Uji",
            "email": "uji@contoh.com", "kata_sandi": "rahasia123"})
        self.assertEqual(r.status_code, 400)

    def test_transaksi_tanpa_token_ditolak_walau_sudah_login(self):
        self.daftar_dengan_token(self.klien)
        r = self.klien.post("/saldo", data={"aksi": "SETOR", "nominal": "1000"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.saldo(), 0)
        r = self.klien.post("/produk/transaksi", data={
            "produk_id": "1", "aksi": "BELI", "nominal": "1000"})
        self.assertEqual(r.status_code, 400)
        r = self.klien.post("/keluar")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.klien.get("/").status_code, 200)   # masih login

    def test_transaksi_dengan_token_diterima(self):
        self.daftar_dengan_token(self.klien)
        token = ambil_token(self.klien.get("/saldo").get_data(as_text=True))
        self.klien.post("/saldo", data={"csrf_token": token, "aksi": "SETOR",
                                        "nominal": "5000"})
        self.assertEqual(self.saldo(), 5000)

    def test_token_berganti_setelah_login(self):
        self.daftar_dengan_token(self.klien)
        lama = ambil_token(self.klien.get("/saldo").get_data(as_text=True))
        self.klien.post("/keluar", data={"csrf_token": lama})
        baru = ambil_token(self.klien.get("/login").get_data(as_text=True))
        self.assertNotEqual(lama, baru)

    def test_setiap_formulir_membawa_token(self):
        self.daftar_dengan_token(self.klien)
        for path in ["/saldo", "/produk", "/", "/riwayat"]:
            html = self.klien.get(path).get_data(as_text=True)
            self.assertEqual(html.count("<form"), html.count('name="csrf_token"'), path)
        anonim = modul.app.test_client()
        for path in ["/login", "/daftar"]:
            html = anonim.get(path).get_data(as_text=True)
            self.assertGreaterEqual(html.count('name="csrf_token"'), 1, path)

    # ---- Pembatasan login ----
    def test_login_diblokir_setelah_lima_kali_salah(self):
        modul.app.config["CSRF_AKTIF"] = False
        self.daftar()
        lain = modul.app.test_client()
        for _ in range(modul.BATAS_GAGAL):
            html = self.masuk(lain, "uji@contoh.com", "salah-salah")
            self.assertIn("Email atau kata sandi salah", html)
        r = lain.post("/login", data={"email": "uji@contoh.com",
                                      "kata_sandi": "rahasia123"})
        self.assertEqual(r.status_code, 429)           # walau sandi benar
        self.assertIn("Terlalu banyak percobaan", r.get_data(as_text=True))
        self.assertEqual(lain.get("/").status_code, 302)

    def test_blokir_berakhir_setelah_jendela_waktu(self):
        modul.app.config["CSRF_AKTIF"] = False
        self.daftar()
        lain = modul.app.test_client()
        for _ in range(modul.BATAS_GAGAL):
            self.masuk(lain, "uji@contoh.com", "salah-salah")
        for kunci in modul.percobaan_gagal:           # anggap sudah 11 menit berlalu
            modul.percobaan_gagal[kunci] = [t - 660 for t in modul.percobaan_gagal[kunci]]
        self.masuk(lain, "uji@contoh.com", "rahasia123")
        self.assertEqual(lain.get("/").status_code, 200)

    def test_login_berhasil_menghapus_catatan_gagal(self):
        modul.app.config["CSRF_AKTIF"] = False
        self.daftar()
        lain = modul.app.test_client()
        for _ in range(modul.BATAS_GAGAL - 1):
            self.masuk(lain, "uji@contoh.com", "salah-salah")
        self.masuk(lain, "uji@contoh.com", "rahasia123")
        self.assertEqual(modul.percobaan_gagal, {})

    def test_blokir_tidak_mengunci_email_yang_sama_dari_alamat_lain(self):
        modul.app.config["CSRF_AKTIF"] = False
        self.daftar()
        penyerang = modul.app.test_client()
        for _ in range(modul.BATAS_GAGAL):
            penyerang.post("/login", data={"email": "uji@contoh.com", "kata_sandi": "x"},
                           environ_base={"REMOTE_ADDR": "10.0.0.9"})
        pemilik = modul.app.test_client()
        r = pemilik.post("/login", data={"email": "uji@contoh.com",
                                         "kata_sandi": "rahasia123"},
                         environ_base={"REMOTE_ADDR": "10.0.0.1"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(pemilik.get("/").status_code, 200)

    # ---- Header, cookie, kunci ----
    def test_header_keamanan_terpasang(self):
        r = self.klien.get("/login")
        self.assertEqual(r.headers["X-Frame-Options"], "DENY")
        self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", r.headers["Content-Security-Policy"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")

    def test_halaman_tidak_memakai_skrip_atau_gaya_inline(self):
        self.daftar_dengan_token(self.klien)
        for path in ["/", "/produk", "/saldo", "/riwayat"]:
            html = self.klien.get(path).get_data(as_text=True)
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)", path)
            self.assertNotIn("<style", html, path)
            self.assertNotRegex(html, r"\sstyle=", path)
            self.assertNotRegex(html, r"\sonclick=", path)

    def test_cookie_sesi_httponly_dan_samesite(self):
        r = self.klien.get("/login")
        cookie = " ".join(r.headers.getlist("Set-Cookie"))
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_kunci_rahasia_kuat_dan_bukan_bawaan_lama(self):
        kunci = modul.app.config["SECRET_KEY"]
        self.assertGreaterEqual(len(kunci), 32)
        self.assertNotIn("ganti-ini", kunci)

    def test_halaman_tidak_ada_menampilkan_pesan_ramah(self):
        r = self.klien.get("/halaman-yang-tidak-ada")
        self.assertEqual(r.status_code, 404)
        html = r.get_data(as_text=True)
        self.assertIn("Halaman tidak ditemukan", html)
        self.assertNotIn("Traceback", html)

    # ---- Batas panjang input ----
    def test_input_terlalu_panjang_ditolak(self):
        modul.app.config["CSRF_AKTIF"] = False
        self.assertIn("terlalu panjang", self.daftar(nama="A" * 101))
        self.assertIn("terlalu panjang", self.daftar(email="a" * 250 + "@x.com"))
        self.assertIn("maksimal 128", self.daftar(sandi="x" * 129))
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 0)


# ======================================================================
class TestPersiapanPublikasi(Dasar):
    def test_siapkan_database_membuat_database_lengkap_jika_belum_ada(self):
        baru = os.path.join(self.folder, "baru.db")
        modul.DB_PATH = baru
        modul.siapkan_database()
        db = sqlite3.connect(baru)
        tabel = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        produk = db.execute("SELECT COUNT(*) FROM produk").fetchone()[0]
        db.close()
        for nama in ("pengguna", "saldo", "produk", "kepemilikan", "transaksi"):
            self.assertIn(nama, tabel)
        self.assertEqual(produk, 3)

    def test_siapkan_database_tidak_menimpa_data_yang_ada(self):
        self.daftar()
        modul.siapkan_database()
        self.assertEqual(self.kueri("SELECT COUNT(*) FROM pengguna")[0][0], 1)

    def test_catatan_simulasi_tampil_di_halaman_login(self):
        html = self.klien.get("/login").get_data(as_text=True)
        self.assertIn("Aplikasi simulasi untuk belajar", html)

    def test_mode_hosting_membaca_pengaturan_dari_environment(self):
        """Jalankan Python terpisah dengan APP_HTTPS=1 (seperti di hosting)."""
        kode = (
            "import app as m\n"
            "c = m.app.test_client()\n"
            "m.app.config['CSRF_AKTIF'] = False\n"
            "r = c.get('/login')\n"
            "print('SECURE', 'Secure' in ' '.join(r.headers.getlist('Set-Cookie')))\n"
            "print('HSTS', 'Strict-Transport-Security' in r.headers)\n"
            "print('KUNCI', m.app.config['SECRET_KEY'] == 'k' * 40)\n"
            "c.post('/login', data={'email': 'x@x.com', 'kata_sandi': 'y'},\n"
            "       headers={'X-Forwarded-For': '203.0.113.7'})\n"
            "print('IP', [k[0] for k in m.percobaan_gagal])\n"
        )
        lingkungan = dict(os.environ, APP_HTTPS="1", SECRET_KEY="k" * 40,
                          DATABASE_PATH=os.path.join(self.folder, "hosting.db"))
        hasil = subprocess.run([sys.executable, "-c", kode], cwd=FOLDER, env=lingkungan,
                               capture_output=True, text=True, timeout=60)
        self.assertEqual(hasil.returncode, 0, hasil.stderr)
        self.assertIn("SECURE True", hasil.stdout)
        self.assertIn("HSTS True", hasil.stdout)
        self.assertIn("KUNCI True", hasil.stdout)
        self.assertIn("IP ['203.0.113.7']", hasil.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)