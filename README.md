# **🤖 Салон Бот — Запись на услуги с AI-консультантом**

> **Полностью российский стек**: все данные клиентов хранятся на серверах в РФ. Соответствие 152-ФЗ «О персональных данных».

## **Возможности**

- **AI-консультант** — отвечает на вопросы об услугах, ценах, уходе
- **Запись на услуги** — пошаговый диалог: услуга → дата → имя → телефон → подтверждение
- **Проверка занятости** — не даст записаться на занятое время
- **Календарь** — создаёт событие в Яндекс.Календаре
- **Таблица клиентов** — сохраняет данные в XLSX на Яндекс.Диске
- **Напоминание** — отправляет `.ics` файл для добавления в личный календарь клиента

## **Архитектура (всё в РФ)**

**Table**


| **Компонент**     | **Технология**            | **Где данные**    |
| ----------------- | ------------------------- | ----------------- |
| AI-консультант    | GigaChat (Сбер)           | 🇷🇺 Россия       |
| Таблица клиентов  | Яндекс.Диск XLSX          | 🇷🇺 Россия       |
| Календарь записей | Яндекс.Календарь (CalDAV) | 🇷🇺 Россия       |
| Бот               | Telegram Bot API          | 🇷🇺 Токен только |


## **Структура проекта**

**plain**

Copy

```plain
.
├── .env                          # Переменные окружения (не коммитить!)
├── requirements.txt              # Зависимости
├── services_pricelist.csv        # Прайс-лист услуг
└── src/
    ├── bot.py                    # Точка входа, Telegram бот
    ├── config.py                 # Загрузка конфигурации из .env
    ├── gigachat_chat.py          # AI-консультант на GigaChat
    ├── yandex_disk_xlsx_client.py # Клиенты → XLSX на Яндекс.Диске
    ├── yandex_calendar_client.py  # Календарь → Яндекс.Календарь
    └── services.py               # Загрузка и форматирование прайса
```

## **Установка**

### **1. Клонирование**

**bash**

Copy

```bash
git clone https://github.com/your-repo/salon-bot.git
cd salon-bot
```

### **2. Зависимости**

**bash**

Copy

```bash
pip install -r requirements.txt
```

### **3. Настройка переменных окружения**

Скопируйте и заполните:

**bash**

Copy

```bash
cp .env.example .env
```

#### **Обязательные переменные**

**Table**


| **Переменная**           | **Как получить**                                                                                                       |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`     | @BotFather в Telegram                                                                                                  |
| `GIGACHAT_CREDENTIALS`   | [developers.sber.ru](https://developers.sber.ru/) — Authorization Key                                                  |
| `YANDEX_DISK_TOKEN`      | [oauth.yandex.ru](https://oauth.yandex.ru/) — создать приложение, получить токен                                       |
| `YANDEX_CALDAV_URL`      | [calendar.yandex.ru](https://calendar.yandex.ru/) → шестерёнка → Экспорт → CalDAV URL                                  |
| `YANDEX_CALDAV_USERNAME` | Ваш логин Яндекса (например `login@yandex.ru`)                                                                         |
| `YANDEX_CALDAV_PASSWORD` | [id.yandex.ru/security/app-passwords](https://id.yandex.ru/security/app-passwords) — пароль для приложения «Календарь» |


#### **Пример** `.env`

**env**

Copy

```env
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

GIGACHAT_CREDENTIALS=base64_encoded_credentials
GIGACHAT_MODEL=GigaChat
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_VERIFY_SSL_CERTS=false

YANDEX_DISK_TOKEN=y0_AgAAAABCD123EFG456
YANDEX_DISK_FILE_PATH=/salon-bot/clients.xlsx

YANDEX_CALDAV_URL=https://caldav.yandex.ru/calendars/login/events-default/
YANDEX_CALDAV_USERNAME=login@yandex.ru
YANDEX_CALDAV_PASSWORD=abcd efgh ijkl mnop

SALON_NAME=Аарон
SALON_TIMEZONE=Europe/Moscow
ADDRESS=ул. Примерная, 123
SERVICES_CSV=services_pricelist.csv
```

### **4. Прайс-лист**

Создайте `services_pricelist.csv`:

**csv**

Copy

```csv
category,service,duration_minutes,price_rub
Стрижка,Женская стрижка,60,2500
Стрижка,Мужская стрижка,30,1500
Окрашивание,Окрашивание в один тон,120,4000
Уход,Кератиновое выпрямление,180,5500
```

### **5. Запуск**

**bash**

Copy

```bash
python -m src.bot
```

При первом запуске бот автоматически создаст файл `clients.xlsx` на Яндекс.Диске (если его ещё нет).

## **Команды бота**

**Table**


| **Команда** | **Описание**               |
| ----------- | -------------------------- |
| `/start`    | Приветствие и список услуг |
| `/price`    | Полный прайс-лист          |
| `/book`     | Начать запись на услугу    |
| `/help`     | Помощь                     |


## **Процесс записи**

**plain**

Copy

```plain
/book → Выбор услуги → Дата и время → Имя → Телефон → Подтверждение
```

Бот проверяет:

- ✅ Существует ли такая услуга
- ✅ Не выходной ли день (суббота)
- ✅ Свободно ли время
- ✅ Формат даты

После подтверждения:

1. Создаётся событие в Яндекс.Календаре
2. Клиент сохраняется в таблицу на Яндекс.Диске
3. Отправляется `.ics` файл для личного календаря клиента

## **Где находятся данные**

### **Таблица клиентов**

- **Физическое место**: Яндекс.Диск, файл `/salon-bot/clients.xlsx`
- **Доступ**: [disk.yandex.ru](https://disk.yandex.ru/) → папка `salon-bot`
- **Формат**: Excel-таблица с заголовками, стилями, шириной колонок
- **Просмотр**: онлайн в браузере или скачать на ПК

### **Календарь записей**

- **Физическое место**: Яндекс.Календарь
- **Доступ**: [calendar.yandex.ru](https://calendar.yandex.ru/)
- **События**: содержат имя клиента, телефон, услугу

### **AI-диалоги**

- Не сохраняются — каждый запрос к GigaChat независимый
- В логах бота нет содержимого сообщений

## **Деплой на Render**

### **Webhook-режим (рекомендуется)**

1. Загрузите код на GitHub
2. Создайте **Web Service** на [render.com](https://render.com/)
3. **Build Command**: `pip install -r requirements.txt`
4. **Start Command**: `python -m src.bot`
5. В **Environment** добавьте все переменные из `.env`
6. Добавьте `RENDER_EXTERNAL_URL=https://your-app.onrender.com`

Бот автоматически настроит webhook при старте.

### **Polling-режим (локально)**

**bash**

Copy

```bash
python -m src.bot
```

Бот работает в режиме long-polling. Не используйте на Render — webhook надёжнее.

## **Соответствие 152-ФЗ**

**Table**


| **Требование**       | **Реализация**                                      |
| -------------------- | --------------------------------------------------- |
| Хранение ПДн в РФ    | ✅ Яндекс.Диск и Яндекс.Календарь — серверы в России |
| Не передаём за рубеж | ✅ Нет Google, AWS, Azure                            |
| Шифрование           | ✅ HTTPS для всех API                                |
| Минимизация данных   | ✅ Храним только необходимое (имя, телефон, ID)      |


## **Возможные проблемы**

### **GigaChat: SSL ошибка**

**plain**

Copy

```plain
ssl.SSLCertVerificationError
```

**Решение**: в `.env` установите `GIGACHAT_VERIFY_SSL_CERTS=false`

### **Яндекс.Диск: файл не создаётся**

**Проверьте**:

- Токен действительный (проверьте через [yandex.ru/dev/disk/poligon](https://yandex.ru/dev/disk/poligon))
- На Диске достаточно места
- Токен имеет доступ к Диску (при создании приложения отмечены галочки)

### **Яндекс.Календарь: не создаётся событие**

**Проверьте**:

- Пароль приложения — именно для «Календаря», не от аккаунта
- CalDAV URL скопирован полностью (со слэшем в конце)
- Логин указан полностью (`login@yandex.ru`)

## **Лицензия**

MIT License. Свободное использование для коммерческих и некоммерческих проектов.

---

**Разработано для салонов красоты РФ** | Соответствие законодательству | Без VPN и прокси