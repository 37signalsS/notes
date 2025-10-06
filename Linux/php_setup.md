# Установка и настройка PHP

*   **Ubuntu и Debian (для Apache):**
    ```bash
    # Для PHP 8.3 может потребоваться добавление репозитория Ondřej Surý PPA
    # sudo add-apt-repository ppa:ondrej/php
    # sudo apt update
    apt -y install php8.3 libapache2-mod-php8.3 php8.3-mysql php8.3-xml php8.3-gd php8.3-mbstring php8.3-curl php8.3-zip
    ```

*   **CentOS:**
    ```bash
    # Для PHP 8.3 может потребоваться подключение репозитория Remi
    # sudo dnf install https://rpms.remirepo.net/enterprise/remi-release-8.rpm # Для CentOS 8
    # sudo dnf install dnf-utils
    # sudo dnf module enable php:remi-8.3
    # sudo dnf update
    yum -y install php83 php83-php-mysqlnd php83-php-common php83-php-cli php83-php-json php83-php-opcache php83-php-mbstring php83-php-curl php83-php-zip
    ```
    > **Примечание:** для современных RHEL-подобных дистрибутивов (AlmaLinux, Rocky Linux) используйте `dnf` вместо `yum`

## Интеграция с Apache

Установленная версия PHP автоматически настроится в качестве модуля Apache. После этого потребуется перезагрузить веб-сервер.

*   **Ubuntu и Debian:**
    ```bash
    systemctl restart apache2
    ```
*   **CentOS:**
    ```bash
    systemctl restart httpd
    ```

## Дополнительные расширения

Посмотреть доступные для установки расширения PHP можно командой:

*   **Ubuntu и Debian:**
    ```bash
    apt-cache search php | egrep 'module' | grep default
    ```
*   **CentOS:**
    ```bash
    yum search php | grep module
    ```

Установить выбранный модуль можно командой (на примере расширения SOAP):

*   **Ubuntu и Debian:**
    ```bash
    apt -y install php-soap
    ```

## Настройка производительности PHP-FPM

Настройки PHP-FPM обычно находятся в файле `www.conf` в директории пула (например, `/etc/php/8.3/fpm/pool.d/www.conf`).

### Управление процессами (Process Manager - PM)

`pm = dynamic` — самый популярный режим, при котором количество дочерних процессов управляется динамически на основе следующих директив:

- `pm.max_children = 5`: Максимальное количество дочерних процессов.
- `pm.start_servers = 3`: Количество процессов, создаваемых при старте.
- `pm.min_spare_servers = 2`: Минимальное количество свободных процессов.
- `pm.max_spare_servers = 4`: Максимальное количество свободных процессов.
- `pm.max_requests = 200`: Количество запросов, после которого дочерний процесс будет перезапущен (помогает предотвратить утечки памяти).

### Аварийный перезапуск

Эти параметры помогают автоматически перезапускать мастер-процесс FPM в случае сбоев дочерних процессов, обеспечивая стабильность.

- `emergency_restart_threshold = 5`: Если 5 дочерних процессов завершатся с ошибкой...
- `emergency_restart_interval = 2m`: ...в течение 2 минут, то мастер-процесс FPM будет перезапущен.
- `process_control_timeout = 10s`: Время ожидания для дочернего процесса перед принудительным завершением после получения сигнала от мастера.

### Логирование медленных запросов

Для отладки проблем с производительностью можно включить логирование медленных запросов.

```ini
; Путь к лог-файлу медленных запросов
slowlog = /var/log/php-fpm-slow.log

; Время выполнения запроса, после которого он считается медленным
request_slowlog_timeout = 5s
```
