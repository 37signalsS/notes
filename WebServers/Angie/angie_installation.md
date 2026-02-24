# Установка Angie

## Определения

В этом документе рассматриваются различные способы установки [Angie](./angie_overview.md) — форка Nginx с расширенной функциональностью.

## Основные концепции

Существует несколько основных способов развертывания Angie:

1. **Установка из пакетов:** Наиболее распространенный метод для серверных ОС, использующий официальные репозитории для `dnf` (RHEL-based) или `apt` (Debian-based).
2. **Использование Docker-контейнеров:** Гибкий и изолированный способ развертывания, рекомендованный для сред контейнеризации.
3. **Установка коммерческой версии (Angie Pro):** Требует наличия лицензии и использует отдельный, защищенный репозиторий.

После установки вы можете перейти к более сложным сценариям, таким как настройка [обратного HTTP-прокси](./angie_reverse_proxy.md), [балансировка нагрузки](./angie_http_load_balancing.md) или [настройка TLS](./angie_tls_setup.md).

## Практические сценарии

### Сценарий 1: Установка на ALMA-Linux (RHEL-based)

1. **Создание файла репозитория:**
    Создайте файл `/etc/yum.repos.d/angie.repo`.

    ```ini
    [angie]
    name=angie
    baseurl=https://download.angie.software/rhel/$releasever/$basearch/
    gpgcheck=1
    gpgkey=https://download.angie.software/keys/angie-signing-key.gpg
    enabled=1
    ```

2. **Установка Angie:**

    ```bash
    sudo dnf install -y angie
    ```

3. **Запуск и проверка:**

    ```bash
    sudo angie -t
    sudo systemctl enable --now angie
    sudo systemctl status angie
    ```

### Сценарий 2: Установка на Ubuntu/Debian

1. **Добавление ключа и репозитория:**

    ```bash
    sudo apt update
    sudo apt install -y curl gpg
    curl -o /etc/apt/trusted.gpg.d/angie-signing-key.gpg https://download.angie.software/keys/angie-signing-key.gpg
    echo "deb https://download.angie.software/ubuntu/ `lsb_release -cs` main" | sudo tee /etc/apt/sources.list.d/angie.list >/dev/null
    ```

2. **Установка Angie:**

    ```bash
    sudo apt update
    sudo apt install -y angie
    ```

3. **Проверка:**

    ```bash
    sudo angie -t
    sudo systemctl status angie
    ```

    Для пользователей, переходящих с Nginx, рекомендуется ознакомиться с [руководством по миграции](./migration_from_nginx.md).

### Сценарий 3: Использование в Docker-контейнерах

1. **Установка Docker:**

    ```bash
    sudo apt install docker.io
    ```

2. **Запуск контейнера:**
    Для управления конфигурацией рекомендуется монтировать ее с хост-машины.

    ```bash
    # Создаем директории на хосте
    mkdir -p ~/angie_config ~/angie_html
    
    # Запускаем временный контейнер, чтобы скопировать дефолтную конфигурацию
    docker run -d --name temp-angie docker.ngsoftware/angie:latest
    docker cp temp-angie:/etc/angie ~/angie_config/
    docker rm -f temp-angie

    # Запускаем постоянный контейнер с монтированными томами
    docker run -d --name angie \
      -p 8800:80 \
      -v ~/angie_html:/usr/share/nginx/html:ro \
      -v ~/angie_config/angie:/etc/angie:ro \
      --restart always \
      docker.ngsoftware/angie:latest
    ```

3. **Перезагрузка конфигурации:**
    После изменения файлов в `~/angie_config/angie` на хосте, примените их, отправив сигнал `HUP` контейнеру:

    ```bash
    docker kill -s HUP angie
    ```

### Сценарий 4: Установка Angie Pro

Установка коммерческой версии Angie Pro требует наличия лицензии.

1. **Подготовка (пример для Debian/Ubuntu):**
    * Удалите Open Source версию, если она установлена.
    * Поместите файлы лицензии репозитория (`angie-repo.crt`, `angie-repo.key`) в `/etc/ssl/angie/`, выставив права `600`.
    * Создайте файл `/etc/apt/apt.conf.d/90angie-pro` для аутентификации в репозитории:

        ```
        Acquire::https::download.angie.software {
            Verify-Peer "true";
            Verify-Host "true";
            Ssl-Certificate "/etc/ssl/angie/angie-repo.crt";
            Ssl-Key "/etc/ssl/angie/angie-repo.key";
        };
        ```

2. **Установка Angie Pro:**

    ```bash
    sudo apt update
    sudo apt install -y angie-pro
    ```

3. **Установка лицензии Angie Pro:**
    * Поместите файл `license.pem` в `/etc/angie/`.
    * Перезагрузите сервис: `sudo systemctl reload angie`. Если лицензия корректна, запустятся все worker-процессы.

## Дополнительная информация

### Сторонние динамические модули

Одним из ключевых преимуществ Angie является наличие большого количества популярных модулей, доступных для установки в виде пакетов из официального репозитория. Это избавляет от необходимости ручной компиляции. Подробнее о преимуществах см. в [общем обзоре](./angie_overview.md).

**Установка:**
Пакеты модулей имеют префикс `angie-module-`.

```bash
# Пример для Ubuntu/Debian
sudo apt install angie-module-brotli angie-module-modsecurity
```

**Подключение:**
После установки не забудьте подключить модуль в `angie.conf` с помощью директивы `load_module`.

```nginx
# /etc/angie/angie.conf
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;
```

Полный список модулей доступен в [официальной документации Angie](https://angie.software/ru/modules/).
