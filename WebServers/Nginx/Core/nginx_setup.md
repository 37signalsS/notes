# Установка и базовая настройка Nginx

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на август 2026)

## Определения

**Nginx** — это высокопроизводительный веб-сервер и обратный прокси-сервер, используемый для обслуживания веб-контента, **[балансировки нагрузки](../Proxy/Load_Balancing/overview_concepts.md)**, кэширования и терминации SSL.

**Виртуальный хост (Server Block)** — блок конфигурации, описывающий параметры обработки запросов для конкретного домена или IP-адреса. Позволяет одному серверу Nginx обслуживать множество сайтов на одном IP-адресе, различая их по заголовку `Host` в запросе.

**Mainline vs Stable** — Nginx предлагает две ветки:
- **Mainline:** содержит последние функции и исправления ошибок (рекомендуется для большинства современных инсталляций).
- **Stable:** получает только критические исправления безопасности.

> Для более глубокого обзора архитектуры и ключевых концепций обратитесь к файлу **[Обзор Nginx](./nginx_overview.md)**.

---

## Базовые концепции

### Структура конфигурации

*   **Главный файл:** `/etc/nginx/nginx.conf`. Точка входа, которая подключает остальные файлы. Содержит глобальные настройки: `user` (пользователь воркеров) и `worker_processes`. Оптимизация этих параметров рассмотрена в заметке о **[тюнинге производительности Nginx](../Performance/nginx_performance_tuning.md)**.
*   **Конфигурация сайтов:**
    *   **Debian/Ubuntu:** Используется система `sites-available` / `sites-enabled`. Nginx читает только директорию `sites-enabled` (через символические ссылки).
    *   **CentOS/RHEL/Official Packages:** Используется директория `/etc/nginx/conf.d/*.conf`.

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

---

## Практические сценарии

### Установка

#### Установка из официального репозитория Nginx (Рекомендуется)

Для получения актуальной версии (например, 1.27+) рекомендуется использовать официальные репозитории.

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

### Настройка Firewall

*   **UFW (Ubuntu):** `sudo ufw allow 'Nginx Full'`
*   **Firewalld (RHEL):** `sudo firewall-cmd --permanent --add-service={http,https} && sudo firewall-cmd --reload`

### Проверка версии и модулей

```bash
nginx -V
# → built with OpenSSL 3.0.x
# → TLS SNI support enabled
# → --with-http_v2_module --with-http_ssl_module --with-stream ...
```

### Управление сервисом (Systemd)

*   **Статус:** `sudo systemctl status nginx`
*   **Reload:** `sudo systemctl reload nginx` (Graceful, сигнал `SIGHUP`).
*   **Restart:** `sudo systemctl restart nginx` (Полная остановка и запуск).

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

---

## Продвинутая настройка

### Директива include в блоке geo (Nginx 1.29.8+)
Поддерживает wildcards для управления большими базами IP.
```nginx
geo $geo_region {
    include /etc/nginx/geo/*.conf;
}
```

### Применение изменений: Правильная процедура
1. **Валидация (ОБЯЗАТЕЛЬНО):** `sudo nginx -t`. Если проверка не пройдена, `reload` не будет выполнен.
2. **Перезагрузка:** `sudo systemctl reload nginx`.

---

## Дополнительная информация

### См. также
- **[Обзор Nginx](./nginx_overview.md)** — архитектура и ключевые особенности.
- **[Директива location: основы и приоритеты](./Location/basics.md)** — детальный разбор маршрутизации.
- **[Тюнинг производительности Nginx](../Performance/nginx_performance_tuning.md)** — оптимизация для высоких нагрузок.
- **[Диагностика неисправностей](../Operations/nginx_troubleshooting.md)** — поиск и решение проблем.
