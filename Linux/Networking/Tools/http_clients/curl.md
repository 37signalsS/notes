# cURL: Универсальный инструмент для передачи данных

## Определения

**cURL** (Client for URLs) — утилита командной строки для передачи данных по множеству протоколов (HTTP, HTTPS, FTP, SCP, SFTP, SMB, LDAP и др.). Стандарт де-факто для работы с API в скриптах и автоматизации.

## Базовые концепции

### 1. Структура команды

```bash
curl [опции] [URL]
```

**Основные группы опций:**

- **Запрос:** `-X`, `-H`, `-d`, `-F`
- **Ответ:** `-o`, `-O`, `-s`, `-v`
- **Безопасность:** `-u`, `-k`, `--cert`, `--key`
- **Таймауты:** `--connect-timeout`, `--max-time`, `--speed-time`

### 2. Поддерживаемые протоколы

| Протокол | Описание |
| :--- | :--- |
| **HTTP/HTTPS** | Веб-запросы (основное использование) |
| **FTP/FTPS** | Передача файлов |
| **SCP/SFTP** | Безопасная передача через SSH |
| **SMB** | Доступ к ресурсам Windows |
| **LDAP** | Работа с каталогами |
| **MQTT** | IoT-протокол |
| **POP3/IMAP/SMTP** | Почтовые протоколы |

---

## Практические сценарии

### Сценарий 1: Безопасная работа в скриптах

```bash
# -f (--fail): завершиться с ошибкой при HTTP 4xx/5xx
# -s (--silent): подавить индикатор прогресса
# -S (--show-error): показать ошибку при использовании -s
curl -fsS https://api.example.com/health

# С таймаутами для CI/CD
curl -f --max-time 10 --connect-timeout 5 https://api.example.com/health
```

> **Важно:** Без `-f` curl вернёт успех (код 0) даже при HTTP 500.

### Сценарий 2: Работа с JSON API

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

# PUT/PATCH
curl -X PUT \
     -H 'Content-Type: application/json' \
     -d '{"id":1,"name":"Jane"}' \
     https://api.example.com/users/1

# DELETE
curl -X DELETE https://api.example.com/users/1
```

### Сценарий 3: Отправка файлов и форм

```bash
# multipart/form-data (загрузка файла)
curl -F 'user=John' \
     -F 'avatar=@/path/to/photo.jpg' \
     https://api.example.com/upload

# "Сырые" бинарные данные
curl --data-binary @archive.zip \
     https://api.example.com/upload

# Несколько файлов
curl -F 'files=@file1.txt' \
     -F 'files=@file2.txt' \
     https://api.example.com/upload
```

### Сценарий 4: Работа с cookies и сессиями

```bash
# Сохранить cookies в файл
curl -c cookies.txt https://example.com/login

# Загрузить cookies из файла
curl -b cookies.txt https://example.com/profile

# Автоматическое управление (чтение + запись)
curl -b cookies.txt -c cookies.txt https://example.com/api
```

### Сценарий 5: Аутентификация

```bash
# Basic auth
curl -u user:password https://api.example.com/protected

# Digest auth
curl --digest -u user:password https://api.example.com/protected

# Bearer token
curl -H 'Authorization: Bearer <token>' https://api.example.com/api/resource

# Через файл .netrc (автоматическая Basic auth)
# ~/.netrc: machine api.example.com login user password pass
curl --netrc https://api.example.com/protected
```

### Сценарий 6: Отладка и диагностика

```bash
# Подробная информация о соединении
curl -v https://example.com

# Только заголовки запроса и ответа
curl -I https://example.com

# Полный дамп обмена данными (включая TLS)
curl --trace trace.log https://example.com

# Вывод временных метрик (DNS, TCP, TLS, сервер)
curl -o /dev/null -s -w \
  "DNS: %{time_namelookup}s\n\
   TCP: %{time_connect}s\n\
   TLS: %{time_appconnect}s\n\
   Server: %{time_starttransfer}s\n\
   Total: %{time_total}s\n" \
  https://example.com
```

> Для детальной диагностики см. **[curl_network_diagnostics.md](../../../Diagnostics/Networking/curl_network_diagnostics.md)**.

### Сценарий 7: Определение публичного IP

```bash
curl -s ifconfig.me
curl -s icanhazip.com
curl -s ipinfo.io/ip
curl 2ip.ru
```

### Сценарий 8: Обход DNS и тестирование локальных настроек

```bash
# Запрос к IP с указанием домена для SNI и Host
curl --resolve example.com:443:93.184.216.34 https://example.com

# Тестирование локального хоста
curl --resolve site1.local:80:192.168.77.11 http://site1.local
```

### Сценарий 9: Работа с большими файлами

```bash
# Продолжение прерванной загрузки
curl -C - -O https://example.com/large-file.zip

# Ограничение скорости скачивания (в байтах/сек)
curl --limit-rate 100K -O https://example.com/file.zip

# Скачивание с фоном (через &)
curl -O https://example.com/file.zip &
```

### Сценарий 10: Интеграция с jq для JSON

```bash
# Форматированный вывод JSON
curl https://api.example.com/users | jq .

# Выборка конкретных полей
curl https://api.example.com/users | jq '.[].name'

# Фильтрация
curl https://api.example.com/users | jq '.[] | select(.age > 25)'
```

---

## Дополнительная информация

### 1. Таймауты и зависания

**Проблема:** curl может "зависнуть" без явных таймаутов, особенно в CI/CD и healthcheck'ах.

**Решение:**

```bash
# Минимальная безопасная конфигурация
curl --max-time 10 --connect-timeout 5 https://example.com

# Продвинутая настройка
curl --connect-timeout 5 \
     --speed-time 10 \
     --speed-limit 100 \
     https://example.com
```

| Опция | Описание |
| :--- | :--- |
| `--connect-timeout <sec>` | Макс. время на установку TCP-соединения |
| `--max-time <sec>` | Макс. время всей операции |
| `--speed-time <sec>` + `--speed-limit <bytes>` | Прервать, если скорость < лимита в течение N сек |

### 2. Игнорирование SSL-ошибок (`-k`, `--insecure`)

```bash
curl -k https://self-signed.example.com
```

> **Предупреждение:** Используйте только в тестовой среде. В продакшене это создаёт уязвимость для MITM-атак.

### 3. Подмена User-Agent

```bash
curl -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36' \
     https://example.com
```

### 4. Коды возврата

| Код | Описание |
| :--- | :--- |
| **0** | Успех |
| **1** | Неподдерживаемый протокол |
| **2** | Ошибка инициализации |
| **6** | Не удалось разрешить хост |
| **7** | Не удалось подключиться к хосту |
| **22** | HTTP-ошибка (4xx/5xx, требуется `-f`) |
| **28** | Превышен таймаут |

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie
- **[Диагностика задержек curl](../../../Diagnostics/Networking/curl_network_diagnostics.md)**
- **[Инструменты диагностики сети](../network_diagnostics_tools.md)**
