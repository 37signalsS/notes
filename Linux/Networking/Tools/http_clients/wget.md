# Wget — надежное скачивание и зеркалирование

## Определения

**GNU Wget** — неинтерактивная утилита командной строки для загрузки файлов по протоколам HTTP, HTTPS и FTP. Ключевой особенностью является высокая отказоустойчивость: Wget спроектирован для работы в условиях медленных или нестабильных сетевых соединений, поддерживая автоматический перезапуск загрузки при обрыве связи.

**Ключевое отличие от curl:** Wget спроектирован для **загрузки файлов** (рекурсивное зеркалирование, возобновление, фоновый режим), тогда как curl — для **взаимодействия с API** (ручные HTTP-запросы, отладка, форматированный вывод). В DevOps-пайплайнах wget используется для скачивания бинарников, настройки окружений и healthcheck'ов в контейнерах, где curl недоступен (BusyBox, Alpine).

## Предварительные требования

### Установка

| Дистрибутив | Команда |
| :--- | :--- |
| **Debian/Ubuntu** | `apt-get install -y wget` |
| **RHEL/CentOS/Rocky** | `dnf install -y wget` |
| **Alpine** | `apk add --no-cache wget` (или `wget` уже есть в BusyBox) |
| **macOS** | `brew install wget` (Homebrew) |

> **BusyBox wget:** В минимальных контейнерах (Alpine, BusyBox) доступен урезанный wget без поддержки HTTPS (нет `--no-check-certificate`, `--ca-certificate`). Проверка: `wget --help 2>&1 | grep https`. Если https не поддерживается — установите полную версию или используйте curl.

### Проверка версии и поддерживаемых функций

```bash
# Версия
wget --version
# → GNU Wget 1.24.5 built on linux-gnu.
# → +https +ipv6 +gnutls +idn

# Важные флаги сборки (в строке "built on"):
# +https   — поддержка HTTPS (если отсутствует, wget не работает с TLS)
# +gnutls  — TLS-библиотека (может бытьopenssl)
# +ipv6    — поддержка IPv6
# +idn     — поддержка международных доменных имён

# Wget2 (если установлен)
wget2 --version
# → wget2 2.1.0
# → +https +http2 +gnutls +brotli +zstd
```

## Основные концепции

### Структура команды

```bash
wget [опции] [URL]
```

**Ключевые группы опций:**

- **Управление загрузкой:** `-O` (имя выходного файла), `-c` (продолжить прерванную загрузку), `-b` (переход в фоновый режим).
- **Рекурсивная загрузка (Зеркалирование):** `-r` (рекурсивно), `-l` (глубина вложенности), `-k` (преобразование ссылок для локального просмотра), `-p` (загрузка всех необходимых ресурсов страницы, таких как изображения и стили).
- **Фильтрация и ограничения:** `-A`/`-R` (белые/черные списки расширений), `--accept-regex` (фильтрация по регулярным выражениям), `--limit-rate` (ограничение скорости).
- **Синхронизация:** `-N` (проверять дату изменения файла и скачивать только если он новее локального).

### Сравнение Wget и Wget2

Wget2 является преемником оригинального Wget и предлагает современные возможности.

| Характеристика | Wget (v1.x) | Wget2 (v2.x) |
| :--- | :--- | :--- |
| **Многопоточность** | Отсутствует (один поток на файл) | Поддерживается (параллельная загрузка чанков) |
| **Протоколы** | HTTP/1.1, FTP | HTTP/2, HTTP/3 (QUIC), Zstandard |
| **Производительность** | Высокая для одиночных файлов | Экстремальная для больших объемов данных |
| **RSS/Atom** | Не поддерживается | Встроенная поддержка подписок |

---

## Практические сценарии

### Сценарий 1. Базовая загрузка и управление именами

```bash
# Загрузка файла с сохранением оригинального имени
wget https://example.com/software-v1.0.tar.gz
# → Сохранит как 'software-v1.0.tar.gz'

# Сохранение под конкретным именем
wget -O app.tar.gz https://example.com/v1.0/download
# → Сохранит как 'app.tar.gz'

# Использование имени из заголовка Content-Disposition
# Полезно для S3 и API, где в URL нет расширения
wget --content-disposition https://api.io/get?file_id=123
# → Сохранит как 'document.pdf' (на основании заголовка сервера)

# Продолжение загрузки (Resume)
wget -c https://mirror.iso.org/large_os.iso
# → # Продолжит с места разрыва
```

### Сценарий 2. Создание локального зеркала (Offline Copy)

```bash
# Полная копия сайта для автономного просмотра
# -r: рекурсивно
# -l inf: максимальная глубина
# -k: замена абсолютных ссылок на относительные локальные
# -p: загрузка всех картинок и CSS для корректного отображения
# -E: добавление расширения .html к файлам, если оно отсутствует
# -np: не подниматься в родительские каталоги (no-parent)
wget -r -l inf -k -p -E -np https://example.com/wiki/

# Инкрементальное обновление зеркала
# Скачивает только новые или измененные файлы (по таймстампу)
wget -r -N https://example.com/docs/
```

### Сценарий 3. Массовая загрузка и автоматизация

```bash
# Загрузка всех URL из текстового файла
wget -i list_of_urls.txt

# Загрузка всех PDF-файлов с сайта
wget -r -l 1 -A pdf https://example.com/reports/

# Проверка доступности (Spider mode)
# Не скачивает контент, только проверяет заголовки
wget --spider -q http://localhost:8080/health || exit 1
# → (exit code 0 при успехе, 8 при 404/500)
```

### Сценарий 4. Аутентификация и работа с формами

```bash
# Передача данных через POST (например, для авторизации)
wget --post-data 'user=admin&pass=secret' https://example.com/api/login

# Сохранение и загрузка Cookies
wget --save-cookies cookies.txt --post-data 'u=a&p=b' https://site.com/auth
wget --load-cookies cookies.txt https://site.com/private-data

# Использование .netrc для скрытия учетных данных из командной строки
# Файл ~/.netrc должен иметь права 600
wget --netrc https://private-repo.com/package.deb
```

### Сценарий 5. Диагностика и отладка

```bash
# Вывод в стандартный поток (stdout) для передачи в конвейер
wget -qO- https://api.ipify.org?format=json | jq .ip
# → "1.2.3.4"

# Подмена User-Agent для обхода блокировок
wget -U "Mozilla/5.0 (X11; Linux x86_64)" https://example.com

# Игнорирование ошибок SSL (только для тестирования в dev-среде)
wget --no-check-certificate https://self-signed.internal/config.yaml
```

### Сценарий 6. Healthcheck в Docker и Kubernetes

wget — стандартный инструмент для healthcheck'ов в контейнерах, поскольку он есть в BusyBox (Alpine, Debian-slim) и не требует установки curl.

**Dockerfile — healthcheck с wget:**

```dockerfile
# BusyBox wget (есть в Alpine "из коробки")
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q --spider http://localhost:8080/health || exit 1
# -q: тихий режим (без прогресса)
# --spider: не скачивать контент, только проверить доступность
# exit 1: вернуть код ошибки при недоступности (обязательно для статуса unhealthy)
```

**Dockerfile —.healthcheck с полной версией wget:**

```dockerfile
# Если установлена полная версияwget (не BusyBox)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1
# --no-verbose: компактный вывод (для docker inspect)
# --tries=1: одна попытка (быстрый таймаут)
```

**Docker Compose — healthcheck:**

```yaml
services:
  app:
    image: my-app:latest
    healthcheck:
      # Форма CMD (рекомендуется — без shell)
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    # Или через CMD-SHELL (если нужна shell-интерполяция)
    # test: ["CMD-SHELL", "wget -q --spider http://localhost:8080/health || exit 1"]
```

> **Разница CMD vs CMD-SHELL:** `CMD` передаёт аргументы напрямую (без shell). `CMD-SHELL` запускает через `/bin/sh -c`, что позволяет использовать `||`, переменные окружения и pipe. Для wget healthcheck рекомендуется `CMD` — это быстрее и не требует наличия shell.

**Kubernetes — init container с wget:**

```yaml
apiVersion: v1
kind: Pod
spec:
  initContainers:
  - name: wait-for-api
    image: busybox:1.36
    command: ['sh', '-c', 'wget -q --spider --timeout=5 http://api-server:8080/health || exit 1']
    # BusyBox wget не поддерживает --spider во всех версиях
    # Альтернатива: wget -q -O /dev/null http://api-server:8080/health
  containers:
  - name: app
    image: my-app:latest
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      initialDelaySeconds: 5
      periodSeconds: 10
    livenessProbe:
      httpGet:
        path: /health
        port: 8080
      initialDelaySeconds: 15
      periodSeconds: 20
```

**Валидация healthcheck изнутри контейнера:**

```bash
# Проверка доступности эндпоинта
kubectl exec -it my-pod -- wget -q --spider http://localhost:8080/health && echo "OK"
# → OK

# Если wget отсутствует — альтернатива
kubectl exec -it my-pod -- wget -q -O /dev/null http://localhost:8080/health

# Проверка через BusyBox (wget --spider может не поддерживаться)
kubectl exec -it my-pod -- wget -q -O /tmp/test http://localhost:8080/health && cat /tmp/test
```

### Сценарий 7. Работа через прокси-сервер

```bash
# Автоматическое использование переменных окружения
export https_proxy=http://proxy.corp:8080
export http_proxy=http://proxy.corp:8080
wget https://example.com/file.tar.gz

# Явное указание прокси
wget -e use_proxy=yes -e http_proxy=http://proxy.corp:8080 https://example.com/file.tar.gz

# Игнорирование прокси для внутренних хостов
export no_proxy=localhost,127.0.0.1,*.internal.corp
wget https://internal.service.corp/config.yaml
```

> **Ограничение wget:** В отличие от curl (`--proxy`), wget не имеет встроенной опции для явного указания прокси. Используйте переменные окружения или опцию `-e` для передачи команд `wget`'у.

### Сценарий 8. Верификация загрузок и целостность файлов

В DevOps-пайплайнах критично проверять целостность скачиваемых бинарников (SHA256, GPG).

```bash
# Скачивание файла + checksum
wget -q https://example.com/tool-v1.0-linux-amd64.tar.gz
wget -q https://example.com/tool-v1.0-linux-amd64.tar.gz.sha256

# Проверка checksum
sha256sum -c tool-v1.0-linux-amd64.tar.gz.sha256
# → tool-v1.0-linux-amd64.tar.gz: OK

# Скачивание + проверка GPG-подписи
wget -q https://example.com/tool-v1.0-linux-amd64.tar.gz
wget -q https://example.com/tool-v1.0-linux-amd64.tar.gz.asc
wget -q https://example.com/KEYS
gpg --import KEYS
gpg --verify tool-v1.0-linux-amd64.tar.gz.asc tool-v1.0-linux-amd64.tar.gz
# → gpg: Good signature from "Maintainer <maintainer@example.com>"
```

**Автоматизация в скрипте:**

```bash
#!/bin/bash
set -euo pipefail

VERSION="1.2.3"
BASE_URL="https://releases.example.com"
ARCHIVE="tool-${VERSION}-linux-amd64.tar.gz"

# Загрузка с повторами и проверкой
wget --tries=3 --waitretry=5 -q "${BASE_URL}/${ARCHIVE}" "${BASE_URL}/${ARCHIVE}.sha256"

if ! sha256sum -c "${ARCHIVE}.sha256" >/dev/null 2>&1; then
  echo "ERROR: Checksum verification failed for ${ARCHIVE}" >&2
  rm -f "${ARCHIVE}" "${ARCHIVE}.sha256"
  exit 1
fi

echo "Downloaded and verified: ${ARCHIVE}"
tar xzf "${ARCHIVE}"
```

### Сценарий 9. Автоматизация в cron-задачах

```bash
# Инкрементальное зеркалирование документации (ежедневно)
# -N: скачивать только файлы новее локальных
# -c: продолжение прерванных загрузок
# -q: тихий режим (для cron)
0 2 * * * wget -r -N -c -q --no-parent https://docs.internal.corp/api/ -P /var/cache/docs/

# Скачивание конфигурации при старте сервиса (systemd)
# /etc/systemd/system/app.service.d/reload.conf
# [Service]
# ExecStartPre=/usr/bin/wget -q -O /etc/app/config.yaml https://config.internal.corp/app/config.yaml
# ExecStartPre=/usr/bin/wget -q -O /etc/app/CA.crt https://config.internal.corp/ca.crt

# Загрузка обновлений с проверкой (Ansible-like)
#!/bin/bash
set -euo pipefail
wget --tries=3 --timeout=30 -q -O /tmp/update.tar.gz https://releases.internal.corp/latest.tar.gz
sha256sum -c /tmp/update.tar.gz.sha256 || { echo "Checksum failed"; exit 1; }
tar xzf /tmp/update.tar.gz -C /opt/app/
systemctl restart app
```

### Сценарий 10. Контроль скорости и этика зеркалирования

При работе с медленными или ограниченными каналами, а также при зеркалировании сторонних ресурсов необходимо контролировать нагрузку.

```bash
# Ограничение скорости до 1 МБ/с
wget --limit-rate=1m https://example.com/large-file.iso

# Пауза между запросами (этика зеркалирования)
# --wait: фиксированная пауза (секунды)
# --random-wait: случайная пауза от 0.5*W до 1.5*W
wget -r --wait=2 --random-wait https://example.com/docs/

# Комбинированный контроль
wget -r --limit-rate=500k --wait=1 --random-wait --no-parent https://example.com/docs/
# → Максимум 500 КБ/с, пауза 0.5-1.5 сек между запросами

# Проверка перед зеркалированием (сколько файлов будет скачано)
wget --spider -r -l 2 https://example.com/docs/ 2>&1 | grep -c "URL:" | head -1
# → Примерное количество файлов
```

---

## Дополнительная информация

### Коды возврата (Exit Codes)

| Код | Описание | Рекомендация |
| :--- | :--- | :--- |
| **0** | Успех | — |
| **1** | Generic error | Проверить вывод wget (убрать `-q`). |
| **2** | Parse error | Неверный синтаксис команды. Проверить опции. |
| **3** | IO error | Ошибка записи файла (нет места, права доступа). |
| **4** | Network failure | Проблемы с соединением (таймаут, DNS). Увеличить `--tries`, проверить сеть. |
| **5** | SSL/TLS failure | Ошибка проверки сертификата. Использовать `--no-check-certificate` (dev) или `--ca-certificate` (prod). |
| **6** | Auth failure | Ошибка аутентификации (401/403). Проверить `--user`/`--password` или `--netrc`. |
| **7** | Protocol error | Неверный URL или неподдерживаемый протокол. |
| **8** | Server error | Ошибка на стороне сервера (404, 500 и т.д.). Проверить URL и статус сервера. |

### Устранение неисправностей

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `SSL certificate problem: unable to get local issuer certificate` | Внутренний CA не входит в системный набор | `--ca-certificate=/path/to/ca.crt` или `--no-check-certificate` (dev only) |
| `ERROR: The certificate's owner does not match hostname` | Имя в сертификате не совпадает с URL | Проверить URL; для внутренних сервисов использовать `--no-check-certificate` |
| `Unable to establish SSL connection` | wget собран без поддержки HTTPS (+https отсутствует в `wget --version`) | Установить полную версию wget (`apt-get install wget`) вместо BusyBox |
| `Failed to connect` (exit 4) | Сервис не запущен, неверный порт, firewall | Проверить `ss -tlnp`, статус сервиса, iptables |
| `DNS lookup failed` (exit 4) | DNS-сервер недоступен или имя не существует | Проверить `/etc/resolv.conf`, `dig`, `nslookup` |
| `Too many redirects` | Циклический редирект на сервере | Добавить `--max-redirect=5` (по умолчанию 20) |
| `Cannot write to ... (No space left on device)` | Диск заполнен | Проверить `df -h`, очистить место |
| `Unable to parse attribute list` (XML/HTML) | Некорректный HTML при рекурсивной загрузке | Добавить `--no-remove-listing` или ограничить глубину `-l 3` |
| `wget --spider возвращает 0, но файл недоступен` | Сервер возвращает 200, но тело пустое или содержит ошибку | Использовать `wget -S -O /dev/null` для просмотра заголовков |

### Тонкая настройка сетевого взаимодействия

- **Повторы:** `--tries=10` — количество попыток скачивания при ошибках.
- **Таймаут:** `--timeout=30` — время ожидания ответа от сервера (в секундах).
- **Повторные попытки с задержкой:** `--waitretry=5` — увеличивать задержку между попытками (до `--tries`).
- **Этика зеркалирования:** `--wait=2 --random-wait` — паузы между запросами, чтобы не перегружать сервер и имитировать поведение человека.
- **Регулярные выражения:** `--accept-regex='.*_v2\..*'` — позволяет гибко фильтровать файлы при рекурсивной загрузке.
- **Keep-Alive:** По умолчанию wget поддерживает keep-alive (HTTP/1.1). Для HTTP/1.0 серверов: `--header="Connection: keep-alive"`.
- **Привязка к интерфейсу:** `--bind-address=192.168.1.100` — полезно на multi-homed серверах.

### Рекомендации по безопасности

1.  **Секреты:** Никогда не передавайте пароли через аргумент `--password`. Они попадают в историю команд и видны другим пользователям через `ps`. Используйте `--netrc` или переменные окружения.
2.  **Валидация SSL:** В рабочих скриптах всегда проверяйте сертификаты. Если сервер использует внутренний CA, укажите его явно: `--ca-certificate=/etc/ssl/certs/internal-ca.crt`.
3.  **HSTS:** При работе с HTTPS рекомендуется использовать `--hsts` для принудительного использования защищенного соединения, если сайт это поддерживает.
4.  **Рекурсивная загрузка:** Ограничивайте глубину (`-l`) и используйте `--no-parent` (`-np`), чтобы не скачать весь сервер. Всегда проверяйте количество файлов через `--spider -r` перед запуском.

### Граничные случаи

**Загрузка файлов с автоматическим определением имени:**

```bash
# wget определяет имя из URL или заголовка Content-Disposition
# Если URL содержит параметры (?key=value), имя файла будет некорректным
wget "https://api.example.com/download?file=report.pdf"
# → Сохранит как 'download?file=report.pdf' (некорректно)

# Решение: указать имя явно
wget -O report.pdf "https://api.example.com/download?file=report.pdf"
```

**Работа с файлами >4GB:**

```bash
# wget корректно работает с файлами >4GB (поддержка large file)
# Продолжение загрузки:
wget -c https://example.com/huge-file.iso
# → #续传使用 -c, автоматически определяет размер уже скачанного файла

# Проверка размера перед загрузкой (HEAD-запрос)
wget --spider -S https://example.com/huge-file.iso 2>&1 | grep "Content-Length"
# → Content-Length: 5368709120
```

**Рекурсивная загрузка с фильтрацией:**

```bash
# Только PDF-файлы с глубиной 2
wget -r -l 2 -A pdf https://example.com/reports/

# Исключение определённых каталогов
wget -r --reject-dir=/tmp,/old https://example.com/docs/

# Только файлы определённого размера (>1MB)
wget -r --accept-regex=".*" --reject-regex=".*" \
  --max-filesize=1048576 https://example.com/files/
```

### Связанные заметки

- **[Обзор HTTP-клиентов](./overview.md)** — сравнение curl, wget, httpie.
- **[Диагностика сети](../../network_diagnostics_tools.md)** — обзор смежных инструментов.
- **[curl: универсальный инструмент](./curl.md)** — основной инструмент для работы с API и отладки.
