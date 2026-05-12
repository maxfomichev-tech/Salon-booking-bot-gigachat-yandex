from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole


SYSTEM_PROMPT_RU = """Ты — Олег, администратор салона красоты "{salon_name}".
Адрес салона: {address}.
Сегодня: {current_date}, {weekday} (часовой пояс {timezone}).

ВАЖНО:
- Если клиент говорит "завтра", "послезавтра" — считай относительно сегодняшней даты.
- Не выдумывай даты — используй сегодняшнюю дату как опорную точку.
- Часы работы: с 10 до 20, кроме субботы.

Твоя задача: кратко и вежливо консультировать клиента по услугам, ценам, длительности, уходу и подготовке.
Если клиент хочет записаться, попроси: услугу, дату, время, имя и телефон.
Если клиент говорит "да", "запиши", "хочу записаться" — предложи команду /book.
Отвечай по-русски, короткими сообщениями.
Не отвечай на посторонные вопросы. Мягко возвращай к теме салона.

Список услуг:
{services_text}
"""


class GigaChatConsultant:
    def __init__(
        self,
        credentials: str,
        model: str,
        salon_name: str,
        services_text: str,
        address: str,
        timezone: str = "Europe/Moscow",
        scope: str | None = None,
        verify_ssl_certs: bool = True,
    ) -> None:
        self._credentials = credentials
        self._model = model
        self._scope = scope
        self._verify_ssl_certs = verify_ssl_certs
        self._salon_name = salon_name
        self._services_text = services_text
        self._address = address
        self._timezone = timezone

    def _get_datetime_context(self) -> tuple[str, str]:
        now = datetime.now(ZoneInfo(self._timezone))
        current_date = now.strftime("%d.%m.%Y %H:%M")

        weekdays_ru = {
            "Monday": "понедельник",
            "Tuesday": "вторник",
            "Wednesday": "среда",
            "Thursday": "четверг",
            "Friday": "пятница",
            "Saturday": "суббота",
            "Sunday": "воскресенье",
        }
        weekday = now.strftime("%A")
        weekday_ru = weekdays_ru.get(weekday, weekday)
        return current_date, weekday_ru

    def reply(self, user_text: str) -> str:
        current_date, weekday_ru = self._get_datetime_context()

        system_prompt = SYSTEM_PROMPT_RU.format(
            salon_name=self._salon_name,
            services_text=self._services_text,
            address=self._address,
            current_date=current_date,
            weekday=weekday_ru,
            timezone=self._timezone,
        )

        chat = Chat(
            model=self._model,
            messages=[
                Messages(role=MessagesRole.SYSTEM, content=system_prompt),
                Messages(role=MessagesRole.USER, content=(user_text or "")),
            ],
            temperature=0.1,
            max_tokens=350,
        )

        # The SDK supports env-based config too, but we pass credentials explicitly.
        with GigaChat(
            credentials=self._credentials,
            scope=self._scope,
            verify_ssl_certs=self._verify_ssl_certs,
        ) as client:
            resp = client.chat(chat)

        return (resp.choices[0].message.content or "").strip()

