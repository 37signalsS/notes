# HTTPie — современный HTTP-клиент для работы с API

## Определения

**HTTPie** (произносится как «эйч-ти-ти-пай») — это кроссплатформенная консольная утилита для взаимодействия с HTTP-сервисами и API. Ключевым отличием от классического curl является ориентация на максимальное удобство пользователя: автоматическое форматирование и подсветка JSON, интуитивно понятный синтаксис параметров и встроенная поддержка сессий.

## Основные концепции

### Структура команды

```bash
http [метод] URL [параметр=значение ...]
```

**Ключевые особенности синтаксиса:**
- **Команды:** `http` для HTTP и `https` для защищенных соединений (автоматически подставляет протокол).
- **Метод:** Необязателен. Если данные не передаются — `GET`, если передаются — `POST`.
- **Параметры:**
  - `key=value`: Данные тела запроса (по умолчанию сериализуются в JSON).
  - `key==value`: Параметры строки запроса (URL Query strings).
  - `Header:Value`: HTTP-заголовки запроса.
  - `key:=value`: Литеральные значения JSON (числа, булевы значения, объекты).

### Установка

```bash
# macOS
brew install httpie

# Debian/Ubuntu
sudo apt install httpie

# Python (универсальный способ через pip)
pip install httpie
```

### Сравнение с curl

| Характеристика | cURL | HTTPie |
| :--- | :--- | :--- |
| **Философия** | Универсальность и автоматизация | Удобство человека (UX) |
| **Работа с JSON** | Вручную (`-H`, `-d`) | Нативно и автоматически |
| **Вывод** | Необработанный (Raw) | Красивый (Formatted/Colored) |
| **Сессии** | Требуют ручного управления куками | Встроенный механизм именованных сессий |
| **Протоколы** | Более 20 (FTP, LDAP, SMB и др.) | Только HTTP, HTTPS |

---

## Практические сценарии

### Сценарий 1. Базовые запросы и параметры

```bash
# Простой GET-запрос (протокол подставится автоматически)
http example.com/api/users

# GET с параметрами URL (?search=john&status=active)
http api.example.com/users search==john status==active

# Проверка только заголовков ответа (HEAD запрос)
http -h example.com
```

### Сценарий 2. Работа с JSON и вложенными структурами

HTTPie автоматически устанавливает `Content-Type: application/json` и `Accept: application/json`.

```bash
# Отправка JSON с разными типами данных
http POST api.example.com/users \
     name="John Doe" \
     email=john@example.com \
     age:=30 \
     is_admin:=true
# → Тело запроса: {"name": "John Doe", "email": "john@example.com", "age": 30, "is_admin": true}

# Передача вложенных объектов (используется синтаксис JSON-литерала)
http POST api.example.com/users \
     name="Jane" \
     settings:='{"theme": "dark", "notifications": false}'
```

### Сценарий 3. Отправка форм и загрузка файлов

```bash
# Классическая форма (application/x-www-form-urlencoded)
http --form POST example.com/api/login username=admin password=secret

# Загрузка файла (multipart/form-data)
http --multipart POST example.com/api/upload \
     title="Report" \
     document@~/Documents/report.pdf
```

### Сценарий 4. Управление сессиями (Cookies и Auth)

Сессии позволяют сохранять состояние (аутентификацию, cookies) между разными вызовами команды.

```bash
# Создание именованной сессии (вход в систему)
http --session=dev-env POST api.example.com/login username=admin password=pass

# Последующий запрос с использованием той же сессии (токены/куки подставятся сами)
http --session=dev-env api.example.com/profile

# Анонимная сессия (только для текущей цепочки, без сохранения в файл)
http --session-read-only api.example.com/stats
```

### Сценарий 5. Методы аутентификации и токены

```bash
# Базовая аутентификация (Basic Auth)
http -a username:password api.example.com/data

# Использование Bearer Token (JWT)
http -A bearer -a MY_JWT_TOKEN api.example.com/resource

# API-ключ в кастомном заголовке
http api.example.com/resource X-API-Key:TOKEN_VALUE
```

### Сценарий 6. Отладка и анализ трафика

```bash
# Просмотр всего обмена (запрос + ответ)
http -v api.example.com/users

# Просмотр только тела ответа (удобно для конвейеров)
http -b api.example.com/users | jq .

# Офлайн-режим (валидация синтаксиса запроса без его отправки)
http --offline POST api.example.com/test k=v
```

---

## Дополнительная информация

### Плагины и расширения

HTTPie поддерживает расширение функциональности через плагины (устанавливаются через `pip install`):
- **httpie-jwt-auth**: Упрощенная передача JWT токенов.
- **httpie-oauth**: Поддержка протоколов OAuth 1.0a и 2.0.
- **httpie-edgegrid**: Для взаимодействия с API Akamai.

### Поддержка HTTP/2

HTTPie поддерживает протокол HTTP/2, если установлена библиотека `httpx` (или через встроенную поддержку в новых версиях). Для принудительного использования:
```bash
http --http2 https://example.com/api
```

### Коды возврата (Exit Codes)

| Код | Описание | Значение |
| :--- | :--- | :--- |
| **0** | Успех | Команда выполнена, сервер вернул 2xx/3xx. |
| **1** | Error | Ошибка в параметрах или конфигурации. |
| **2** | Timeout | Превышено время ожидания сети. |
| **4** | HTTP Error | Сервер вернул ошибку **4xx** или **5xx**. |

### Рекомендации по безопасности

1.  **Защита секретов**: Не указывайте пароли в аргументе `-a username:password`. HTTPie предложит ввести пароль интерактивно, если указать только `-a username`.
2.  **Сессии**: Файлы сессий хранятся в открытом виде в директории конфигурации (обычно `~/.config/httpie/sessions/`). Ограничьте права доступа к этой директории.
3.  **HSTS**: При использовании команды `https` утилита будет следовать политикам безопасности сервера.

### Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)** — описание семантики методов.
- **[curl: универсальный инструмент](./curl.md)** — когда нужна максимальная переносимость и работа в сложных скриптах.
