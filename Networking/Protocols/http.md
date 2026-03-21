# HTTP Протокол

> **Примечание:** Этот файл был декомпозирован на тематические заметки.

## Структура раздела

Документация по HTTP протоколу была разделена на следующие тематические файлы:

| Файл | Описание |
| :--- | :--- |
| [HTTP: Базовые концепции](./HTTP/http_basics.md) | Определения, модель "Запрос-Ответ", Stateless, структура сообщения |
| [HTTP Методы](./HTTP/http_methods.md) | GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS, CONNECT, TRACE |
| [HTTP Коды ответа](./HTTP/http_status_codes.md) | 1xx, 2xx, 3xx, 4xx, 5xx |
| [Эволюция HTTP и HTTPS](./HTTP/http_versions.md) | HTTP/1.0, 1.1, 2, 3, HTTPS |
| [HTTP Кэширование](./HTTP/http_caching.md) | Cache-Control, ETag, Last-Modified, типы кэшей |
| [HTTP Аутентификация](./HTTP/http_authentication.md) | Basic, Digest, Form-based, Token, Cookies, SSO |
| [HTTP API и REST](./HTTP/http_rest_api.md) | API, REST, CRUD-операции |

## Связанные документы

* **[TLS](./tls.md)** — Шифрование HTTP (HTTPS)
* **[Оптимизация HTTP](./http_protocols_optimization.md)** — Производительность, HTTP/2, HTTP/3
* **[Nginx](../../WebServers/Nginx/Security/nginx_security_guide.md)** — Настройка веб-сервера
* **[cURL](../../Linux/Networking/Tools/http_clients/curl.md)** — Утилиты для работы с HTTP
* **[OAuth 2.0](../../Security/Concepts/oauth2_overview.md)** — Аутентификация и авторизация

## RFC

* **RFC 7230-7237** — HTTP/1.1
* **RFC 7540** — HTTP/2
* **RFC 9112** — HTTP/1.2 (2022)
* **RFC 9113** — HTTP/2 (2022)
* **RFC 9114** — HTTP/3 (2022)
