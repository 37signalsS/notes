# Установка и базовая настройка Nginx

## Определения

**Nginx** — это высокопроизводительный веб-сервер и обратный прокси-сервер, используемый для обслуживания веб-контента, **[балансировки нагрузки](../Proxy/Load_Balancing/overview_concepts.md)**, кэширования и терминации SSL.

**Виртуальный хост (Server Block)** — блок конфигурации, описывающий параметры обработки запросов для конкретного домена или IP-адреса.
- **Аналогия:** Представьте веб-сервер как здание, внутри которого находятся офисы разных компаний (сайты). Одно здание может обслуживать множество арендаторов.
- **Логика выбора:** Nginx сопоставляет заголовок **`Host`** в HTTP-запросе клиента с директивой `server_name` в конфигурации.
- **Fallback (Отказоустойчивость):** Если Nginx не находит точного совпадения `server_name`, он использует первый доступный блок конфигурации в алфавитном порядке имен файлов (обычно это `default`). Поэтому важно правильно настраивать "дефолтный" сервер.

**Mainline vs Stable** — Nginx предлагает две ветки:
- **Mainline:** содержит последние функции и исправления ошибок (рекомендуется для большинства современных инсталляций).
- **Stable:** получает только критические исправления безопасности.

> Для более глубокого обзора архитектуры и ключевых концепций обратитесь к файлу **[Обзор Nginx](./nginx_overview.md)**.

---

## Базовые концепции

### Архитектура и процессная модель

Nginx использует событийно-ориентированную (event-driven) архитектуру для эффективной обработки тысяч одновременных соединений в неблокирующем режиме.

**Компоненты:**
1. **Мастер-процесс (Master Process):** Читает конфигурацию, управляет жизненным циклом рабочих процессов и обрабатывает сигналы управления. Не обрабатывает клиентские запросы напрямую.
2. **Рабочие процессы (Worker Processes):** Выполняют фактическую обработку запросов в event loop. Количество управляется директивой `worker_processes`.

**Жизненный цикл graceful reload:** При отправке сигнала `HUP` мастер-процесс запускает новых воркеров с новой конфигурацией, старые воркеры завершают обработку текущих соединений и только потом выходят. Это обеспечивает отсутствие простоев.

### Командная строка (CLI)

Основные команды для управления и диагностики Nginx:

| Команда | Описание |
| :--- | :--- |
| `nginx -h` | **Вызов справки.** Краткий перечень доступных опций и аргументов командной строки. |
| `nginx -t` | **Валидация синтаксиса.** Самая важная команда. Проверяет файлы конфигурации на ошибки перед перезагрузкой. |
| `nginx -v` | Показывает версию Nginx. |
| `nginx -V` | Подробный вывод: версия, параметры компиляции и список установленных модулей. |
| `nginx -T` | Выводит полную текущую конфигурацию в консоль (удобно для аудита, поддержки и отладки). |
| `nginx -s <сигнал>` | Отправка сигнала мастер-процессу: `stop`, `quit`, `reload`, `reopen`. |

*Совет: Рекомендуется использовать `reload` вместо `restart`, так как это позволяет обновить конфигурацию без разрыва текущих соединений.*

### Структура конфигурации и иерархия блоков

Файл `nginx.conf` имеет четкую иерархическую структуру:

1.  **Глобальные настройки (Global Context):** Верхний уровень. Определяет параметры всего сервера: привилегии пользователя (`user`), количество воркеров (`worker_processes`), путь к PID-файлу (`pid`), настройки лимитов и сжатия.
2.  **Блок `events`:** Управление сетевыми соединениями и многопоточностью (`worker_connections`, модель обработки событий).
3.  **Блок `http`:** Основной контекст для веб-трафика. Включает глобальные HTTP-оптимизации, правила безопасности и подключение внешних файлов через `include`.

**Best Practice по организации файлов:**
- **Изоляция:** Рекомендуется никогда не размещать блоки `server` (виртуальные хосты) напрямую в `nginx.conf`. Вместо этого следует создавать отдельный файл конфигурации для каждого сайта.
- **Механизм `include`:**
    - Директива `include /etc/nginx/conf.d/*.conf;` использует подстановочный знак (`*`) для автоматического подключения всех файлов с расширением `.conf`.
    - Директива `include /etc/nginx/sites-enabled/*;` (часто без расширения) подключает абсолютно все файлы в директории. Это требует особой осторожности: любые временные или резервные файлы в этой папке будут прочитаны Nginx, что может привести к конфликтам.

4.  **Блок `server`:** Определение виртуального хоста (сайта). Задает логику ответа для конкретных доменов или IP.
5.  **Блок `location`:** Правила обработки конкретных URI внутри сервера.

*Примечание: Иерархия контекстов и правила наследования директив подробно описаны в **[Обзоре Nginx](./nginx_overview.md)**.*

### Структура директорий и ключевые файлы

-   **Главный файл:** `/etc/nginx/nginx.conf`. Точка входа.
-   **Директории конфигурации сайтов:**
    -   **Debian/Ubuntu:**
        -   `/etc/nginx/sites-available/` — все созданные конфиги (включая неактивные).
        -   `/etc/nginx/sites-enabled/` — символические ссылки на активные конфиги.
        -   *Специфика:* В отличие от Apache, у Nginx нет встроенных команд вроде `a2ensite`. Активация выполняется вручную созданием символической ссылки (`ln -s`).
    -   **CentOS/RHEL/Official Packages:** `/etc/nginx/conf.d/*.conf`.
-   **Контент сайтов (Root):**
    -   **Ubuntu:** `/var/www/`
    -   **RHEL:** `/usr/share/nginx/html/`
-   **Логи:** `/var/log/nginx/` — файлы `access.log` и `error.log`. Критически важны для мониторинга и отладки.
    - *Организация:* Для крупных проектов рекомендуется настраивать отдельные пути логирования для каждого виртуального хоста, создавая при необходимости поддиректории (например, `/var/log/nginx/example.com/access.log`).
-   **MIME-типы:** `/etc/nginx/mime.types` — определяет, как сервер должен обрабатывать различные расширения файлов.
-   **PID-файл:** хранит идентификатор процесса мастера, необходим для передачи сигналов управления.
-   **Runtime-директория:** `/var/run/nginx/` — содержит PID-файл и файлы блокировки. В systemd-системах создается автоматически.

### Ключевые директивы и расчет производительности

В главном файле конфигурации (`nginx.conf`) определяются параметры, напрямую влияющие на пропускную способность сервера:

- **`user`**: определяет пользователя, от имени которого работают рабочие процессы (например, `www-data` в Ubuntu или `nginx` в RHEL).
- **`worker_processes`**: количество рабочих процессов. Значение `auto` автоматически устанавливает их число равным количеству ядер CPU, что оптимально для производительности.
- **`worker_connections`** (в блоке `events`): максимальное количество одновременных соединений, которое может открыть один рабочий процесс.
- **`worker_rlimit_nofile`**: максимальное количество открытых файловых дескрипторов на воркер. Должно быть минимум в 2 раза больше `worker_connections`, так как на каждое проксируемое соединение тратится два дескриптора (клиент + бэкенд).

**Расчет максимального количества клиентов:**
```text
Max Clients = worker_processes * worker_connections
```
Например, для сервера с 4 ядрами (`worker_processes 4`) и `worker_connections 1024`, Nginx сможет обрабатывать до 4096 одновременных соединений.

### Важность правильной структуры: блок `http` и его вложенность

Блок `http { ... }` является глобальным контекстом. Он должен быть определен только один раз на верхнем уровне.

**Распространенная ошибка:** Попытка вложить блок `http` внутрь `server`.

```nginx
# НЕПРАВИЛЬНО: Пример недопустимой вложенности
server {
    listen 80;
    server_name example.com;

    http { # Этот блок здесь недопустим
        proxy_cache_path /var/cache/nginx/api_cache levels=1:2 keys_zone=api_cache:10m;
        # ...
    }
}
```

**Правильное решение:** Глобальные директивы, такие как [`proxy_cache_path`](../Performance/Caching/proxy_caching.md), должны определяться один раз в основном `http` блоке.

```nginx
# ПРАВИЛЬНО: В /etc/nginx/nginx.conf
http {
    proxy_cache_path /var/cache/nginx/api_cache
        levels=1:2
        keys_zone=api_cache:10m
        max_size=1g
        inactive=10m
        use_temp_path=off; # Отключение использования временного пути для I/O
    # ...
}

# ПРАВИЛЬНО: В /etc/nginx/conf.d/example.com.conf
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_cache api_cache;
        proxy_pass http://backend_service;
    }
}
```

### Блок stream для L4 проксирования

Начиная с Nginx 1.9.0, для балансировки TCP/UDP трафика используется блок `stream`. Он находится на том же уровне иерархии, что и `http`.

```nginx
# В основном nginx.conf
stream {
    include /etc/nginx/stream.d/*.conf;
}
```

### Директива include в блоке geo (Nginx 1.29.8+)

Начиная с версии 1.29.8, блок `geo` поддерживает wildcards в директиве `include` для удобного управления большими базами IP:

```nginx
geo $geo_region {
    include /etc/nginx/geo/*.conf;
}
```

---

## Практические сценарии

### Установка

#### Установка из официального репозитория Nginx (Рекомендуется)

Для получения актуальной версии (Mainline 1.31+ или Stable 1.30+) рекомендуется использовать официальные репозитории.

**Debian / Ubuntu:**
```bash
# Установка зависимостей и ключа
sudo apt update && sudo apt install -y curl gnupg2 ca-certificates lsb-release ubuntu-keyring
curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor | sudo tee /usr/share/keyrings/nginx-archive-keyring.gpg >/dev/null

# Добавление репозитория (Mainline)
echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/ubuntu `lsb_release -cs` nginx" | sudo tee /etc/apt/sources.list.d/nginx.list

sudo apt update && sudo apt install nginx
```

**CentOS / RHEL / Rocky Linux:**
Создайте `/etc/yum.repos.d/nginx.repo` с `baseurl=http://nginx.org/packages/mainline/centos/$releasever/$basearch/`.

#### Фиксация версии (Pinning)

Чтобы предотвратить нежелательные обновления в продакшене:
- Ubuntu: `sudo apt-mark hold nginx`
- RHEL: `sudo dnf versionlock nginx`

### Настройка системных лимитов

Перед настройкой Nginx необходимо убедиться, что система разрешает достаточное количество открытых файлов и соединений.

**Проверка текущих лимитов:**
```bash
ulimit -n
# → 1024 (значение по умолчанию часто недостаточно)
```

**Настройка через systemd (рекомендуется):**
```bash
sudo systemctl edit nginx
```
Добавьте в файл override:
```ini
[Service]
LimitNOFILE=65535
```

**Альтернатива — через `/etc/nginx/nginx.conf` (глобальный лимит воркеров):**
```nginx
worker_rlimit_nofile 65535;
```

После изменения unit-файла:
```bash
sudo systemctl daemon-reload
sudo systemctl restart nginx
```

**Проверка примененных лимитов:**
```bash
cat /proc/$(pgrep -n nginx)/limits | grep "Max open files"
```

### Настройка Firewall

Безопасная настройка подразумевает открытие только необходимых портов: **80** (HTTP), **443** (HTTPS) и **22** (SSH).

- **UFW (Ubuntu):**
    - `sudo ufw allow 'Nginx Full'`
    - **ВНИМАНИЕ:** Перед активацией UFW (`ufw enable`) убедитесь, что разрешен SSH (`ufw allow 22`), иначе вы потеряете доступ к серверу по сети.
- **Firewalld (RHEL):**
    - `sudo firewall-cmd --permanent --add-service={http,https,ssh}`
    - `sudo firewall-cmd --reload`

### Базовое укрепление безопасности при установке

Минимальные настройки, которые должны присутствовать в `nginx.conf` на этапе развертывания:

```nginx
http {
    # Сокрытие версии Nginx
    server_tokens off;

    # Лимиты на защиту от Slowloris и переполнения буферов
    client_body_timeout 10s;
    client_header_timeout 10s;
    send_timeout 10s;

    client_body_buffer_size 16k;
    client_header_buffer_size 1k;
    large_client_header_buffers 4 8k;

    # Ограничение количества заголовков (Nginx 1.25.1+)
    max_headers 100;
}
```

Детали hardening описаны в **[Руководстве по безопасности Nginx](../Security/nginx_security_guide.md)**.

### Проверка версии и модулей

```bash
nginx -V
# → built with OpenSSL 3.0.x
# → TLS SNI support enabled
# → --with-http_v2_module --with-http_ssl_module --with-stream ...
```

### Управление сервисом (Systemd)

- **Статус:** `sudo systemctl status nginx`
- **Reload:** `sudo systemctl reload nginx` (Graceful, сигнал `SIGHUP`).
- **Restart:** `sudo systemctl restart nginx` (Полная остановка и запуск).
- **Включение в автозагрузку:** `sudo systemctl enable nginx`

### Пример базовой конфигурации сайта

```nginx
server {
    listen 80;
    listen [::]:80; # Поддержка IPv6
    server_name example.com www.example.com;

    root /var/www/example.com;
    index index.html;

    # Настройка HTTPS описана в:
    # [Настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)
    # [Nginx с Let's Encrypt](../Scenarios/nginx_with_letsencrypt.md)

    location / {
        # try_files: проверка файла -> директории -> fallback 404
        try_files $uri $uri/ =404;
    }
}
```

#### Ключевые директивы блока server

- **`listen`**: определяет порт и IP, на которых Nginx ожидает соединения. Стандарты: 80 (HTTP) или 443 (HTTPS). Может использоваться 8080 для проксирования.
- **`server_name`**: доменное имя сайта. Используется для сопоставления с заголовком `Host` запроса.
- **`root`**: путь к файлам сайта на диске (например, `/var/www/site`).
- **`index`**: файл, отдаваемый по умолчанию при обращении к корню (обычно `index.html`).
- **`location /`**: корень домена или "посадочная страница" (landing page).
- **`try_files`**: последовательная проверка существования ресурсов (`$uri` — файл, `$uri/` — папка) перед выполнением fallback-действия.

### Настройка IPv6 (dual-stack)

Production-серверы должны слушать и IPv4, и IPv6 (`listen 80` + `listen [::]:80`). В Nginx IPv6-сокет по умолчанию принимает и IPv4 (dual-stack, если ядро включило `net.ipv6.bindv6only=0`); `ipv6only=on` делает сокет строго IPv6.

```nginx
server {
    listen 80;
    listen [::]:80;                  # dual-stack (IPv4-mapped :::80)
    listen 443 ssl;
    listen [::]:443 ssl;             # http2/ssl — по тому же принципу

    server_name example.com;
    root /var/www/example.com;
}
```

Проверка:

```bash
# Слушает ли nginx оба стека
ss -tlnp | grep :80
# → LISTEN 0 128 0.0.0.0:80  0.0.0.0:*   (IPv4)
# → LISTEN 0 128 :::80      :::*       (IPv6, при dual-stack принимает и IPv4)
# Проверка IPv6-доступности
curl -6 -I http://[2606:4700::6810:84e5]/
```

Best practices: добавляйте `resolver` для IPv6-апстримов (`resolver 1.1.1.1 [2606:4700:4700::1111] valid=30s;`), не забывайте `::ffff:`-mapped адреса в access-логах при проксировании. Системная настройка IPv6 (sysctl, disable/enable, dual-stack для сервисов) — в [Настройке сервисов для IPv6](../../../Linux/Networking/Settings/ipv6_configuration/services_configuration.md), особенности адресации — в [Специальных и частных IP-адресах](../../../Networking/Protocols/IP_addressing/special_addresses.md).

### Управление конфигурацией через Git и CI/CD

Конфиги Nginx — это код: их версионируют в `git`, применяют через конвейер с автоматической валидацией `nginx -t` и rollback. Категорически не редактировать `/etc/nginx` напрямую в проде.

```bash
# Репозиторий конфигурации
git init /etc/nginx && cd /etc/nginx
git config --global user.email ops@example.com
git add conf.d/ sites-available/ snippets/ nginx.conf
git commit -m "chore: baseline nginx config"

# Проверка расхождений между git и файловой системой
git status --short /etc/nginx
git diff --stat HEAD
```

Pipeline (GitLab CI-профиль для конфигов):

```yaml
stages: [test, deploy]
validate:
  stage: test
  script:
    - nginx -t -c /etc/nginx/nginx.conf   # синтаксис
    - nginx -T | grep -n "server_name"     # слияние include
deploy:
  stage: deploy
  script:
    - git -C /etc/nginx pull --ff-only
    - nginx -t && systemctl reload nginx || { git -C /etc/nginx checkout HEAD^; systemctl reload nginx; exit 1; }
  environment: production
```

Принципы: **одна конфигурация — один источник правды**; перед `reload` — обязательный `nginx -t`; при неудачном применении — мгновенный откат на предыдущий commit; изменения вносятся только через merge request (audit trail). Детали pipeline-паттернов — в [Pipeline Workflow](../../../CI-CD/Core_Concepts/pipeline_workflow.md) и [Security Hardening CI/CD](../../../CI-CD/Core_Concepts/ci_cd_security_hardening.md).

### Конфигурация default_server

Если Nginx не находит точного совпадения `server_name`, запрос направляется в первый блок для данного порта. Рекомендуется явно задать блок-заглушку:

```nginx
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 444; # Нет ответа (Nginx-specific)
}
```

### Валидация и применение изменений

1.  **Валидация (ОБЯЗАТЕЛЬНО):** `sudo nginx -t`. Если проверка не пройдена, `reload` не будет выполнен.
2.  **Перезагрузка:** `sudo systemctl reload nginx`.

### Стратегия резервного копирования и отката

Для production-серверов настройте быстрый откат при ошибках конфигурации:

```bash
# Сохранить текущую рабочую конфигурацию
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak.$(date +%Y%m%d%H%M%S)

# При ошибке после reload — мгновенный откат
cp /etc/nginx/nginx.conf.bak.20260922153000 /etc/nginx/nginx.conf
sudo systemctl reload nginx
```

В системах с `git` конфигурации Nginx рекомендуется хранить в репозитории и применять через CI/CD pipeline с автоматическим `nginx -t` и rollback.

### Настройка ротации логов

По умолчанию Nginx использует `logrotate`. Проверка конфигурации:

```bash
cat /etc/logrotate.d/nginx
```

Принудительная ротация:

```bash
sudo logrotate -f /etc/logrotate.d/nginx
```

---

## Операции и команды

### Управление процессами (Сигналы)

Nginx управляется через сигналы, посылаемые мастер-процессу:

| Сигнал | Описание |
| :--- | :--- |
| `HUP` (`reload`) | Перечитывание конфигурации. Graceful reload без разрыва соединений. |
| `QUIT` (`quit`) | Плавное завершение работы. |
| `TERM/INT` (`stop`) | Немедленная остановка. |
| `USR1` (`reopen`) | Переоткрытие лог-файлов (используется для ротации). |
| `USR2` | Обновление бинарного файла сервера на лету без остановки соединений. |

### Валидация и отладка конфигурации

```bash
# Проверка синтаксиса
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Просмотр объединенного конфига с подстановкой include
sudo nginx -T | grep -n "server_name"

# Graceful reload — без потери соединений
sudo nginx -s reload
# → signal processed

# Принудительная остановка (разрывает активные соединения)
sudo nginx -s stop
```

### Проверка статуса и ресурсов

```bash
# Статус systemd-службы
sudo systemctl status nginx

# Список процессов и владельцев
ps aux | grep nginx

# Проверка открытых портов
ss -lnpt | grep nginx

# Проверка лимитов дескрипторов воркера
cat /proc/$(pgrep -n nginx)/limits | grep "Max open files"
```

### Ротация логов

```bash
# Проверка конфигурации logrotate
cat /etc/logrotate.d/nginx

# Принудительная ротация
sudo logrotate -f /etc/logrotate.d/nginx
```

---

## Диагностика и устранение неполадок

Типовые ошибки при первоначальной настройке и запуске:

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `nginx: [emerg] bind() failed` | Порт уже занят другим процессом | `ss -lnpt \| grep :80`, остановить конфликтующий процесс |
| `nginx: [emerg] unknown directive` | Ошибка в синтаксисе или модуль не загружен | Проверить `nginx -t`, убедиться что модуль собран |
| `403 Forbidden` на статический файл | Нет прав на чтение или `disable_symlinks` | `chown -R www-data:www-data /var/www/site`, `chmod 755` |
| `404 Not Found` при существующем файле | Неверный `root`/`alias` или off-by-slash | Проверить `$document_root` через `return` |
| Запрос попадает в неожиданный vhost | Отсутствует `default_server` или неверный `server_name` | Явно указать `default_server` для заглушки |

Детальная методология диагностики (сеть, TLS, upstream, ошибки 5xx) описана в **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)**.

---

## Лучшие практики

1.  **Валидация перед reload:** Всегда выполняйте `nginx -t` перед `nginx -s reload`. Ошибка в синтаксисе не затрагивает уже работающий Nginx.
2.  **Версионирование конфигурации:** Храните конфиги в `git`, применяйте через CI/CD с автоматическим `nginx -t` и rollback.
3.  **Сокрытие версии:** Используйте `server_tokens off;` для минимизации информации о стеке.
4.  **Разделение ответственности:** Используйте отдельного пользователя для конфигов (`root`) и процесса (`www-data`/`nginx`).
5.  **Логирование:** Настройте раздельные логи для каждого виртуального хоста. Для production используйте JSON-формат для интеграции с SIEM.
6.  **Изоляция include:** Не размещайте временные файлы в `sites-enabled/` или `conf.d/`, чтобы избежать случайного подключения.
7.  **SELinux/AppArmor:** Проверяйте контекст безопасности при развертывании на RHEL/Ubuntu. Подробнее — в **[Руководстве по безопасности Nginx](../Security/nginx_security_guide.md)** и **[харденинге юнита/SELinux/AppArmor](../Security/nginx_systemd_selinux_hardening.md)**.

Дополнительные рекомендации по настройке location-блоков и производительности см.:
- **[Nginx location: лучшие практики и отладка](./Location/best_practices.md)**
- **[Тюнинг производительности Nginx](../Performance/nginx_performance_tuning.md)**

---

## Дополнительная информация

### См. также

- **[Обзор Nginx](./nginx_overview.md)** — архитектура и ключевые особенности.
- **[Директива location: основы и приоритеты](./Location/basics.md)** — детальный разбор маршрутизации.
- **[Тюнинг производительности Nginx](../Performance/nginx_performance_tuning.md)** — оптимизация для высоких нагрузок.
- **[Диагностика неисправностей](../Operations/nginx_troubleshooting.md)** — поиск и решение проблем.
- **[Безопасность Nginx](../Security/nginx_security_guide.md)** — защита от атак и харденинг.
