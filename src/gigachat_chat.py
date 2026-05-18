from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from gigachat.exceptions import AuthenticationError, GigaChatException

logger = logging.getLogger("aaron-salon-bot")

SYSTEM_PROMPT_RU = """Ты — Олег, администратор салона красоты "{salon_name}".
Адрес салона: {address}.
Сегодня: {current_date}, {weekday} (часовой пояс {timezone}).

ВАЖНО:
- Если клиент говорит "завтра", "послезавтра" — считай относительно сегодняшней даты.
- Не выдумывай даты — используй сегодняшнюю дату как опорную точку.
- Часы работы: с {work_start} до {work_end}, кроме субботы и воскресенья.

Твоя задача: кратко и вежливо консультировать клиента по услугам, ценам, длительности, уходу и подготовке.
Если клиент хочет записаться, попроси: услугу, дату, время, имя и телефон.
Если клиент говорит "да", "запиши", "хочу записаться" — предложи команду /book.
Отвечай по-русски, короткими сообщениями.
Не признавайся, что ты бот или робот.
Не отвечай на посторонние вопросы: только на тему услуг и работы салона. Мягко возвращай к теме записи.

Список услуг:
{services_text}
"""


class GigaChatConsultant:
    """
    Консультант на базе GigaChat с автоматическим управлением токенами OAuth.

    Как работает аутентификация (автоматически, без участия разработчика):
    1. SDK получает access token при первом запросе через OAuth 2.0 Client Credentials
    2. Токен кэшируется внутри SDK и переиспользуется
    3. При истечении срока (30 минут) SDK автоматически запрашивает новый
    4. При ошибке 401 SDK делает retry с обновлённым токеном

    Документация: https://github.com/ai-forever/gigachat
    """

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
        work_start_hour: int = 10,
        work_end_hour: int = 20,
    ) -> None:
        self._model = model
        self._salon_name = salon_name
        self._services_text = services_text
        self._address = address
        self._timezone = timezone
        self._work_start_hour = work_start_hour
        self._work_end_hour = work_end_hour

        # Создаём клиент ОДИН РАЗ при инициализации бота
        # Параметры credentials и scope также можно задать через env:
        # GIGACHAT_CREDENTIALS и GIGACHAT_SCOPE — SDK подхватит их автоматически,
        # но явная передача приоритетнее.
        self._client = GigaChat(
            credentials=credentials,
            scope=scope,
            verify_ssl_certs=verify_ssl_certs,
            # Автоматический retry с exponential backoff при transient ошибках
            # Включаем retry на случай 401 (expired token) — SDK обновит токен и повторит
            max_retries=2,
            retry_backoff_factor=0.5,
        )
        logger.info(
            "GigaChat client initialized (model=%s, scope=%s, ssl=%s)",
            model,
            scope or "default",
            verify_ssl_certs,
        )

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
        """
        Отправляет сообщение в GigaChat и возвращает ответ.

        Токен управляется автоматически SDK:
        - НЕ нужно вызывать /token вручную
        - НЕ нужно обновлять токен каждые 2 часа или 30 минут
        - SDK сама кэширует и обновляет access token
        """
        current_date, weekday_ru = self._get_datetime_context()

        system_prompt = SYSTEM_PROMPT_RU.format(
            salon_name=self._salon_name,
            services_text=self._services_text,
            address=self._address,
            current_date=current_date,
            weekday=weekday_ru,
            timezone=self._timezone,
            work_start=self._work_start_hour,
            work_end=self._work_end_hour,
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

        try:
            # Используем переиспользуемый клиент
            # SDK автоматически обновит токен, если он истёк
            resp = self._client.chat(chat)
            return (resp.choices[0].message.content or "").strip()

        except AuthenticationError as e:
            logger.error("GigaChat authentication failed (credentials invalid?): %s", e)
            return (
                "Извините, произошла ошибка авторизации с AI-сервисом. "
                "Пожалуйста, свяжитесь с администратором."
            )
        except GigaChatException as e:
            logger.error("GigaChat API error: %s", e)
            return (
                "Извините, AI-сервис временно недоступен. "
                "Пожалуйста, попробуйте позже."
            )
        except Exception as e:
            logger.exception("Unexpected error in GigaChat reply")
            return (
                "Произошла непредвиденная ошибка. "
                "Пожалуйста, попробуйте ещё раз."
            )
