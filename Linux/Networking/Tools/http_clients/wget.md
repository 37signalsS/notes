# Wget — надежное скачивание и зеркалирование

## Определения

**GNU Wget** — утилита командной строки для надежного скачивания файлов и создания локальных зеркал веб-сайтов. Поддерживает протоколы HTTP, HTTPS и FTP. Основное преимущество — высокая устойчивость к нестабильным сетевым соединениям: Wget может автоматически продолжать загрузку после обрыва связи.

## Основные концепции

### 1. Структура команды

```bash
wget [опции] [URL]
```

**Основные группы опций:**

- **Загрузка:** `-O` (имя выходного файла), `-c` (продолжить загрузку), `-b` (работа в фоне).
- **Рекурсия:** `-r` (рекурсивно), `-l` (глубина), `-k` (преобразовать ссылки), `-p` (все ресурсы страницы).
- **Аутентификация:** `--user`, `--password`, `--load-cookies`, `--save-cookies`.
- **Сеть:** `--tries` (попытки), `--timeout`, `--limit-rate` (ограничение скорости).

### 2. Сравнение Wget и Wget2

Wget2 — это современный наследник Wget, разработанный с нуля для работы в многопоточном режиме.

| Характеристика | Wget (v1.x) | Wget2 (v2.x) |
| :--- | :--- | :--- |
| **Многопоточность** | Нет (последовательно) | Да (параллельная загрузка чанков) |
| **HTTP/2 и HTTP/3** | Только HTTP/1.1 | Поддержка HTTP/2 и HTTP/3 |
| **Производительность** | Стандартная | Значительно быстрее на больших файлах |
| **Совместимость** | Полная | Высокая, но некоторые флаги отличаются |

---

## Практические сценарии

### Сценарий 1. Базовая загрузка и управление файлами

```bash
# Простая загрузка файла в текущую директорию
wget https://example.com/file.zip

# Загрузка с переименованием (имя из URL игнорируется)
wget -O production_backup.zip https://example.com/backup_2024.zip

# Использование имени файла из заголовка Content-Disposition (важно для API/S3)
wget --content-disposition https://example.com/download?id=123

# Продолжение прерванной загрузки (Resume)
wget -c https://example.com/large-iso-image.iso

# Работа в фоновом режиме (логи записываются в wget-log)
wget -b https://example.com/archive.tar.gz
```

### Сценарий 2. Создание зеркала сайта (Offline Copy)

```bash
# Полная копия сайта для локального просмотра
# -r: рекурсивно
# -l inf: бесконечная глубина
# -k: замена ссылок на локальные (./path/to/file)
# -p: загрузка изображений/стилей для корректного рендеринга
# -np: не подниматься выше родительской директории
wget -r -l inf -k -p -np --adjust-extension https://example.com/docs/

# Ограничение нагрузки на сервер (этичное зеркалирование)
wget -r --limit-rate=200k --wait=2 --random-wait https://example.com
```

### Сценарий 3. Массовая автоматизация и CI/CD

```bash
# Загрузка списка URL из файла
wget -i download_list.txt

# Использование в Docker Healthcheck (тихий режим, проверка статуса)
wget --spider -q http://localhost:8080/health || exit 1

# Повторные попытки при ошибках сервера (5xx)
# Полезно для нестабильных API в пайплайнах
wget --tries=10 --retry-on-http-error=503,504 https://api.example.com/data
```

### Сценарий 4. Аутентификация и Cookies

```bash
# Базовая аутентификация
wget --user=devops --password=secret https://repo.example.com/file.rpm

# Работа с сессионными cookies
# 1. Сначала логинимся и сохраняем cookies
wget --post-data 'user=a&pass=b' --save-cookies auth.txt https://example.com/login
# 2. Используем их для доступа к закрытым данным
wget --load-cookies auth.txt https://example.com/dashboard

# Использование .netrc для безопасности (не светить пароль в истории команд)
# ~/.netrc: machine repo.example.com login devops password secret
wget --netrc https://repo.example.com/file.rpm
```

### Сценарий 5. Диагностика и обход ограничений

```bash
# Проверка существования файла без загрузки
wget --spider https://example.com/huge-file.zip
# → Remote file exists.

# Подмена User-Agent (для сайтов, блокирующих wget)
wget -U "Mozilla/5.0 (Windows NT 10.0; rv:100.0) Gecko/20100101 Firefox/100.0" https://example.com

# Игнорирование ошибок SSL (для self-signed сертификатов в dev-среде)
wget --no-check-certificate https://internal-dev.local/config.yaml

# Поддержка HSTS (HTTP Strict Transport Security)
wget --hsts --hsts-file=~/.wget-hsts https://example.com
```

---

## Дополнительная информация

### 1. Коды возврата (Exit Codes)

| Код | Описание |
| :--- | :--- |
| **0** | Успех |
| **1** | Общая ошибка |
| **4** | Ошибка сети (Network failure) |
| **5** | Ошибка SSL/TLS |
| **6** | Ошибка аутентификации (401/403) |
| **8** | Сервер вернул ошибку (404, 500 и т.д.) |

### 2. Вывод в стандартный поток (stdout)

Для передачи данных в конвейер (например, для `jq` или `grep`) используйте `-O -`:

```bash
# Тихая загрузка JSON и его обработка
wget -qO- https://api.ipify.org?format=json | jq .ip
```

### 3. Работа с Metalink

Wget поддерживает Metalink для автоматического выбора лучшего зеркала и проверки контрольных сумм:

```bash
wget --metalink=distribution.metalink
```

### 4. Рекомендации по безопасности

1.  **Не передавайте пароли через флаги:** Используйте `--netrc` или переменные окружения, так как параметры командной строки видны в списке процессов (`ps aux`).
2.  **Проверка сертификатов:** Старайтесь не использовать `--no-check-certificate` в продакшене. Если сертификат самоподписанный, лучше использовать `--ca-certificate=/path/to/cert.crt`.

### 5. Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Диагностика сети](../../network_diagnostics_tools.md)** — общие инструменты.
- **[curl: универсальный инструмент](./curl.md)** — основной CLI-клиент для API.
