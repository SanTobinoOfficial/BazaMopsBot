#!/usr/bin/env python3
"""
Generuje instrukcja_systemu.pdf
Biale tlo, brak polskich znakow diakrytycznych, styl dokumentu technicznego.
"""

from datetime import date
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)

# ─── Kolory (jasny motyw) ─────────────────────────────────────────────────────

C_WHITE      = colors.white
C_BLACK      = colors.HexColor('#1a1a2e')
C_BLUE_DARK  = colors.HexColor('#1a3a6b')
C_BLUE       = colors.HexColor('#2c5282')
C_BLUE_LIGHT = colors.HexColor('#ebf4ff')
C_BLUE_MID   = colors.HexColor('#bee3f8')
C_GREEN      = colors.HexColor('#276749')
C_GREEN_LIGHT= colors.HexColor('#f0fff4')
C_YELLOW     = colors.HexColor('#744210')
C_YELLOW_BG  = colors.HexColor('#fffff0')
C_RED        = colors.HexColor('#9b2c2c')
C_MUTED      = colors.HexColor('#4a5568')
C_MUTED_LIGHT= colors.HexColor('#718096')
C_GREY_BG    = colors.HexColor('#f7fafc')
C_GREY_LINE  = colors.HexColor('#e2e8f0')
C_PANEL      = colors.HexColor('#edf2f7')
C_CODE_BG    = colors.HexColor('#f1f5f9')
C_CODE_TEXT  = colors.HexColor('#1a365d')
C_HEADER_BG  = colors.HexColor('#2c5282')
C_ROW_ALT    = colors.HexColor('#f0f4f8')

PAGE_W, PAGE_H = A4

# ─── Style ────────────────────────────────────────────────────────────────────

sTitle = ParagraphStyle('sTitle',
    fontName='Helvetica-Bold', fontSize=26, textColor=C_WHITE,
    alignment=TA_CENTER, spaceAfter=6, leading=32)

sSubtitle = ParagraphStyle('sSubtitle',
    fontName='Helvetica', fontSize=13, textColor=C_BLUE_MID,
    alignment=TA_CENTER, spaceAfter=4, leading=17)

sDate = ParagraphStyle('sDate',
    fontName='Helvetica', fontSize=10, textColor=C_BLUE_MID,
    alignment=TA_CENTER)

sH1 = ParagraphStyle('sH1',
    fontName='Helvetica-Bold', fontSize=16, textColor=C_BLUE_DARK,
    spaceBefore=16, spaceAfter=6, leading=20,
    borderPad=0)

sH2 = ParagraphStyle('sH2',
    fontName='Helvetica-Bold', fontSize=12, textColor=C_BLACK,
    spaceBefore=10, spaceAfter=4, leading=15)

sH3 = ParagraphStyle('sH3',
    fontName='Helvetica-Bold', fontSize=10, textColor=C_BLUE,
    spaceBefore=6, spaceAfter=3, leading=13)

sBody = ParagraphStyle('sBody',
    fontName='Helvetica', fontSize=10, textColor=C_BLACK,
    spaceBefore=3, spaceAfter=3, leading=14, alignment=TA_JUSTIFY)

sBodyL = ParagraphStyle('sBodyL',
    fontName='Helvetica', fontSize=10, textColor=C_BLACK,
    spaceBefore=2, spaceAfter=2, leading=14)

sBullet = ParagraphStyle('sBullet',
    fontName='Helvetica', fontSize=10, textColor=C_BLACK,
    spaceBefore=1, spaceAfter=1, leading=13,
    leftIndent=14, firstLineIndent=0)

sCode = ParagraphStyle('sCode',
    fontName='Courier', fontSize=8.5, textColor=C_CODE_TEXT,
    spaceBefore=4, spaceAfter=4, leading=12,
    leftIndent=8, rightIndent=8,
    backColor=C_CODE_BG, borderPad=6)

sNote = ParagraphStyle('sNote',
    fontName='Helvetica-Oblique', fontSize=9, textColor=C_MUTED,
    spaceBefore=3, spaceAfter=3, leading=12, leftIndent=10)

sWarn = ParagraphStyle('sWarn',
    fontName='Helvetica-Bold', fontSize=9.5, textColor=C_YELLOW,
    spaceBefore=4, spaceAfter=4, leading=13, leftIndent=10,
    backColor=C_YELLOW_BG, borderPad=5)

sOk = ParagraphStyle('sOk',
    fontName='Helvetica-Bold', fontSize=9.5, textColor=C_GREEN,
    spaceBefore=4, spaceAfter=4, leading=13, leftIndent=10,
    backColor=C_GREEN_LIGHT, borderPad=5)

sTH = ParagraphStyle('sTH',
    fontName='Helvetica-Bold', fontSize=9, textColor=C_WHITE,
    alignment=TA_CENTER, leading=11)

sTD = ParagraphStyle('sTD',
    fontName='Helvetica', fontSize=9, textColor=C_BLACK,
    leading=12, leftIndent=4)

sTDc = ParagraphStyle('sTDc',
    fontName='Helvetica', fontSize=9, textColor=C_BLACK,
    leading=12, alignment=TA_CENTER)

sTDcode = ParagraphStyle('sTDcode',
    fontName='Courier', fontSize=8, textColor=C_CODE_TEXT,
    leading=11, leftIndent=4)

sTDbold = ParagraphStyle('sTDbold',
    fontName='Helvetica-Bold', fontSize=9, textColor=C_BLACK,
    leading=12, leftIndent=4)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def h1(txt):
    return [
        HRFlowable(width='100%', thickness=2, color=C_BLUE, spaceAfter=4,
                   spaceBefore=14),
        Paragraph(txt, sH1),
        HRFlowable(width='100%', thickness=0.5, color=C_GREY_LINE, spaceAfter=6),
    ]

def h2(txt):   return Paragraph(txt, sH2)
def h3(txt):   return Paragraph(txt, sH3)
def body(txt): return Paragraph(txt, sBody)
def note(txt): return Paragraph('INFO: ' + txt, sNote)
def warn(txt): return Paragraph('UWAGA: ' + txt, sWarn)
def ok(txt):   return Paragraph('OK: ' + txt, sOk)
def sp(h=0.3): return Spacer(1, h * cm)

def code(*lines):
    joined = '<br/>'.join(lines)
    return Paragraph(joined, sCode)

def bullet(items):
    return [Paragraph('  -  ' + i, sBullet) for i in items]

def make_table(headers, rows, col_widths=None, first_col_code=True):
    data = [[Paragraph(h, sTH) for h in headers]]
    for row in rows:
        r = []
        for i, c in enumerate(row):
            if i == 0 and first_col_code:
                r.append(Paragraph(str(c), sTDcode))
            else:
                r.append(Paragraph(str(c), sTD))
        data.append(r)

    if col_widths is None:
        n = len(headers)
        col_widths = [16.5 * cm / n] * n

    style = TableStyle([
        ('BACKGROUND',   (0, 0), (-1, 0),   C_HEADER_BG),
        ('ROWBACKGROUNDS',(0,1), (-1,-1),    [C_WHITE, C_ROW_ALT]),
        ('GRID',         (0, 0), (-1, -1),  0.5, C_GREY_LINE),
        ('TOPPADDING',   (0, 0), (-1, -1),  5),
        ('BOTTOMPADDING',(0, 0), (-1, -1),  5),
        ('LEFTPADDING',  (0, 0), (-1, -1),  6),
        ('RIGHTPADDING', (0, 0), (-1, -1),  6),
        ('VALIGN',       (0, 0), (-1, -1),  'MIDDLE'),
        ('BOX',          (0, 0), (-1, -1),  1,   C_GREY_LINE),
    ])
    t = Table(data, colWidths=col_widths)
    t.setStyle(style)
    return t

def pin_table(rows):
    return make_table(
        ['Pin GPIO', 'Nazwa w kodzie', 'Podlacz do', 'Opis'],
        rows,
        col_widths=[2.3*cm, 4.2*cm, 4.5*cm, 5.5*cm],
        first_col_code=True
    )

def conn_table(rows):
    return make_table(
        ['Skad', 'Dokad', 'Opis'],
        rows,
        col_widths=[5*cm, 5.5*cm, 6*cm],
        first_col_code=False
    )

# ─── Naglowek / stopka ────────────────────────────────────────────────────────

def _header_footer(canvas, doc):
    canvas.saveState()
    # biale tlo
    canvas.setFillColor(C_WHITE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # pasek gorny
    canvas.setFillColor(C_HEADER_BG)
    canvas.rect(0, PAGE_H - 1.1*cm, PAGE_W, 1.1*cm, fill=1, stroke=0)
    canvas.setFont('Helvetica-Bold', 7.5)
    canvas.setFillColor(C_WHITE)
    canvas.drawString(1.5*cm, PAGE_H - 0.72*cm,
                      'INSTRUKCJA SYSTEMU LACZNOSCI - SZALAS')
    canvas.setFont('Helvetica', 7.5)
    canvas.setFillColor(C_BLUE_MID)
    canvas.drawRightString(PAGE_W - 1.5*cm, PAGE_H - 0.72*cm,
                           f'v1.0  |  {date.today().strftime("%d.%m.%Y")}')
    # linia pod paskiem
    canvas.setStrokeColor(C_BLUE)
    canvas.setLineWidth(0.5)
    canvas.line(0, PAGE_H - 1.1*cm, PAGE_W, PAGE_H - 1.1*cm)
    # pasek dolny
    canvas.setFillColor(C_GREY_BG)
    canvas.rect(0, 0, PAGE_W, 0.85*cm, fill=1, stroke=0)
    canvas.setStrokeColor(C_GREY_LINE)
    canvas.setLineWidth(0.5)
    canvas.line(0, 0.85*cm, PAGE_W, 0.85*cm)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(C_MUTED)
    canvas.drawCentredString(PAGE_W / 2, 0.28*cm, f'Strona {doc.page}')
    canvas.restoreState()

def _title_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_WHITE)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    # duzy niebieski blok tytulowy
    canvas.setFillColor(C_HEADER_BG)
    canvas.rect(0, PAGE_H * 0.55, PAGE_W, PAGE_H * 0.45, fill=1, stroke=0)
    # zielony pasek akcentowy
    canvas.setFillColor(C_GREEN)
    canvas.rect(0, PAGE_H * 0.55 - 0.35*cm, PAGE_W, 0.35*cm, fill=1, stroke=0)
    # stopka
    canvas.setFillColor(C_GREY_BG)
    canvas.rect(0, 0, PAGE_W, 1.2*cm, fill=1, stroke=0)
    canvas.setStrokeColor(C_GREY_LINE)
    canvas.line(0, 1.2*cm, PAGE_W, 1.2*cm)
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(C_MUTED)
    canvas.drawCentredString(PAGE_W / 2, 0.42*cm, 'Strona 1')
    canvas.restoreState()

# ─── TRESC DOKUMENTU ─────────────────────────────────────────────────────────

def build_story():
    s = []

    # ===================================================================
    # STRONA TYTULOWA
    # ===================================================================
    s.append(Spacer(1, 4.5*cm))
    s.append(Paragraph('Instrukcja Systemu Lacznosci', sTitle))
    s.append(Paragraph('Szalas  -  Baza Komunikacyjna i Zarzadzania', sSubtitle))
    s.append(sp(0.4))
    s.append(Paragraph(
        f'Wersja 1.0   |   {date.today().strftime("%d.%m.%Y")}   |   '
        'ESP32 + Raspberry Pi 4 + Discord', sDate))
    s.append(sp(1.8))

    # ramka opisu na stronie tytulowej
    desc_data = [[Paragraph(
        'System laczy fizyczne krotkofalowki RF z serwerem Discord przez siec 4G LTE. '
        'Urzadzenia ESP32 umozliwiaja clock in/out oraz komunikacje PTT przez Wi-Fi. '
        'Raspberry Pi 4 stoi przy szalasie jako centralny wezel audio, laczac kanaly '
        'glosowe Discorda z nadajnikiem radiowym RF. Panel webowy pozwala zarzadzac '
        'uzytkownikami, punktami, rangami i konfiguracja systemu.',
        sBody)]]
    desc_tbl = Table(desc_data, colWidths=[16.5*cm])
    desc_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),(-1,-1), C_BLUE_LIGHT),
        ('BOX',          (0,0),(-1,-1), 1.5, C_BLUE),
        ('LEFTPADDING',  (0,0),(-1,-1), 14),
        ('RIGHTPADDING', (0,0),(-1,-1), 14),
        ('TOPPADDING',   (0,0),(-1,-1), 12),
        ('BOTTOMPADDING',(0,0),(-1,-1), 12),
    ]))
    s.append(desc_tbl)
    s.append(PageBreak())

    # ===================================================================
    # SPIS TRESCI (reczny)
    # ===================================================================
    s += h1('Spis tresci')
    toc_items = [
        ('1.', 'Wstep - Opis systemu'),
        ('2.', 'Lista komponentow'),
        ('3.', 'Schemat polaczen - Stacja bazowa (Raspberry Pi 4)'),
        ('4.', 'Schemat polaczen - Urzadzenie ESP32 D1 Mini'),
        ('5.', 'Konfiguracja oprogramowania - Serwer (Replit / Pi)'),
        ('6.', 'Konfiguracja przez panel webowy (Dashboard)'),
        ('7.', 'Wgrywanie firmware na ESP32'),
        ('8.', 'Pierwsze uruchomienie'),
        ('9.', 'Rozwiazywanie problemow'),
    ]
    toc_data = [[Paragraph(n, sTDbold), Paragraph(t, sTD)] for n, t in toc_items]
    toc_tbl = Table(toc_data, colWidths=[1.2*cm, 15.3*cm])
    toc_tbl.setStyle(TableStyle([
        ('BACKGROUND',   (0,0),(-1,-1), C_WHITE),
        ('ROWBACKGROUNDS',(0,0),(-1,-1),[C_WHITE, C_GREY_BG]),
        ('TOPPADDING',   (0,0),(-1,-1), 5),
        ('BOTTOMPADDING',(0,0),(-1,-1), 5),
        ('LEFTPADDING',  (0,0),(-1,-1), 6),
        ('LINEBELOW',    (0,0),(-1,-1), 0.3, C_GREY_LINE),
    ]))
    s.append(toc_tbl)
    s.append(PageBreak())

    # ===================================================================
    # 1. WSTEP
    # ===================================================================
    s += h1('1. Wstep - Opis systemu')
    s.append(body(
        'System sklada sie z dwoch rodzajow urzadzen: <b>stacji bazowej</b> umieszczonej '
        'przy szalasie oraz <b>urzadzen przenosnych ESP32</b> noszonych przez czlonkow grupy. '
        'Wszystko zarzadzane jest przez serwer Discord i panel webowy Flask.'
    ))
    s.append(sp(0.4))

    s.append(h2('Stacja bazowa (przy szalasie)'))
    s += bullet([
        'Raspberry Pi 4 - komputer glowny: serwer Flask, boty Discord, most audio RF',
        'Router 4G LTE TP-Link MR100 - internet przez karte SIM',
        'Akumulator AGM 12V 20Ah + przetwornica 12V-5V - zasilanie autonomiczne ok. 12h',
        'Adapter USB audio - wejscie/wyjscie audio z fizycznej krotkofalowki',
        'Krotkofalowka z kablem PTT Kenwood 2-pin - nadawanie na czestotliwosci RF',
        'Tranzystor NPN 2N2222 na GPIO Pi - sterowanie linia PTT',
    ])
    s.append(sp(0.3))

    s.append(h2('Urzadzenia przenosne ESP32'))
    s += bullet([
        'ESP32 D1 Mini - mikrokontroler z Wi-Fi',
        'Mikrofon INMP441 (I2S) - cyfrowy mikrofon do PTT',
        'Glosnik 28mm + wzmacniacz PAM8403 - odtwarzanie dzwieku z sieci',
        '4 przyciski: Clock In, Clock Out, PTT, Zmiana kanalu',
        '3 diody LED: zielona (Wi-Fi), czerwona (blad), zolta (PTT / kanal)',
        'Bateria 18650 + modul ladowania TP4056',
    ])
    s.append(sp(0.3))

    s.append(h2('Jak to dziala - przeplyw audio'))
    s += bullet([
        'ESP32 laczy sie z Wi-Fi szalasu i rejestruje sie w serwerze przez HTTP API',
        'Przyciski Clock In/Out rejestruja czas pracy i naliczaja punkty w bazie SQLite',
        'PTT: mikrofon INMP441 (I2S, 16kHz) -> WebSocket -> serwer -> inne urzadzenia i Discord',
        'Przycisk zmiany kanalu cyklicznie przelacza ESP32 miedzy kanalami PTT',
        'Raspberry Pi 4: kazdy kanal Discord ma osobnego bota stale podlaczonego do kanalu glosowego',
        '  -> Audio z Discorda (dowolny kanal) -> kolejka PTT -> fizyczna krotkofalowka RF',
        '  -> Audio z radia RF -> broadcast do WSZYSTKICH kanalow Discorda jednoczesnie',
        'Panel webowy: przeglad punktow, rang, frakcji, konfiguracja serwera',
    ])
    s.append(PageBreak())

    # ===================================================================
    # 2. LISTA KOMPONENTOW
    # ===================================================================
    s += h1('2. Lista komponentow')

    s.append(h2('2.1  Stacja bazowa przy szalasie'))
    s.append(make_table(
        ['Komponent', 'Ilosc', 'Opis i uwagi'],
        [
            ['Raspberry Pi 4 (min. 2GB RAM)',          '1 szt.', 'Serwer, boty Discord, most audio'],
            ['Karta microSD 32GB+',                    '1 szt.', 'System: Raspberry Pi OS 64-bit Lite'],
            ['Router 4G LTE TP-Link MR100',            '1 szt.', 'Internet przez karte SIM LTE'],
            ['Akumulator AGM 12V 20Ah',                '1 szt.', 'Zasilanie autonomiczne ok. 12h'],
            ['Przetwornica DC-DC 12V->5V 3A (LM2596)', '1 szt.', 'Zasilanie Pi z akumulatora, min. 3A'],
            ['Adapter USB audio (karta dzwiekowa USB)', '1 szt.', 'Wejscie MIC + wyjscie SPK do radia'],
            ['Krotkofalowka z kablem Kenwood 2-pin',   '1 szt.', 'Dowolna K-type np. Baofeng UV-5R'],
            ['Kabel PTT Kenwood 2-pin (rozgaleznik)',  '1 szt.', 'Rozdzielony na MIC, SPK, PTT, GND'],
            ['Tranzystor NPN 2N2222 (TO-92)',          '1 szt.', 'Sterowanie linia PTT z GPIO Pi'],
            ['Rezystor 1 kOhm',                        '1 szt.', 'Ogranicznik pradu bazy tranzystora'],
            ['Rezystor 10 kOhm',                       '1 szt.', 'Pull-down na linii PTT (opcjonalnie)'],
            ['Skrzynka wodoszczelna IP65',             '1 szt.', 'Obudowa stacji, min. 20x15x10 cm'],
            ['Kabel USB-C zasilajacy Pi',              '1 szt.', 'Z przetwornicy 5V do Pi 4'],
            ['Przewody polaczeniowe dupont',           '20 szt.','M-M i M-F do polaczen'],
        ],
        col_widths=[6.5*cm, 1.8*cm, 8.2*cm],
        first_col_code=False
    ))
    s.append(sp(0.5))

    s.append(h2('2.2  Urzadzenie przenosne ESP32 (1 sztuka na osobe)'))
    s.append(make_table(
        ['Komponent', 'Ilosc', 'Opis i uwagi'],
        [
            ['ESP32 D1 Mini (LOLIN / Wemos)',         '1 szt.', 'Mikrokontroler z wbudowanym Wi-Fi 2.4GHz'],
            ['Mikrofon INMP441 (I2S MEMS)',           '1 szt.', 'Cyfrowy mikrofon, interfejs I2S, 3.3V'],
            ['Glosnik 28mm 8 Ohm 0.5W',              '1 szt.', 'Odtwarzanie dzwieku PTT z sieci'],
            ['Wzmacniacz audio PAM8403 (mini board)', '1 szt.', 'Wzmocnienie sygnalu do glosnika'],
            ['Przycisk chwilowy 6x6mm',              '4 szt.', 'Clock In, Clock Out, PTT, Zmiana kanalu'],
            ['LED 5mm zielona',                      '1 szt.', 'Status Wi-Fi / polaczony'],
            ['LED 5mm czerwona',                     '1 szt.', 'Blad / brak polaczenia'],
            ['LED 5mm zolta',                        '1 szt.', 'PTT aktywne / potwierdzenie kanalu'],
            ['Rezystor 220 Ohm',                     '3 szt.', 'Ograniczniki pradu LED (jeden na LED)'],
            ['Akumulator Li-Ion 18650 3.7V',         '1 szt.', 'Zasilanie urzadzenia, ok. 8h PTT'],
            ['Modul ladowania TP4056 z USB-C',       '1 szt.', 'Ladowanie ogniwa 18650'],
            ['Plytka stykowa mini lub PCB',          '1 szt.', 'Montaz ukladu'],
            ['Obudowa ABS lub druk 3D',              '1 szt.', 'Ochrona, uchwyt w dloni'],
        ],
        col_widths=[5.5*cm, 1.8*cm, 9.2*cm],
        first_col_code=False
    ))
    s.append(PageBreak())

    # ===================================================================
    # 3. SCHEMAT BAZY (RASPBERRY PI)
    # ===================================================================
    s += h1('3. Schemat polaczen - Stacja bazowa (Raspberry Pi 4)')

    s.append(body(
        'Stacja bazowa laczy Raspberry Pi 4 z fizyczna krotkofalowka przez adapter USB audio. '
        'Linia PTT krotkofalowki jest sterowana tranzystorem NPN 2N2222 podpietym '
        'do pinu GPIO 17 (BCM) Raspberry Pi.'
    ))
    s.append(sp(0.4))

    s.append(h2('3.1  Polaczenia zasilania'))
    s.append(conn_table([
        ['Akumulator 12V (+)', 'Przetwornica - wejscie (+)',      'Zasilanie z akumulatora AGM'],
        ['Akumulator 12V (-)', 'Przetwornica - wejscie (-)',      'Masa akumulatora'],
        ['Przetwornica 5V (+)','Pi - kabel USB-C lub Pin 2 (5V)','Zasilanie Pi z przetwornicy'],
        ['Przetwornica GND',   'Pi - Pin 6 (GND)',               'Masa wspolna'],
        ['Przetwornica 5V',    'Router TP-Link - zasilanie',     'Router rowniez z przetwornicy'],
    ]))
    s.append(sp(0.3))
    s.append(warn(
        'Przetwornica musi obsługiwac min. 3A ciagle. '
        'Raspberry Pi 4 pobiera do 3A przy pelnym obciazeniu + USB audio.'
    ))
    s.append(sp(0.4))

    s.append(h2('3.2  Adapter USB audio <-> Krotkofalowka (kabel Kenwood 2-pin)'))
    s.append(body(
        'Kabel Kenwood 2-pin po przecieciu / rozgalezieniu ma cztery przewody. '
        'Sprawdz kolorystyke kabla multimetrem lub dokumentacja Twojej krotkofalowki.'
    ))
    s.append(sp(0.2))
    s.append(conn_table([
        ['Krotkofalowka - SPK (audio out)',
         'Adapter USB - gniazdo MIC (rozowe 3.5mm)',
         'Dzwiek z radia -> Pi (wejscie)'],
        ['Krotkofalowka - MIC (audio in)',
         'Adapter USB - gniazdo SPK (zielone 3.5mm)',
         'Dzwiek z Pi -> radio (wyjscie)'],
        ['Krotkofalowka - PTT',
         'Kolektor tranzystora 2N2222',
         'Linia PTT przez tranzystor (zwarcie = nadawanie)'],
        ['Krotkofalowka - GND',
         'Pi GND + emiter tranzystora',
         'Masa wspolna ukladu'],
        ['Adapter USB audio',
         'Port USB Pi (dowolny z 4)',
         'Karta dzwiekowa USB, wykrywana automatycznie'],
    ]))
    s.append(sp(0.4))

    s.append(h2('3.3  Tranzystor PTT - NPN 2N2222 (obudowa TO-92)'))
    s.append(body(
        'Tranzystor 2N2222 dziala jako przelacznik elektroniczny. '
        'Gdy Pi wystawia stan HIGH (3.3V) na GPIO 17, tranzystor przewodzi '
        'i zwiera linie PTT krotkofalowki do masy - uruchamiajac nadawanie.'
    ))
    s.append(sp(0.3))
    s.append(code(
        'Widok od plaskiej strony obudowy TO-92:',
        '',
        '     [  E     B     C  ]',
        '      Emiter  Baza  Kolektor',
        '',
        'Polaczenia:',
        '  Baza (B)      <--  Rezystor 1kOhm  <--  Pi GPIO BCM 17',
        '  Emiter (E)    -->  Pi GND (Pin 9 lub 25)',
        '  Kolektor (C)  -->  Krotkofalowka - linia PTT',
        '                     (drugi koniec PTT idzie do GND krotkofalowki)',
    ))
    s.append(sp(0.3))
    s.append(make_table(
        ['Nozka 2N2222', 'Podlacz do', 'Opis'],
        [
            ['Baza (B)',     'Pi GPIO BCM 17 przez rezystor 1kOhm', 'Sygnal sterujacy z Pi (0V lub 3.3V)'],
            ['Emiter (E)',   'Pi GND (Pin 9)',                      'Masa ukladu'],
            ['Kolektor (C)', 'Krotkofalowka - linia PTT',          'Zwarcie PTT->GND = nadawanie'],
        ],
        col_widths=[3.5*cm, 7.5*cm, 5.5*cm],
        first_col_code=True
    ))
    s.append(sp(0.4))

    s.append(h2('3.4  Uzywane piny GPIO Raspberry Pi 4 (naglowek 40-pin, numeracja BCM)'))
    s.append(make_table(
        ['Pin fizyczny', 'Numer BCM', 'Funkcja w projekcie'],
        [
            ['Pin 2',   '5V',  'Zasilanie +5V (z przetwornicy) - lub kabel USB-C'],
            ['Pin 6',   'GND', 'Masa'],
            ['Pin 11',  '17',  'PTT OUT - sterowanie tranzystorem 2N2222'],
            ['Brak',    '-',   'Reszta GPIO: nieuzywana w projekcie bazowym'],
        ],
        col_widths=[3.5*cm, 3.5*cm, 9.5*cm],
        first_col_code=False
    ))
    s.append(sp(0.3))
    s.append(note(
        'Adapter USB audio jest osobnym urzadzeniem podpietym przez USB - '
        'nie wymaga zadnego polaczenia z pinami GPIO.'
    ))
    s.append(PageBreak())

    # ===================================================================
    # 4. SCHEMAT ESP32
    # ===================================================================
    s += h1('4. Schemat polaczen - Urzadzenie ESP32 D1 Mini')

    s.append(body(
        'Tabele ponizej pokazuja wszystkie polaczenia urzadzenia przenosnego. '
        'Na ESP32 D1 Mini piny Dx odpowiadaja konkretnym numerom GPIO. '
        'Upewnij sie ze uzywasz wlasciwej odmiany plytki LOLIN / Wemos D1 Mini ESP32.'
    ))
    s.append(sp(0.3))

    s.append(h2('4.1  Mapowanie pinow D -> GPIO (LOLIN ESP32 D1 Mini)'))
    s.append(make_table(
        ['Oznaczenie plytki', 'Numer GPIO', 'Uzycie w projekcie'],
        [
            ['D2',       'GPIO 21', 'Przycisk CLOCK IN'],
            ['D3',       'GPIO 17', 'Przycisk CLOCK OUT'],
            ['D4',       'GPIO 16', 'Przycisk PTT'],
            ['D5',       'GPIO 14', 'LED Zielona (Wi-Fi OK)'],
            ['D6',       'GPIO 12', 'LED Czerwona (blad)'],
            ['D7',       'GPIO 13', 'LED Zolta (PTT / kanal)'],
            ['(brak D)', 'GPIO 27', 'Przycisk ZMIANA KANALU'],
            ['(brak D)', 'GPIO 26', 'I2S Mikrofon - BCK (Bit Clock)'],
            ['(brak D)', 'GPIO 25', 'I2S Mikrofon - WS (Word Select)'],
            ['(brak D)', 'GPIO 33', 'I2S Mikrofon - SD (Serial Data)'],
            ['(brak D)', 'GPIO 19', 'I2S Glosnik - BCLK'],
            ['(brak D)', 'GPIO 18', 'I2S Glosnik - LRC'],
            ['(brak D)', 'GPIO 22', 'I2S Glosnik - DOUT'],
        ],
        col_widths=[3.8*cm, 3*cm, 9.7*cm],
        first_col_code=True
    ))
    s.append(sp(0.4))

    s.append(h2('4.2  Przyciski (INPUT_PULLUP - drugie nozki wszystkich do GND)'))
    s.append(pin_table([
        ['GPIO 21', 'PIN_BTN_CLOCK_IN',  'Przycisk -> GND', 'Wcisniecie = Clock In (rejestracja czasu pracy)'],
        ['GPIO 17', 'PIN_BTN_CLOCK_OUT', 'Przycisk -> GND', 'Wcisniecie = Clock Out (koniec zmiany)'],
        ['GPIO 16', 'PIN_BTN_PTT',       'Przycisk -> GND', 'Przytrzymanie = nadawanie PTT przez Wi-Fi'],
        ['GPIO 27', 'PIN_BTN_CHANNEL',   'Przycisk -> GND', 'Wcisniecie = nastepny kanal PTT; zolta LED miga N razy'],
    ]))
    s.append(sp(0.2))
    s.append(note(
        'Rezystor pull-up jest wbudowany w ESP32 (INPUT_PULLUP). '
        'Nie potrzeba zewnetrznych rezystorow dla przyciskow.'
    ))
    s.append(sp(0.4))

    s.append(h2('4.3  Diody LED (OUTPUT - przez rezystor 220 Ohm do GND)'))
    s.append(pin_table([
        ['GPIO 14', 'PIN_LED_GREEN',
         'Anoda LED -> GPIO, katoda -> 220Ohm -> GND',
         'SWIECI ciagle: Wi-Fi OK. GASNIE: brak sieci.'],
        ['GPIO 12', 'PIN_LED_RED',
         'Anoda LED -> GPIO, katoda -> 220Ohm -> GND',
         'MIGA 1x: heartbeat fail. MIGA 3x: clock error. MIGA co 1s: brak Wi-Fi.'],
        ['GPIO 13', 'PIN_LED_YELLOW',
         'Anoda LED -> GPIO, katoda -> 220Ohm -> GND',
         'SWIECI: PTT aktywne. MIGA N razy: numer kanalu po zmianie (N = kanal + 1).'],
    ]))
    s.append(sp(0.4))

    s.append(h2('4.4  Mikrofon INMP441 (I2S wejscie)'))
    s.append(body(
        'Mikrofon INMP441 to cyfrowy mikrofon MEMS z interfejsem I2S. '
        'Zasilanie 3.3V. Pin L/R ustawia kanal audio (GND = lewy kanal = ONLY_LEFT w kodzie).'
    ))
    s.append(sp(0.2))
    s.append(make_table(
        ['Pin INMP441', 'Podlacz do ESP32', 'Opis'],
        [
            ['VDD', '3.3V',     'Zasilanie 3.3V'],
            ['GND', 'GND',      'Masa'],
            ['SCK', 'GPIO 26',  'I2S Bit Clock (BCK)'],
            ['WS',  'GPIO 25',  'I2S Word Select / L-R Clock'],
            ['SD',  'GPIO 33',  'I2S Serial Data (wyjscie danych audio)'],
            ['L/R', 'GND',      'Wybor kanalu: GND = lewy (ONLY_LEFT w kodzie firmware)'],
        ],
        col_widths=[2.5*cm, 3.5*cm, 10.5*cm],
        first_col_code=True
    ))
    s.append(sp(0.4))

    s.append(h2('4.5  Glosnik przez wzmacniacz PAM8403'))
    s.append(body(
        'Wzmacniacz PAM8403 to mini modul stereo. W projekcie uzywamy jednego kanalu. '
        'Alternatywnie mozna uzyc modulu MAX98357A ktory obsluguje I2S bezposrednio '
        '(lepsza jakosc dzwieku, prostsze polaczenie).'
    ))
    s.append(sp(0.2))
    s.append(make_table(
        ['Pin / Komponent', 'Podlacz do', 'Opis'],
        [
            ['PAM8403 - VCC',        '5V (z TP4056 lub USB)',    'Zasilanie wzmacniacza (3.3-5V)'],
            ['PAM8403 - GND',        'GND wspolny',              'Masa'],
            ['PAM8403 - IN-L lub IN-R', 'GPIO 22 (DOUT I2S)',   'Sygnal audio z ESP32 I2S'],
            ['PAM8403 - wyjscie L',  'Glosnik 28mm (+)',         'Wyjscie audio do glosnika'],
            ['PAM8403 - GND (out)',  'Glosnik 28mm (-)',         'Masa do glosnika'],
            ['Alternatywa MAX98357A','GPIO 19 (BCLK), 18 (LRC), 22 (DIN)', 'I2S bezposrednio, lepsza jakosc'],
        ],
        col_widths=[4.5*cm, 5.2*cm, 6.8*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('4.6  Zasilanie ESP32 (bateria 18650 + modul TP4056)'))
    s.append(make_table(
        ['Polaczenie', 'Opis'],
        [
            ['TP4056 BAT+ -> ogniwo 18650 (+)', 'Ladowanie i rozladowanie ogniwa'],
            ['TP4056 BAT- -> ogniwo 18650 (-)', 'Masa ogniwa'],
            ['TP4056 OUT+ -> ESP32 5V lub VIN', 'Zasilanie ESP32 z ogniwa (3.7-4.2V, ESP32 ma regulator wewnetrzny)'],
            ['TP4056 OUT- -> ESP32 GND',         'Masa wspolna'],
            ['TP4056 USB-C',                     'Ladowanie ogniwa 5V przez USB'],
        ],
        col_widths=[8*cm, 8.5*cm],
        first_col_code=False
    ))
    s.append(PageBreak())

    # ===================================================================
    # 5. KONFIGURACJA OPROGRAMOWANIA
    # ===================================================================
    s += h1('5. Konfiguracja oprogramowania - Serwer (Replit / Pi)')

    s.append(body(
        'Serwer projektu "SerwerDiscordBazaMops" uruchamia jednoczesnie bota Discord '
        'i panel webowy Flask na porcie 5000. Ponizej krok po kroku jak go skonfigurowac.'
    ))
    s.append(sp(0.3))

    s.append(h2('5.1  Wymagane zmienne srodowiskowe (plik .env)'))
    s.append(body('Utworz plik <font face="Courier">.env</font> w glownym katalogu projektu:'))
    s.append(code(
        '# .env - wypelnij przed uruchomieniem',
        '',
        '# Token glownego bota Discord (system rang i clock in/out)',
        'DISCORD_TOKEN=wklej_token_tutaj',
        '',
        '# Losowy klucz sesji Flask (min. 32 znaki, dowolny ciag)',
        'DASHBOARD_SECRET=wygeneruj_losowy_klucz_np_64_znaki',
        '',
        '# Haslo do panelu webowego',
        'DASHBOARD_PASSWORD=twoje_haslo_do_panelu',
    ))
    s.append(sp(0.4))

    s.append(h2('5.2  Tworzenie glownego bota Discord'))
    s += bullet([
        'Wejdz na: <b>discord.com/developers/applications</b>',
        'Kliknij "New Application" -> wpisz nazwe np. "BazaMOPS Bot"',
        'Przejdz do zakladki "Bot" -> kliknij "Add Bot"',
        'Skopiuj <b>Token</b> -> wklej do DISCORD_TOKEN w pliku .env',
        'Wlacz "Privileged Gateway Intents": SERVER MEMBERS INTENT + MESSAGE CONTENT INTENT',
        'Przejdz do "OAuth2 -> URL Generator" -> zaznacz: bot + applications.commands',
        'W "Bot Permissions" zaznacz: Send Messages, Read Messages, Manage Roles, Connect, Speak',
        'Skopiuj wygenerowany URL i otworz w przegladarce -> dodaj bota do swojego serwera Discord',
    ])
    s.append(sp(0.3))
    s.append(warn(
        'Dla botow kanalow Audio (Radio 1, Radio 2 itd.) stworz ODREBNE aplikacje Discord. '
        'Kazdy bot kanalu ma swoj wlasny token. Token przypisz w: '
        'Dashboard -> Urzadzenia -> edytuj -> "Token bota Discord".'
    ))
    s.append(sp(0.4))

    s.append(h2('5.3  Uruchomienie na Replit'))
    s += bullet([
        'Otworz projekt na replit.com -> zakladka "Secrets" (ikona klodki po lewej)',
        'Dodaj sekret: DISCORD_TOKEN = (token z Discord Developer Portal)',
        'Dodaj sekret: DASHBOARD_SECRET = (losowy ciag min. 32 znaki)',
        'Dodaj sekret: DASHBOARD_PASSWORD = (haslo do panelu)',
        'Kliknij przycisk Run - Replit uruchomi: python main.py',
        'Dashboard dostepny pod URL projektu Replit: https://nazwaapp.replit.app',
        'Port 5000 jest automatycznie mapowany na 80/443 przez infrastrukture Replit',
    ])
    s.append(sp(0.4))

    s.append(h2('5.4  Uruchomienie lokalnie na Raspberry Pi'))
    s.append(code(
        '# Zainstaluj zaleznosci serwera',
        'pip install -r requirements.txt',
        '',
        '# Zainstaluj zaleznosci pi_bridge',
        'pip install -r pi_bridge_requirements.txt',
        'sudo apt install python3-rpi.gpio   # GPIO dla Pi',
        '',
        '# Skonfiguruj zmienne srodowiskowe',
        'nano .env',
        '',
        '# Terminal 1: uruchom serwer glowny',
        'python main.py',
        '',
        '# Terminal 2: uruchom pi_bridge (most audio RF <-> Discord)',
        'GUILD_ID=123456789012345678 \\',
        '  SERVER_URL=http://localhost:5000 \\',
        '  AUDIO_INPUT_IDX=1 \\',
        '  AUDIO_OUTPUT_IDX=1 \\',
        '  GPIO_PTT_PIN=17 \\',
        '  python pi_bridge.py',
    ))
    s.append(sp(0.3))
    s.append(note(
        'GUILD_ID to ID serwera Discord. Aby go znalezc: Discord -> Ustawienia -> '
        'Zaawansowane -> wlacz Tryb dewelopera -> prawy przycisk na nazwie serwera -> "Kopiuj ID serwera".'
    ))
    s.append(PageBreak())

    # ===================================================================
    # 6. KONFIGURACJA DASHBOARDU
    # ===================================================================
    s += h1('6. Konfiguracja przez panel webowy (Dashboard)')

    s.append(body(
        'Panel webowy dostepny pod adresem serwera (URL Replit lub http://IP_PI:5000). '
        'Zaloguj sie haslem ustawionym w DASHBOARD_PASSWORD.'
    ))
    s.append(sp(0.3))

    s.append(h2('6.1  Dodanie urzadzenia ESP32'))
    s += bullet([
        'Wejdz do: Dashboard -> <b>Urzadzenia</b> -> kliknij "Dodaj urzadzenie"',
        '<b>Device ID</b>: unikalna nazwa np. radio_1 (male litery, cyfry, podkreslniki)',
        '<b>Nazwa</b>: wyswietlana nazwa np. "Radio Tomka"',
        '<b>Token bota Discord</b>: token bota przypisanego do tego urzadzenia (opcjonalnie)',
        '<b>Discord User ID</b>: ID konta Discord wlasciciela (dla clock in/out)',
        'Po zapisaniu zobaczysz wygenerowany <b>API Secret</b>',
        'Kliknij na skrocony kod API Secret -> skopiuje sie do schowka',
        'Wklej ten sekret do firmware ESP32 jako API_SECRET',
    ])
    s.append(sp(0.4))

    s.append(h2('6.2  Jak znalezc Discord User ID'))
    s += bullet([
        'W Discordzie: Ustawienia uzytkownika -> Zaawansowane -> wlacz "Tryb dewelopera"',
        'Kliknij prawym przyciskiem myszy na swoje imie w czacie lub na liscie czlonkow',
        'Wybierz "Kopiuj ID uzytkownika"',
        'Wklej ten numer (18 cyfr) w polu Discord User ID w dashboardzie',
    ])
    s.append(sp(0.4))

    s.append(h2('6.3  Konfiguracja kanalow PTT'))
    s += bullet([
        'Wejdz do: Dashboard -> <b>Kanaly PTT</b> -> kliknij "Dodaj kanal"',
        '<b>Nazwa</b>: np. "Kanal 1 Ogolny", "Kanal 2 Alpha-1"',
        '<b>Kolejnosc</b>: 0, 1, 2... - kolejnosc przelaczania przyciskiem D8 na ESP32',
        '<b>Kanal glosowy Discord</b>: wybierz kanal voice powiazany z tym kanalem PTT',
        '<b>Bot Device ID</b>: urzadzenie / bot siedzacy na tym kanale glosowym',
        '<b>Radio bridge</b>: zaznacz na kanale ktory ma PRIORYTET w kolejce PTT do radia',
        'Dodaj tyle kanalow ile masz botow Discord z tokenami w Urzadzeniach',
    ])
    s.append(sp(0.3))
    s.append(note(
        'Kanal oznaczony jako Radio bridge nie jest juz dedykowanym mostem - '
        'teraz oznacza tylko ze audio z tego kanalu Discord trafia do radia '
        'z wyzszym priorytetem (jako pierwsze w kolejce PTT).'
    ))
    s.append(sp(0.4))

    s.append(h2('6.4  Konfiguracja serwera (Config)'))
    s += bullet([
        'Wejdz do: Dashboard -> <b>Konfiguracja</b>',
        '<b>Kanal zegara (apel)</b>: kanal Discord gdzie bot postuje clock in/out',
        '<b>Kanal logow</b>: kanal gdzie zapisywane sa logi akcji adminow',
        '<b>Punkty na godzine</b>: ile punktow zarabia sie za godzine clock in (domyslnie 10)',
        '<b>Role adminow</b>: role Discord majace dostep do komend adminowych bota',
        'Kliknij "Zapisz konfiguracje" - zmiany obowiazuja natychmiast',
    ])
    s.append(sp(0.4))

    s.append(h2('6.5  Auto-konfiguracja MOPS (opcjonalnie)'))
    s += bullet([
        'Wejdz do: Dashboard -> Konfiguracja -> przycisk "MOPS Auto-Setup"',
        'System automatycznie stworzy: role Discord, kategorie, kanaly, frakcje i prace',
        'Operacja jest bezpieczna - nie nadpisze istniejacych rol / kanalow o tych samych nazwach',
        'Po zakonczeniu bot wysle panele interaktywne do kanalow #apel i #prace',
    ])
    s.append(PageBreak())

    # ===================================================================
    # 7. WGRYWANIE KODU NA ESP32
    # ===================================================================
    s += h1('7. Wgrywanie firmware na ESP32')

    s.append(h2('7.1  Instalacja Arduino IDE i obslugi ESP32'))
    s += bullet([
        'Pobierz <b>Arduino IDE 2.x</b> ze strony: arduino.cc/en/software',
        'Zainstaluj i uruchom Arduino IDE',
        'Otworz: Plik -> Preferencje -> "Adresy URL menedzera plytek"',
        'Dodaj URL (caly w jednej linii bez spacji):',
    ])
    s.append(code(
        'https://raw.githubusercontent.com/espressif/arduino-esp32/'
        'gh-pages/package_esp32_index.json'
    ))
    s += bullet([
        'Przejdz do: Narzedzia -> Plytka -> Menedzer plytek',
        'Wyszukaj "esp32" -> zainstaluj pakiet: <b>esp32 by Espressif Systems</b>',
        'Narzedzia -> Plytka -> ESP32 Arduino -> wybierz: <b>ESP32 Dev Module</b> lub <b>LOLIN D32</b>',
    ])
    s.append(sp(0.4))

    s.append(h2('7.2  Wymagane biblioteki Arduino'))
    s.append(body('Zainstaluj przez: Szkic -> Dolacz biblioteke -> Zarzadzaj bibliotekami:'))
    s.append(make_table(
        ['Biblioteka', 'Autor', 'Wersja', 'Uwagi'],
        [
            ['ArduinoJson',  'Benoit Blanchon', 'v6.x', 'Parsowanie JSON (heartbeat, clock, channel)'],
            ['WebSockets',   'Markus Sattler',  'v2.x', 'arduinoWebSockets - klient WebSocket PTT'],
            ['WiFi.h',       '(wbudowana)',      '-',    'Wi-Fi ESP32, nie wymaga instalacji'],
            ['HTTPClient.h', '(wbudowana)',      '-',    'Zapytania HTTP REST API, wbudowana'],
            ['driver/i2s.h', '(wbudowana)',      '-',    'I2S ESP32-IDF, wbudowana w framework'],
        ],
        col_widths=[3.5*cm, 3.8*cm, 2*cm, 7.2*cm],
        first_col_code=True
    ))
    s.append(sp(0.4))

    s.append(h2('7.3  Konfiguracja stalych w firmware (plik esp32/firmware.ino)'))
    s.append(body(
        'Otworz plik <font face="Courier">esp32/firmware.ino</font> '
        'i zmien nastepujace stale w sekcji CONFIGURATION na gorze pliku:'
    ))
    s.append(code(
        '// ─── KONFIGURACJA - zmien przed wgraniem ────────────────────',
        '',
        '#define WIFI_SSID      "NazwaTwojejSieci"',
        '#define WIFI_PASSWORD  "HasloDoSieci"',
        '',
        '// Skopiuj Device ID i API Secret z Dashboard -> Urzadzenia',
        '#define DEVICE_ID      "radio_1"          // Twoje Device ID',
        '#define API_SECRET     "abc123xyz..."      // API Secret z dashboardu',
        '',
        '// Adres serwera: URL Replit lub IP Raspberry Pi',
        '#define API_HOST       "https://nazwaapp.replit.app"',
        '',
        '// WebSocket - ten sam serwer co API_HOST',
        '#define WS_HOST        "nazwaapp.replit.app"   // bez https://',
        '#define WS_PORT        443',
        '#define WS_PATH        "/ws/audio"',
        '#define WS_USE_SSL     true   // true dla Replit/HTTPS, false dla LAN',
        '',
        '// Dla sieci lokalnej (LAN bez SSL):',
        '// #define API_HOST    "http://192.168.1.100:5000"',
        '// #define WS_HOST     "192.168.1.100"',
        '// #define WS_PORT     5000',
        '// #define WS_USE_SSL  false',
    ))
    s.append(sp(0.4))

    s.append(h2('7.4  Wgrywanie firmware (krok po kroku)'))
    s += bullet([
        'Podlacz ESP32 D1 Mini kablem USB-C do komputera',
        'W Arduino IDE: Narzedzia -> Port -> wybierz port COM (Windows: COM3, Linux: /dev/ttyUSB0)',
        'Narzedzia -> Upload Speed -> ustaw 115200',
        'Kliknij strzalke "Wgraj" (lub Ctrl+U) - czekaj ok. 30-60 sekund',
        'Po wgraniu: Narzedzia -> Monitor portu szeregowego (predkosc: 115200 baud)',
        'Powinienes zobaczyc: "[MOPS] Booting..." -> "[WiFi] Connected IP: 192.168.x.x"',
        'Jesli blad "Failed to connect": przytrzymaj przycisk BOOT na plytce podczas wgrywania',
    ])
    s.append(PageBreak())

    # ===================================================================
    # 8. PIERWSZE URUCHOMIENIE
    # ===================================================================
    s += h1('8. Pierwsze uruchomienie')

    s.append(h2('8.1  Kolejnosc wlaczania'))
    s.append(make_table(
        ['Krok', 'Co wlaczyc / uruchomic', 'Czekaj az...'],
        [
            ['1', 'Akumulator 12V -> przetwornica',          'Dioda przetownicy swieci stale'],
            ['2', 'Router 4G LTE',                           'Wskaznik 4G swieci (ok. 60 sekund)'],
            ['3', 'Raspberry Pi 4',                          'LED ACT (zielona) na Pi miga i gasnie (ok. 45s)'],
            ['4', 'python main.py na Pi',                    'Terminal: "[Bot] Ready!" i "[Dashboard] Running"'],
            ['5', 'python pi_bridge.py na Pi',               'Terminal: boty kanalow loguja sie na Discord'],
            ['6', 'Wlacz krotkofalowke',                     'Kanal ustawiony zgodnie z konfiguracja'],
            ['7', 'Wlacz urzadzenie ESP32 (podlacz zasilanie)', 'Zielona LED swieci ciagle (Wi-Fi OK)'],
        ],
        col_widths=[1.0*cm, 7.5*cm, 8.0*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('8.2  Co powinny pokazywac diody LED na ESP32'))
    s.append(make_table(
        ['Stan LED', 'Co oznacza', 'Co robic'],
        [
            ['Zielona SWIECI ciagle',         'Wi-Fi polaczony, serwer odpowiada',    'Wszystko OK'],
            ['Zielona MIGA podczas bootowania','Laczenie z Wi-Fi',                     'Czekaj ok. 10s'],
            ['Czerwona MIGA 1 raz',           'Heartbeat fail (brak serwera)',        'Sprawdz czy serwer dziala'],
            ['Czerwona MIGA 3 razy',          'Clock In/Out nie powiodlo sie',        'Sprawdz User ID w dashboardzie'],
            ['Czerwona MIGA co 1 sekunde',    'Brak Wi-Fi',                           'Sprawdz SSID i haslo w firmware'],
            ['Zolta SWIECI ciagle',           'PTT aktywne - trwa nadawanie',         'Normalne podczas trzymania PTT'],
            ['Zolta MIGA N razy',             'Zmiana kanalu - N = numer kanalu+1',   'Normalne po wcisnieciu przycisku D8'],
        ],
        col_widths=[4*cm, 6*cm, 6.5*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('8.3  Test clock in / clock out'))
    s += bullet([
        'Upewnij sie ze Discord User ID jest przypisany do urzadzenia w dashboardzie',
        'Wcisniej przycisk <b>Clock In (D2 / GPIO 21)</b>',
        'Zielona LED powinna mignac 1 raz = sukces',
        'Na kanale Discord #apel powinien pojawic sie embed "Clock In - Urzadzenie"',
        'Wcisniej przycisk <b>Clock Out (D3 / GPIO 17)</b>',
        'Sprawdz #apel: embed "Clock Out" z naliczonymi punktami i czasem pracy',
        'Sprawdz Dashboard -> Uzytkownicy -> Twoj profil: sesja powinna byc widoczna w historii',
    ])
    s.append(sp(0.4))

    s.append(h2('8.4  Test PTT audio (WiFi -> Discord)'))
    s += bullet([
        'Upewnij sie ze pi_bridge.py dziala i boty kanalow sa online na Discordzie',
        'Wejdz na serwer Discord -> kanal glosowy powiazany z kanalem urzadzenia',
        'Przytrzymaj przycisk <b>PTT (D4 / GPIO 16)</b> - zolta LED swieci',
        'Mow do mikrofonu INMP441',
        'Drugi uzytkownik na Discord powinien slyszec Twoj glos przez bota kanalu',
        'Zwolnienie PTT -> zolta LED gasnie -> sygnal END wysylany do serwera',
    ])
    s.append(sp(0.4))

    s.append(h2('8.5  Test audio RF (radio -> Discord)'))
    s += bullet([
        'Upewnij sie ze pi_bridge.py jest uruchomiony na Pi i boty sa na kanalach',
        'Nadaj krotkofalowka na tej samej czestotliwosci co stacja bazowa',
        'pi_bridge wykryje sygnal (squelch RMS > prog) i zacznie streamowac do Discorda',
        'Wszystkie kanaly glosowe Discord powinny jednoczesnie odtworzyc audio z radia',
        'Jesli brak dzwieku: zmniejsz prog squelch (zmienna SQUELCH_RMS w .env pi_bridge)',
    ])
    s.append(PageBreak())

    # ===================================================================
    # 9. ROZWIAZYWANIE PROBLEMOW
    # ===================================================================
    s += h1('9. Rozwiazywanie problemow')

    s.append(h2('9.1  ESP32 nie laczy sie z Wi-Fi'))
    s.append(make_table(
        ['Objaw', 'Przyczyna', 'Rozwiazanie'],
        [
            ['Czerwona LED miga co 1s bez konca',
             'Bledne SSID lub haslo Wi-Fi',
             'Sprawdz WIFI_SSID i WIFI_PASSWORD w firmware. Unikaj znakow specjalnych.'],
            ['Zielona LED miga chwile i gasnie',
             'Router niedostepny lub za slaby zasieg',
             'Zbliz ESP32 do routera. Sprawdz czy router 4G ma zasieg.'],
            ['Monitor portu: "Could not connect"',
             'Siec 5GHz (ESP32 dziala TYLKO na 2.4GHz)',
             'Wlacz pasmo 2.4GHz na routerze. ESP32 nie obsluguje 5GHz.'],
            ['Poprawne SSID/haslo ale nadal fail',
             'Zbyt duzo urzadzen na routerze lub DHCP pelny',
             'Sprawdz tabele DHCP w ustawieniach routera. Zrestartuj router.'],
        ],
        col_widths=[4.2*cm, 5*cm, 7.3*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('9.2  Bot pokazuje Offline w dashboardzie'))
    s.append(make_table(
        ['Objaw', 'Przyczyna', 'Rozwiazanie'],
        [
            ['Bot pokazuje Offline po >60s',
             'Brak heartbeatu od ESP32',
             'Monitor portu: szukaj "[HB] ok". Sprawdz DEVICE_ID i API_SECRET w firmware.'],
            ['Bot nigdy nie byl online',
             'Bledny token bota lub bot nie zaproszony',
             'Wygeneruj nowy token w Discord Developer Portal -> Bot -> Reset Token.'],
            ['pi_bridge: "nieprawidlowy token"',
             'Token bota kanalu wygasl',
             'Nowy token w Discord Dev Portal, zaktualizuj w Dashboard -> Urzadzenia.'],
        ],
        col_widths=[4.2*cm, 5*cm, 7.3*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('9.3  Brak dzwieku przez radio RF'))
    s.append(make_table(
        ['Objaw', 'Przyczyna', 'Rozwiazanie'],
        [
            ['pi_bridge uruchomiony ale brak dzwieku z radia',
             'Bledny indeks urzadzenia audio',
             'Uruchom: python -c "import pyaudio; p=pyaudio.PyAudio(); '
             '[print(i,p.get_device_info_by_index(i)[chr(110)+chr(97)+chr(109)+chr(101)]) '
             'for i in range(p.get_device_count())]" '
             'i ustaw AUDIO_INPUT_IDX / OUTPUT_IDX na wlasciwy numer.'],
            ['Radio nadaje ale Discord nie slyszy',
             'Za niski poziom wejscia mikrofonu',
             'W terminalu: alsamixer -> F4 -> zwieksz "Mic Capture". '
             'Lub zmniejsz SQUELCH_RMS w .env (np. z 300 na 150).'],
            ['PTT sie aktywuje ale radio nie nadaje',
             'Tranzystor 2N2222 nie przewodzi',
             'Sprawdz: rezystor 1kOhm na bazie, emiter do GND. '
             'Sprawdz czy GPIO 17 daje 3.3V podczas PTT (multimetrem).'],
            ['Dzwiek z Discorda nie wychodzi przez radio',
             'Boty kanalow nie sa polaczone z voice',
             'Sprawdz logi pi_bridge: "polaczony z kanalem glosowym". '
             'Sprawdz discord_channel_id w ustawieniach kanalu w dashboardzie.'],
        ],
        col_widths=[4*cm, 4.5*cm, 8*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('9.4  Clock In / Out nie dziala'))
    s.append(make_table(
        ['Objaw', 'Przyczyna', 'Rozwiazanie'],
        [
            ['Czerwona LED miga 3 razy po wcisnieciu',
             'Brak Discord User ID w urzadzeniu',
             'Dashboard -> Urzadzenia -> Edytuj -> wpisz Discord User ID.'],
            ['LED miga ale brak embeda na Discordzie',
             'Brak kanalu zegara w konfiguracji',
             'Dashboard -> Konfiguracja -> ustaw "Kanal zegara" (clock_channel_id).'],
            ['"already clocked in" w logach',
             'Poprzednia sesja nie zostala zamknieta',
             'Komenda bota: .forceclockout @uzytkownik - lub reset przez dashboard.'],
        ],
        col_widths=[4.2*cm, 5*cm, 7.3*cm],
        first_col_code=False
    ))
    s.append(sp(0.4))

    s.append(h2('9.5  Sprawdzanie logow systemu'))
    s.append(code(
        '# Logi serwera Flask + bota Discord (Pi lub Replit Console)',
        'python main.py',
        '',
        '# Logi pi_bridge - tryb szczegolow (debug)',
        'LOG_LEVEL=DEBUG python pi_bridge.py',
        '',
        '# Logi ESP32 - Monitor Portu Szeregowego w Arduino IDE',
        '# Predkosc: 115200 baud',
        '# Prefiks logow:',
        '#   [WiFi]        - status Wi-Fi i polaczenia',
        '#   [HB]          - heartbeat do serwera',
        '#   [Clock/...]   - operacje clock in / clock out',
        '#   [BTN]         - wcisniecia przyciskow',
        '#   [PTT]         - start / stop nadawania PTT',
        '#   [CH]          - zmiana kanalu PTT',
        '#   [WS]          - WebSocket audio (polaczenie, bledy)',
        '#   [I2S]         - inicjalizacja mikrofonu i glosnika',
    ))
    s.append(sp(0.4))

    s.append(h2('9.6  Przydatne komendy bota Discord (prefix ".")'))
    s.append(make_table(
        ['Komenda', 'Kto moze', 'Opis'],
        [
            ['.clock',               'Uzytkownik', 'Sprawdz swoj status clock in/out i czas sesji'],
            ['.points',              'Uzytkownik', 'Sprawdz swoje punkty i pozycje na liscie'],
            ['.lb',                  'Uzytkownik', 'Tabela wynikow (leaderboard) serwera'],
            ['.profile',             'Uzytkownik', 'Pelny profil: punkty, rangi, frakcja, praca'],
            ['.help',                'Uzytkownik', 'Lista wszystkich dostepnych komend'],
            ['.forceclockout @ktos', 'Admin',      'Wymus zamkniecie sesji clock in uzytkownika'],
            ['.addpoints @ktos N',   'Admin',      'Dodaj N punktow uzytkownikowi'],
            ['.setpoints @ktos N',   'Admin',      'Ustaw dokladna liczbe punktow uzytkownika'],
            ['.userinfo @ktos',      'Admin',      'Szczegolowe informacje o uzytkowniku'],
            ['.config',              'Admin',      'Pokaz aktualna konfiguracje serwera'],
            ['.apel',                'Admin',      'Wysli panel Clock In/Out na kanal #apel'],
        ],
        col_widths=[4.5*cm, 2.5*cm, 9.5*cm],
        first_col_code=True
    ))

    s.append(sp(0.8))
    s.append(HRFlowable(width='100%', thickness=1, color=C_GREY_LINE))
    s.append(sp(0.3))
    s.append(Paragraph(
        'Instrukcja wygenerowana automatycznie z kodu zrodlowego projektu SerwerDiscordBazaMops.',
        sNote))
    s.append(Paragraph(
        f'Data generowania: {date.today().strftime("%d.%m.%Y")}   |   '
        'Pi Bridge v2 (multi-channel)   |   Firmware ESP32 v1.1',
        sNote))

    return s


# ─── Build PDF ────────────────────────────────────────────────────────────────

OUTPUT = 'instrukcja_systemu.pdf'

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    leftMargin=1.5*cm,
    rightMargin=1.5*cm,
    topMargin=1.9*cm,
    bottomMargin=1.4*cm,
    title='Instrukcja Systemu Lacznosci - Szalas',
    author='BazaMOPS',
    subject='System komunikacyjny ESP32 + Discord + RF Radio',
)

story = build_story()

doc.build(
    story,
    onFirstPage=_title_page,
    onLaterPages=_header_footer,
)

print(f'PDF wygenerowany: {OUTPUT}')
