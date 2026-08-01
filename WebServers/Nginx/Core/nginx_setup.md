# Установка и базовая настройка Nginx

> **Надежность: 10** (Подтверждено актуальной документацией Nginx на июль 2026)

## Определения

**Nginx** — это высокопроизводительный веб-сервер и обратный прокси-сервер, используемый для обслуживания веб-контента, **[балансировки нагрузки](../Proxy/Load_Balancing/overview_concepts.md)**, кэширования и других задач. Для тех, кто интересуется альтернативами, существует заметка о **[миграции с Nginx на Angie](../../Angie/migration_from_nginx.md)**, его отечественном форке.

**Виртуальный хост (Server Block)** — блок конфигурации, описывающий отдельный сайт (домен). Позволяет одному серверу Nginx обслуживать множество сайтов на одном IP (Internet Protocol — интернет-протокол) адресе, различая их по заголовку `Host` в запросе.

> Для более глубокого обзора архитектуры и ключевых концепций обратитесь к файлу **[Обзор Nginx](./nginx_overview.md)**.

---

## Базовые концепции

### Структура конфигурации

* **Главный файл:** `/etc/nginx/nginx.conf`. Это точка входа, которая подключает остальные файлы. Содержит глобальные настройки, такие как `user` (пользователь, от которого работает воркер) и `worker_processes` (количество рабочих процессов). Оптимизация этих параметров рассмотрена в заметке о **[тюнинге производительности Nginx](../Performance/nginx_performance_tuning.md)**.

* **Конфигурация сайтов:**
  * **Debian/Ubuntu:** Используется система `sites-available` / `sites-enabled`.
    * `/etc/nginx/sites-available/`: Содержит файлы конфигурации для всех сайтов.
    * `/etc/nginx/sites-enabled/`: Содержит символические ссылки на файлы в `sites-available`. Nginx читает только эту директорию.
  * **CentOS/RHEL (Red Hat Enterprise Linux):** Используется директория `conf.d`.
    * `/etc/nginx/conf.d/*.conf`: Nginx автоматически подключает все `.conf` файлы из этой директории.

### Важность правильной структуры: блок `http` и его вложенность

Блок `http { ... }` в Nginx является глобальным контекстом, в котором определяются все HTTP (Hypertext Transfer Protocol — протокол передачи гипертекста) серверы (`server { ... }`), а также глобальные настройки: кэширование, MIME (Multipurpose Internet Mail Extensions — многоцелевые расширения почты Интернета) типы, сжатие и т.д. Он должен быть определен только один раз на верхнем уровне.

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

**Правильное решение:**
Глобальные директивы, такие как [`proxy_cache_path`](../Performance/Caching/proxy_caching.md#шаг-1-глобальное-определение-пути-кэша), должны определяться один раз в основном `http` блоке.

```nginx
# ПРАВИЛЬНО: В /etc/nginx/nginx.conf
http {
    # ...
    proxy_cache_path /var/cache/nginx/api_cache
        levels=1:2
        keys_zone=api_cache:10m
        max_size=1g
        inactive=10m
        use_temp_path=off; # Отключение использования временного пути для I/O (Input/Output — ввод-вывод)
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

---

## Практические сценарии

### Установка

Nginx может быть установлен из стандартных репозиториев ОС (Operating System — операционная система) или из официального репозитория Nginx для получения актуальной версии. Подробнее о контейнеризации в руководстве по **[запуску Nginx в Docker](../../../Docker/Docker_compose/docker_compose_file_example.md)**.

#### Установка из стандартных репозиториев

**Debian / Ubuntu:**
```bash
sudo apt update
sudo apt install nginx
# → установка стабильной версии из репозиториев ОС
```

**CentOS / RHEL:**
```bash
# Требуется EPEL (Extra Packages for Enterprise Linux — дополнительные пакеты для корпоративного Linux)
sudo dnf install epel-release
sudo dnf install nginx
# → установка nginx 1.2x+
```

#### Установка из официального репозитория Nginx (Debian/Ubuntu)

Для получения версии Mainline (последние функции) или Stable (проверенная):

```bash
# Установка ключа и репозитория
curl https://nginx.org/keys/nginx_signing.key | gpg --dearmor | sudo tee /usr/share/keyrings/nginx-archive-keyring.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/nginx-archive-keyring.gpg] http://nginx.org/packages/mainline/ubuntu `lsb_release -cs` nginx" | sudo tee /etc/apt/sources.list.d/nginx.list
sudo apt update
sudo apt install nginx
```

### Проверка установленной версии и модулей

```bash
nginx -v
# → nginx version: nginx/1.27.0

nginx -V
# → nginx version: nginx/1.27.0
# → built with OpenSSL 3.0.13 30 Jan 2024
# → TLS SNI support enabled
# → configure arguments: --with-http_ssl_module --with-http_v2_module ...
```

### Управление сервисом

Управление осуществляется через `systemctl` (Systemd — системный менеджер). Подробнее: **[управление службами Systemd](../../../Linux/Core/systemd/service_management.md)**.

* **Статус:** `sudo systemctl status nginx`  # → active (running)
* **Запуск:** `sudo systemctl start nginx`
* **Автозагрузка:** `sudo systemctl enable nginx`
* **Перезагрузка конфига:** `sudo systemctl reload nginx` # → graceful reload (без обрыва соединений)
* **Перезапуск:** `sudo systemctl restart nginx` # → полная остановка и запуск (с обрывом соединений)

### Пример базовой конфигурации сайта

1. **Создайте файл конфигурации:**
    * Ubuntu: `/etc/nginx/sites-available/example.com`
    * CentOS: `/etc/nginx/conf.d/example.com.conf`

2. **Добавьте содержимое:**
    Подробности в руководстве **[Глубокое погружение в директиву location](./Location/basics.md)**.

    ```nginx
    server {
        listen 80;
        listen [::]:80; # Поддержка IPv6

        # Настройка HTTPS описана в:
        # [Настройка TLS/SSL в Nginx](../Security/TLS_SSL/nginx_tls_ssl_overview.md)
        # [Nginx с Let's Encrypt](../Scenarios/nginx_with_letsencrypt.md)
        # TLS (Transport Layer Security — безопасность транспортного уровня)
        # SSL (Secure Sockets Layer — уровень защищенных сокетов)

        server_name example.com www.example.com;

        root /var/www/example.com;
        index index.html;

        location / {
            # try_files проверяет наличие файла, затем директории, иначе отдает 404
            try_files $uri $uri/ =404;
        }
    }
    ```

    Подробнее о маршрутизации: **[Rewrite, Redirect и try_files](./nginx_rewrite_rules_and_try_files.md)**.

3. **Разберите ключевые директивы:**

    * `listen 80;`: Прослушивание порта 80 (стандарт для HTTP).
    * `root /var/www/example.com;`: Корневой каталог файлов сайта.
    * `index index.html;`: Файл по умолчанию для директории.
    * `server_name`: Доменные имена, для которых предназначен этот блок.

4. **Активируйте сайт (только для Debian/Ubuntu):**

    ```bash
    sudo ln -s /etc/nginx/sites-available/example.com /etc/nginx/sites-enabled/
    ```

5. **Проверьте и перезагрузите Nginx:**

    ```bash
    sudo nginx -t
    # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
    # → nginx: configuration file /etc/nginx/nginx.conf test is successful

    sudo systemctl reload nginx
    ```

    Теперь сайт доступен по адресу домена (если настроена DNS — Domain Name System, система доменных имен).

### Применение изменений: reload vs restart

**Правильная процедура:**

1. **Проверка синтаксиса (Обязательно!):** `sudo nginx -t`. Если проверка не пройдена, не перезагружайте сервер. Подробнее: **[диагностика неисправностей](../Operations/nginx_troubleshooting.md)**.
2. **Грациозная перезагрузка (`reload`):** Применяет конфиг без обрыва соединений (сигнал `SIGHUP`). См. **[Сигналы в Linux](../../../Linux/Core/processes/signals.md)**.
3. **Перезапуск (`restart`):** Используется только в крайних случаях (обновление бинарного файла, изменение глобальных лимитов ОС).

---

## Дополнительная информация

### Директива include в блоке geo

Начиная с **nginx 1.29.8**, директива `include` внутри блока `geo` корректно поддерживает **wildcards** (шаблоны с подстановочными символами).

```nginx
geo $geo_region {
    include /etc/nginx/geo/*.conf;       # Все файлы в каталоге
    include /etc/nginx/geo-regions.d/*.conf;  # Шаблонные пути
}
```

Это упрощает управление большими базами IP-адресов, разделяя их на логические файлы.

### См. также

- **[Обзор Nginx](./nginx_overview.md)** — архитектура и ключевые особенности.
- **[Директива location: основы и приоритеты](./Location/basics.md)** — детальный разбор маршрутизации.
- **[Тюнинг производительности Nginx](../Performance/nginx_performance_tuning.md)** — оптимизация для высоких нагрузок.
