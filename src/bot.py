from __future__ import annotations

import os
import sys
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ParseMode, ChatAction
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from src.yandex_calendar_client import Booking, YandexCalendarClient
from src.config import Config, load_config
from src.yandex_disk_xlsx_client import YandexDiskXlsxClient
from src.gigachat_chat import GigaChatConsultant
from src.services import load_services, format_services, Service

logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
logger = logging.getLogger("aaron-salon-bot")


class BookingFlow(StatesGroup):
    category = State()
    service = State()
    dt = State()
    name = State()
    phone = State()
    confirm = State()


def _parse_datetime_ru(text: str, tz: str) -> datetime | None:
    text = text.strip()
    now = datetime.now(ZoneInfo(tz))

    try:
        dt = datetime.strptime(text, "%d.%m")
        return dt.replace(year=now.year, tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m.%Y")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m %H:%M")
        return dt.replace(year=now.year, tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%d.%m.%Y %H:%M")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        pass

    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=ZoneInfo(tz))
    except ValueError:
        return None


def _is_weekend(dt: datetime) -> bool:
    """Суббота и воскресенье — выходной."""
    return dt.weekday() >= 5


def _is_outside_work_hours(dt: datetime, work_start: int, work_end: int) -> bool:
    return dt.hour < work_start or dt.hour >= work_end


def _format_work_hours(work_start: int, work_end: int) -> str:
    return f"{work_start:02d}:00–{work_end:02d}:00"


def _categories_keyboard(services: list[Service]) -> InlineKeyboardMarkup:
    cats = sorted({s.category for s in services})
    kb = [[InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}")] for cat in cats]
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _services_keyboard(services: list[Service], category: str, page: int = 0) -> InlineKeyboardMarkup:
    cat_svcs = [(i, s) for i, s in enumerate(services) if s.category == category]
    PER_PAGE = 8
    total = (len(cat_svcs) + PER_PAGE - 1) // PER_PAGE
    start = page * PER_PAGE
    items = cat_svcs[start:start + PER_PAGE]

    kb = [[InlineKeyboardButton(text=s.label, callback_data=f"svc:{orig_i}")] for orig_i, s in items]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="← Назад", callback_data=f"page:{page - 1}"))
    if page < total - 1:
        nav.append(InlineKeyboardButton(text="Ещё →", callback_data=f"page:{page + 1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton(text="← К категориям", callback_data="back:cat")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _time_slots_keyboard(work_start: int, work_end: int) -> InlineKeyboardMarkup:
    slots = list(range(work_start, work_end, 2))
    kb = []
    row = []
    for h in slots:
        row.append(InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"time:{h:02d}:00"))
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([InlineKeyboardButton(text="⌨️ Другое время", callback_data="time:other")])
    kb.append([InlineKeyboardButton(text="← Назад", callback_data="back:dt")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, записать", callback_data="confirm:yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm:no")],
    ])


@dataclass(frozen=True)
class AppState:
    cfg: Config
    services: list[Service]
    consultant: GigaChatConsultant
    calendar: YandexCalendarClient
    clients: YandexDiskXlsxClient


def _match_service(services: list[Service], user_text: str) -> Service | None:
    t = (user_text or "").strip().lower()
    if not t:
        return None
    for s in services:
        if t in s.service.lower() or s.service.lower() in t:
            return s
    return None


async def send_typing_and_reply(message: Message, text: str, parse_mode=None):
    await message.bot.send_chat_action(
        chat_id=message.chat.id, action=ChatAction.TYPING
    )
    await asyncio.sleep(0.5)
    await message.answer(text, parse_mode=parse_mode)


async def cmd_start(message: Message, state: FSMContext, app: AppState) -> None:
    await state.clear()
    await message.answer(
        f"✨ Здравствуйте! Я — Олег, ваш персональный консультант салона красоты <b>{app.cfg.salon_name}</b>\n\n"
        "Я могу:\n"
        "- подсказать по услугам и ценам 📋\n"
        "- записать вас на услугу 📅\n\n"
        f"Часы работы: {_format_work_hours(app.cfg.work_start_hour, app.cfg.work_end_hour)}\n"
        "Команды:\n"
        "/price — прайс-лист\n"
        "/book — запись \n"
        "/help — помощь\n",
        parse_mode=ParseMode.HTML,
    )
    await message.answer(format_services(app.services, limit=12))


async def cmd_help(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("📝 Напишите вопрос текстом или используйте /book для записи.")


async def cmd_price(message: Message, app: AppState) -> None:
    await message.answer(format_services(app.services, limit=30))


async def cmd_book(message: Message, state: FSMContext, app: AppState) -> None:
    await state.set_state(BookingFlow.category)
    await state.update_data(draft={})
    await message.answer(
        "📝 Ок, давайте запишем вас. Выберите категорию или напишите название услуги:",
        reply_markup=_categories_keyboard(app.services),
    )


async def handle_category_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    cat = cq.data.split(":", 1)[1]
    await state.update_data(category=cat)
    await state.set_state(BookingFlow.service)
    await cq.message.edit_text(
        f"📌 {cat}. Выберите услугу:",
        reply_markup=_services_keyboard(app.services, cat),
    )
    await cq.answer()


async def handle_service_page_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    page = int(cq.data.split(":", 1)[1])
    data = await state.get_data()
    cat = data.get("category", "")
    await cq.message.edit_reply_markup(reply_markup=_services_keyboard(app.services, cat, page))
    await cq.answer()


async def handle_service_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    idx = int(cq.data.split(":", 1)[1])
    svc = app.services[idx]
    await state.update_data(
        service=svc.service,
        duration_minutes=svc.duration_minutes,
        price_rub=svc.price_rub,
    )
    await state.set_state(BookingFlow.dt)
    await cq.message.edit_text(
        "✅ Отлично. Напишите дату. Например: <code>20.06</code>\n"
        f"Часовой пояс: {app.cfg.salon_timezone}",
        parse_mode=ParseMode.HTML,
    )
    await cq.answer()


async def handle_time_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    data = await state.get_data()
    selected_date_iso = data.get("selected_date_iso")
    if not selected_date_iso:
        await cq.message.answer("Сначала напишите дату.")
        await cq.answer()
        return

    time_part = cq.data.split(":", 1)[1]
    if time_part == "other":
        await cq.message.edit_text(
            "Напишите дату и время полностью. Например: <code>20.06 15:30</code>",
            parse_mode=ParseMode.HTML,
        )
        await cq.answer()
        return

    hour, minute = map(int, time_part.split(":"))
    dt = datetime.fromisoformat(selected_date_iso).replace(hour=hour, minute=minute)

    if _is_weekend(dt):
        await cq.message.answer(
            "⚠️ Вы выбрали выходной день.\n"
            "Салон работает с понедельника по пятницу. Выберите другую дату.",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        await cq.answer()
        return

    if _is_outside_work_hours(dt, app.cfg.work_start_hour, app.cfg.work_end_hour):
        await cq.message.answer(
            f"⚠️ Салон работает с {_format_work_hours(app.cfg.work_start_hour, app.cfg.work_end_hour)}.\n"
            f"Вы выбрали {dt.strftime('%H:%M')}. Пожалуйста, выберите время в рабочие часы.",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        await cq.answer()
        return

    duration = int(data.get("duration_minutes", 60))
    end = dt + timedelta(minutes=duration)

    try:
        if not app.calendar.is_time_available(dt, end):
            await cq.message.answer(
                f"⚠️ К сожалению, время {dt.strftime('%H:%M')} уже занято. Выберите другое:",
                reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
            )
            await cq.answer()
            return
    except Exception as e:
        logger.error("Error checking availability: %s", e)

    await state.update_data(start_iso=dt.isoformat())
    await state.set_state(BookingFlow.name)
    await cq.message.edit_text("😊 Как вас зовут?")
    await cq.answer()


async def handle_back_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    target = cq.data.split(":", 1)[1]
    if target == "cat":
        await state.set_state(BookingFlow.category)
        await cq.message.edit_text(
            "Выберите категорию или напишите название услуги:",
            reply_markup=_categories_keyboard(app.services),
        )
    elif target == "dt":
        await state.set_state(BookingFlow.dt)
        await cq.message.edit_text(
            "Напишите дату. Например: <code>20.06</code>",
            parse_mode=ParseMode.HTML,
        )
    await cq.answer()


async def handle_confirm_cb(cq: CallbackQuery, state: FSMContext, app: AppState) -> None:
    answer = cq.data.split(":", 1)[1]
    if answer == "no":
        await state.clear()
        await cq.message.edit_text("❌ Отменил. Если захотите — /book")
        await cq.answer()
        return

    await confirm_booking(cq.message, state, app, user_id=str(cq.from_user.id))
    await cq.answer()


async def book_service(message: Message, state: FSMContext, app: AppState) -> None:
    # также срабатывает если пользователь напечатал название вручную
    category = None
    for cat in sorted({s.category for s in app.services}):
        if cat.lower() in (message.text or "").lower():
            category = cat
            break
    if category and not _match_service(app.services, message.text or ""):
        await state.update_data(category=category)
        await state.set_state(BookingFlow.service)
        await message.answer(
            f"📌 {category}. Выберите услугу:",
            reply_markup=_services_keyboard(app.services, category),
        )
        return

    svc = _match_service(app.services, message.text or "")
    if not svc:
        await message.answer(
            "Не нашёл такую услугу. Выберите категорию:",
            reply_markup=_categories_keyboard(app.services),
        )
        return

    await state.update_data(
        service=svc.service,
        duration_minutes=svc.duration_minutes,
        price_rub=svc.price_rub,
    )
    await state.set_state(BookingFlow.dt)
    await message.answer(
        "✅ Отлично. Напишите дату. Например: <code>20.06</code>\n"
        f"Часовой пояс: {app.cfg.salon_timezone}",
        parse_mode=ParseMode.HTML,
    )


async def book_dt(message: Message, state: FSMContext, app: AppState) -> None:
    dt = _parse_datetime_ru(message.text or "", app.cfg.salon_timezone)
    if not dt:
        await message.answer(
            "Не понял дату. Напишите в формате <code>20.06</code> (день.месяц)\n"
            "или нажмите /help для продолжения консультации",
            parse_mode=ParseMode.HTML,
        )
        return

    # если время не указано — показываем слоты
    time_specified = any(c.isdigit() for c in message.text.split()[-1]) if len(message.text.split()) >= 2 else False
    has_time = len(message.text.split()) >= 2 and (":" in message.text.split()[-1] or time_specified)

    if not has_time:
        # только дата — сохраняем и показываем слоты
        dt_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        await state.update_data(selected_date_iso=dt_midnight.isoformat())
        await message.answer(
            f"📅 {dt.strftime('%d.%m.%Y')}. Выберите время:",
            reply_markup=_time_slots_keyboard(app.cfg.work_start_hour, app.cfg.work_end_hour),
        )
        return

    if _is_weekend(dt):
        await message.answer(
            "⚠️ Вы выбрали выходной день.\n"
            "Наш салон работает с понедельника по пятницу.\n"
            "Пожалуйста, выберите другую дату."
        )
        return

    if _is_outside_work_hours(dt, app.cfg.work_start_hour, app.cfg.work_end_hour):
        await message.answer(
            f"⚠️ Салон работает с {_format_work_hours(app.cfg.work_start_hour, app.cfg.work_end_hour)}.\n"
            f"Вы выбрали {dt.strftime('%H:%M')}. Пожалуйста, выберите время в рабочие часы."
        )
        return

    data = await state.get_data()
    duration = int(data.get("duration_minutes", 60))
    end = dt + timedelta(minutes=duration)

    try:
        if not app.calendar.is_time_available(dt, end):
            await message.answer(
                f"⚠️ К сожалению, время {dt.strftime('%H:%M')} уже занято.\n"
                "Пожалуйста, выберите другое время:"
            )
            return
    except Exception as e:
        logger.error("Error checking availability: %s", e)

    await state.update_data(start_iso=dt.isoformat())
    await state.set_state(BookingFlow.name)
    await message.answer("😊 Как вас зовут?")


async def book_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Имя слишком короткое. Напишите ещё раз.")
        return
    await state.update_data(client_name=name)
    await state.set_state(BookingFlow.phone)
    await message.answer("📱 Ваш телефон (например: +7 999 123-45-67)?")


async def book_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if len(phone) < 6:
        await message.answer(
            "Похоже на слишком короткий номер. Напишите телефон ещё раз."
        )
        return
    await state.update_data(phone=phone)
    await state.set_state(BookingFlow.confirm)

    data = await state.get_data()
    start = datetime.fromisoformat(data["start_iso"])
    formatted_date = start.strftime("%d.%m.%Y %H:%M")

    await message.answer(
        "Проверьте запись:\n"
        f"- Услуга: {data['service']} ({data['duration_minutes']} мин, {data['price_rub']} ₽)\n"
        f"- Когда: {formatted_date}\n"
        f"- Имя: {data['client_name']}\n"
        f"- Телефон: {data['phone']}",
        reply_markup=_confirm_keyboard(),
    )


async def confirm_booking(msg: Message, state: FSMContext, app: AppState, user_id: str | None = None) -> None:
    data = await state.get_data()
    start = datetime.fromisoformat(data["start_iso"])
    booking = Booking(...
        service_name=data["service"],
        client_name=data["client_name"],
        phone=data["phone"],
        start=start,
        duration_minutes=int(data["duration_minutes"]),
        timezone=app.cfg.salon_timezone,
        salon_name=app.cfg.salon_name,
    )

    try:
        link = await asyncio.to_thread(app.calendar.create_booking_event, booking)
        logger.info("Calendar event created: %s", link)
    except Exception as e:
        logger.error("Error creating calendar event: %s", e)
        link = ""

    await state.clear()
    await msg.answer("✅ Готово! Вы записаны! Ждём вас 💖")

    try:
        await asyncio.to_thread(
            app.clients.add_or_update,
            client_id=user_id or str(msg.from_user.id),
            name=data["client_name"],
            phone=data["phone"],
            service_name=data["service"],
            service_date=data["start_iso"],
        )
        logger.info("Client saved: %s", msg.from_user.id)
    except Exception as e:
        logger.error("Error saving client: %s", e)

    try:
        ics_content = await asyncio.to_thread(app.calendar.generate_ics, booking)
        await msg.answer_document(
            document=types.BufferedInputFile(
                file=ics_content.encode("utf-8"),
                filename=f"booking_{booking.start.strftime('%d%m%Y')}.ics",
            ),
            caption="Добавьте запись в свой календарь 📅",
        )
    except Exception as e:
        logger.error("Error sending ics: %s", e)


async def book_confirm_text(message: Message, state: FSMContext, app: AppState) -> None:
    answer = (message.text or "").strip().lower()
    if answer not in {"да", "нет"}:
        await message.answer("Ответьте «да» или «нет».", reply_markup=_confirm_keyboard())
        return
    if answer == "нет":
        await state.clear()
        await message.answer("❌ Отменил. Если захотите — /book")
        return
    await confirm_booking(message, state, app)


async def consult(message: Message, state: FSMContext, app: AppState) -> None:
    if await state.get_state() is not None:
        return
    try:
        reply = app.consultant.reply(message.text or "")
    except Exception as e:
        logger.exception("GigaChat error")
        await send_typing_and_reply(
            message, f"Ошибка консультации. Попробуйте ещё раз.\n\n{e}"
        )
        return
    await send_typing_and_reply(message, reply)


async def maybe_start_booking(
    message: Message, state: FSMContext, app: AppState
) -> None:
    text = (message.text or "").strip().lower()

    booking_triggers = [
        "запиши",
        "записаться",
        "хочу записаться",
        "хочу на",
        "запись",
        "booking",
    ]

    for trigger in booking_triggers:
        if trigger in text:
            await cmd_book(message, state, app)
            return

    await consult(message, state, app)


def main() -> None:
    cfg = load_config()
    services = load_services(cfg.services_csv)

    # ═══════════════════════════════════════════════════════════════
    # ЯНДЕКС.ДИСК — таблица клиентов
    # ═══════════════════════════════════════════════════════════════
    clients_manager = YandexDiskXlsxClient(
        oauth_token=cfg.yandex_disk_token,
        file_path=cfg.yandex_disk_file_path,
    )
    logger.info("✅ Yandex Disk XLSX initialized")

    # ═══════════════════════════════════════════════════════════════
    # ЯНДЕКС.КАЛЕНДАРЬ
    # ═══════════════════════════════════════════════════════════════
    calendar = YandexCalendarClient(
        calendar_url=cfg.yandex_caldav_url,
        username=cfg.yandex_caldav_username,
        password=cfg.yandex_caldav_password,
    )
    logger.info("✅ Yandex Calendar initialized")

    # ═══════════════════════════════════════════════════════════════
    # GIGACHAT
    # ═══════════════════════════════════════════════════════════════
    consultant = GigaChatConsultant(
        credentials=cfg.gigachat_credentials,
        model=cfg.gigachat_model,
        scope=cfg.gigachat_scope,
        verify_ssl_certs=cfg.gigachat_verify_ssl_certs,
        salon_name=cfg.salon_name,
        services_text=format_services(services, limit=60),
        address=cfg.address,
        timezone=cfg.salon_timezone,
        work_start_hour=cfg.work_start_hour,
        work_end_hour=cfg.work_end_hour,
    )

    app_state = AppState(
        cfg=cfg,
        services=services,
        consultant=consultant,
        calendar=calendar,
        clients=clients_manager,
    )

    async def _run() -> None:
        print("BOT_STARTING", flush=True)
        bot = Bot(token=cfg.telegram_bot_token)
        dp = Dispatcher(storage=MemoryStorage())

        @dp.callback_query.middleware()
        async def log_callback_query(handler, event, data):
            print(f"CALLBACK_MW: data={event.data}", flush=True)
            return await handler(event, data)

        async def _cmd_start(message: Message, state: FSMContext) -> None:
            await cmd_start(message, state, app_state)

        async def _cmd_price(message: Message) -> None:
            await cmd_price(message, app_state)

        async def _cmd_book(message: Message, state: FSMContext) -> None:
            await cmd_book(message, state, app_state)

        async def _book_service(message: Message, state: FSMContext) -> None:
            await book_service(message, state, app_state)

        async def _book_dt(message: Message, state: FSMContext) -> None:
            await book_dt(message, state, app_state)

        async def _book_confirm_text(message: Message, state: FSMContext) -> None:
            await book_confirm_text(message, state, app_state)

        async def _maybe_start_booking(message: Message, state: FSMContext) -> None:
            await maybe_start_booking(message, state, app_state)

        async def _handle_callback(cq: CallbackQuery, state: FSMContext) -> None:
            if not cq.data:
                await cq.answer()
                return
            try:
                data = cq.data
                st = await state.get_state()
                logger.info("Callback: data=%s state=%s", data, st)

                if data.startswith("cat:"):
                    if st == BookingFlow.category.state:
                        await handle_category_cb(cq, state, app_state)
                        return
                elif data.startswith("svc:"):
                    if st == BookingFlow.service.state:
                        idx = int(data.split(":", 1)[1])
                        svc = app_state.services[idx]
                        await state.update_data(
                            service=svc.service,
                            duration_minutes=svc.duration_minutes,
                            price_rub=svc.price_rub,
                        )
                        await state.set_state(BookingFlow.dt)
                        await cq.message.edit_text(
                            "✅ Отлично. Напишите дату. Например: <code>20.06</code> или <code>20.06 15:30</code>\n"
                            f"Часовой пояс: {app_state.cfg.salon_timezone}",
                            parse_mode=ParseMode.HTML,
                        )
                        await cq.answer()
                        return
                elif data.startswith("page:"):
                    if st == BookingFlow.service.state:
                        await handle_service_page_cb(cq, state, app_state)
                        return
                elif data.startswith("back:"):
                    if st in (BookingFlow.service.state, BookingFlow.dt.state):
                        await handle_back_cb(cq, state, app_state)
                        return
                elif data.startswith("time:"):
                    if st == BookingFlow.dt.state:
                        await handle_time_cb(cq, state, app_state)
                        return
                elif data.startswith("confirm:"):
                    if st == BookingFlow.confirm.state:
                        await handle_confirm_cb(cq, state, app_state)
                        return

                logger.warning("Unhandled callback: %s (state: %s)", data, st)
                await cq.answer("⚠️ Кнопка устарела. Начните /book заново.")
            except Exception as e:
                logger.exception("Callback error: data=%s", cq.data)
                await cq.answer("⚠️ Ошибка. Попробуйте /book заново.")

        dp.message.register(_cmd_start, Command("start"))
        dp.message.register(cmd_help, Command("help"))
        dp.message.register(_cmd_price, Command("price"))
        dp.message.register(_cmd_book, Command("book"))

        dp.message.register(_book_service, BookingFlow.category, F.text)
        dp.message.register(_book_service, BookingFlow.service, F.text)
        dp.message.register(_book_dt, BookingFlow.dt, F.text)
        dp.message.register(book_name, BookingFlow.name, F.text)
        dp.message.register(book_phone, BookingFlow.phone, F.text)
        dp.message.register(_book_confirm_text, BookingFlow.confirm, F.text)

        dp.callback_query.register(_handle_callback)

        dp.message.register(_maybe_start_booking, F.text)

        webhook_url = (os.getenv("WEBHOOK_URL") or "").strip()
        render_external_url = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
        port = int(os.getenv("PORT", "10000"))

        if not webhook_url and render_external_url:
            webhook_url = f"{render_external_url.rstrip('/')}/webhook"

        if webhook_url:
            await bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"],
            )
            wh_info = await bot.get_webhook_info()
            logger.info("Webhook set: url=%s allowed_updates=%s", wh_info.url, wh_info.allowed_updates)
            logger.info("Bot starting in webhook mode on port %s", port)

            app = web.Application()
            app.router.add_get("/", lambda _: web.Response(text="ok"))
            app.router.add_get("/health", lambda _: web.Response(text="ok"))
            SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
            setup_application(app, dp, bot=bot)

            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, host="0.0.0.0", port=port)
            await site.start()

            await asyncio.Event().wait()
        else:
            logger.info("Bot starting in polling mode...")
            if (os.getenv("RENDER_EXTERNAL_URL") or "").strip():
                raise RuntimeError(
                    "Refusing to start polling on Render. Set WEBHOOK_URL or ensure "
                    "RENDER_EXTERNAL_URL is available so the bot can run in webhook mode."
                )
            await bot.delete_webhook(drop_pending_updates=True)
            await dp.start_polling(bot)

    asyncio.run(_run())


if __name__ == "__main__":
    main()