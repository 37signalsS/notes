# HTTPie — современный HTTP-клиент для работы с API

> **Надёжность: 10/10** (Официальная документация + промышленный стандарт для отладки)
> **Актуальность:** Август 2024 (проверено для HTTPie 3.x)

## Определения

**HTTPie** (произносится как «эйч-ти-ти-пай») — это современный консольный HTTP-клиент, предназначенный для удобного взаимодействия с веб-сервисами и API. В отличие от curl, HTTPie ориентирован на человекочитаемость: он автоматически форматирует JSON, подсвечивает синтаксис цветом и использует интуитивно понятный синтаксис параметров без лишних флагов.

## Основные концепции

### 1. Структура команды

```bash
http [метод] URL [параметр=значение ...]
```

**Ключевые особенности синтаксиса:**
- **Метод:** Необязателен (по умолчанию `GET` или `POST`, если переданы данные).
- **URL:** Можно опускать `http://` (HTTPie добавит его сам).
- **HTTPS:** Для безопасных соединений используйте команду `https` вместо `http`.
- **Параметры:**
  - `key=value`: Данные тела запроса (по умолчанию JSON).
  - `key==value`: Параметры строки запроса (URL Query).
  - `Header:Value`: HTTP-заголовки.

### 2. Установка

```bash
# macOS
brew install httpie

# Debian/Ubuntu
sudo apt install httpie

# Python (универсальный способ)
pip install httpie
```

### 3. Сравнение с curl

| Характеристика | curl | HTTPie |
| :--- | :--- | :--- |
| **Основная цель** | Универсальность и скрипты | Интерактивная отладка и чтение |
| **JSON** | Вручную (`-d '{"k":"v"}'`) | Автоматически (`k=v`) |
| **Вывод** | Сырой (Raw) | Форматированный и цветной |
| **Сессии** | Требуют ручного управления | Встроенная поддержка (`--session`) |
| **Протоколы** | Множество (FTP, SMB, и др.) | Только HTTP/HTTPS |

---

## Практические сценарии

### Сценарий 1. Базовые запросы и параметры

```bash
# Простой GET-запрос
http example.com/api/users

# GET с параметрами URL (?search=john&status=active)
http api.example.com/users search==john status==active

# Использование HTTPS-алиаса
https api.github.com/repos/httpie/httpie
```

### Сценарий 2. Работа с JSON (автоматическая сериализация)

HTTPie определяет типы данных автоматически:

```bash
# Отправка JSON (Content-Type добавится автоматически)
http POST api.example.com/users \
     name="John Doe" \
     email=john@example.com \
     age:=30 \
     is_admin:=true
# → Тело: {"name": "John Doe", "email": "john@example.com", "age": 30, "is_admin": true}

# Вложенные объекты (Nested JSON)
http POST api.example.com/users \
     name="Jane" \
     address:='{"city": "Berlin", "zip": 10115}'
```

| Синтаксис | Тип данных | Пример результата |
| :--- | :--- | :--- |
| `key=val` | Строка | `"key": "val"` |
| `key:=val` | Число/Булево/Объект | `"key": 30`, `"key": true` |
| `key@file` | Содержимое файла | Данные из файла как строка |

### Сценарий 3. Отправка форм и файлов

```bash
# Обычная форма (application/x-www-form-urlencoded)
http --form POST example.com/api/login username=admin password=secret

# Загрузка файла (multipart/form-data)
http --multipart POST example.com/api/upload \
     title="My Photo" \
     image@~/Pictures/photo.jpg
```

### Сценарий 4. Управление сессиями (Cookies и Auth)

Сессии позволяют сохранять состояние (аутентификацию, cookies) между запросами.

```bash
# Создание сессии (логин)
http --session=admin POST api.example.com/login username=admin password=pass

# Использование сохраненной сессии (запрос профиля)
http --session=admin api.example.com/profile

# Анонимная сессия (в оперативную память)
http --session-read-only=admin api.example.com/stats
```

### Сценарий 5. Аутентификация

```bash
# Basic Auth
http -a username:password api.example.com/data

# Bearer Token (OAuth2 / JWT)
http -A bearer -a MY_TOKEN api.example.com/resource

# API Key в заголовке
http api.example.com/resource X-API-Key:TOP_SECRET
```

### Сценарий 6. Отладка и просмотр запроса

```bash
# Просмотр заголовков и тела (запрос + ответ)
http -v api.example.com/users

# Только заголовки ответа
http -h api.example.com/users

# Только тело ответа (удобно для перенаправления в файл)
http -b api.example.com/users > response.json

# Офлайн-режим (посмотреть, как будет выглядеть запрос, без отправки)
http --offline POST api.example.com/test k=v
```

---

## Дополнительная информация

### 1. Плагины и расширения

HTTPie поддерживает систему плагинов. Самые популярные:
- `httpie-jwt-auth`: упрощает работу с JSON Web Tokens.
- `httpie-oauth`: поддержка OAuth 1.0a.

### 2. HTTPie Desktop

Существует графическая версия (GUI) — **HTTPie Desktop**, которая позволяет синхронизировать коллекции запросов между CLI и графическим интерфейсом.

### 3. Таймауты

```bash
# Общий таймаут в секундах
http --timeout=2.5 api.example.com/slow-endpoint

# Раздельные таймауты для подключения и чтения
http --timeout=connect:2,read:10 api.example.com/stream
```

### 4. Коды возврата (Exit Codes)

| Код | Описание |
| :--- | :--- |
| **0** | Успех |
| **1** | Ошибка данных/параметров |
| **2** | Тайм-аут или ошибка сети |
| **3** | Ошибка при обработке ответа (невалидный JSON и др.) |
| **4** | HTTP-ошибка (статус 4xx или 5xx) |

> **Внимание:** В отличие от curl, HTTPie возвращает ненулевой код выхода, если сервер ответил с ошибкой (например, 404 или 500).

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)** — глубокое описание логики методов.
- **[curl: универсальный инструмент](./curl.md)** — когда нужно больше гибкости или работа в скриптах.
