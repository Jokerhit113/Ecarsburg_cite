# Запуск на card.e-carsburg.ru (Beget)

## 1. Поддомен
Панель Beget → «Домены и поддомены» → создать поддомен `card` для e-carsburg.ru,
создать для него отдельный сайт (каталог `~/card.e-carsburg.ru/`). В «DNS» запись появится сама.
Включить бесплатный SSL (Let's Encrypt) для поддомена.

## 2. Файлы
Загрузить ВЕСЬ проект в корень сайта `~/card.e-carsburg.ru/` (рядом с `public_html`),
НЕ внутрь `public_html` — иначе `.env` и `ecarsburg.db` можно будет скачать по ссылке.
Не загружать: `debug_admin.py`, `create_admin.py` (после создания админа удалить).

## 3. Python (по справке Beget)
Из коробки на хостинге Python 3.6/3.7 — для актуальных Flask/Pillow этого мало.
Нужен Python 3.10+ (сборка в ~/.local по инструкции Beget) либо VPS.
По SSH: `ssh localhost -p222`, затем в корне сайта:
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt

## 4. .htaccess в корне сайта (рядом с passenger_wsgi.py)
    PassengerEnabled On
    PassengerPython /home/<буква>/<логин>/card.e-carsburg.ru/venv/bin/python

## 5. Настройки (.env рядом с app.py)
    BITRIX_WEBHOOK_URL=...
    SECRET_KEY=<длинная случайная строка>
Сгенерировать ключ: `python3 -c "import secrets; print(secrets.token_hex(32))"`

## 6. Права и перезапуск
Папки `static/img`, `static/video` и файл `ecarsburg.db` должны быть доступны на запись.
Перезапуск после любых изменений: `mkdir -p tmp && touch tmp/restart.txt`

## 7. Проверка
Открыть https://card.e-carsburg.ru/ , отправить тестовую заявку, войти в админку.
