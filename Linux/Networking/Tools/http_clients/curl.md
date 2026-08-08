# cURL — универсальный инструмент для передачи данных

## Определения

**cURL** (Client for URLs) — мощная утилита командной строки и кроссплатформенная библиотека (libcurl) для передачи данных с использованием синтаксиса URL. Поддерживает более 20 протоколов, включая HTTP(S), FTP, SCP, SFTP, SMB, LDAP, MQTT и другие. Является промышленным стандартом для взаимодействия с API, автоматизации задач (CI/CD) и низкоуровневой диагностики сетевых сервисов.

## Основные концепции

### Структура команды

```bash
curl [опции] [URL]
```

**Основные группы опций:**

- **Запрос:** `-X` (явное указание метода), `-H` (добавление заголовка), `-d` (отправка данных), `-F` (multipart-форма), `--json` (автоматический JSON-запрос).
- **Ответ:** `-o` (сохранить в файл), `-O` (сохранить с именем из URL), `-s` (тихий режим), `-i` (вывод заголовков ответа), `-v` (подробный лог).
- **Безопасность:** `-u` (аутентификация), `-k` (игнорировать ошибки SSL), `--cert`/`--key` (клиентские сертификаты).
- **Таймауты и повторы:** `--connect-timeout`, `--max-time`, `--retry`, `--retry-delay`.
- **Производительность:** `-Z` (параллельная загрузка нескольких ресурсов).

### Поддерживаемые протоколы

| Протокол | Описание и применение |
| :--- | :--- |
| **HTTP/HTTPS** | Работа с веб-сервисами, поддержка HTTP/1.1, HTTP/2 и HTTP/3 (QUIC). |
| **gRPC** | Поддерживается через HTTP/2 (требуется специфическая передача заголовков). |
| **FTP/FTPS** | Классическая передача файлов, включая защищенные TLS-версии. |
| **SCP/SFTP** | Безопасная передача данных поверх SSH. |
| **SMB/CIFS** | Доступ к файловым ресурсам Windows. |
| **LDAP(S)** | Взаимодействие со службами каталогов. |
| **MQTT** | Протокол для интернета вещей (IoT). |
| **SMTP/POP3/IMAP** | Протоколы работы с электронной почтой. |

---

## Практические сценарии

### Сценарий 1: Безопасная работа в скриптах и CI/CD

В скриптах крайне важно обрабатывать ошибки сервера и ограничивать время ожидания.

```bash
# -f (--fail): возвращает код 22 при HTTP 4xx/5xx (без него curl вернет 0)
# -s (--silent): подавляет вывод прогресса (мусор в логах CI)
# -S (--show-error): показывает ошибку даже в тихом режиме
curl -fsS https://api.example.com/health || exit 1

# Настройка надежных таймаутов
curl -f --max-time 10 --connect-timeout 5 https://api.example.com/api
```

### Сценарий 2: Работа с JSON API

**Современный способ (curl 7.82.0+):**
Опция `--json` автоматически добавляет заголовки `Content-Type: application/json` и `Accept: application/json`, а также устанавливает метод POST (если не указано иное).

```bash
# POST с JSON данными
curl --json '{"user_id":42, "status":"active"}' https://api.example.com/v1/update
```

**Классический способ:**
```bash
# GET с аутентификацией и заголовком
curl -H 'Accept: application/json' -H "Authorization: Bearer $TOKEN" https://api.example.com/data

# POST с данными из строки
curl -X POST -H 'Content-Type: application/json' -d '{"name":"test"}' https://api.example.com/resource

# PATCH (частичное обновление)
curl -X PATCH -H 'Content-Type: application/merge-patch+json' -d '{"active":false}' https://api.example.com/resource/1
```

### Сценарий 3: Передача файлов и форм

```bash
# multipart/form-data (загрузка файла через форму)
curl -F 'user=John' -F 'avatar=@/path/to/photo.jpg' https://api.example.com/upload

# Отправка "сырых" бинарных данных (например, для S3 или объектных хранилищ)
curl --data-binary @archive.zip https://api.example.com/storage

# Загрузка нескольких файлов одновременно
curl -F 'files=@f1.txt' -F 'files=@f2.txt' https://api.example.com/upload
```

### Сценарий 4: Работа с Cookies и сессиями

```bash
# Сохранить полученные cookies в файл (cookie jar)
curl -c cookies.txt https://example.com/login

# Загрузить cookies из файла для выполнения авторизованного запроса
curl -b cookies.txt https://example.com/profile

# Совместное использование (чтение и запись обновлений)
curl -b cookies.txt -c cookies.txt https://example.com/api
```

### Сценарий 5: Методы аутентификации

```bash
# Базовая аутентификация (Basic Auth)
curl -u user:password https://api.example.com/protected

# Bearer токен (OAuth2 / JWT)
curl -H "Authorization: Bearer $TOKEN" https://api.example.com/api/resource

# Использование .netrc (наиболее безопасно для паролей)
# Файл ~/.netrc должен иметь права 600 и содержать:
# machine api.example.com login user password pass
curl --netrc https://api.example.com/protected
```

### Сценарий 6: Отладка и диагностика

```bash
# Подробный лог TLS-рукопожатия и заголовков
curl -v https://example.com

# Получение только заголовков (HEAD запрос)
curl -I https://example.com

# Полный дамп обмена в текстовом формате
curl --trace-ascii debug.log https://example.com

# Форматированный вывод временных метрик
curl -o /dev/null -s -w \
  "DNS: %{time_namelookup}s\n\
   TCP: %{time_connect}s\n\
   TLS: %{time_appconnect}s\n\
   Server: %{time_starttransfer}s\n\
   Total: %{time_total}s\n" \
  https://example.com
```
*Для глубокого анализа см. [Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md).*

### Сценарий 7: Определение публичного IP-адреса

```bash
# Быстрая проверка внешнего IP
curl -s ifconfig.me
curl -s icanhazip.com
curl -s ipinfo.io/ip
```

### Сценарий 8: Обход DNS и тестирование через SNI

```bash
# Принудительное сопоставление домена и IP (тестирование ноды за балансировщиком)
curl --resolve example.com:443:93.184.216.34 https://example.com

# Тестирование локальных виртуальных хостов
curl --resolve site.local:80:127.0.0.1 http://site.local
```

### Сценарий 9: Работа с большими файлами и повторы

```bash
# Продолжение прерванной загрузки (Resume)
curl -C - -O https://example.com/huge-file.zip

# Ограничение скорости (шейпинг) до 500 КБ/с
curl --limit-rate 500K -O https://example.com/file.zip

# Логика повторов при сетевых сбоях
# --retry-connrefused: повторять даже если соединение отклонено
curl --retry 5 --retry-delay 2 --retry-connrefused https://api.example.com/unstable
```

### Сценарий 10: Обработка JSON через jq

Интеграция curl и jq позволяет строить мощные конвейеры обработки данных.

```bash
# Красивое форматирование JSON
curl -s https://api.github.com/repos/curl/curl | jq .

# Выборка конкретных полей
curl -s https://api.example.com/users | jq '.[].email'

# Сложная фильтрация
curl -s https://api.example.com/orders | jq '.[] | select(.status == "failed") | .id'
```

### Сценарий 11: Проверка версий протокола (HTTP/2 и HTTP/3)

```bash
# Проверка поддержки HTTP/2
curl -I --http2 https://example.com/

# Проверка HTTP/3 (требуется поддержка QUIC в сборке curl)
curl -I --http3 https://example.com/
```

---

## Дополнительная информация

### 1. Конфигурация через .curlrc

Чтобы не указывать повторяющиеся опции (например, таймауты или User-Agent), используйте файл `~/.curlrc`.

```ini
# Пример ~/.curlrc
--connect-timeout 10
--max-time 30
--fail
--show-error
--user-agent "SRE-Monitoring-Bot/1.2"
```

### 2. Безопасность и передача секретов

**Никогда не передавайте токены в строке команды**, так как они сохраняются в `history` и видны в списке процессов (`ps`).

- **Безопасно:** Чтение данных из stdin или файла:
  ```bash
  curl -X POST -H "Authorization: Bearer $(cat token.txt)" -d @payload.json https://api.io
  ```
- **HSTS:** Начиная с версии 7.74.0, curl поддерживает кэширование политик HSTS (`--hsts hsts-cache.txt`).

### 3. Таймауты и предотвращение зависаний

| Опция | Описание |
| :--- | :--- |
| `--connect-timeout <sec>` | Время на установку TCP-соединения. |
| `--max-time <sec>` | Общее время на всю операцию (включая передачу данных). |
| `--speed-time` / `--speed-limit` | Прервать, если скорость ниже лимита в течение N секунд. |

### 4. Основные коды возврата (Exit Codes)

| Код | Значение | Рекомендация |
| :--- | :--- | :--- |
| **0** | Успех | — |
| **6** | Could not resolve host | Проверить DNS или наличие интернета. |
| **7** | Failed to connect | Проверить порт, firewall или статус сервиса. |
| **22** | HTTP page not retrieved | Возникает при `-f`, если сервер вернул статус >= 400. |
| **28** | Operation timeout | Превышен `--max-time`. Увеличить лимит или проверить задержки. |
| **35** | SSL/TLS connect error | Ошибка рукопожатия. Проверить версии TLS или сертификаты. |
| **52** | Empty reply from server | Сервер закрыл соединение без данных (возможен сбой приложения). |

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md)** — глубокий анализ производительности.
- **[Инструменты диагностики сети](../../network_diagnostics_tools.md)** — контекст применения в траблшутинге.
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)** — описание семантики методов.
