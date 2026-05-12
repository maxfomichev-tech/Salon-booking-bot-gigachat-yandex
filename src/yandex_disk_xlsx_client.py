"""
Yandex Disk XLSX Client — хранение клиентов в Excel-файле на Яндекс.Диске.

Преимущества перед CSV:
• Настоящая таблица с форматированием
• Открывается онлайн на Яндекс.Диске (как Google Sheets)
• Распознаёт числа, даты
• Красивые заголовки, ширина колонок

Настройка .env:
    YANDEX_DISK_TOKEN=your_oauth_token
    YANDEX_DISK_FILE_PATH=/salon-bot/clients.xlsx
"""

from __future__ import annotations

import io
import logging
import os
from datetime import datetime
from typing import Optional

import requests
import urllib3
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

urllib3.disable_warnings()

logger = logging.getLogger("aaron-salon-bot")


class YandexDiskXlsxClient:
    """
    Хранит клиентов в XLSX-файле на Яндекс.Диске.
    Файл открывается онлайн как настоящая таблица.
    """

    API_BASE = "https://cloud-api.yandex.net/v1/disk"

    # Стили для красивого оформления
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=12)
    HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center")
    BORDER = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    def __init__(
        self,
        oauth_token: str,
        file_path: str = "/salon-bot/clients.xlsx",
    ) -> None:
        self._token = oauth_token
        self._file_path = file_path
        self._headers = {"Authorization": f"OAuth {oauth_token}"}

        logger.info("YandexDiskXlsxClient initialized, file: %s", file_path)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """HTTP-запрос с retry."""
        for attempt in range(3):
            try:
                resp = requests.request(
                    method, url,
                    headers=self._headers,
                    timeout=30,
                    verify=False,
                    **kwargs
                )
                return resp
            except requests.exceptions.ConnectionError:
                if attempt < 2:
                    import time
                    time.sleep(1)
                else:
                    raise

    def _create_folder_if_needed(self) -> None:
        """Создаёт папку на Яндекс.Диске если её нет."""
        folder = os.path.dirname(self._file_path)
        if not folder or folder == "/":
            return

        url = f"{self.API_BASE}/resources"
        params = {"path": folder}
        resp = self._request("PUT", url, params=params)

        if resp.status_code == 201:
            logger.info("Created folder: %s", folder)
        elif resp.status_code == 409:
            logger.debug("Folder already exists: %s", folder)
        else:
            logger.warning("Folder creation status %s: %s", resp.status_code, resp.text[:100])

    def _download_file(self) -> bytes:
        """Скачивает XLSX с Диска как bytes."""
        # Получаем ссылку на скачивание
        url = f"{self.API_BASE}/resources/download"
        params = {"path": self._file_path}
        resp = self._request("GET", url, params=params)
        resp.raise_for_status()
        download_url = resp.json()["href"]

        # Скачиваем файл
        resp = self._request("GET", download_url)
        resp.raise_for_status()
        return resp.content

    def _upload_file(self, content: bytes) -> None:
        """Загружает XLSX на Диск."""
        # Сначала убедимся что папка существует
        self._create_folder_if_needed()

        # Получаем ссылку для загрузки
        url = f"{self.API_BASE}/resources/upload"
        params = {"path": self._file_path, "overwrite": "true"}
        resp = self._request("GET", url, params=params)

        if resp.status_code != 200:
            logger.error("Failed to get upload URL: %s %s", resp.status_code, resp.text[:200])
            raise RuntimeError(f"Cannot get upload URL: {resp.status_code}")

        upload_url = resp.json()["href"]

        # Загружаем
        resp = self._request("PUT", upload_url, data=content)
        resp.raise_for_status()
        logger.info("File uploaded successfully to Yandex Disk")

    def _create_workbook(self) -> bytes:
        """Создаёт новый XLSX с заголовками."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Клиенты"

        headers = [
            "ID клиента", "Имя", "Телефон",
            "Первый контакт", "Последний контакт",
            "Дата услуги", "Услуга", "Визитов"
        ]

        # Заголовки
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = self.HEADER_FONT
            cell.fill = self.HEADER_FILL
            cell.alignment = self.HEADER_ALIGNMENT
            cell.border = self.BORDER

        # Ширина колонок
        ws.column_dimensions["A"].width = 15
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 22
        ws.column_dimensions["E"].width = 22
        ws.column_dimensions["F"].width = 22
        ws.column_dimensions["G"].width = 25
        ws.column_dimensions["H"].width = 10

        # Заморозить заголовок
        ws.freeze_panes = "A2"

        output = io.BytesIO()
        wb.save(output)
        return output.getvalue()

    def _read_all(self) -> list[dict]:
        """Читает все записи из XLSX."""
        try:
            data = self._download_file()
            wb = load_workbook(io.BytesIO(data))
            ws = wb["Клиенты"]

            records = []
            headers = [cell.value for cell in ws[1]]

            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] is None:
                    continue
                records.append(dict(zip(headers, row)))

            return records
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                logger.info("File not found on Yandex Disk, returning empty list")
                return []
            logger.error("Error reading XLSX: %s", e)
            return []
        except Exception as e:
            logger.error("Error reading XLSX: %s", e)
            return []

    def _write_all(self, rows: list[dict]) -> None:
        """Перезаписывает весь XLSX на Диске."""
        wb = Workbook()
        ws = wb.active
        ws.title = "Клиенты"

        headers = [
            "ID клиента", "Имя", "Телефон",
            "Первый контакт", "Последний контакт",
            "Дата услуги", "Услуга", "Визитов"
        ]

        # Заголовки
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = self.HEADER_FONT
            cell.fill = self.HEADER_FILL
            cell.alignment = self.HEADER_ALIGNMENT
            cell.border = self.BORDER

        # Данные
        for row_idx, row_data in enumerate(rows, 2):
            values = [
                row_data.get("ID клиента", ""),
                row_data.get("Имя", ""),
                row_data.get("Телефон", ""),
                row_data.get("Первый контакт", ""),
                row_data.get("Последний контакт", ""),
                row_data.get("Дата услуги", ""),
                row_data.get("Услуга", ""),
                row_data.get("Визитов", ""),
            ]
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.border = self.BORDER

        # Ширина колонок
        ws.column_dimensions["A"].width = 15
        ws.column_dimensions["B"].width = 20
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 22
        ws.column_dimensions["E"].width = 22
        ws.column_dimensions["F"].width = 22
        ws.column_dimensions["G"].width = 25
        ws.column_dimensions["H"].width = 10

        ws.freeze_panes = "A2"

        output = io.BytesIO()
        wb.save(output)
        self._upload_file(output.getvalue())

    def add_or_update(
        self,
        client_id: str,
        name: str,
        phone: str,
        service_name: str,
        service_date: str | None = None,
    ) -> None:
        """Добавляет или обновляет клиента в XLSX на Яндекс.Диске.

        Args:
            service_date: Дата и время услуги (ISO format). 
                         Если None — используется текущее время.
        """
        now = datetime.now().isoformat()
        # Дата услуги = переданная дата записи, или текущее время
        last_service = service_date if service_date else now

        rows = self._read_all()

        for row in rows:
            if str(row.get("ID клиента", "")) == str(client_id):
                # Обновляем существующего
                # first_contact НЕ трогаем!
                row["Последний контакт"] = now
                row["Дата услуги"] = last_service  # ← Дата из записи!
                row["Услуга"] = service_name
                row["Визитов"] = str(int(str(row.get("Визитов", "0"))) + 1)
                if not row.get("Имя"):
                    row["Имя"] = name
                if not row.get("Телефон"):
                    row["Телефон"] = phone
                self._write_all(rows)
                logger.info("Updated client %s in XLSX", client_id)
                return

        # Новый клиент
        rows.append({
            "ID клиента": str(client_id),
            "Имя": name,
            "Телефон": phone,
            "Первый контакт": now,
            "Последний контакт": now,
            "Дата услуги": last_service,  # ← Дата из записи!
            "Услуга": service_name,
            "Визитов": "1",
        })
        self._write_all(rows)
        logger.info("Added new client %s to XLSX", client_id)

    def get_client(self, client_id: str) -> Optional[dict]:
        """Получает данные клиента по ID."""
        rows = self._read_all()
        for row in rows:
            if str(row.get("ID клиента", "")) == str(client_id):
                return row
        return None