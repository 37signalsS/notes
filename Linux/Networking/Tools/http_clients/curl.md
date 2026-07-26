# cURL — универсальный инструмент для передачи данных

> **Надёжность: 10/10** (Официальная документация + практический опыт)
> **Актуальность:** Июль 2024 (проверено для curl 8.x)

## Определения

**cURL** (Client for URLs) — утилита командной строки для передачи данных по множеству протоколов (HTTP, HTTPS, FTP, SCP, SFTP, SMB, LDAP и др.). Стандарт де-факто для работы с API (Application Programming Interface) в скриптах и автоматизации.

## Основные концепции

### 1. Структура команды

```bash
curl [опции] [URL]
```

**Основные группы опций:**

- **Запрос:** `-X` (метод), `-H` (заголовок), `-d` (данные), `-F` (форма), `--json` (современный JSON-запрос)
- **Ответ:** `-o` (сохранить в файл), `-O` (имя из URL), `-s` (тихий режим), `-v` (подробно)
- **Безопасность:** `-u` (логин:пароль), `-k` (игнорировать SSL), `--cert`, `--key`
- **Таймауты:** `--connect-timeout`, `--max-time`, `--speed-time`
- **Производительность:** `-Z` (параллельные загрузки)

### 2. Поддерживаемые протоколы

| Протокол | Описание |
| :--- | :--- |
| **HTTP/HTTPS** | Веб-запросы (основное использование), включая HTTP/2 и HTTP/3 |
| **FTP/FTPS** | Передача файлов по классическому протоколу |
| **SCP/SFTP** | Безопасная передача через SSH (Secure Shell) |
| **SMB** | Доступ к файловым ресурсам Windows |
| **LDAP** | Взаимодействие со службами каталогов |
| **MQTT** | Протокол для интернета вещей (IoT) |
| **POP3/IMAP/SMTP** | Протоколы работы с электронной почтой |

---

## Практические сценарии

### Сценарий 1: Безопасная работа в скриптах

```bash
# -f (--fail): завершиться с ошибкой при HTTP 4xx/5xx
# -s (--silent): подавить индикатор прогресса
# -S (--show-error): показать ошибку при использовании -s
curl -fsS https://api.example.com/health
# → (пустой вывод при успехе, ошибка при 4xx/5xx)

# С таймаутами для CI/CD (Continuous Integration / Continuous Deployment)
curl -f --max-time 10 --connect-timeout 5 https://api.example.com/health
```

> **Важно:** Без `-f` curl вернёт код выхода 0 даже при получении HTTP 500, что может привести к ложноположительным результатам в пайплайнах.

### Сценарий 2: Работа с JSON API

**Современный способ (curl 7.82.0+):**
Опция `--json` автоматически добавляет заголовки `Content-Type: application/json` и `Accept: application/json`.

```bash
# POST с JSON данными
curl --json '{"name":"John","age":30}' https://api.example.com/users
```

**Классический способ:**
```bash
# GET с заголовками
curl -H 'Accept: application/json' \
     -H 'Authorization: Bearer <token>' \
     https://api.example.com/users

# POST с JSON
curl -X POST \
     -H 'Content-Type: application/json' \
     -d '{"name":"John","age":30}' \
     https://api.example.com/users
# → { "id": 123, "status": "created" }

# PUT/PATCH (полное или частичное обновление)
curl -X PUT \
     -H 'Content-Type: application/json' \
     -d '{"id":1,"name":"Jane"}' \
     https://api.example.com/users/1

# DELETE (удаление ресурса)
curl -X DELETE https://api.example.com/users/1
# → HTTP/1.1 204 No Content
```

### Сценарий 3: Отправка файлов и форм

```bash
# multipart/form-data (загрузка файла через форму)
curl -F 'user=John' \
     -F 'avatar=@/path/to/photo.jpg' \
     https://api.example.com/upload

# "Сырые" бинарные данные
curl --data-binary @archive.zip \
     https://api.example.com/upload

# Загрузка нескольких файлов одновременно
curl -F 'files=@file1.txt' \
     -F 'files=@file2.txt' \
     https://api.example.com/upload
```

### Сценарий 4: Работа с cookies и сессиями

```bash
# Сохранить полученные cookies в файл
curl -c cookies.txt https://example.com/login

# Загрузить cookies из файла для запроса
curl -b cookies.txt https://example.com/profile

# Автоматическое управление (чтение из файла и запись обновлений)
curl -b cookies.txt -c cookies.txt https://example.com/api
```

### Сценарий 5: Методы аутентификации

```bash
# Базовая аутентификация (Basic Auth)
curl -u user:password https://api.example.com/protected

# Digest аутентификация
curl --digest -u user:password https://api.example.com/protected

# Bearer токен (OAuth2 / JWT)
curl -H 'Authorization: Bearer <token>' https://api.example.com/api/resource

# Использование файла .netrc для автоматической аутентификации
# Файл ~/.netrc должен содержать: machine api.example.com login user password pass
curl --netrc https://api.example.com/protected
```

### Сценарий 6: Отладка и диагностика

```bash
# Подробная информация о TLS-рукопожатии и заголовках
curl -v https://example.com
# → * Connected to example.com (93.184.216.34) port 443 ...

# Получение только заголовков ответа
curl -I https://example.com
# → HTTP/1.1 200 OK ...

# Полный дамп обмена данными в текстовый файл
curl --trace-ascii trace.log https://example.com

# Вывод временных метрик (DNS, TCP, TLS, время до первого байта)
curl -o /dev/null -s -w \
  "DNS: %{time_namelookup}s\n\
   TCP: %{time_connect}s\n\
   TLS: %{time_appconnect}s\n\
   Server: %{time_starttransfer}s\n\
   Total: %{time_total}s\n" \
  https://example.com
# → DNS: 0.001s ... Total: 0.050s
```

> Для глубокой диагностики производительности см. **[curl_network_diagnostics.md](../../../Diagnostics/Networking/curl_network_diagnostics.md)**.

### Сценарий 7: Определение публичного IP-адреса

```bash
curl -s ifconfig.me
# → 93.184.216.34

curl -s icanhazip.com
curl -s ipinfo.io/ip
```

### Сценарий 8: Обход DNS и тестирование через SNI

```bash
# Принудительное сопоставление домена и IP (удобно для тестирования конкретного сервера за балансировщиком)
curl --resolve example.com:443:93.184.216.34 https://example.com

# Тестирование локальной конфигурации без правки /etc/hosts
curl --resolve site1.local:80:127.0.0.1 http://site1.local
```

### Сценарий 9: Работа с большими файлами и пропускной способностью

```bash
# Продолжение прерванной загрузки (Resume)
curl -C - -O https://example.com/large-file.zip

# Ограничение скорости скачивания (например, 100 КБ/с)
curl --limit-rate 100K -O https://example.com/file.zip

# Параллельная загрузка нескольких файлов (curl 7.66.0+)
curl -Z -O https://host1.com/a.zip -O https://host2.com/b.zip
```

### Сценарий 10: Обработка JSON через jq

```bash
# Красивый вывод (Pretty print)
curl -s https://api.example.com/users | jq .

# Выборка значений по ключу
curl -s https://api.example.com/users | jq '.[].name'

# Фильтрация объектов по условию
curl -s https://api.example.com/users | jq '.[] | select(.age > 25)'
```

### Сценарий 11: Проверка версий протокола (HTTP/2 и HTTP/3)

```bash
# Принудительное использование HTTP/2
curl -I --http2 https://example.com/

# Проверка поддержки HTTP/3 (требуется поддержка QUIC в сборке curl)
curl -I --http3 https://example.com/
```

---

## Дополнительная информация

### 1. Таймауты и предотвращение зависаний

**Проблема:** По умолчанию curl может бесконечно ждать ответа, что критично для CI/CD-пайплайнов и систем мониторинга.

**Решение:**

```bash
# Безопасный набор опций
curl --max-time 10 --connect-timeout 5 https://example.com

# Умный таймаут (прервать, если скорость < 100 байт/с в течение 10 секунд)
curl --connect-timeout 5 \
     --speed-time 10 \
     --speed-limit 100 \
     https://example.com
```

| Опция | Описание |
| :--- | :--- |
| `--connect-timeout <sec>` | Максимальное время на установку соединения |
| `--max-time <sec>` | Общее ограничение времени на всю операцию |
| `--speed-time` + `--speed-limit` | Логика прерывания при низкой скорости |

### 2. Игнорирование ошибок SSL (-k, --insecure)

```bash
curl -k https://self-signed.example.com
```

> **Предупреждение:** Использование `-k` отключает проверку цепочки сертификатов, что делает соединение уязвимым для атак Man-in-the-Middle (MITM). Используйте только в изолированных тестовых средах.

### 3. Подмена User-Agent

Используется для имитации запросов от различных браузеров или для обхода ограничений на стороне сервера.

```bash
curl -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' \
     https://example.com
```

### 4. Основные коды возврата (Exit Codes)

| Код | Описание |
| :--- | :--- |
| **0** | Успешное выполнение |
| **1** | Указан неподдерживаемый протокол |
| **6** | Не удалось разрешить DNS-имя хоста |
| **7** | Ошибка подключения к хосту (Connection refused) |
| **22** | HTTP-ошибка (требуется `-f` для возврата этого кода при 4xx/5xx) |
| **28** | Тайм-аут операции (превышено `--max-time`) |
| **35** | Ошибка при TLS/SSL рукопожатии |

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie
- **[Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md)**
- **[Инструменты диагностики сети](../../network_diagnostics_tools.md)**
- **[Методы HTTP](../../../../Networking/Protocols/HTTP/http_methods.md)**
