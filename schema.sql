CREATE TABLE IF NOT EXISTS pengguna (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    kata_sandi TEXT NOT NULL,
    dibuat_pada TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS saldo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pengguna_id INTEGER NOT NULL UNIQUE REFERENCES pengguna(id),
    jumlah INTEGER NOT NULL DEFAULT 0 CHECK (jumlah >= 0)
);
CREATE TABLE IF NOT EXISTS produk (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nama TEXT NOT NULL UNIQUE,
    jenis TEXT NOT NULL,
    kenaikan_persen REAL NOT NULL DEFAULT 0,
    aktif INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS kepemilikan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id),
    produk_id INTEGER NOT NULL REFERENCES produk(id),
    modal INTEGER NOT NULL DEFAULT 0 CHECK (modal >= 0),
    UNIQUE (pengguna_id, produk_id)
);
CREATE TABLE IF NOT EXISTS transaksi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pengguna_id INTEGER NOT NULL REFERENCES pengguna(id),
    produk_id INTEGER REFERENCES PRODUK(id),
    jenis TEXT NOT NULL CHECK (jenis IN ('SETOR', 'TARIK', 'BELI','JUAL')),
    nominal INTEGER NOT NULL CHECK (nominal > 0),
    tanggal TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
 INSERT OR IGNORE INTO produk (nama, jenis, kenaikan_persen) VALUES
   ('Reksadana Pasar Uang', 'Reksadana', 5.0),
   ('Obligasi Negara', 'Obligasi', 6.0),
   ('Emas', 'Logam Mulia', 2.0)