# Установка Angie из пакетов

В этом документе рассматриваются различные способы установки Angie, начиная от пакетной установки на различные дистрибутивы и заканчивая использованием Docker-контейнеров.

## 1. Установка Angie на ALMA-Linux (RHEL-based)

Инструкция для ALMA-Linux 9.5, но также подходит для других дистрибутивов на базе RHEL.

1.  **Проверка версии системы:**
    ```bash
    cat /etc/redhat-release
    # ALMA-Linux release 9.5 (Sea Pan)
    ```

2.  **Создание файла репозитория:**
    Создайте файл `/etc/yum.repos.d/angie.repo` для пакетного менеджера `dnf` (`yum`).
    ```bash
    sudo nano /etc/yum.repos.d/angie.repo
    ```
    Содержимое файла:
    ```ini
    [angie]
    name=angie
    baseurl=https://download.angie.software/rhel/$releasever/$basearch/
    gpgcheck=1
    gpgkey=https://download.angie.software/keys/angie-signing-key.gpg
    enabled=1
    ```

3.  **Установка Angie и дополнительных модулей:**
    Установите Angie через пакетный менеджер. Можно сразу добавить необходимые модули.
    ```bash
    sudo dnf install -y angie angie-module-brotli
    ```

4.  **Настройка модулей:**
    Чтобы подключить установленные модули, добавьте директивы `load_module` в основной конфигурационный файл `/etc/angie/angie.conf`.
    ```nginx
    # /etc/angie/angie.conf
    # ...
    load_module modules/ngx_http_brotli_filter_module.so;
    load_module modules/ngx_http_brotli_static_module.so;
    # ...
    ```

5.  **Запуск и проверка Angie:**
    *   Проверьте синтаксис конфигурации:
        ```bash
        sudo angie -t
        ```
    *   Включите автозагрузку и запустите сервис Angie:
        ```bash
        sudo systemctl enable --now angie
        ```
    *   Убедитесь, что процессы Angie запущены:
        ```bash
        ps aux | grep angie
        ```
    *   После внесения изменений в конфигурацию, ее можно перезагрузить:
        ```bash
        sudo systemctl reload angie
        ```

## 2. Установка Angie на Ubuntu/Debian

Инструкция для Ubuntu 24, но также подходит для других LTS-версий Ubuntu и Debian.

1.  **Установка зависимостей:**
    ```bash
    sudo apt update
    sudo apt install -y curl gpg
    ```

2.  **Добавление ключа репозитория:**
    ```bash
    curl -o /etc/apt/trusted.gpg.d/angie-signing-key.gpg https://download.angie.software/keys/angie-signing-key.gpg
    ```

3.  **Создание файла репозитория:**
    Создайте файл `/etc/apt/sources.list.d/angie.list`.
    ```bash
    echo "deb https://download.angie.software/ubuntu/ `lsb_release -cs` main" | sudo tee /etc/apt/sources.list.d/angie.list >/dev/null
    ```

4.  **Установка Angie и дополнительных модулей:**
    ```bash
    sudo apt update
    sudo apt install -y angie angie-module-brotli
    ```

5.  **Настройка модулей:**
    Как и в случае с ALMA-Linux, добавьте директивы `load_module` в `/etc/angie/angie.conf`.
    ```nginx
    # /etc/angie/angie.conf
    # ...
    load_module modules/ngx_http_brotli_filter_module.so;
    load_module modules/ngx_http_brotli_static_module.so;
    # ...
    ```

6.  **Запуск и проверка Angie:**
    *   В Debian-based системах сервис обычно запускается и добавляется в автозагрузку автоматически.
    *   Проверьте синтаксис конфигурации:
        ```bash
        sudo angie -t
        ```
    *   Проверьте статус сервиса:
        ```bash
        sudo systemctl status angie
        ```
    *   Для отслеживания успешности перезагрузки конфигурации можно смотреть на "поколение" worker-процессов. После каждой успешной перезагрузки (`sudo service angie reload`) номер поколения увеличивается.
        ```bash
        ps aux | grep angie
        # root      ... /usr/sbin/angie: master process ...
        # www-data  ... /usr/sbin/angie: worker process (generation: 2)
        ```

## 3. Установка Angie Pro

Установка коммерческой версии [Angie Pro](../Angie/angie_pro_features.md) требует наличия лицензии и ключей доступа к репозиторию.

1.  **Удаление Open Source версии Angie (если установлена):**
    ```bash
    sudo apt purge angie angie-module-*
    sudo rm /etc/apt/sources.list.d/angie.list
    sudo apt update
    ```

2.  **Подготовка файлов лицензии:**
    *   Создайте директорию для ключей доступа к репозиторию:
        ```bash
        sudo mkdir -p /etc/ssl/angie
        ```
    *   Поместите файлы лицензии (`angie-repo.crt` и `angie-repo.key`) в эту директорию.
    *   Установите правильные права доступа:
        ```bash
        sudo chown -R root:root /etc/ssl/angie
        sudo chmod 600 /etc/ssl/angie/*
        ```

3.  **Подключение репозитория Angie Pro:**
    *   Установите зависимости и скачайте ключ репозитория Angie Pro.
    *   Создайте файл репозитория для Angie Pro.
    *   Создайте файл `/etc/apt/apt.conf.d/90angie-pro` для настройки доступа к репозиторию с использованием ваших ключей. Содержимое файла:
        ```
        Acquire::https::download.angie.software {
            Verify-Peer "true";
            Verify-Host "true";
            Ssl-Certificate "/etc/ssl/angie/angie-repo.crt";
            Ssl-Key "/etc/ssl/angie/angie-repo.key";
        };
        ```

4.  **Установка Angie Pro и модулей:**
    ```bash
    sudo apt update
    sudo apt install -y angie-pro angie-pro-module-brotli
    ```
    Обратите внимание на префикс `angie-pro-` в названии пакетов.

5.  **Установка лицензии Angie Pro:**
    *   Поместите файл лицензии `license.pem` в директорию `/etc/angie/`.
    *   Проверьте конфигурацию. Angie Pro без лицензии запустится только с одним worker-процессом.
        ```bash
        sudo angie -t
        ```
    *   Перезагрузите сервис. Если лицензия корректна, запустятся все worker-процессы, указанные в `angie.conf`.
        ```bash
        sudo systemctl reload angie
        ```

## 4. Использование Angie в Docker-контейнерах

1.  **Установка Docker:**
    Установите Docker из репозитория вашей операционной системы (например, `docker.io` для Ubuntu).
    ```bash
    sudo apt install docker.io
    ```

2.  **Запуск стандартного контейнера Angie:**
    Запустите контейнер Angie, пробросив порты и смонтировав директорию для статики.
    ```bash
    docker run -d --name angie \
      -p 8800:80 \
      -v /path/to/your/html:/usr/share/nginx/html:ro \
      docker.ngsoftware/angie:latest
    ```
    *   `-d`: фоновый режим.
    *   `--name angie`: имя контейнера.
    *   `-p 8800:80`: проброс порта 80 контейнера на порт 8800 хоста.
    *   `-v ...:ro`: монтирование директории с хоста в контейнер в режиме "только для чтения".
    *   `docker.ngsoftware/angie:latest`: официальный образ Angie.

3.  **Управление конфигурацией внутри контейнера:**
    Для управления конфигурацией рекомендуется скопировать ее из контейнера на хост, а затем монтировать как volume.
    *   Скопируйте конфигурацию из запущенного контейнера на хост:
        ```bash
        # Создаем директорию на хосте
        mkdir ~/angie_config
        # Копируем конфиг
        docker cp angie:/etc/angie ~/angie_config/
        ```
    *   Удалите временный контейнер:
        ```bash
        docker rm -f angie
        ```
    *   Запустите новый контейнер, смонтировав директорию с конфигурацией с хоста:
        ```bash
        docker run -d --name angie \
          -p 8800:80 \
          -v /path/to/your/html:/usr/share/nginx/html:ro \
          -v ~/angie_config/angie:/etc/angie:ro \
          --restart always \
          docker.ngsoftware/angie:latest
        ```
        Добавлен флаг `--restart always` для автоматического перезапуска контейнера.
    *   Для перезагрузки конфигурации после ее изменения на хосте, отправьте сигнал `HUP` контейнеру:
        ```bash
        docker kill -s HUP angie
        ```

## 5. Сторонние динамические модули

Одним из ключевых преимуществ Angie является наличие большого количества популярных сторонних модулей, которые уже собраны, протестированы и доступны для установки в виде пакетов из официального репозитория. Это избавляет от необходимости вручную компилировать Angie или отдельные модули, как это часто приходилось делать с Nginx.

Название пакета обычно следует формату `angie-module-<имя>`.

**Примеры доступных модулей:**

*   **Сжатие:** Более подробную информацию о настройке сжатия можно найти в [Кэширование в Angie](../Angie/angie_caching.md) (раздел "Сравнение алгоритмов сжатия").
    *   `angie-module-brotli`
    *   `angie-module-zstd`
*   **Безопасность:**
    *   `angie-module-modsecurity`
*   **Работа с данными и бэкендами:**
    *   `angie-module-redis`
    *   `angie-module-postgres`
*   **Стриминг видео:**
    *   `angie-module-vod`
    *   `angie-module-rtmp`

Установка выполняется стандартным пакетным менеджером:
```bash
# Пример для Ubuntu/Debian
sudo apt install angie-module-modsecurity angie-module-zstd
```

После установки не забудьте подключить модуль в `angie.conf` с помощью директивы `load_module`.

Полный и актуальный список доступных динамических модулей можно найти в [официальной документации Angie](https://angie.software/ru/modules/).

## 6. См. также

*   [Обзор Angie](../Angie/angie_overview.md)
*   [Возможности Angie Pro](../Angie/angie_pro_features.md)
*   [Миграция с Nginx на Angie](../Angie/migration_from_nginx.md)
*   [Настройка Angie в роли обратного HTTP-прокси](../Angie/angie_reverse_proxy.md)
*   [Настройка TLS в Angie: безопасность и скорость](../Angie/angie_tls_setup.md)
*   [Балансировка нагрузки HTTP(S) в Angie](../Angie/angie_http_load_balancing.md)
*   [Директивы `location` в Angie](../Angie/angie_location_directives.md)
*   [Балансировка и проксирование L4-трафика (TCP/UDP) в Angie](../Angie/l4_balancing_and_proxying.md)
*   [Мониторинг Angie с помощью Prometheus и Grafana](../Angie/monitoring_with_prometheus_and_grafana.md)
*   [Мониторинг Angie с помощью Console Lite и API](../Angie/angie_monitoring.md)
*   [Кэширование в Angie](../Angie/angie_caching.md)
*   [Динамические группы проксируемых серверов в Angie](../Angie/dynamic_upstreams.md)
*   [Перенаправления и перезапись URI в Angie](../Angie/angie_redirects_and_rewrites.md)
*   [Почему стоит переходить на Angie](../Angie/angie_why_migrate.md)
*   [Запуск Nginx в Docker](../Nginx/nginx_in_docker.md)
*   [Установка и базовая настройка Nginx](../Nginx/nginx_setup.md)

