from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

CONTRACT_PDF_FILENAMES = (
    "Allmänna hyresvillkor – tältuthyrning.pdf",
    "Allmänna-hyresvillkor-tältuthyrning.pdf",
    "Allmänna-hyresvillkor-tältuthyrning-old.pdf",
)
LOGO_FILENAME = "Kada_logo_horizontel.png"
ORDER_ACCEPT_TERMS_VERSION = "2026-02-22"


def _as_decimal(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _format_money(value) -> str:
    amount = _as_decimal(value).quantize(Decimal("1.00"))
    if amount == amount.to_integral():
        return f"{int(amount)} kr"
    return f"{amount.normalize()} kr"


def _format_date(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _format_bool(value, *, true_label: str = "Ja", false_label: str = "Nej") -> str:
    return true_label if value else false_label


def _text(value) -> str:
    if value is None or value == "":
        return "-"
    return escape(str(value))


def _booking_location(booking) -> str:
    if booking.get("delivery_address"):
        return booking["delivery_address"]

    parts = [booking.get("address"), booking.get("postal_city")]
    text = ", ".join(part for part in parts if part)
    return text or "-"


def _type_label(row) -> str:
    if row.get("is_tent") or row.get("type_label") == "Tent":
        return "Tält"
    if row.get("is_furnishing"):
        return row.get("furnishing_kind") or "Tillbehör"
    if row.get("type_label") == "Furnishing":
        return "Tillbehör"
    return str(row.get("type_label") or "Artikel")


def _append_contract_pages(order_pdf_bytes: bytes, *, static_root: Path) -> bytes:
    writer = PdfWriter()

    order_reader = PdfReader(BytesIO(order_pdf_bytes))
    for page in order_reader.pages:
        writer.add_page(page)

    for filename in CONTRACT_PDF_FILENAMES:
        contract_path = static_root / "pdf" / filename
        if not contract_path.exists():
            continue

        contract_reader = PdfReader(str(contract_path))
        for page in contract_reader.pages:
            writer.add_page(page)
        break

    merged = BytesIO()
    writer.write(merged)
    return merged.getvalue()


def _append_section(story, flowables, *, keep_together: bool):
    if keep_together:
        story.append(KeepTogether(flowables))
        return
    story.extend(flowables)


def build_booking_order_pdf(
    *,
    booking,
    item_summary,
    total,
    cost_breakdown,
    static_root: Path,
) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "OrderTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )
    intro_style = ParagraphStyle(
        "OrderIntro",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "OrderSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )
    label_style = ParagraphStyle(
        "OrderLabel",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )
    body_style = ParagraphStyle(
        "OrderBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    note_style = ParagraphStyle(
        "OrderNote",
        parent=styles["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )
    numeric_style = ParagraphStyle(
        "OrderNumeric",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    def field_paragraph(label: str, value: str) -> Paragraph:
        return Paragraph(f"<b>{label}</b> {_text(value)}", body_style)

    delivery_distance_suffix = ""
    if booking.get("delivery_distance_km") is not None:
        delivery_distance_suffix = f" ({booking.get('delivery_distance_km')} km)"

    delivery_cost_text = _format_money(cost_breakdown.get("delivery_cost") if cost_breakdown else 0)
    if booking.get("include_delivery"):
        delivery_cost_text = f"{delivery_cost_text}{delivery_distance_suffix}"

    story = []
    logo_path = static_root / "img" / LOGO_FILENAME
    if logo_path.exists():
        story.append(Image(str(logo_path), width=58 * mm, height=13 * mm))
        story.append(Spacer(1, 6))

    story.append(Paragraph("Beställning / Orderbekräftelse", title_style))
    story.append(
        Paragraph(
            (
                "Detta dokument sammanfattar bokningen och hänvisar till de bifogade "
                "allmänna hyresvillkoren för tältuthyrning."
            ),
            intro_style,
        )
    )

    party_section = [Paragraph("1. Parter", section_style)]
    party_table = Table(
        [
            [
                Paragraph(
                    (
                        "<b>Uthyrare</b><br/>"
                        "KADA PartyTillbehör-Handelsbolag<br/>"
                        "Org.nr 969803-3504<br/>"
                        "Östersjövägen 45<br/>"
                        "374 31 Karlshamn<br/>"
                        "073-0813710<br/>"
                        "kadaparty@kadaparty.se"
                    ),
                    body_style,
                ),
                Paragraph(
                    (
                        "<b>Kund</b><br/>"
                        f"{_text(booking.get('full_name'))}<br/>"
                        f"{_text(booking.get('email'))}<br/>"
                        f"{_text(booking.get('phone'))}<br/>"
                        f"{_text(_booking_location(booking))}"
                    ),
                    body_style,
                ),
            ]
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    party_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    party_section.append(party_table)
    _append_section(story, party_section, keep_together=True)

    booking_section = [Paragraph("2. Leverans- och bokningsuppgifter", section_style)]
    booking_info = Table(
        [
            [
                field_paragraph("Hyresperiod:", f"{_format_date(booking.get('start_date'))} till {_format_date(booking.get('end_date'))}"),
                "",
            ],
            [
                field_paragraph("Bokningsnummer:", str(booking.get("id") or "-")),
                field_paragraph("Skapad:", _format_date(booking.get("created_at"))),
            ],
            [
                field_paragraph("Leverans:", _format_bool(booking.get("include_delivery"), true_label="Ingår", false_label="Ingår inte")),
                field_paragraph("Montering:", _format_bool(booking.get("include_setup_service"), true_label="Ingår", false_label="Ingår inte")),
            ],
            [
                field_paragraph("Plats/adress:", _booking_location(booking)),
                field_paragraph("Leveranskostnad:", delivery_cost_text),
            ],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    booking_info.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("SPAN", (0, 0), (1, 0)),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    booking_section.append(booking_info)

    if booking.get("booking_note"):
        booking_section.append(Spacer(1, 4))
        booking_section.append(
            Paragraph(
                f"<b>Bokningsanteckning:</b> {_text(booking['booking_note'])}",
                body_style,
            )
        )
    _append_section(story, booking_section, keep_together=True)

    story.append(Paragraph("3. Beställd utrustning", section_style))
    ordered_rows = [
        [
            Paragraph("<b>Artikel</b>", label_style),
            Paragraph("<b>Typ</b>", label_style),
            Paragraph("<b>Hyresperiod</b>", label_style),
            Paragraph("<b>Antal</b>", numeric_style),
            Paragraph("<b>Pris/st</b>", numeric_style),
            Paragraph("<b>Radtotal</b>", numeric_style),
        ]
    ]

    if item_summary:
        for row in item_summary:
            ordered_rows.append(
                [
                    Paragraph(_text(row.get("display_name")), body_style),
                    Paragraph(_text(_type_label(row)), body_style),
                    Paragraph(_text(row.get("quoted_period_label")), body_style),
                    Paragraph(_text(row.get("quantity") or 0), numeric_style),
                    Paragraph(_format_money(row.get("effective_line_total") or 0), numeric_style),
                    Paragraph(_format_money(row.get("group_total") or 0), numeric_style),
                ]
            )
    else:
        ordered_rows.append(
            [
                Paragraph("Inga artiklar kopplade till bokningen.", body_style),
                "",
                "",
                "",
                "",
                "",
            ]
        )

    ordered_table = Table(
        ordered_rows,
        colWidths=[52 * mm, 25 * mm, 34 * mm, 14 * mm, 25 * mm, 28 * mm],
        repeatRows=1,
    )
    ordered_table_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#93c5fd")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbeafe")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if not item_summary:
        ordered_table_commands.append(("SPAN", (0, 1), (-1, 1)))
    ordered_table.setStyle(TableStyle(ordered_table_commands))
    story.append(ordered_table)

    summary_section = [Paragraph("4. Summering", section_style)]
    total_rows = [
        [
            Paragraph("Artiklar", body_style),
            Paragraph(f"{int(cost_breakdown.get('item_count') or 0)} valda", numeric_style),
        ],
        [
            Paragraph("Hyra", body_style),
            Paragraph(_format_money(cost_breakdown.get("rental_without_surcharge") if cost_breakdown else 0), numeric_style),
        ],
        [
            Paragraph("Montering", body_style),
            Paragraph(
                _format_money(cost_breakdown.get("setup_cost") if cost_breakdown else 0)
                if booking.get("include_setup_service")
                else "Inte tillvalt",
                numeric_style,
            ),
        ],
        [
            Paragraph("Leverans", body_style),
            Paragraph(
                delivery_cost_text
                if booking.get("include_delivery")
                else "Inte tillvalt",
                numeric_style,
            ),
        ],
    ]
    if cost_breakdown and cost_breakdown.get("show_furnishing_surcharge"):
        total_rows.append(
            [
                Paragraph("Inredning utan tält (+25%)", body_style),
                Paragraph(_format_money(cost_breakdown.get("furnishing_surcharge") or 0), numeric_style),
            ]
        )
    if cost_breakdown and cost_breakdown.get("show_vat_breakdown"):
        total_rows.append(
            [
                Paragraph("Moms (25%)", body_style),
                Paragraph(_format_money(cost_breakdown.get("vat_amount") or 0), numeric_style),
            ]
        )
    if total and total.get("has_booking_override"):
        total_rows.append(
            [
                Paragraph("Bokningsoverride", body_style),
                Paragraph(_format_money(cost_breakdown.get("booking_custom_total_price") or 0), numeric_style),
            ]
        )
    if cost_breakdown and cost_breakdown.get("show_vat_breakdown"):
        total_rows.append(
            [
                Paragraph("Pris exkl. moms", body_style),
                Paragraph(_format_money(cost_breakdown.get("subtotal_ex_vat") or 0), numeric_style),
            ]
        )
    total_rows.append(
        [
            Paragraph(
                "<b>Totalt inkl. moms</b>" if cost_breakdown and cost_breakdown.get("show_vat_breakdown")
                else "<b>Totalt att betala</b>",
                label_style,
            ),
            Paragraph(f"<b>{_format_money(cost_breakdown.get('total_cost') if cost_breakdown else 0)}</b>", numeric_style),
        ]
    )
    total_table = Table(total_rows, colWidths=[138 * mm, 40 * mm])
    total_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, 0), (-1, -2), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#ecfccb")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    summary_section.append(total_table)

    if total and total.get("booking_custom_price_note"):
        summary_section.append(Spacer(1, 4))
        summary_section.append(
            Paragraph(
                f"<b>Kommentar till totalsumma:</b> {_text(total['booking_custom_price_note'])}",
                body_style,
            )
        )

    _append_section(story, summary_section, keep_together=True)

    accept_section = [Spacer(1, 8), Paragraph("5. Accept och underskrift", section_style)]
    accept_section.append(
        Paragraph(
            (
                "Kunden bekräftar genom underskrift att Kunden tagit del av och accepterar "
                f"Allmänna hyresvillkor – tältuthyrning (version {ORDER_ACCEPT_TERMS_VERSION})."
            ),
            body_style,
        )
    )
    accept_section.append(Spacer(1, 6))

    signature_table = Table(
        [
            [Paragraph("Ort och datum: _______________________________", body_style), ""],
            [Paragraph("Uthyrare: _______________________________", body_style), Paragraph("Kund: _______________________________", body_style)],
            [Paragraph("Namnförtydligande: __________________________", body_style), Paragraph("Namnförtydligande: __________________________", body_style)],
        ],
        colWidths=[89 * mm, 89 * mm],
    )
    signature_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("SPAN", (0, 0), (1, 0)),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    accept_section.append(signature_table)
    accept_section.append(
        Paragraph(
            "Kunden ansvarar för att spara en kopia av Beställningen och Villkoren.",
            body_style,
        )
    )
    accept_section.append(Spacer(1, 8))
    accept_section.append(
        Paragraph(
            (
                "De bifogade allmänna hyresvillkoren utgör en del av avtalet. "
                "Vid motstridighet gäller uppgifterna i denna beställning före villkoren."
            ),
            note_style,
        )
    )
    _append_section(story, accept_section, keep_together=True)

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Booking {booking.get('id')} order",
    )
    doc.build(story)

    return _append_contract_pages(pdf_buffer.getvalue(), static_root=static_root)


def build_booking_receipt_pdf(
    *,
    booking,
    item_summary,
    total,
    cost_breakdown,
    static_root: Path,
) -> bytes:
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReceiptTitle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=8,
    )
    intro_style = ParagraphStyle(
        "ReceiptIntro",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#475569"),
        spaceAfter=8,
    )
    section_style = ParagraphStyle(
        "ReceiptSection",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True,
    )
    label_style = ParagraphStyle(
        "ReceiptLabel",
        parent=styles["BodyText"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0f172a"),
    )
    body_style = ParagraphStyle(
        "ReceiptBody",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#334155"),
    )
    note_style = ParagraphStyle(
        "ReceiptNote",
        parent=styles["BodyText"],
        fontName="Helvetica-Oblique",
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#64748b"),
    )
    numeric_style = ParagraphStyle(
        "ReceiptNumeric",
        parent=body_style,
        alignment=TA_RIGHT,
    )

    def field_paragraph(label: str, value: str) -> Paragraph:
        return Paragraph(f"<b>{label}</b> {_text(value)}", body_style)

    delivery_distance_suffix = ""
    if booking.get("delivery_distance_km") is not None:
        delivery_distance_suffix = f" ({booking.get('delivery_distance_km')} km)"

    delivery_cost_text = _format_money(cost_breakdown.get("delivery_cost") if cost_breakdown else 0)
    if booking.get("include_delivery"):
        delivery_cost_text = f"{delivery_cost_text}{delivery_distance_suffix}"

    story = []
    logo_path = static_root / "img" / LOGO_FILENAME
    if logo_path.exists():
        story.append(Image(str(logo_path), width=58 * mm, height=13 * mm))
        story.append(Spacer(1, 6))

    story.append(Paragraph("Kvitto / Receipt", title_style))
    story.append(
        Paragraph(
            (
                "Detta dokument sammanfattar vad den mottagna betalningen avser for bokning "
                f"#{_text(booking.get('id'))}. Extern betalningsreferens, som Swish-nummer, "
                "hanteras utanför systemet."
            ),
            intro_style,
        )
    )

    parties_section = [Paragraph("1. Parter", section_style)]
    parties_table = Table(
        [
            [
                Paragraph(
                    (
                        "<b>Uthyrare</b><br/>"
                        "KADA PartyTillbehor-Handelsbolag<br/>"
                        "Org.nr 969803-3504<br/>"
                        "Ostersjovagen 45<br/>"
                        "374 31 Karlshamn<br/>"
                        "073-0813710<br/>"
                        "kadaparty@kadaparty.se"
                    ),
                    body_style,
                ),
                Paragraph(
                    (
                        "<b>Kund</b><br/>"
                        f"{_text(booking.get('full_name'))}<br/>"
                        f"{_text(booking.get('email'))}<br/>"
                        f"{_text(booking.get('phone'))}<br/>"
                        f"{_text(_booking_location(booking))}"
                    ),
                    body_style,
                ),
            ]
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    parties_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    parties_section.append(parties_table)
    _append_section(story, parties_section, keep_together=True)

    receipt_section = [Paragraph("2. Betalningen avser", section_style)]
    receipt_info = Table(
        [
            [
                field_paragraph("Bokningsnummer:", str(booking.get("id") or "-")),
                field_paragraph("Bokning skapad:", _format_date(booking.get("created_at"))),
            ],
            [
                field_paragraph("Hyresperiod:", f"{_format_date(booking.get('start_date'))} till {_format_date(booking.get('end_date'))}"),
                field_paragraph("Plats/adress:", _booking_location(booking)),
            ],
            [
                field_paragraph("Status:", booking.get("status") or "-"),
                field_paragraph("Montering:", _format_bool(booking.get("include_setup_service"), true_label="Ingår", false_label="Ingår inte")),
            ],
            [
                field_paragraph("Leverans:", _format_bool(booking.get("include_delivery"), true_label="Ingår", false_label="Ingår inte")),
                field_paragraph("Leveranskostnad:", delivery_cost_text),
            ],
        ],
        colWidths=[85 * mm, 85 * mm],
    )
    receipt_info.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    receipt_section.append(receipt_info)

    if booking.get("booking_note"):
        receipt_section.append(Spacer(1, 4))
        receipt_section.append(
            Paragraph(
                f"<b>Bokningsanteckning:</b> {_text(booking['booking_note'])}",
                body_style,
            )
        )

    _append_section(story, receipt_section, keep_together=True)

    story.append(Paragraph("3. Artiklar", section_style))
    ordered_rows = [
        [
            Paragraph("<b>Artikel</b>", label_style),
            Paragraph("<b>Typ</b>", label_style),
            Paragraph("<b>Hyresperiod</b>", label_style),
            Paragraph("<b>Antal</b>", numeric_style),
            Paragraph("<b>Pris/st</b>", numeric_style),
            Paragraph("<b>Radtotal</b>", numeric_style),
        ]
    ]

    if item_summary:
        for row in item_summary:
            ordered_rows.append(
                [
                    Paragraph(_text(row.get("display_name")), body_style),
                    Paragraph(_text(_type_label(row)), body_style),
                    Paragraph(_text(row.get("quoted_period_label")), body_style),
                    Paragraph(_text(row.get("quantity") or 0), numeric_style),
                    Paragraph(_format_money(row.get("effective_line_total") or 0), numeric_style),
                    Paragraph(_format_money(row.get("group_total") or 0), numeric_style),
                ]
            )
    else:
        ordered_rows.append(
            [
                Paragraph("Inga artiklar kopplade till bokningen.", body_style),
                "",
                "",
                "",
                "",
                "",
            ]
        )

    ordered_table = Table(
        ordered_rows,
        colWidths=[52 * mm, 25 * mm, 34 * mm, 14 * mm, 25 * mm, 28 * mm],
        repeatRows=1,
    )
    ordered_table_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#93c5fd")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dbeafe")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if not item_summary:
        ordered_table_commands.append(("SPAN", (0, 1), (-1, 1)))
    ordered_table.setStyle(TableStyle(ordered_table_commands))
    story.append(ordered_table)

    summary_section = [Paragraph("4. Summering", section_style)]
    total_rows = [
        [
            Paragraph("Artiklar", body_style),
            Paragraph(f"{int(cost_breakdown.get('item_count') or 0)} valda", numeric_style),
        ],
        [
            Paragraph("Hyra", body_style),
            Paragraph(_format_money(cost_breakdown.get("rental_without_surcharge") if cost_breakdown else 0), numeric_style),
        ],
        [
            Paragraph("Montering", body_style),
            Paragraph(
                _format_money(cost_breakdown.get("setup_cost") if cost_breakdown else 0)
                if booking.get("include_setup_service")
                else "Inte tillvalt",
                numeric_style,
            ),
        ],
        [
            Paragraph("Leverans", body_style),
            Paragraph(
                delivery_cost_text
                if booking.get("include_delivery")
                else "Inte tillvalt",
                numeric_style,
            ),
        ],
    ]
    if cost_breakdown and cost_breakdown.get("show_furnishing_surcharge"):
        total_rows.append(
            [
                Paragraph("Inredning utan talt (+25%)", body_style),
                Paragraph(_format_money(cost_breakdown.get("furnishing_surcharge") or 0), numeric_style),
            ]
        )
    if cost_breakdown and cost_breakdown.get("show_vat_breakdown"):
        total_rows.append(
            [
                Paragraph("Moms (25%)", body_style),
                Paragraph(_format_money(cost_breakdown.get("vat_amount") or 0), numeric_style),
            ]
        )
    if total and total.get("has_booking_override"):
        total_rows.append(
            [
                Paragraph("Bokningsoverride", body_style),
                Paragraph(_format_money(cost_breakdown.get("booking_custom_total_price") or 0), numeric_style),
            ]
        )
    if cost_breakdown and cost_breakdown.get("show_vat_breakdown"):
        total_rows.append(
            [
                Paragraph("Pris exkl. moms", body_style),
                Paragraph(_format_money(cost_breakdown.get("subtotal_ex_vat") or 0), numeric_style),
            ]
        )
    total_rows.append(
        [
            Paragraph(
                "<b>Totalt inkl. moms</b>" if cost_breakdown and cost_breakdown.get("show_vat_breakdown")
                else "<b>Totalt</b>",
                label_style,
            ),
            Paragraph(f"<b>{_format_money(cost_breakdown.get('total_cost') if cost_breakdown else 0)}</b>", numeric_style),
        ]
    )
    total_table = Table(total_rows, colWidths=[138 * mm, 40 * mm])
    total_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                ("BACKGROUND", (0, 0), (-1, -2), colors.white),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dcfce7")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    summary_section.append(total_table)

    if total and total.get("booking_custom_price_note"):
        summary_section.append(Spacer(1, 4))
        summary_section.append(
            Paragraph(
                f"<b>Kommentar till totalsumma:</b> {_text(total['booking_custom_price_note'])}",
                body_style,
            )
        )

    _append_section(story, summary_section, keep_together=True)

    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            (
                "Detta kvitto ar ett internt betalningsunderlag for att koppla en mottagen "
                "betalning till bokningens innehall och totalbelopp."
            ),
            note_style,
        )
    )

    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Booking {booking.get('id')} receipt",
    )
    doc.build(story)
    return pdf_buffer.getvalue()
