# HTTPie — современный HTTP-клиент для работы с API

## Определения

**HTTPie** (произносится как «эйч-ти-ти-пай») — это кроссплатформенная консольная утилита для взаимодействия с HTTP-сервисами и API. Ключевым отличием от классического curl является ориентация на максимальное удобство пользователя: автоматическое форматирование и подсветка JSON, интуитивно понятный синтаксис параметров и встроенная поддержка сессий.

**Ключевое отличие от curl:** HTTPie спроектирован для **ручного тестирования API** (подсветка JSON, сессии, автодополнение), тогда как curl — для **скриптов и автоматизации** (переносимость, минимальные зависимости). В DevOps-контексте httpie используется при отладке API, разработке и интерактивном исследовании эндпоинтов, тогда как curl — в CI/CD пайплайнах и скриптах, где критична минимальная зависимость от окружения.

## Предварительные требования

### Требования к окружению

| Требование | Минимальное | Рекомендуемое |
| :--- | :--- | :--- |
| **Python** | 3.7+ | 3.9+ |
| **pip** | 20.0+ | Последняя версия |
| **ОС** | Linux, macOS, Windows | Любая |

> **BusyBox и Alpine:** HTTPie НЕ входит в стандартный набор BusyBox и минимальных Alpine-образов. В контейнерах для healthcheck'ов используйте curl или wget (`wget -q --spider`). Если httpie необходим — установите явно: `pip install httpie` или `apk add --no-cache httpie`.

### Установка

| Дистрибутив | Команда |
| :--- | :--- |
| **Debian/Ubuntu** | `apt-get install -y httpie` |
| **RHEL/CentOS/Rocky** | `dnf install -y httpie` |
| **Alpine** | `apk add --no-cache httpie` |
| **macOS** | `brew install httpie` |
| **pip (универсально)** | `pip install httpie` |
| **pipx (изолированно)** | `pipx install httpie` |

```bash
# Проверка установки и версии
http --version
# → HTTPie 3.2.2

# Проверка доступности Python (обязательно для httpie)
python3 --version
# → Python 3.11.4
```

### CLI команды

HTTPie устанавливает несколько утилит:

| Команда | Описание |
| :--- | :--- |
| `http` | Основная команда для HTTP/HTTPS-запросов |
| `https` | Алиас для HTTPS (эквивалент `http https://...`) |
| `httpie` | Синоним `http` (обратная совместимость) |
| `http-prompt` | Интерактивный режим с автодополнением (если установлен) |
| `httpie-env` | Управление переменными окружения httpie |

```bash
# Все команды эквивалентны:
http https://api.example.com/users
https api.example.com/users
httpie https://api.example.com/users

# Интерактивный режим (если установлен http-prompt)
http-prompt https://api.example.com
# → Интерактивная консоль с автодополнением эндпоинтов

# Управление переменными окружения
httpie-env set base_url https://api.example.com
httpie-env list
```

### Сравнение с curl

| Характеристика | cURL | HTTPie |
| :--- | :--- | :--- |
| **Философия** | Универсальность и автоматизация | Удобство человека (UX) |
| **Работа с JSON** | Вручную (`-H`, `-d`) | Нативно и автоматически |
| **Вывод** | Необработанный (Raw) | Красивый (Formatted/Colored) |
| **Сессии** | Требуют ручного управления куками | Встроенный механизм именованных сессий |
| **Протоколы** | Более 20 (FTP, LDAP, SMB и др.) | Только HTTP, HTTPS |

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

### Сценарий 7. Работа через прокси и управление сертификатами

HTTPie не имеет встроенной опции прокси (в отличие от curl `--proxy`). Используйте переменные окружения или настройки системы.

```bash
# Через переменные окружения
export https_proxy=http://proxy.corp:8080
export http_proxy=http://proxy.corp:8080
http api.example.com/users

# Игнорирование прокси для внутренних хостов
export no_proxy=localhost,127.0.0.1,*.internal.corp
http internal.service.corp/health

# Отключение проверки сертификата (только для dev/test сред)
http --verify=no https://self-signed.internal/api

# Клиентский сертификат (mTLS)
http --cert=client.crt --cert-key=client.key https://mtls-required.internal/api

# Указание CA-сертификата
http --verify=/etc/ssl/certs/internal-ca.crt https://internal.service/api
```

> **Ограничение HTTPie:** В отличие от curl (`--proxy http://proxy:8080`), httpie не принимает прокси через аргументы командной строки. Используйте `http_proxy`/`https_proxy` переменные окружения или настройки системы.

### Сценарий 8. Скачивание файлов

HTTPie поддерживает скачивание файлов через флаг `--download`.

```bash
# Скачивание файла с определением имени из заголовка Content-Disposition
http --download https://example.com/files/report.pdf
# → Сохранит файл в текущей директории с именем из заголовка

# Скачивание с явным указанием имени файла
http --download --output report.pdf https://example.com/files/data

# Скачивание с перезаписью существующего файла
http --download --output report.pdf https://example.com/files/new-report.pdf

# Просмотр только заголовков (без скачивания контента)
http -h --download https://example.com/files/large.zip
```

### Сценарий 9. Использование в скриптах и CI/CD

HTTPie применим в скриптах, но требует внимания к кодам возврата и зависимостям.

```bash
# Проверка HTTP-кода (выход с ошибкой при 4xx/5xx)
http --check-status https://api.example.com/health
# → exit 4 при 4xx, exit 5 при 5xx

# Получение только тела ответа (для парсинга)
http -b api.example.com/version | jq -r '.version'
# → "1.2.3"

# Ограничение по таймауту (в секундах)
http --timeout=30 https://slow-api.example.com/data

# Сохранение ответа в переменную
STATUS=$(http -b -h api.example.com/health | head -1)
echo "Health status: $STATUS"

# Пакетное тестирование API-эндпоинтов
for endpoint in users posts comments; do
  http -b --check-status "api.example.com/$endpoint" >/dev/null && echo "$endpoint: OK" || echo "$endpoint: FAIL"
done

# Использование в CI/CD (GitHub Actions)
# - name: Verify API endpoint
#   run: |
#     pip install httpie
#     http --check-status --timeout=10 https://api.staging.example.com/health
```

> **Рекомендация для CI/CD:** В автоматизации предпочтительнее curl — он есть в каждом Docker-образе и не требует Python. HTTPie используйте только когда критична читаемость вывода (отладка, ручное тестирование).

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

### Конфигурация и переменные окружения

HTTPie хранит конфигурацию в стандартных директориях:

| Путь | Описание |
| :--- | :--- |
| `~/.config/httpie/` | Основная директория конфигурации |
| `~/.config/httpie/sessions/` | Файлы именованных сессий |
| `~/.config/httpie/config.json` | Глобальные настройки |

**Переменные окружения:**

| Переменная | Описание |
| :--- | :--- |
| `HTTPIE_CONFIG_DIR` | Переопределение директории конфигурации |
| `HTTPIE_DEFAULT_OPTIONS` | Параметры по умолчанию (JSON-строка) |
| `http_proxy` / `https_proxy` | Прокси-сервер (стандартные переменные) |
| `no_proxy` | Исключения из прокси |

```bash
# Переопределение директории конфигурации (для контейнеров)
export HTTPIE_CONFIG_DIR=/tmp/httpie-config

# Установка параметров по умолчанию
export HTTPIE_DEFAULT_OPTIONS='{"default_options": ["--timeout=30"]}'

# Использование в Docker-контейнере
docker run -v ./httpie-config:/root/.config/httpie httpie/httpie http api.example.com
```

### Коды возврата (Exit Codes)

| Код | Описание | Значение |
| :--- | :--- | :--- |
| **0** | Успех | Команда выполнена, сервер вернул 2xx/3xx. |
| **1** | Error | Ошибка в параметрах или конфигурации. |
| **2** | Timeout | Превышено время ожидания сети. |
| **4** | HTTP Error | Сервер вернул ошибку **4xx** или **5xx**. |

> **Важно для скриптов:** В отличие от curl (который по умолчанию возвращает 0 даже при 500), HTTPie корректно возвращает ненулевой код при ошибках HTTP. Это упрощает обработку ошибок в скриптах.

### Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `command not found: http` | HTTPie не установлен или не в PATH | `pip install httpie` или проверить `$PATH` |
| `ModuleNotFoundError: No module named 'httpie'` | Установка через pip в виртуальное окружение | Активировать окружение или `pip install httpie --user` |
| `ConnectionError: HTTPSConnectionPool` | Проблемы с прокси или сертификатом | Проверить `https_proxy`, `--verify=no` (dev only) |
| `TimeoutError: Read timed out` | Медленный сервер или сети | Увеличить `--timeout=60` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | Самоподписанный сертификат или внутренний CA | `--verify=no` (dev) или `--verify=/path/to/ca.crt` |
| `http: error: unrecognized arguments` | Неверный синтаксис команды | Проверить帮助 `http --help`, убрать лишние пробелы в URL |
| `Connection refused` | Сервис не запущен или неверный порт | Проверить `ss -tlnp`, статус сервиса |
| `HTTPError: 401 Unauthorized` | Ошибка аутентификации | Проверить токен/пароль, заголовок `Authorization` |
| `KeyboardInterrupt` при вводе пароля | Интерактивный ввод заблокирован | Использовать `--session` или переменные окружения |

### Граничные случаи

**Работа с большими payload:**

```bash
# HTTPie автоматически буферизует вывод. Для очень больших ответов
# используйте -b (body only) и pipe в файл:
http -b api.example.com/export > data.json

# Ограничение размера тела ответа (через timeout):
http --timeout=300 api.example.com/large-export > data.json
```

**Работа с не-JSON форматами:**

```bash
# Отправка XML
http --raw='<request><user>test</user></request>' POST api.example.com/xml \
  Content-Type:application/xml

# Отправка form-urlencoded (без --form)
http -f POST api.example.com/login username=admin password=secret
# → Content-Type: application/x-www-form-urlencoded

# Получение plain text
http -b api.example.com/plain-text
# → (без форматирования, raw текст)
```

**Управление куками вручную:**

```bash
# Просмотр всех кук из сессии
cat ~/.config/httpie/sessions/dev-env.json | jq .cookies

# Удаление сессии
rm ~/.config/httpie/sessions/dev-env.json

# Копирование сессии между машинами
scp user@host:~/.config/httpie/sessions/prod.json ~/.config/httpie/sessions/
```

### Рекомендации по безопасности

1.  **Защита секретов**: Не указывайте пароли в аргументе `-a username:password`. HTTPie предложит ввести пароль интерактивно, если указать только `-a username`.
2.  **Сессии**: Файлы сессий хранятся в открытом виде в директории конфигурации (обычно `~/.config/httpie/sessions/`). Ограничьте права доступа к этой директории.
3.  **HSTS**: При использовании команды `https` утилита будет следовать политикам безопасности сервера.
4.  **В CI/CD**: Не храните секреты в переменных окружения, видимых в логах. Используйте GitHub Secrets, GitLab CI Variables или Vault.

### Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)** — описание семантики методов.
- **[curl: универсальный инструмент](./curl.md)** — когда нужна максимальная переносимость и работа в сложных скриптах.
