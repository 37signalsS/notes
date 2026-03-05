# HTTPie: Современный HTTP-клиент для работы с API

## Определения

**HTTPie** — утилита командной строки для работы с HTTP и API. Отличается интуитивным синтаксисом, автоматическим форматированием вывода (JSON, подсветка) и встроенной поддержкой сессий. Создана для интерактивной отладки API, а не для скриптов.

## Базовые концепции

### 1. Структура команды

```bash
http [метод] [URL] [параметры]
```

**Элементы команды:**
- **Метод:** `GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `HEAD` (по умолчанию `GET`)
- **URL:** Полный адрес или домен (автоматически добавляет `http://`)
- **Параметры:**
  - `key=value` — данные тела запроса (JSON по умолчанию)
  - `key==value` — параметры URL (query string)
  - `@file` — загрузка файла
  - `Header: Value` — заголовки

### 2. Установка

```bash
# pip
pip install httpie

# apt (Debian/Ubuntu)
sudo apt install httpie

# yum/dnf (RHEL/CentOS/Fedora)
sudo yum install httpie
sudo dnf install httpie

# brew (macOS)
brew install httpie
```

### 3. Отличия от curl

| Характеристика | curl | httpie |
| :--- | :--- | :--- |
| **Синтаксис** | Флаги (`-X`, `-H`, `-d`) | Подкоманды и аргументы |
| **JSON** | Вручную через `-d` и `-H` | Автоматически (`key=value`) |
| **Вывод** | Сырой | Цветной, форматированный |
| **Сессии** | Через файлы cookies | Встроенные (`--session`) |
| **Скрипты** | Да (с `-f`) | Не рекомендуется |
| **Протоколы** | Множество (HTTP, FTP, SCP...) | Только HTTP/HTTPS |

---

## Практические сценарии

### Сценарий 1: Базовые GET-запросы

```bash
# Простой GET (метод по умолчанию)
http https://api.example.com/users

# Явный GET
http GET https://api.example.com/users

# С параметрами URL (автоматически кодируются)
http GET https://api.example.com/users name==John age==30
# Эквивалентно: https://api.example.com/users?name=John&age=30

# С заголовками
http GET https://api.example.com/users Accept:application/json
```

### Сценарий 2: POST с JSON (по умолчанию)

```bash
# Отправка JSON (автоматически добавляет Content-Type: application/json)
http POST https://api.example.com/users name=John age:=30
# Отправляет: {"name": "John", "age": 30}

# Вложенные объекты (через := для сырого JSON)
http POST https://api.example.com/users \
  name=John \
  address:='{"city":"Moscow","street":"Lenina 1"}'

# Массивы
http POST https://api.example.com/users \
  name=John \
  tags:='["admin","user"]'
```

**Типы данных:**

| Синтаксис | Тип | Пример |
| :--- | :--- | :--- |
| `key=value` | Строка | `name=John` |
| `key:=value` | Число/булево/JSON | `age:=30`, `active:=true` |
| `key==value` | Параметр URL | `search==john` |
| `key@filename` | Загрузка файла | `avatar@photo.jpg` |

### Сценарий 3: Отправка форм

```bash
# application/x-www-form-urlencoded
http --form POST https://api.example.com/users name=John age=30

# multipart/form-data (для загрузки файлов)
http --multipart POST https://api.example.com/upload \
  user=John \
  avatar@/path/to/photo.jpg
```

### Сценарий 4: Загрузка файлов

```bash
# Загрузка одного файла
http --download POST https://api.example.com/upload file@document.pdf

# Загрузка с прогресс-баром
http --download GET https://example.com/large-file.zip

# Продолжение прерванной загрузки
http --download --continue GET https://example.com/large-file.zip
```

### Сценарий 5: Сессии

```bash
# Создание именованной сессии (сохраняется в ~/.httpie/sessions/)
http --session=admin POST https://api.example.com/login \
  username=admin password=secret

# Использование сессии (cookies и заголовки сохраняются)
http --session=admin GET https://api.example.com/profile

# Временная сессия (не сохраняется)
http --session=/tmp/session.json GET https://api.example.com/profile

# Просмотр сохранённой сессии
cat ~/.httpie/sessions/admin.json
```

### Сценарий 6: Аутентификация

```bash
# Basic auth (автоматически)
http -a user:password https://api.example.com/protected

# Digest auth
http --auth-type=digest -a user:password https://api.example.com/protected

# Bearer token
http -A bearer -a YOUR_TOKEN https://api.example.com/api/resource

# Через заголовок
http Authorization:'Bearer YOUR_TOKEN' https://api.example.com/api/resource
```

### Сценарий 7: Офлайн-режим (превью запроса)

```bash
# Показать запрос без отправки
http --offline POST https://api.example.com/users name=John age=30

# Полезно для проверки синтаксиса перед отправкой
```

### Сценарий 8: Отладка и вывод

```bash
# Подробный вывод заголовков
http -v GET https://api.example.com/users

# Только заголовки запроса
http -h GET https://api.example.com/users

# Только тело ответа
http -b GET https://api.example.com/users

# Отключить цвета (для скриптов)
http --pretty=none GET https://api.example.com/users
```

**Уровни вывода:**

| Опция | Описание |
| :--- | :--- |
| `-h`, `--headers` | Только заголовки |
| `-b`, `--body` | Только тело |
| `-v`, `--verbose` | Заголовки + тело (запрос и ответ) |
| `--pretty=none` | Отключить форматирование |

### Сценарий 9: Работа с таймаутами

```bash
# Общий таймаут
http --timeout=10 GET https://api.example.com/users

# Раздельные таймауты (чтение, подключение)
http --timeout=read:10,connect:5 GET https://api.example.com/users
```

### Сценарий 10: Интеграция с jq

```bash
# HTTPie уже форматирует JSON, но можно добавить jq для фильтрации
http GET https://api.example.com/users | jq '.[].name'

# Фильтрация по условию
http GET https://api.example.com/users | jq '.[] | select(.age > 25)'
```

---

## Дополнительная информация

### 1. Плагины

HTTPie поддерживает плагины для расширения функциональности:

```bash
# Установка плагина
pip install httpie-plugin-name

# Примеры плагинов:
# - httpie-jwt-auth: аутентификация через JWT
# - httpie-oauth1: OAuth 1.0a
# - httpie-edgegrid: EdgeGrid auth
```

### 2. Конфигурация

Конфигурационный файл: `~/.httpie/config.json`

```json
{
  "default_options": [
    "--pretty=true",
    "--verify=false"
  ]
}
```

### 3. Коды возврата

| Код | Описание |
| :--- | :--- |
| **0** | Успех |
| **1** | Ошибка запроса (неверный синтаксис) |
| **2** | Ошибка сети |
| **3** | Ошибка парсинга ответа |
| **4** | HTTP-ошибка (4xx/5xx) |

> HTTPie автоматически возвращает ошибку при HTTP 4xx/5xx, в отличие от curl без `-f`.

### 4. Ограничения

- **Только HTTP/HTTPS:** Нет поддержки FTP, SCP, SFTP (в отличие от curl)
- **Не для скриптов:** Интерактивный инструмент, не рекомендуется для CI/CD
- **Меньше протоколов:** Специализирован на API, не универсальный инструмент

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie
- **[Инструменты диагностики сети](../network_diagnostics_tools.md)**
