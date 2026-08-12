# Apache HTTP Server (Обзор)

---

## Определения

**Apache HTTP Server** (часто называемый просто Apache) — это один из самых популярных веб-серверов в мире, известный своей гибкостью, мощностью и широким набором функций. Он обрабатывает запросы клиентов по протоколам [HTTP/HTTPS](../../Networking/Protocols/HTTP/http_versions.md) и отдает им веб-контент. В 2026 году Apache остается критически важным инструментом для сценариев, требующих динамической конфигурации через `.htaccess` и богатой экосистемы модулей.

## Основные концепции

### Конфигурационные файлы

Основная конфигурация Apache находится в текстовых файлах. Расположение зависит от операционной системы:

*   **Ubuntu/Debian:** `/etc/apache2/apache2.conf`
*   **RHEL/Rocky Linux/AlmaLinux:** `/etc/httpd/conf/httpd.conf`

**Структура конфигурации:**

*   **/etc/httpd/conf/httpd.conf**: Основной файл конфигурации.
*   **/etc/httpd/conf.d/**: Директория для дополнительных конфигурационных файлов (`.conf`). Apache автоматически подгружает все файлы из этой директории. Это стандартная практика для разделения конфигурации на логические части (например, для каждого сайта).
*   **Расширения файлов**: Для корректной работы (например, при использовании `a2ensite` в Debian/Ubuntu) файлы конфигурации в `sites-available` или `conf.d` должны иметь расширение `.conf`. В противном случае они могут быть проигнорированы сервером.

**Ключевые директивы в `httpd.conf`:**

*   **`ServerRoot`**: Определяет корневую директорию, где хранятся конфигурационные файлы сервера, логи и другие ресурсы. По умолчанию часто `/etc/httpd`.
*   **`Listen`**: Указывает IP-адрес и порт, на котором Apache будет прослушивать входящие соединения. По умолчанию `Listen 80`. Для IPv6: `Listen [::]:80`.
*   **`User apache`, `Group apache`**: Пользователь и группа, от имени которых будут работать дочерние процессы Apache. В системах с SELinux, корректный [контекст безопасности](../../Linux/Security/Mechanisms/SELinux.md) является критически важным для доступа к файлам.
*   **`DocumentRoot`**: Определяет корневую директорию для файлов веб-сайта. По умолчанию `/var/www/html`.
*   **`Include` / `IncludeOptional`**: Позволяет включать другие конфигурационные файлы (например, `IncludeOptional conf.d/*.conf`), что используется для модульной организации, например, для виртуальных хостов.

### Уровни конфигурации (Scopes)

Параметры Apache могут быть ограничены определенными контекстами:

1.  **Глобальный**: Настройки вне любых контейнеров.
2.  **Директории (`<Directory path>`)**: Применяется к указанному пути в файловой системе и его поддиректориям.
3.  **URL-пути (`<Location URL>`)**: Применяется к пути в URL запроса.
4.  **Файлы (`<Files filename>`)**: Применяется к конкретным файлам.
5.  **Виртуальные хосты (`<VirtualHost>`)**: Группировка настроек для конкретного домена или IP.

### Контроль доступа

В Apache 2.4+ используется система управления доступом на основе директивы `Require`:

```apacheconf
<Directory "/var/www/html/private">
    # Разрешить доступ только из локальной сети
    Require ip 192.168.1.0/24
    
    # Либо разрешить только конкретному пользователю
    # Require user admin
    
    # По умолчанию для публичных зон
    # Require all granted
</Directory>
```

### Модульная система

Apache имеет модульную архитектуру, позволяющую динамически подключать функциональность (сжатие, аутентификация, проксирование).

*   **RHEL/Rocky**: Модули загружаются через `LoadModule` в основном конфиге или файлах в `conf.modules.d/`.
*   **Debian/Ubuntu**: Используются утилиты управления:
    *   `a2enmod <module_name>` — включить модуль (создает симлинк в `mods-enabled`).
    *   `a2dismod <module_name>` — выключить модуль.

### Логирование

Apache поддерживает гибкую настройку журналов.

*   **ErrorLog**: Журнал ошибок сервера (`/var/log/httpd/error_log`).
*   **CustomLog**: Журнал доступа клиентов (`/var/log/httpd/access_log`).
*   **LogFormat**: Определяет формат записи (например, `combined` — стандарт для анализа логов).

```apacheconf
LogFormat "%h %l %u %t \"%r\" %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" combined
CustomLog "logs/access_log" combined
```

### Виртуальные хосты

Для размещения нескольких сайтов на одном сервере используются **виртуальные хосты**. Их конфигурации обычно размещаются в отдельных файлах в директории `conf.d/` или `sites-available/`.

**Пример виртуального хоста:**

```apacheconf
<VirtualHost *:80>
    ServerName site1.example.com
    DocumentRoot /var/www/site1
    ErrorLog logs/site1_error.log
    CustomLog logs/site1_access.log combined
</VirtualHost>

<VirtualHost [2001:db8::10]:80>
    ServerName ipv6.example.com
    DocumentRoot /var/www/ipv6
</VirtualHost>
```

Чтобы Apache начал слушать дополнительный порт, необходимо добавить директиву `Listen 8080` в основной конфиг.

### Файлы `.htaccess`

Файлы `.htaccess` — это распределенные конфигурационные файлы, которые позволяют управлять настройками сервера на уровне отдельных директорий.

*   **Преимущества**: Позволяют делегировать управление частью конфигурации разработчикам без доступа к основным файлам.
*   **Недостатки**: Снижают производительность, так как Apache ищет и обрабатывает `.htaccess` в каждой директории при каждом запросе. Рекомендуется отключать (`AllowOverride None`), если есть доступ к основному конфигу.

В отличие от Apache, Nginx не поддерживает аналог `.htaccess`. Подробнее см. [сравнение с Nginx](../Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).

## Практические сценарии

### Установка

**RHEL/Rocky Linux/AlmaLinux:**

```bash
sudo dnf install httpd
```

**Ubuntu/Debian:**

```bash
sudo apt update && sudo apt install apache2
```

Установка и базовая настройка могут быть автоматизированы с помощью [Ansible](../../Ansible/PlaybookStructure/basics.md).

### Управление службой

Для управления используется [systemctl](../../Linux/Core/systemd/service_management.md).

1.  **Проверить статус службы:**

    ```bash
    sudo systemctl status httpd # → active (running)
    ```

2.  **Утилиты управления (Debian/Ubuntu):**
    *   `a2ensite <config>` — включить виртуальный хост.
    *   `a2dissite <config>` — выключить виртуальный хост.
    *   `apache2ctl configtest` — проверить синтаксис конфигурации.

3.  **Проверить прослушиваемые порты:** Подробнее об утилите см. [**`ss`**](../../Linux/Diagnostics/Networking/ss.md).

    ```bash
    sudo ss -tlpn | grep httpd # → LISTEN 0 128 *:80 *:*
    ```

### Включение HTTP/2

Современный стандарт для ускорения загрузки страниц. Требует модуля `mod_http2` и TLS.

```apacheconf
# В основном конфиге или VirtualHost
Protocols h2 http/1.1
```

### Настройка SSL/TLS (HTTPS)

Для работы HTTPS необходим модуль `mod_ssl` и SSL-сертификат (например, от [Let's Encrypt](../Concepts/https_with_certbot.md)).

```apacheconf
<VirtualHost *:443>
    ServerName secure.example.com
    DocumentRoot /var/www/secure

    SSLEngine on
    SSLCertificateFile /etc/pki/tls/certs/example.crt
    SSLCertificateKeyFile /etc/pki/tls/private/example.key
    
    # Настройки безопасности TLS (актуально на 2026 год)
    SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
    SSLCipherSuite HIGH:!aNULL:!MD5
    SSLHonorCipherOrder on
</VirtualHost>
```

### Настройка обратного прокси (Reverse Proxy)

Apache может выступать в роли прокси-сервера для других приложений (Node.js, Python и др.). Требуются модули `mod_proxy` и `mod_proxy_http`.

```apacheconf
<VirtualHost *:80>
    ServerName app.example.com

    ProxyPreserveHost On
    ProxyPass / http://127.0.0.1:3000/
    ProxyPassReverse / http://127.0.0.1:3000/
</VirtualHost>
```

### Интеграция с PHP через PHP-FPM

Рекомендуемый способ работы с PHP для высокой производительности.

```apacheconf
<FilesMatch \.php$>
    SetHandler "proxy:fcgi://127.0.0.1:9000"
</FilesMatch>
```

### Настройка Firewall (RHEL-based)

```bash
sudo firewall-cmd --permanent --add-service={http,https}
sudo firewall-cmd --reload
```

## Дополнительная информация

### Архитектура и модули обработки (MPM)

Apache использует модульную архитектуру **Multi-Processing Modules (MPM)** для обработки запросов.

*   **`Prefork`**: Старая модель, один процесс на соединение. Надежна для старых PHP-модулей (mod_php), но потребляет много памяти.
*   **`Worker`**: Гибридная модель (процессы + потоки). Более эффективна при большом количестве соединений.
*   **`Event`**: **Современный стандарт**. Оптимизирован для `Keep-Alive`, использует асинхронную обработку. По умолчанию во многих современных дистрибутивах.

### Протокол HTTP/3 (QUIC)

На июль 2026 года поддержка HTTP/3 в Apache находится в стадии активной разработки и доступна через сторонние модули или экспериментальные сборки. Для полноценного внедрения HTTP/3 на текущий момент чаще используются Nginx или Angie.

### Сравнение с Nginx

Apache выигрывает в гибкости и возможности динамической настройки через `.htaccess`, что удобно для shared-хостингов. Nginx превосходит в производительности при обработке статики и огромного количества одновременных подключений (C10k). Оптимальная связка: Nginx как фронтенд (SSL + статика) и Apache как бэкенд. Подробнее см. [сравнение с Nginx](../Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).

### См. также

*   [Укрепление безопасности Apache](./apache_hardening.md) — руководство по защите сервера.
*   [Тестирование производительности веб-серверов](../webserver_benchmarking.md) — использование `ab` (Apache Benchmark).
*   [Мониторинг Apache](../../Prometheus/Exporters/other_exporters.md#apache_exporter) — использование экспортера для Prometheus.
