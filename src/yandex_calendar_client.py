"""
Yandex Calendar Client — работа с Яндекс.Календарём через CalDAV.

Преимущества:
• Данные хранятся на серверах Яндекса (РФ) — соответствует 152-ФЗ
• Полноценный API: создание, чтение, удаление событий
• Проверка занятости через поиск событий
• Работает из любой точки мира (включая Render)

Настройка:
1. Получите пароль приложения для CalDAV:
   - https://id.yandex.ru/security/app-passwords
   - Выберите "Календарь" → "Создать пароль"
   - Сохраните 16-значный пароль

2. Узнайте URL календаря:
   - Откройте https://calendar.yandex.ru
   - Настройки (шестерёнка) → нужный календарь → вкладка "Экспорт"
   - Скопируйте адрес CalDAV (вида https://caldav.yandex.ru/calendars/ваш_логин/events-default/)

3. Добавьте в .env:
   YANDEX_CALDAV_URL=https://caldav.yandex.ru/calendars/ваш_логин/events-default/
   YANDEX_CALDAV_USERNAME=ваш_логин@yandex.ru
   YANDEX_CALDAV_PASSWORD=пароль_приложения
"""

from __future__ import annotations

import logging
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional

import requests
import urllib3
urllib3.disable_warnings()
from requests.auth import HTTPBasicAuth

logger = logging.getLogger("aaron-salon-bot")


@dataclass(frozen=True)
class Booking:
    service_name: str
    client_name: str
    phone: str
    start: datetime
    duration_minutes: int
    timezone: str
    salon_name: str

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)


class YandexCalendarClient:
    """
    Клиент для Яндекс.Календаря через CalDAV.
    """

    CALDAV_BASE = "https://caldav.yandex.ru"

    def __init__(
        self,
        calendar_url: str,
        username: str,
        password: str,
    ) -> None:
        self._calendar_url = calendar_url.rstrip("/")
        self._username = username
        self._password = password
        self._auth = HTTPBasicAuth(username, password)

        logger.info("YandexCalendarClient initialized for %s", username)

    def _request(self, method: str, url: str, data: str = "", headers: dict | None = None) -> requests.Response:
        """HTTP-запрос с Basic Auth."""
        default_headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if headers:
            default_headers.update(headers)

        resp = requests.request(
            method, url,
            auth=self._auth,
            headers=default_headers,
            data=data.encode("utf-8"),
            timeout=30,
            verify=False,  # Яндекс использует самоподписанные сертификаты
        )
        return resp

    @staticmethod
    def _fold_ics_line(line: str, max_bytes: int = 75) -> str:
        raw = line.encode("utf-8")
        if len(raw) <= max_bytes:
            return line
        # folding на границе слов
        parts = []
        while line:
            tail = line[:max_bytes]
            # откатываемся до пробела, не превышая max_bytes
            while len(tail.encode("utf-8")) > max_bytes or (len(line) > len(tail) and tail[-1] != ' '):
                tail = tail[:-1]
            parts.append(tail.rstrip(" "))
            line = line[len(tail):]
        result = "\r\n ".join(parts)
        return result

    def _generate_ics(self, booking: Booking, uid: str) -> str:
        """Генерирует iCalendar формат для события."""
        dt_format = "%Y%m%dT%H%M%SZ"
        start_utc = booking.start.astimezone(timezone.utc)
        end_utc = booking.end.astimezone(timezone.utc)

        start_str = start_utc.strftime(dt_format)
        end_str = end_utc.strftime(dt_format)
        now_str = datetime.utcnow().strftime(dt_format)

        summary = f"Запись: {booking.service_name}"

        desc_parts = [
            f"👤 Клиент: {booking.client_name}",
            f"📞 Телефон: {booking.phone}",
            f"✂️ Услуга: {booking.service_name}",
            f"🏠 Салон: {booking.salon_name}",
        ]
        description_raw = "\\n".join(desc_parts)
        description = self._fold_ics_line(description_raw)

        ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//{booking.salon_name}//RU
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
UID:{uid}
DTSTAMP:{now_str}
DTSTART:{start_str}
DTEND:{end_str}
SUMMARY:{summary}
DESCRIPTION:{description}
LOCATION:{booking.salon_name}
END:VEVENT
END:VCALENDAR"""
        return ics

    def is_time_available(self, start: datetime, end: datetime) -> bool:
        """Проверяет, свободно ли время (нет ли событий в этом интервале)."""
        try:
            events = self._get_events_in_range(start, end)
            return len(events) == 0
        except Exception as e:
            logger.error("Error checking availability: %s", e)
            # Если не удалось проверить — считаем занято (безопаснее)
            return False

    def _get_events_in_range(self, start: datetime, end: datetime) -> list[dict]:
        """Получает события в диапазоне через CalDAV REPORT."""
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        start_str = start_utc.strftime("%Y%m%dT%H%M%SZ")
        end_str = end_utc.strftime("%Y%m%dT%H%M%SZ")

        body = f"""<?xml version="1.0" encoding="utf-8"?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop>
    <C:calendar-data/>
  </D:prop>
  <C:filter>
    <C:comp-filter name="VCALENDAR">
      <C:comp-filter name="VEVENT">
        <C:time-range start="{start_str}" end="{end_str}"/>
      </C:comp-filter>
    </C:comp-filter>
  </C:filter>
</C:calendar-query>"""

        resp = self._request(
            "REPORT",
            self._calendar_url + "/",
            data=body,
            headers={"Content-Type": "text/xml; charset=utf-8", "Depth": "1"}
        )

        if resp.status_code not in (200, 207):
            logger.error("CalDAV REPORT failed: %s %s", resp.status_code, resp.text[:200])
            return []

        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError as e:
            logger.error("Failed to parse CalDAV XML response: %s", e)
            return []

        CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
        events = []

        for cd in root.iter(f"{{{CALDAV_NS}}}calendar-data"):
            ics = cd.text or ""
            m = re.search(r"^UID:(.+)$", ics, re.MULTILINE)
            uid = m.group(1).strip() if m else "unknown"
            events.append({"uid": uid, "found": True})

        logger.info("Found %d events in range %s – %s", len(events), start_str, end_str)
        return events

    def create_booking_event(self, booking: Booking) -> str:
        """Создаёт событие в Яндекс.Календаре."""
        uid = str(uuid.uuid4())
        event_url = f"{self._calendar_url}/{uid}.ics"

        ics_data = self._generate_ics(booking, uid)

        resp = self._request("PUT", event_url, data=ics_data)

        if resp.status_code in (200, 201, 204):
            logger.info("Created Yandex Calendar event: %s", uid)
            return f"https://calendar.yandex.ru/event?event_id={uid}"
        else:
            logger.error("Failed to create event: %s %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"CalDAV PUT failed: {resp.status_code}")

    def delete_event(self, uid: str) -> None:
        """Удаляет событие по UID."""
        event_url = f"{self._calendar_url}/{uid}.ics"
        resp = self._request("DELETE", event_url)

        if resp.status_code in (200, 204):
            logger.info("Deleted Yandex Calendar event: %s", uid)
        else:
            logger.error("Failed to delete event: %s", resp.status_code)

    def generate_ics(self, booking: Booking) -> str:
        """Генерирует .ics файл для отправки клиенту."""
        uid = str(uuid.uuid4())
        return self._generate_ics(booking, uid)