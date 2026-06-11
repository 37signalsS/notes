# Обзор HTTP-клиентов в Linux

## Определения

**HTTP-клиент командной строки** — утилита для отправки HTTP (HyperText Transfer Protocol) запросов и получения ответов из терминала. Используется для тестирования API (Application Programming Interface), автоматизации задач, скачивания файлов и отладки веб-сервисов.

## Основные концепции

### 1. Основные клиенты

| Клиент | Основное назначение | Протоколы |
| :--- | :--- | :--- |
| **[wget](./wget.md)** | Скачивание файлов, зеркалирование сайтов | HTTP, HTTPS (HyperText Transfer Protocol Secure), FTP (File Transfer Protocol) |
| **[curl](./curl.md)** | Универсальная передача данных, API, скрипты | HTTP, HTTPS, FTP, SCP (Secure Copy Protocol), SFTP (SSH File Transfer Protocol), SMB (Server Message Block), LDAP (Lightweight Directory Access Protocol) и др. |
| **[httpie](./httpie.md)** | Интерактивная работа с API, отладка | HTTP, HTTPS |

### 2. Сравнительная таблица

| Задача | Wget | cURL | HTTPie |
| :--- | :--- | :--- | :--- |
| **Скачать файл** | `wget <url>` | `curl -O <url>` | `http --download <url>` |
| **Продолжить скачивание** | `wget -c <url>` | `curl -C - -O <url>` | `http --download --continue <url>` |
| **Отправить JSON** | Вручную через `--post-data` | `curl -H 'Content-Type: application/json' -d '{"a":1}'` | `http POST <url> a=1` (автоматически) |
| **Отправить форму** | `--post-data='a=1&b=2'` | `curl -d 'a=1&b=2'` или `curl -F 'a=1'` | `http -f POST <url> a=1 b=2` |
| **Поведение при HTTP 4xx/5xx** | Возвращает ошибку (wget2) | **Не возвращает!** Требуется `-f` (`--fail`) | Возвращает ошибку |
| **Вывод** | Лог-файл | Сырой вывод | Цветной, форматированный |
| **Сессии** | Через `--save-cookies`/`--load-cookies` | Через `--cookie`/`--cookie-jar` | Встроенные (`--session=<name>`) |
| **Скрипты** | Надёжен (wget2) | Требует `-f`/`--fail` | Надёжен по умолчанию |

### 3. Выбор инструмента

**Использовать wget:**

- Рекурсивное скачивание сайтов (зеркалирование)
- Массовая загрузка файлов по списку
- Работа в фоне с продолжением прерванной загрузки

**Использовать curl:**

- Работа с API в скриптах (CI/CD (Continuous Integration / Continuous Deployment), автоматизация)
- Отправка файлов через `multipart/form-data`
- Работа с нестандартными протоколами (SCP, SFTP, LDAP)
- Тонкая настройка таймаутов и диагностика

**Использовать httpie:**

- Интерактивная отладка API
- Быстрое тестирование endpoints
- Работа с JSON (JavaScript Object Notation) API (автоматическая сериализация)

---

## Практические сценарии

### Сценарий 1: Проверка доступности API

```bash
# curl с проверкой статуса ответа
curl -f https://api.example.com/health
# → (вывод при успехе отсутствует, код возврата 0)

# httpie (автоматически покажет статус)
http GET https://api.example.com/health
# → HTTP/1.1 200 OK ...

# wget (wget2 вернёт ошибку при 4xx/5xx)
wget -q https://api.example.com/health
# → (тихая загрузка в файл)
```

### Сценарий 2: Отправка JSON в API

```bash
# curl (явное указание заголовка)
curl -X POST -H 'Content-Type: application/json' \
  -d '{"name":"John","age":30}' \
  https://api.example.com/users
# → {"status": "success", "id": 123}

# httpie (автоматически добавляет Content-Type: application/json)
http POST https://api.example.com/users name=John age:=30
# → {"status": "success", "id": 123}
```

### Сценарий 3: Скачивание файла с продолжением

```bash
# wget
wget -c https://example.com/large-file.zip
# → 'large-file.zip' saved [1024/1024]

# curl
curl -C - -O https://example.com/large-file.zip
# → ** Resuming transfer from byte offset 512

# httpie
http --download --continue https://example.com/large-file.zip
# → [################################] 100%
```

### Сценарий 4: Зеркалирование сайта

```bash
# wget: полная копия сайта для офлайн-просмотра
wget -r -l inf -k -p --adjust-extension https://example.com
```

### Сценарий 5: Аутентификация в API

```bash
# Basic auth
curl -u user:password https://api.example.com/protected
http -a user:password https://api.example.com/protected

# Bearer token
curl -H 'Authorization: Bearer <token>' https://api.example.com/api/resource
http -A bearer -a <token> https://api.example.com/api/resource
```

---

## Дополнительная информация

### 1. Концепции аутентификации

| Тип | Описание | Безопасность |
| :--- | :--- | :--- |
| **BASIC** | Логин/пароль в Base64 | Только с HTTPS |
| **DIGEST** | Хеш с challenge-ответом | Устарел, заменён на Bearer |
| **BEARER** | Токен (JWT (JSON Web Token), OAuth (Open Authorization)) | Только с HTTPS |
| **Cookies** | Сессионные cookie | Только с HTTPS |

### 2. Инструменты для тестирования

- **[httpbin.org](https://httpbin.org)** — тестовый API, "отражающий" запросы
- **[badssl.com](https://badssl.com)** — сайты с некорректными SSL (Secure Sockets Layer) сертификатами
- **Встроенный сервер Python:** `python3 -m http.server 8000`

### 3. Безопасность

- **Никогда не используйте `-k`/`--insecure` в продакшене** — это отключает проверку SSL
- **Всегда используйте `-f`/`--fail` в скриптах** для curl — иначе HTTP 4xx/5xx не будет ошибкой
- **Проверяйте коды возврата** в автоматизации: `wget2` и `httpie` надёжнее curl по умолчанию

### 4. Связанные заметки

- **[Диагностика сетевых задержек с curl](../../../Diagnostics/Networking/curl_network_diagnostics.md)**
- **[Инструменты диагностики сети](../../network_diagnostics_tools.md)**
- **[Жизненный цикл веб-запроса](../../../../Networking/Concepts/web_request_lifecycle.md)**
