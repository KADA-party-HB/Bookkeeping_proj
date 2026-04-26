from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from email.message import EmailMessage
from email.utils import formataddr
import smtplib
import ssl

from flask import current_app, render_template, url_for


_BOOKING_NOTIFICATION_COPY = {
    "created": {
        "subject": "Din bokning #{booking_id} har tagits emot",
        "headline": "Vi har tagit emot din bokning",
        "intro": (
            "Din bokning är nu registrerad som väntande medan vi går igenom den."
        ),
        "status_label": "Väntande",
    },
    "confirmed": {
        "subject": "Din bokning #{booking_id} är bekräftad",
        "headline": "Din bokning är bekräftad",
        "intro": "Bokningen är nu bekräftad och planeras för de valda datumen.",
        "status_label": "Bekräftad",
    },
    "cancelled": {
        "subject": "Din bokning #{booking_id} har avbokats",
        "headline": "Din bokning har avbokats",
        "intro": "Bokningen är nu avbokad i vårt system.",
        "status_label": "Avbokad",
    },
}


def _format_money(value) -> str:
    try:
        decimal_value = Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        decimal_value = Decimal("0")
    decimal_value = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{decimal_value} kr"


def _format_date(value) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def _normalized_email(value) -> str:
    return (value or "").strip().lower()


def send_booking_event_email(
    *,
    notification_type: str,
    booking,
    total,
    item_summary,
    pending_hold_label: str | None = None,
) -> bool:
    if not current_app.config.get("MAIL_ENABLED"):
        return False

    copy = _BOOKING_NOTIFICATION_COPY.get(notification_type)
    if not copy:
        raise ValueError(f"Unsupported booking notification type: {notification_type}")

    recipient = (booking.get("email") or "").strip()
    if not recipient:
        current_app.logger.info(
            "booking_email_skipped booking_id=%s reason=no-recipient",
            booking.get("id"),
        )
        return False

    context = {
        "site_name": current_app.config.get("BOOKING_EMAIL_SITE_NAME", "KADA PartyTillbehör"),
        "headline": copy["headline"],
        "intro": copy["intro"],
        "notification_type": notification_type,
        "booking_id": booking.get("id"),
        "customer_name": booking.get("full_name") or "kund",
        "status_label": copy["status_label"],
        "start_date": _format_date(booking.get("start_date")),
        "end_date": _format_date(booking.get("end_date")),
        "include_delivery": bool(booking.get("include_delivery")),
        "include_setup_service": bool(booking.get("include_setup_service")),
        "delivery_address": booking.get("delivery_address") or "",
        "booking_note": booking.get("booking_note") or "",
        "pending_hold_label": pending_hold_label or "",
        "rental_cost_text": _format_money((total or {}).get("rental_cost")),
        "setup_cost_text": _format_money((total or {}).get("setup_cost")),
        "delivery_cost_text": _format_money((total or {}).get("delivery_cost")),
        "total_cost_text": _format_money((total or {}).get("total_cost")),
        "items": [
            {
                "display_name": row.get("display_name") or "Artikel",
                "quantity": row.get("quantity") or 0,
                "line_total_text": _format_money(row.get("group_total")),
            }
            for row in (item_summary or [])
        ],
        "booking_url": url_for("routes.booking_detail", booking_id=booking.get("id"), _external=True),
        "login_url": url_for("auth.login_form", _external=True),
        "contact_email": (
            current_app.config.get("BOOKING_EMAIL_REPLY_TO")
            or current_app.config.get("SMTP_FROM_EMAIL")
        ),
    }

    message = EmailMessage()
    subject = copy["subject"].format(booking_id=booking.get("id"))
    message["Subject"] = subject
    message["From"] = formataddr(
        (
            current_app.config.get("SMTP_FROM_NAME") or "",
            current_app.config.get("SMTP_FROM_EMAIL") or "",
        )
    )
    message["To"] = recipient

    archive_recipient = (current_app.config.get("SMTP_FROM_EMAIL") or "").strip()
    archive_copy_enabled = False
    if (
        notification_type == "created"
        and archive_recipient
        and _normalized_email(archive_recipient) != _normalized_email(recipient)
    ):
        message["Bcc"] = archive_recipient
        archive_copy_enabled = True

    reply_to = current_app.config.get("BOOKING_EMAIL_REPLY_TO")
    if reply_to:
        message["Reply-To"] = reply_to

    message.set_content(render_template("emails/booking_notification.txt", **context))
    message.add_alternative(
        render_template("emails/booking_notification.html", **context),
        subtype="html",
    )

    smtp_host = current_app.config["SMTP_HOST"]
    smtp_port = current_app.config["SMTP_PORT"]
    smtp_timeout = current_app.config["SMTP_TIMEOUT_SECONDS"]
    smtp_username = current_app.config.get("SMTP_USERNAME") or ""
    smtp_password = current_app.config.get("SMTP_PASSWORD") or ""
    smtp_use_ssl = bool(current_app.config.get("SMTP_USE_SSL"))
    smtp_use_starttls = bool(current_app.config.get("SMTP_USE_STARTTLS"))

    smtp_class = smtplib.SMTP_SSL if smtp_use_ssl else smtplib.SMTP
    ssl_context = ssl.create_default_context()

    with smtp_class(smtp_host, smtp_port, timeout=smtp_timeout) as smtp:
        if not smtp_use_ssl:
            smtp.ehlo()
        if smtp_use_starttls:
            smtp.starttls(context=ssl_context)
            smtp.ehlo()
        if smtp_username:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)

    current_app.logger.info(
        "booking_email_sent booking_id=%s type=%s to=%s archive_copy=%s archive_recipient=%s subject=%s",
        booking.get("id"),
        notification_type,
        recipient,
        archive_copy_enabled,
        archive_recipient if archive_copy_enabled else "",
        subject,
    )
    return True
