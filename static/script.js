// Dipakai di halaman Saldo dan Produk
(function () {
  "use strict";

  function rupiah(angka) {
    return "Rp" + angka.toLocaleString("id-ID");
  }

  // 1. Tampilkan nominal dalam format rupiah saat mengetik
  document.querySelectorAll('input[name="nominal"]').forEach(function (kolom) {
    var info = document.createElement("small");
    info.className = "info-nominal";
    var tempat = kolom.closest("label") || kolom.form;
    tempat.insertAdjacentElement("afterend", info);

    function perbarui() {
      var angka = parseInt(kolom.value, 10);
      info.textContent = angka > 0 ? "= " + rupiah(angka) : "";
    }
    kolom.addEventListener("input", perbarui);
    kolom.addEventListener("change", perbarui);
    kolom._perbarui = perbarui;
  });

  // 2. Tombol "Semua": isi nominal dengan seluruh nilai
  document.querySelectorAll(".isi-semua").forEach(function (tombol) {
    tombol.addEventListener("click", function () {
      var kolom = tombol.form.querySelector('input[name="nominal"]');
      kolom.value = tombol.dataset.nilai;
      if (kolom._perbarui) { kolom._perbarui(); }
      kolom.focus();
    });
  });

  // 3. Minta konfirmasi sebelum transaksi dikirim
  var kataAksi = { BELI: "membeli", JUAL: "menjual", SETOR: "menyetor", TARIK: "menarik" };

  document.querySelectorAll("form[data-konfirmasi]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      var tombol = e.submitter;
      var aksi = tombol && tombol.value;
      if (!kataAksi[aksi]) {
        var tersembunyi = form.querySelector('input[type="hidden"][name="aksi"]');
        aksi = tersembunyi ? tersembunyi.value : "";
      }
      var angka = parseInt(form.querySelector('input[name="nominal"]').value, 10);
      var nama = form.dataset.nama ? " " + form.dataset.nama : "";
      var pertanyaan = "Yakin " + (kataAksi[aksi] || "melanjutkan") + nama +
                       " sebesar " + rupiah(angka || 0) + "?";

      if (!window.confirm(pertanyaan)) {
        e.preventDefault();
        return;
      }
      // Cegah klik ganda (ditunda agar tombol yang diklik tetap ikut terkirim)
      setTimeout(function () {
        form.querySelectorAll("button").forEach(function (b) { b.disabled = true; });
      }, 0);
    });
  });

  // Kalau halaman dibuka lewat tombol "Kembali", muat ulang agar tombol aktif lagi
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) { window.location.reload(); }
  });
})();