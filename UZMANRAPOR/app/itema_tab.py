from __future__ import annotations

import os
from typing import Dict, Optional

import pandas as pd
from PySide6.QtCore import Qt, QMarginsF
from PySide6.QtGui import QPainter, QPageSize, QPageLayout
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QGridLayout,
    QMessageBox,
    QScrollArea,
    QGroupBox,
    QInputDialog,
    QSizePolicy,
)

from app.itema_settings import build_itema_settings, ITEMA_COLUMNS, ConnectionLike
from app.sql_api_client import get_sql_connection


class ItemaAyarTab(QWidget):
    """
    Excel'deki ITEMA_AYAR_FORMU sayfasına benzer yeni sekme.
    Tip kodu girilip 'Otomatik Ayarları Getir' denildiğinde:
      - Varsayılan ayarlar
      - Otomatik ayarlar (sp_ItemaOtomatikAyar)
      - Tip-özel ayarlar (sp_ItemaTipOzelAyar)
    birleştirilerek arayüz alanlarına yazılır.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fields: Dict[str, QLineEdit] = {}
        self._dynamic_fields: Dict[str, QLineEdit] = {}
        self._last_tip_features: Dict[str, Optional[str]] = {}
        self._manual_password = (
            os.getenv("ITEMA_MANUAL_PASSWORD")
            or os.getenv("ITEMA_FORM_PASSWORD")
            or "itema2024"
        )

        # Yarım ekran görünümü için
        self._left_panel: Optional[QWidget] = None
        self._right_panel: Optional[QWidget] = None
        self._print_widget: Optional[QWidget] = None  # yazdırılacak widget (inner)
        self._compact_level = 0  # 0 normal, 1 kompakt, 2 ultra kompakt

        self._build_ui()
        self._apply_compact_by_height()  # ilk açılışta da uygula

    # ------------------------------------------------------------------
    # UI KURULUMU
    # ------------------------------------------------------------------
    def _build_ui(self):
        self._apply_style()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        # ÜST BAR: Tip gir + buton
        top = QHBoxLayout()
        top.setSpacing(8)

        lbl_tip = QLabel("Tip Kodu:")
        lbl_tip.setObjectName("ItemaLabel")
        top.addWidget(lbl_tip)

        self.ed_tip = QLineEdit()
        self.ed_tip.setPlaceholderText("Örn: RX14908")
        self.ed_tip.setMaxLength(50)
        self.ed_tip.setObjectName("ItemaTipEdit")
        top.addWidget(self.ed_tip)

        self.btn_fetch = QPushButton("Otomatik Ayarları Getir")
        self.btn_fetch.setObjectName("ItemaPrimaryButton")
        self.btn_fetch.clicked.connect(self._on_fetch_clicked)
        top.addWidget(self.btn_fetch)

        self.btn_print = QPushButton("A4 Çıktı Al")
        self.btn_print.setObjectName("ItemaSecondaryButton")
        self.btn_print.clicked.connect(self._print_form)
        top.addWidget(self.btn_print)

        top.addStretch(1)
        main_layout.addLayout(top)

        # ALANLAR: scroll içinde form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("ItemaScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        inner = QWidget()
        inner.setObjectName("ItemaInner")

        # Dikey sığdırma için KOMPAKT layout
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(6, 6, 6, 6)
        inner_layout.setSpacing(6)

        inner_layout.addWidget(self._build_header_box())
        inner_layout.addWidget(self._build_body_box())
        inner_layout.addWidget(self._build_footer_box())
        # Dikeyde boşluk uzatmasın diye stretch eklemiyoruz

        scroll.setWidget(inner)
        self._print_widget = inner  # yazdırma için en doğru hedef

        # Gövdeyi iki kolon gibi yap: sol form, sağ boş alan
        body = QHBoxLayout()
        body.setSpacing(12)

        left_panel = QWidget()
        left_panel.setObjectName("ItemaLeftPanel")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(scroll)

        right_panel = QWidget()
        right_panel.setObjectName("ItemaRightPanel")
        right_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        body.addWidget(left_panel)
        body.addWidget(right_panel, 1)

        main_layout.addLayout(body, 1)

        self._left_panel = left_panel
        self._right_panel = right_panel

        # İlk açılışta yarım genişliğe oturt
        self._apply_half_width()

    def _apply_style(self) -> None:
        """
        Mavi-beyaz tema + kompakt dikey görünüm (baz).
        Kompakt seviyeleri ayrıca _apply_compact_by_height() ile dinamik eklenir.
        """
        self.setStyleSheet(
            """
            QWidget#ItemaLeftPanel {
                background: #F7FAFF;
                border: 1px solid #D6E6FF;
                border-radius: 10px;
            }
            QWidget#ItemaRightPanel {
                background: #FFFFFF;
            }

            QScrollArea#ItemaScroll {
                border: 0px;
                background: transparent;
            }
            QWidget#ItemaInner {
                background: transparent;
            }

            QLabel#ItemaLabel {
                font-weight: 600;
                color: #0A5097;
            }

            QGroupBox {
                border: 1px solid #D6E6FF;
                border-radius: 10px;
                margin-top: 10px;
                background: #FFFFFF;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #0A5097;
                font-weight: 700;
            }

            QLineEdit {
                border: 1px solid #C9D9F2;
                border-radius: 8px;
                padding: 3px 6px;
                min-height: 22px;
                background: #FFFFFF;
            }
            QLineEdit:focus {
                border: 1px solid #2F80ED;
            }

            QPushButton#ItemaPrimaryButton {
                background: #2F80ED;
                color: white;
                border: 1px solid #2F80ED;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 700;
            }
            QPushButton#ItemaPrimaryButton:hover {
                background: #1E6FD6;
                border-color: #1E6FD6;
            }
            QPushButton#ItemaPrimaryButton:pressed {
                background: #165DB5;
                border-color: #165DB5;
            }

            QPushButton#ItemaSecondaryButton {
                background: #E9F2FF;
                color: #0A5097;
                border: 1px solid #BFD6FF;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 700;
            }
            QPushButton#ItemaSecondaryButton:hover {
                background: #DCEBFF;
                border-color: #AFCBFF;
            }
            QPushButton#ItemaSecondaryButton:pressed {
                background: #CFE2FF;
                border-color: #9FBFFF;
            }

            QPushButton#ItemaWarnButton {
                background: #FFF3D6;
                color: #7A4B00;
                border: 1px solid #FFD28A;
                border-radius: 10px;
                padding: 6px 10px;
                font-weight: 800;
            }
            QPushButton#ItemaWarnButton:hover {
                background: #FFE8B6;
            }
            QPushButton#ItemaWarnButton:pressed {
                background: #FFDE9A;
            }
            """
        )

    def _apply_compact_by_height(self) -> None:
        """
        Pencere yüksekliği küçükse formun dikey ölçülerini otomatik sıkıştırır.
        0: normal
        1: kompakt (genelde 900px altı)
        2: ultra (genelde 780px altı)
        """
        h = self.height()

        level = 0
        if h < 900:
            level = 1
        if h < 780:
            level = 2

        if level == getattr(self, "_compact_level", 0):
            return

        self._compact_level = level

        # Stil parametreleri
        if level == 0:
            le_pad = "3px 6px"
            le_min_h = "22px"
            gb_margin_top = "10px"
            btn_pad = "6px 10px"
            title_font_weight = "700"
            inner_margins = (6, 6, 6, 6)
            inner_spacing = 6
        elif level == 1:
            le_pad = "2px 6px"
            le_min_h = "20px"
            gb_margin_top = "8px"
            btn_pad = "5px 10px"
            title_font_weight = "700"
            inner_margins = (5, 5, 5, 5)
            inner_spacing = 5
        else:
            le_pad = "1px 5px"
            le_min_h = "18px"
            gb_margin_top = "6px"
            btn_pad = "4px 9px"
            title_font_weight = "600"
            inner_margins = (4, 4, 4, 4)
            inner_spacing = 4

        # Inner layout margin/spacing güncelle (varsa)
        if self._print_widget is not None:
            lay = self._print_widget.layout()
            if lay is not None:
                lay.setContentsMargins(*inner_margins)
                lay.setSpacing(inner_spacing)

        # Baz stil + kompakt override ekle (tema bozulmasın)
        base = self.styleSheet()
        compact_qss = f"""
        QGroupBox {{ margin-top: {gb_margin_top}; }}
        QGroupBox::title {{ font-weight: {title_font_weight}; }}
        QLineEdit {{ padding: {le_pad}; min-height: {le_min_h}; }}
        QPushButton#ItemaPrimaryButton,
        QPushButton#ItemaSecondaryButton,
        QPushButton#ItemaWarnButton {{ padding: {btn_pad}; }}
        """
        # Aynı override tekrar tekrar eklenmesin diye en pratik yol: base'e eklemeden önce
        # önceki compact bloklarını kabaca ayıklamak zor; burada minimal riskle ekliyoruz.
        # Çünkü level değiştikçe yeniden set edilecek ve en alttaki selector geçerli olacak.
        self.setStyleSheet(base + compact_qss)

        # Layout yeniden hesap
        self.updateGeometry()
        if self._print_widget is not None:
            self._print_widget.adjustSize()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_half_width()
        self._apply_compact_by_height()

    def _apply_half_width(self) -> None:
        if not self._left_panel:
            return
        # Sekme genişliğinin %50'si. Çok dar ekranlarda kullanılabilirlik için min 520 px.
        w = self.width()
        target = max(520, int(w * 0.50))
        self._left_panel.setFixedWidth(target)

    def _build_header_box(self) -> QGroupBox:
        box = QGroupBox("Ürün / Tip Bilgileri")
        layout = QGridLayout(box)
        layout.setVerticalSpacing(4)
        layout.setHorizontalSpacing(10)

        def add(label: str, key: str, row: int, col: int, dynamic: bool = True):
            lbl = QLabel(label)
            lbl.setStyleSheet("font-weight: 700; color: #0A5097;")
            edit = QLineEdit()
            edit.setObjectName(key)
            layout.addWidget(lbl, row, col)
            layout.addWidget(edit, row, col + 1)
            (self._dynamic_fields if dynamic else self._fields)[key] = edit

        # --- Genel bilgiler (iki blok: sol 0-1, sağ 2-3) ---
        add("Tip Kodu", "tip", 0, 0)
        add("Kök Tip", "kok_tip", 0, 2)

        add("Tarak Grubu", "tarak_grubu", 1, 0)
        add("Atkı Sıklığı", "atki_sikligi", 1, 2)

        add("Zemin Örgü", "zemin_orgu", 2, 0)
        add("Kenar Örgü", "kenar_orgu", 2, 2)

        add("Süs Kenar", "sus_kenar", 3, 0)
        add("Dokunabilirlik", "dokunabilirlik", 3, 2)

        add("Çözgü Kodu", "cozgu_kodu", 4, 0)
        add("Boya Kodu", "boya_kodu", 4, 2)

        add("Çerçeve Adedi", "cerceve_adedi", 5, 0)
        add("Kenar Çerçeve", "kenar_cerceve", 5, 2)

        # --- ÇÖZGÜ (2x2 düzen) ---
        add("Çözgü 1", "cozgu1", 6, 0)
        add("Çözgü 3", "cozgu3", 6, 2)

        add("Çözgü 2", "cozgu2", 7, 0)
        add("Çözgü 4", "cozgu4", 7, 2)

        # --- ATKI + ATIM sağa hizalı ---
        add("Atkı 1", "atki1", 8, 0)
        add("Atkı1 Atım", "atki1_atim", 8, 2)

        add("Atkı 2", "atki2", 9, 0)
        add("Atkı2 Atım", "atki2_atim", 9, 2)

        add("Atkı 3", "atki3", 10, 0)
        add("Atkı 4", "atki4", 11, 0)

        return box

    def _build_body_box(self) -> QGroupBox:
        box = QGroupBox("Makine Ayarları")
        grid = QGridLayout(box)
        grid.setVerticalSpacing(4)
        grid.setHorizontalSpacing(10)

        row = 0

        def add_row(
            label_left: str,
            key_left: str,
            label_right: Optional[str] = None,
            key_right: Optional[str] = None,
            color: Optional[str] = None,
        ):
            nonlocal row
            lblL = QLabel(label_left)
            if color:
                lblL.setStyleSheet(f"color: {color}; font-weight: 700;")
            editL = QLineEdit()
            editL.setObjectName(key_left)
            grid.addWidget(lblL, row, 0)
            grid.addWidget(editL, row, 1)
            self._fields[key_left] = editL

            if label_right and key_right:
                lblR = QLabel(label_right)
                if color:
                    lblR.setStyleSheet(f"color: {color}; font-weight: 700;")
                editR = QLineEdit()
                editR.setObjectName(key_right)
                grid.addWidget(lblR, row, 2)
                grid.addWidget(editR, row, 3)
                self._fields[key_right] = editR

            row += 1

        add_row("Telef Sol", "telef_ken1", "Telef Sağ", "telef_ken2", color="#d9534f")
        add_row("Fırça Seçimi", "firca_secim", "Cımbar", "cimbar_secim")
        add_row("Üfleme Zamanı 1", "ufleme_zam_1", "Üfleme Zamanı 2", "ufleme_zam_2")
        add_row("Tansiyon", "coz_tansiyon", "Devir", "devir")
        add_row("Leno", "leno", "Arka Desen", "ark_desen")

        add_row("Ağızlık Geometrisi (Strok)", "agizlik", "Arka Köprü Derinlik", "derinlik")
        add_row("Arka Köprü Pozisyon", "pozisyon", "Testere Uzaklık", "testere_uzk")
        add_row("Testere Yükseklik", "testere_yuk", "Tansiyon Yay Pozisyonu", "tan_yay_pozisyon")
        add_row("Tansiyon Yay Yüksekliği", "tan_yay_yukseklik", "Tansiyon Yay Konumu", "tan_yay_konumu")
        add_row("Yay Boğumu", "tan_yay_bogumu", "Zemin Ağızlık", "zem_agizlik")
        add_row("Kapanma Dur 1", "kapanma_dur_1", "Oturma Düzeyi 1", "oturma_duzeyi_1")
        add_row("Kapanma Dur 2", "kapanma_dur_2", "Oturma Düzeyi 2", "oturma_duzeyi_2")

        # Motor rampaları (tek sıra)
        ramp_box = QGroupBox("Motor Rampaları")
        ramp_grid = QGridLayout(ramp_box)
        ramp_grid.setVerticalSpacing(4)
        ramp_grid.setHorizontalSpacing(8)

        for idx in range(1, 7):
            lbl = QLabel(f"Rampa {idx}")
            edit = QLineEdit()
            key = f"rampa_{idx}"
            edit.setObjectName(key)
            self._fields[key] = edit
            r = 0
            c = idx - 1
            ramp_grid.addWidget(lbl, r, c * 2)
            ramp_grid.addWidget(edit, r, c * 2 + 1)

        grid.addWidget(ramp_box, row, 0, 1, 4)
        row += 1

        return box

    def _add_field(self, key: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setObjectName(key)
        self._fields[key] = edit
        return edit

    def _build_footer_box(self) -> QGroupBox:
        box = QGroupBox("Notlar / Yetki")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        grid.addWidget(QLabel("Açıklama"), 0, 0)
        grid.addWidget(self._add_field("aciklama"), 0, 1)
        grid.addWidget(QLabel("Değişiklik Yapan"), 1, 0)
        grid.addWidget(self._add_field("degisiklik_yapan"), 1, 1)

        self.btn_save_manual = QPushButton("Manuel Ayarı Kaydet")
        self.btn_save_manual.setObjectName("ItemaWarnButton")
        self.btn_save_manual.clicked.connect(self._on_manual_save)
        grid.addWidget(self.btn_save_manual, 0, 2, 2, 1)

        return box

    def _clear_form(self, keep_tip: Optional[str] = None) -> None:
        # Dinamik alanlar (header)
        for _, w in self._dynamic_fields.items():
            w.blockSignals(True)
            w.setText("")
            w.blockSignals(False)

        # Makine alanları + notlar
        for _, w in self._fields.items():
            w.blockSignals(True)
            w.setText("")
            w.blockSignals(False)

        # Tip kalsın istiyorsan
        if keep_tip:
            if "tip" in self._dynamic_fields:
                self._dynamic_fields["tip"].setText(keep_tip)
            self.ed_tip.setText(keep_tip)

        self._last_tip_features = {}

    # ------------------------------------------------------------------
    # LOGİK: AYAR ÇEKME
    # ------------------------------------------------------------------
    def _on_fetch_clicked(self):
        tip_raw = (self.ed_tip.text() or "").strip()
        if not tip_raw:
            QMessageBox.warning(self, "Uyarı", "Önce bir tip kodu girin.")
            return

        tip = tip_raw.upper()

        # >>> KRİTİK: HER FETCH'TE ÖNCE FORMU TEMİZLE <<<
        self._clear_form(keep_tip=tip)

        # Dinamik rapordaki verileri başlık alanlarına taşı
        tip_features = self._populate_from_dynamic(tip)

        # Dinamik raporda tip yoksa: form zaten temiz; uyar
        if not tip_features or len(tip_features.keys()) <= 1:
            QMessageBox.information(
                self,
                "Bilgi",
                f"{tip} tipi dinamik raporda bulunamadı. Form temizlendi."
            )
            return

        try:
            conn = get_sql_connection()
        except Exception as e:
            QMessageBox.critical(self, "Bağlantı Hatası", f"SQL sunucusuna bağlanılamadı:\n\n{e}")
            return

        try:
            settings = build_itema_settings(conn, tip, tip_features)
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"ITEMA ayarları okunurken bir hata oluştu:\n\n{e}")
            return
        finally:
            try:
                conn.close()
            except Exception:
                pass

        if not settings:
            QMessageBox.information(
                self,
                "Bilgi",
                f"{tip} tipi için ayar kağıdı bulunamadı. Form temizlendi."
            )
            return

        # Alanlara yaz (makine ayarları vb.)
        for key, widget in self._fields.items():
            widget.setText(settings.get(key) or "")

        # Başlık/dinamik alanlar (tip, kök tip vb.)
        for key, widget in self._dynamic_fields.items():
            val = settings.get(key)
            if val is None:
                continue
            widget.setText(str(val))

        QMessageBox.information(self, "Tamam", f"{tip} tipi için otomatik ITEMA ayarları getirildi.")

    # ------------------------------------------------------------------
    # Dinamik rapordan başlık bilgilerini doldurma
    # ------------------------------------------------------------------
    def _populate_from_dynamic(self, tip: str) -> Dict[str, Optional[str]]:
        win = self.window()
        df: Optional[pd.DataFrame] = getattr(win, "df_dinamik_full", None)

        tip_features: Dict[str, Optional[str]] = {}

        if df is None or df.empty:
            return tip_features

        norm_tip = (tip or "").strip().upper()
        tip_features["tip"] = norm_tip
        if "tip" in self._dynamic_fields:
            self._dynamic_fields["tip"].setText(norm_tip)

        # Tip satırını bul
        candidates = []
        for col in ["Mamul Tip Kodu", "Tip Kodu", "Tip", "Kök Tip Kodu"]:
            if col in df.columns:
                s = df[col].astype(str).str.strip().str.upper()
                m = df[s == norm_tip]
                if not m.empty:
                    candidates.append(m)

        if not candidates:
            return tip_features

        row = candidates[0].iloc[0]

        def get_first(*cols: str) -> Optional[str]:
            for c in cols:
                if c in row.index and pd.notna(row[c]):
                    v = str(row[c]).strip()
                    if v and v.lower() != "nan":
                        return v
            return None

        def set_dyn(ui_key: str, value: Optional[str]):
            if value is None:
                return
            tip_features[ui_key] = value
            w = self._dynamic_fields.get(ui_key)
            if w is not None:
                w.setText(str(value))

        # Mapping
        set_dyn("kok_tip", get_first("Kök Tip Kodu", "Kok Tip Kodu", "KökTip"))
        set_dyn("tarak_grubu", get_first("Tarak Grubu", "Tarak"))
        set_dyn("zemin_orgu", get_first("Zemin Örgü", "Zemin Orgu"))
        set_dyn("kenar_orgu", get_first("Kenar Örgü", "Kenar Orgu"))
        set_dyn("sus_kenar", get_first("Süs Kenar", "Sus Kenar"))
        set_dyn("dokunabilirlik", get_first("Dokunabilirlik Oranı", "Dokunabilirlik"))
        set_dyn("atki_sikligi", get_first("7100", "Atkı Sıklığı", "Atki Sikligi"))
        set_dyn("cozgu_kodu", get_first("Çözgü Kodu", "Cozgu Kodu"))
        set_dyn("boya_kodu", get_first("İhzarat Boya Kodu", "Ihzarat Boya Kodu", "Boya Kodu"))
        set_dyn("cerceve_adedi", get_first("Çerçeve Adedi", "Cerceve Adedi"))
        set_dyn("kenar_cerceve", get_first("Kenar Adedi", "Kenar Çerçeve", "Kenar Cerceve"))

        def combine(no_col: str, yarn_col: str) -> Optional[str]:
            no = get_first(no_col)
            yarn = get_first(yarn_col)
            if not no and not yarn:
                return None
            if yarn and no and yarn.startswith(no):
                return yarn
            parts = [p for p in [no, yarn] if p]
            return " ".join(parts) if parts else None

        set_dyn("cozgu1", combine("Çözgü İplik No 1", "Çözgü İpliği 1"))
        set_dyn("cozgu2", combine("Çözgü İplik No 2", "Çözgü İpliği 2"))
        set_dyn("cozgu3", combine("Çözgü İplik No 3", "Çözgü İpliği 3"))
        set_dyn("cozgu4", combine("Çözgü İplik No 4", "Çözgü İpliği 4"))

        set_dyn("atki1", combine("Atkı İplik No 1", "Atkı İpliği 1"))
        set_dyn("atki2", combine("Atkı İplik No 2", "Atkı İpliği 2"))
        set_dyn("atki3", combine("Atkı İplik No 3", "Atkı İpliği 3"))
        set_dyn("atki4", combine("Atkı İplik No 4", "Atkı İpliği 4"))

        set_dyn("atki1_atim", get_first("Atkı Atma Adedi 1", "Atki Atma Adedi 1"))
        set_dyn("atki2_atim", get_first("Atkı Atma Adedi 2", "Atki Atma Adedi 2"))

        return tip_features

    # ------------------------------------------------------------------
    # MANUEL KAYIT
    # ------------------------------------------------------------------
    def _on_manual_save(self):
        pwd, ok = QInputDialog.getText(
            self,
            "Manuel Ayar Yetkisi",
            "Lütfen yetki şifresini girin:",
            echo=QLineEdit.Password,
        )
        if not ok:
            return
        if pwd != self._manual_password:
            QMessageBox.warning(self, "Yetki", "Geçersiz şifre.")
            return

        tip_widget = self._dynamic_fields.get("tip")
        tip_val = tip_widget.text().strip().upper() if tip_widget else self.ed_tip.text().strip().upper()
        if not tip_val:
            QMessageBox.warning(self, "Uyarı", "Kaydetmek için bir tip kodu girin.")
            return

        try:
            conn = get_sql_connection()
        except Exception as e:
            QMessageBox.critical(self, "Bağlantı", f"SQL bağlantısı açılamadı:\n{e}")
            return

        data = {
            **{k: f.text() for k, f in self._fields.items()},
            **{k: f.text() for k, f in self._dynamic_fields.items()},
        }

        # header'daki Tarak Grubu -> SQL kolon adı "tarak"
        tg = self._dynamic_fields.get("tarak_grubu")
        if tg and tg.text().strip():
            data["tarak"] = tg.text().strip()

        data["tip"] = tip_val

        try:
            self._save_manual_settings(conn, data)
            QMessageBox.information(self, "Tamam", f"{tip_val} tipi için manuel ayar güncellendi.")
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Kayıt sırasında hata oluştu:\n{e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _save_manual_settings(self, conn: ConnectionLike, values: Dict[str, str]) -> None:
        table = "dbo.ItemaAyar"

        # sira_no identity => asla insert/update listesine koyma
        cols = [c for c in ITEMA_COLUMNS if c.lower() != "sira_no"]

        tip_val = (values.get("tip") or "").strip().upper()
        if not tip_val:
            raise ValueError("Tip boş olamaz.")

        set_cols = [c for c in cols if c.lower() != "tip"]

        update_set_sql = ", ".join([f"[{c}] = ?" for c in set_cols])
        insert_cols_sql = ", ".join([f"[{c}]" for c in cols])
        insert_placeholders = ", ".join(["?"] * len(cols))

        update_params = [(values.get(c) or None) for c in set_cols]
        insert_params = [(values.get(c) or None) for c in cols]

        sql = f"""
        IF EXISTS (SELECT 1 FROM {table} WHERE [tip] = ?)
        BEGIN
            UPDATE {table}
            SET {update_set_sql}
            WHERE [tip] = ?;
        END
        ELSE
        BEGIN
            INSERT INTO {table} ({insert_cols_sql})
            VALUES ({insert_placeholders});
        END
        """

        exec_params = [tip_val, *update_params, tip_val, *insert_params]

        cur = conn.cursor()
        cur.execute(sql, exec_params)
        conn.commit()

    # ------------------------------------------------------------------
    # A4 ÇIKTI (YAZICIYA GÖNDER) - TEK SAYFAYA SIĞDIR
    # ------------------------------------------------------------------
    def _print_form(self):
        target = self._print_widget or (self._left_panel if self._left_panel else self)
        if target is None:
            QMessageBox.warning(self, "Çıktı", "Yazdırılacak alan bulunamadı.")
            return

        # Layout hesapları güncel olsun
        target.adjustSize()

        printer = QPrinter(QPrinter.HighResolution)
        printer.setOutputFormat(QPrinter.NativeFormat)

        # A4 + Portrait + margin (mm)
        page_size = QPageSize(QPageSize.PageSizeId.A4)
        page_layout = QPageLayout(
            page_size,
            QPageLayout.Orientation.Portrait,
            QMarginsF(10, 10, 10, 10),  # mm
            QPageLayout.Unit.Millimeter,
        )
        printer.setPageLayout(page_layout)

        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("ITEMA Ayar Formu - A4 Yazdır")
        if dlg.exec() != QPrintDialog.Accepted:
            return

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(self, "Çıktı", "Yazıcı başlatılamadı.")
            return

        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)

            # Yazdırılabilir alan (pixel)
            page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)

            # Gerçek içerik boyutu: adjustSize sonrası target.size() en güvenlisi
            src_size = target.size()
            if src_size.width() <= 0 or src_size.height() <= 0:
                src_size = target.sizeHint()

            if src_size.width() <= 0 or src_size.height() <= 0:
                QMessageBox.warning(self, "Çıktı", "Form ölçüsü okunamadı.")
                return

            # Ölçek: sayfaya sığdır (aspect ratio koru)
            sx = page_rect.width() / float(src_size.width())
            sy = page_rect.height() / float(src_size.height())
            scale = min(sx, sy)

            # Ortala
            new_w = int(src_size.width() * scale)
            new_h = int(src_size.height() * scale)
            x_off = page_rect.x() + max(0, (page_rect.width() - new_w) // 2)
            y_off = page_rect.y() + max(0, (page_rect.height() - new_h) // 2)

            painter.translate(x_off, y_off)
            painter.scale(scale, scale)

            # PySide6 doğru imza: renderFlags parametresi
            target.render(
                painter,
                renderFlags=QWidget.RenderFlag.DrawWindowBackground | QWidget.RenderFlag.DrawChildren,
            )
        finally:
            painter.end()
