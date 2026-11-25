import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "database.db")



def muat_secret_key():
    """Ambil kunci rahasia dari environment; kalau tidak ada, buat file rahasia.key."""
    dari_env = os.environ.get("SECRET_KEY")
    if dari_env:
        return dari_env
    lokasi = os.path.join(BASE_DIR, "rahasia.key")
    if os.path.exists(lokasi):
        with open(lokasi, encoding="utf-8") as f:
            return f.read().strip()
    kunci = secrets.token_hex(32)
    with open(lokasi, "w", encoding="utf-8") as f:
        f.write(kunci)
    return kunci


# Isi APP_HTTPS=1 setelah aplikasi dipublikasikan dengan HTTPS (Tahap 9)
PAKAI_HTTPS = os.environ.get("APP_HTTPS") == "1"

app = Flask(__name__)
app.config.update(
    SECRET_KEY=muat_secret_key(),
    SESSION_COOKIE_HTTPONLY=True,      # cookie tidak bisa dibaca JavaScript
    SESSION_COOKIE_SAMESITE="Lax",     # cookie tidak ikut dikirim dari situs lain
    SESSION_COOKIE_SECURE=PAKAI_HTTPS, # hanya lewat HTTPS (kalau sudah dipakai)
    CSRF_AKTIF=True,
)

# Di hosting, aplikasi berada di belakang server perantara (proxy). Kalau tidak
# diatur, semua pengunjung tampak berasal dari satu alamat yang sama.
if PAKAI_HTTPS:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)


# ---------- Database ----------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def tutup_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def siapkan_database():
    """Buat database dari schema.sql kalau belum ada (berguna saat pertama dipublikasikan)."""
    sudah_ada = False
    if os.path.exists(DB_PATH):
        db = sqlite3.connect(DB_PATH)
        try:
            sudah_ada = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pengguna'"
            ).fetchone() is not None
        finally:
            db.close()
    if not sudah_ada:
        with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
            skema = f.read()
        db = sqlite3.connect(DB_PATH)
        try:
            db.executescript(skema)
            db.commit()
        finally:
            db.close()


siapkan_database()


# ---------- Keamanan ----------
def token_csrf():
    """Token acak per sesi; dipasang di setiap formulir."""
    token = session.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf"] = token
    return token


app.jinja_env.globals["csrf_token"] = token_csrf


@app.before_request
def periksa_csrf():
    """Tolak kiriman formulir yang tidak membawa token yang benar."""
    if request.method != "POST" or not app.config.get("CSRF_AKTIF", True):
        return
    asli = session.get("csrf", "")
    dikirim = request.form.get("csrf_token", "")
    if not asli or not secrets.compare_digest(asli.encode(), dikirim.encode()):
        abort(400)


@app.after_request
def tambah_header_keamanan(respons):
    respons.headers["X-Content-Type-Options"] = "nosniff"
    respons.headers["X-Frame-Options"] = "DENY"
    respons.headers["Referrer-Policy"] = "same-origin"
    respons.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data:; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    )
    if PAKAI_HTTPS:
        respons.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.endpoint != "static":
        respons.headers["Cache-Control"] = "no-store"
    return respons


PESAN_ERROR = {
    400: "Permintaan tidak valid atau formulir sudah kedaluwarsa. "
         "Muat ulang halaman lalu coba lagi.",
    404: "Halaman tidak ditemukan.",
    405: "Cara akses ini tidak diizinkan.",
    429: "Terlalu banyak percobaan. Coba lagi nanti.",
}


@app.errorhandler(HTTPException)
def tangani_error(e):
    kode = e.code or 500
    pesan = PESAN_ERROR.get(kode, "Terjadi kesalahan pada server.")
    return render_template("error.html", kode=kode, pesan=pesan), kode


# Pembatasan login: maksimal 5 kali salah dalam 10 menit per alamat + email
BATAS_GAGAL = 5
JENDELA_DETIK = 600
percobaan_gagal = {}


def kunci_percobaan(email):
    return (request.remote_addr or "?", email)


def _masih_berlaku(daftar, sekarang):
    return [t for t in daftar if sekarang - t < JENDELA_DETIK]


def terlalu_banyak_gagal(kunci):
    sekarang = time.time()
    if len(percobaan_gagal) > 5000:          # bersihkan data lama
        for k in list(percobaan_gagal):
            sisa = _masih_berlaku(percobaan_gagal[k], sekarang)
            if sisa:
                percobaan_gagal[k] = sisa
            else:
                del percobaan_gagal[k]
    daftar = _masih_berlaku(percobaan_gagal.get(kunci, []), sekarang)
    if daftar:
        percobaan_gagal[kunci] = daftar
    else:
        percobaan_gagal.pop(kunci, None)
    return len(daftar) >= BATAS_GAGAL


def catat_gagal(kunci):
    percobaan_gagal.setdefault(kunci, []).append(time.time())


# ---------- Format rupiah untuk tampilan ----------
@app.template_filter("rupiah")
def format_rupiah(angka):
    angka = int(angka)
    tanda = "-" if angka < 0 else ""
    return tanda + "Rp" + f"{abs(angka):,}".replace(",", ".")


WIB = timezone(timedelta(hours=7))


@app.template_filter("waktu_wib")
def format_waktu_wib(teks):
    """Database menyimpan jam UTC; tampilkan dalam WIB (UTC+7)."""
    try:
        utc = datetime.strptime(teks, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return teks
    return utc.astimezone(WIB).strftime("%d/%m/%Y %H:%M")


@app.template_filter("persen")
def format_persen(angka):
    return f"{float(angka):+.2f}".replace(".", ",") + "%"


# ---------- Fungsi bantu ----------
BATAS_NOMINAL = 1_000_000_000_000  # 1 triliun rupiah


def baca_nominal(teks):
    """Ubah teks jadi angka bulat > 0. Kalau tidak valid, kembalikan None."""
    teks = (teks or "").strip()
    # Hanya angka 0-9 (tanpa tanda +/-, titik, koma, atau garis bawah)
    if not (teks.isascii() and teks.isdigit()) or len(teks) > 15:
        return None
    angka = int(teks)
    if angka <= 0 or angka > BATAS_NOMINAL:
        return None
    return angka


def ambil_saldo(db, pengguna_id):
    baris = db.execute(
        "SELECT jumlah FROM saldo WHERE pengguna_id = ?", (pengguna_id,)
    ).fetchone()
    return baris["jumlah"] if baris else 0


def hitung_nilai(modal, persen):
    """Nilai sekarang = modal x (1 + persen/100), dibulatkan ke rupiah."""
    faktor = Decimal(1) + Decimal(str(persen)) / Decimal(100)
    hasil = (Decimal(modal) * faktor).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return int(hasil)


def proses_beli(db, pengguna_id, produk, nominal):
    if not produk["aktif"]:
        return False, "Produk ini sedang tidak tersedia untuk dibeli."

    # Saldo hanya berkurang kalau jumlahnya cukup
    cur = db.execute(
        "UPDATE saldo SET jumlah = jumlah - ? "
        "WHERE pengguna_id = ? AND jumlah >= ?",
        (nominal, pengguna_id, nominal),
    )
    if cur.rowcount == 0:
        return False, "Saldo tidak cukup."

    db.execute(
        "INSERT INTO kepemilikan (pengguna_id, produk_id, modal) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT (pengguna_id, produk_id) "
        "DO UPDATE SET modal = modal + excluded.modal",
        (pengguna_id, produk["id"], nominal),
    )
    db.execute(
        "INSERT INTO transaksi (pengguna_id, produk_id, jenis, nominal) "
        "VALUES (?, ?, 'BELI', ?)",
        (pengguna_id, produk["id"], nominal),
    )
    return True, f"Beli {produk['nama']} sebesar {format_rupiah(nominal)} berhasil."


def proses_jual(db, pengguna_id, produk, nominal):
    punya = db.execute(
        "SELECT id, modal FROM kepemilikan WHERE pengguna_id = ? AND produk_id = ?",
        (pengguna_id, produk["id"]),
    ).fetchone()
    modal = punya["modal"] if punya else 0
    nilai = hitung_nilai(modal, produk["kenaikan_persen"])

    if nilai <= 0:
        return False, "Anda belum memiliki produk ini."
    if nominal > nilai:
        return False, (f"Nominal melebihi nilai sekarang "
                       f"({format_rupiah(nilai)}).")

    # Modal yang dilepas sebanding dengan bagian yang dijual
    if nominal == nilai:
        modal_dilepas = modal
    else:
        modal_dilepas = (2 * modal * nominal + nilai) // (2 * nilai)

    db.execute(
        "UPDATE kepemilikan SET modal = modal - ? WHERE id = ?",
        (modal_dilepas, punya["id"]),
    )
    db.execute(
        "UPDATE saldo SET jumlah = jumlah + ? WHERE pengguna_id = ?",
        (nominal, pengguna_id),
    )
    db.execute(
        "INSERT INTO transaksi (pengguna_id, produk_id, jenis, nominal) "
        "VALUES (?, ?, 'JUAL', ?)",
        (pengguna_id, produk["id"], nominal),
    )
    return True, f"Jual {produk['nama']} sebesar {format_rupiah(nominal)} berhasil."


def ringkasan_portofolio(db, pengguna_id):
    """Hitung modal, nilai sekarang, keuntungan, dan total aset pengguna."""
    baris = db.execute(
        "SELECT p.nama, p.kenaikan_persen, k.modal "
        "FROM kepemilikan k JOIN produk p ON p.id = k.produk_id "
        "WHERE k.pengguna_id = ? AND k.modal > 0 ORDER BY p.id",
        (pengguna_id,),
    ).fetchall()

    investasi = []
    total_modal = 0
    total_nilai = 0
    for b in baris:
        nilai = hitung_nilai(b["modal"], b["kenaikan_persen"])
        investasi.append({
            "nama": b["nama"],
            "persen": b["kenaikan_persen"],
            "modal": b["modal"],
            "nilai": nilai,
            "untung": nilai - b["modal"],
        })
        total_modal += b["modal"]
        total_nilai += nilai

    untung = total_nilai - total_modal
    if total_modal > 0:
        persen = float(Decimal(untung) * 100 / Decimal(total_modal))
    else:
        persen = 0.0

    saldo = ambil_saldo(db, pengguna_id)
    return {
        "saldo": saldo,
        "investasi": investasi,
        "total_modal": total_modal,
        "total_nilai": total_nilai,
        "untung": untung,
        "persen": persen,
        "total_aset": saldo + total_nilai,
    }


# ---------- Login ----------
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Silakan masuk terlebih dahulu."
login_manager.login_message_category = "error"


class User(UserMixin):
    def __init__(self, id, nama, email):
        self.id = id
        self.nama = nama
        self.email = email


@login_manager.user_loader
def muat_pengguna(user_id):
    baris = get_db().execute(
        "SELECT id, nama, email FROM pengguna WHERE id = ?", (int(user_id),)
    ).fetchone()
    if baris:
        return User(baris["id"], baris["nama"], baris["email"])
    return None


# ---------- Halaman ----------
@app.route("/")
@login_required
def dashboard():
    ringkasan = ringkasan_portofolio(get_db(), current_user.id)
    return render_template("dashboard.html", r=ringkasan)


@app.route("/saldo", methods=["GET", "POST"])
@login_required
def halaman_saldo():
    db = get_db()

    if request.method == "POST":
        aksi = request.form.get("aksi")
        nominal = baca_nominal(request.form.get("nominal"))

        if aksi not in ("SETOR", "TARIK"):
            flash("Aksi tidak dikenal.", "error")
        elif nominal is None:
            flash("Nominal harus berupa angka bulat lebih dari 0 "
                  "(tanpa titik atau koma).", "error")
        elif aksi == "SETOR":
            db.execute(
                "UPDATE saldo SET jumlah = jumlah + ? WHERE pengguna_id = ?",
                (nominal, current_user.id),
            )
            db.execute(
                "INSERT INTO transaksi (pengguna_id, jenis, nominal) "
                "VALUES (?, 'SETOR', ?)",
                (current_user.id, nominal),
            )
            db.commit()
            flash(f"Setor {format_rupiah(nominal)} berhasil.", "sukses")
        else:
            # Saldo hanya berkurang kalau jumlahnya cukup
            cur = db.execute(
                "UPDATE saldo SET jumlah = jumlah - ? "
                "WHERE pengguna_id = ? AND jumlah >= ?",
                (nominal, current_user.id, nominal),
            )
            if cur.rowcount == 0:
                db.rollback()
                flash("Saldo tidak cukup.", "error")
            else:
                db.execute(
                    "INSERT INTO transaksi (pengguna_id, jenis, nominal) "
                    "VALUES (?, 'TARIK', ?)",
                    (current_user.id, nominal),
                )
                db.commit()
                flash(f"Tarik {format_rupiah(nominal)} berhasil.", "sukses")

        return redirect(url_for("halaman_saldo"))

    return render_template("saldo.html", saldo=ambil_saldo(db, current_user.id))


@app.route("/daftar", methods=["GET", "POST"])
def daftar():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        nama = request.form.get("nama", "").strip()
        email = request.form.get("email", "").strip().lower()
        sandi = request.form.get("kata_sandi", "")

        if not nama or not email or not sandi:
            flash("Semua kolom wajib diisi.", "error")
        elif len(nama) > 100 or len(email) > 254:
            flash("Nama atau email terlalu panjang.", "error")
        elif len(sandi) < 8:
            flash("Kata sandi minimal 8 karakter.", "error")
        elif len(sandi) > 128:
            flash("Kata sandi maksimal 128 karakter.", "error")
        else:
            db = get_db()
            try:
                cur = db.execute(
                    "INSERT INTO pengguna (nama, email, kata_sandi) VALUES (?, ?, ?)",
                    (nama, email, generate_password_hash(sandi)),
                )
                db.execute(
                    "INSERT INTO saldo (pengguna_id, jumlah) VALUES (?, 0)",
                    (cur.lastrowid,),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash("Email sudah terdaftar.", "error")
            else:
                login_user(User(cur.lastrowid, nama, email))
                session.pop("csrf", None)     # token baru setelah login
                flash("Akun berhasil dibuat. Selamat datang!", "sukses")
                return redirect(url_for("dashboard"))

    return render_template("daftar.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        sandi = request.form.get("kata_sandi", "")
        kunci = kunci_percobaan(email)

        if terlalu_banyak_gagal(kunci):
            flash("Terlalu banyak percobaan masuk. Coba lagi dalam 10 menit.", "error")
            return render_template("login.html"), 429

        baris = get_db().execute(
            "SELECT * FROM pengguna WHERE email = ?", (email,)
        ).fetchone()

        if baris and check_password_hash(baris["kata_sandi"], sandi):
            percobaan_gagal.pop(kunci, None)
            login_user(User(baris["id"], baris["nama"], baris["email"]))
            session.pop("csrf", None)         # token baru setelah login
            return redirect(url_for("dashboard"))

        catat_gagal(kunci)
        flash("Email atau kata sandi salah.", "error")

    return render_template("login.html")


@app.route("/produk")
@login_required
def halaman_produk():
    db = get_db()
    baris = db.execute(
        "SELECT p.id, p.nama, p.jenis, p.kenaikan_persen, "
        "       COALESCE(k.modal, 0) AS modal "
        "FROM produk p "
        "LEFT JOIN kepemilikan k "
        "       ON k.produk_id = p.id AND k.pengguna_id = ? "
        "WHERE p.aktif = 1 OR COALESCE(k.modal, 0) > 0 "
        "ORDER BY p.id",
        (current_user.id,),
    ).fetchall()

    daftar = []
    for b in baris:
        daftar.append({
            "id": b["id"],
            "nama": b["nama"],
            "jenis": b["jenis"],
            "kenaikan_persen": b["kenaikan_persen"],
            "modal": b["modal"],
            "nilai": hitung_nilai(b["modal"], b["kenaikan_persen"]),
        })

    return render_template("produk.html", produk=daftar,
                           saldo=ambil_saldo(db, current_user.id))


@app.route("/produk/transaksi", methods=["POST"])
@login_required
def transaksi_produk():
    db = get_db()
    aksi = request.form.get("aksi")
    nominal = baca_nominal(request.form.get("nominal"))
    try:
        produk_id = int(request.form.get("produk_id", ""))
    except ValueError:
        produk_id = None

    if aksi not in ("BELI", "JUAL") or produk_id is None:
        flash("Permintaan tidak valid.", "error")
    elif nominal is None:
        flash("Nominal harus berupa angka bulat lebih dari 0 "
              "(tanpa titik atau koma).", "error")
    else:
        db.execute("BEGIN IMMEDIATE")   # kunci database selama transaksi
        try:
            produk = db.execute(
                "SELECT * FROM produk WHERE id = ?", (produk_id,)
            ).fetchone()
            if produk is None:
                berhasil, pesan = False, "Produk tidak ditemukan."
            elif aksi == "BELI":
                berhasil, pesan = proses_beli(db, current_user.id, produk, nominal)
            else:
                berhasil, pesan = proses_jual(db, current_user.id, produk, nominal)

            if berhasil:
                db.commit()
            else:
                db.rollback()
        except Exception:
            db.rollback()
            raise
        flash(pesan, "sukses" if berhasil else "error")

    return redirect(url_for("halaman_produk"))


@app.route("/riwayat")
@login_required
def halaman_riwayat():
    baris = get_db().execute(
        "SELECT t.id, t.jenis, t.nominal, t.tanggal, p.nama AS produk "
        "FROM transaksi t LEFT JOIN produk p ON p.id = t.produk_id "
        "WHERE t.pengguna_id = ? ORDER BY t.id DESC LIMIT 200",
        (current_user.id,),
    ).fetchall()
    return render_template("riwayat.html", transaksi=baris)


@app.route("/keluar", methods=["POST"])
@login_required
def keluar():
    logout_user()
    session.pop("csrf", None)
    flash("Anda sudah keluar.", "sukses")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)