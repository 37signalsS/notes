# Укрепление безопасности Apache

---

**Reliability Score: 10** (Верифицированные данные + Современные стандарты 2026 года)
**Freshness: Актуально на июль 2026**

---

## Определения

**Укрепление безопасности Apache (Apache hardening)** — это процесс настройки веб-сервера с целью уменьшения его поверхности атаки и защиты от распространенных уязвимостей. Основная задача — минимизировать риски путем отключения ненужных функций, ограничения доступа и контроля над ресурсами.

## Основные концепции

### Расположение конфигурационных файлов

- **Основной конфиг (Debian/Ubuntu):** `/etc/apache2/apache2.conf`
- **Основной конфиг (RHEL/Rocky/AlmaLinux):** `/etc/httpd/conf/httpd.conf`
- **Виртуальные хосты (Debian/Ubuntu):** `/etc/apache2/sites-available/`
- **Виртуальные хосты (RHEL/Rocky/AlmaLinux):** `/etc/httpd/conf.d/`

### Ключевые модули безопасности

Для минимизации поверхности атаки рекомендуется отключать неиспользуемые модули, оставляя только необходимые:

- **`mod_security`** — WAF (Web Application Firewall). Подробные правила и примеры см. в **[Обзор WAF](../../Security/ApplicationSecurity/waf.md)**.
- **`mod_headers`** — управление HTTP-заголовками (CSP, HSTS, X-Frame-Options).
- **`mod_ssl`** — поддержка TLS и управление сертификатами.
- **`mod_evasive`** — базовая защита от DoS и Brute-force на уровне IP.
- **`mod_reqtimeout`** — критически важен для защиты от атак типа Slowloris.

### MPM и безопасность

Выбор модуля обработки запросов (MPM) напрямую влияет на поверхность атаки, изоляцию процессов и устойчивость сервера к DoS-атакам. Детальное сравнение архитектур `prefork`, `worker` и `event` приведено в **[Обзор Apache](./apache_overview.md)**.

## Практические сценарии

### Безопасность файловой системы

**Проблема:** Неправильные права доступа позволяют злоумышленнику, захватившему веб-процесс, изменять код сайта или читать конфиденциальные файлы конфигурации.

**Решение:** Следовать принципу наименьших привилегий. Веб-сервер должен иметь права только на чтение контента.

```bash
# Владелец — root, группа — веб-пользователь (www-data или apache)
sudo chown -R root:www-data /var/www/html
# Директории: 750 (rwxr-x---)
sudo find /var/www/html -type d -exec chmod 750 {} \;
# Файлы: 640 (rw-r-----)
sudo find /var/www/html -type f -exec chmod 640 {} \;

# Исключение для каталогов загрузки (только если необходимо!)
sudo chown -R www-data:www-data /var/www/html/uploads
```

### Защита от Slowloris (Тайм-ауты)

**Проблема:** Атаки типа Slowloris удерживают соединения открытыми, отправляя данные крайне медленно, что быстро исчерпывает лимит доступных процессов/потоков (`MaxRequestWorkers`).

**Решение:** Использовать модуль `mod_reqtimeout` для установки жестких таймаутов на чтение заголовков и тела запроса.

```apacheconf
<IfModule mod_reqtimeout.c>
    # Ждать заголовки 20 секунд, минимальная скорость 500 байт/с
    RequestReadTimeout header=20-40,MinRate=500
    # Ждать тело запроса 20 секунд, минимальная скорость 500 байт/с
    RequestReadTimeout body=20,MinRate=500
</IfModule>
```

### Дополнительные заголовки безопасности

**Проблема:** Отсутствие специальных заголовков делает пользователей уязвимыми для кликджекинга, XSS и перехвата трафика (SSL Stripping).

**Решение:** Использование `mod_headers` для принудительной активации механизмов защиты в браузере.

```apacheconf
# 1. HSTS — принудительный HTTPS на 2 года
Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

# 2. Защита от кликджекинга (запрет вставки в iframe)
Header always set X-Frame-Options "SAMEORIGIN"

# 3. Запрет MIME-sniffing
Header always set X-Content-Type-Options "nosniff"

# 4. Referrer Policy
Header always set Referrer-Policy "strict-origin-when-cross-origin"
```

### Защита от атак через символические ссылки

**Проблема:** Если включена опция `FollowSymLinks`, злоумышленник может создать ссылку на чувствительный файл (например, `/etc/passwd`) внутри веб-каталога и прочитать его через сервер.

**Решение:** Заменить `FollowSymLinks` на `SymLinksIfOwnerMatch` или полностью отключить переход по ссылкам.

```apacheconf
<Directory /var/www/html>
    Options -FollowSymLinks +SymLinksIfOwnerMatch
</Directory>
```

### Отключение листинга каталогов

**Проблема:** По умолчанию Apache выводит содержимое директорий, если в них отсутствуют индексные файлы. Это раскрывает структуру проекта.

**Решение:** Отключить листинг каталогов с помощью директивы `Options -Indexes`.

```apacheconf
<Directory /var/www/html>
    Options -Indexes
</Directory>
```

### Защита конфиденциальных каталогов

**Проблема:** Служебные страницы (`/server-status`, `/server-info`) предоставляют детали о работе сервера.

**Решение:** Ограничить доступ по IP и добавить базовую аутентификацию.

```apacheconf
<Location "/server-status">
  SetHandler server-status
  Require ip 192.168.0.0/24
  AuthType Basic
  AuthName "Server status"
  AuthUserFile /etc/apache2/.htpasswd
  Require valid-user
</Location>

<Location "/server-info">
  SetHandler server-info
  Require ip 192.168.0.0/24
  AuthType Basic
  AuthName "Server info"
  AuthUserFile /etc/apache2/.htpasswd
  Require valid-user
</Location>
```

### Ограничение размера запроса

**Проблема:** Чрезмерно большие запросы могут привести к DoS или переполнению буфера.

**Решение:** Использовать `LimitRequestBody`.

```apacheconf
<VirtualHost *:80>
    ServerName example.com
    LimitRequestBody 102400 # 100 КБ для всего сайта

    <Directory "/var/www/uploads">
        LimitRequestBody 10485760 # 10 МБ для загрузок
    </Directory>
</VirtualHost>
```

### Использование пользовательских страниц ошибок

**Решение:** Скрыть версию сервера и пути через `ErrorDocument`.

```apacheconf
ErrorDocument 404 /custom404.html
ErrorDocument 500 /custom500.html
```

### Настройка и анализ журналов

**Решение:** Настроить структурированные логи и их отправку в [syslog](../../Linux/SystemAdministration/Logging/rsyslog.md) для последующего анализа в [SIEM](../../Security/Tools/wazuh.md). Подробнее: **[Обзор логирования](../../Linux/SystemAdministration/Logging/logging_overview.md)**.

```apacheconf
LogFormat "%h \"%{X-Forwarded-For}i\" %A %p %u %f %t %m %V %U \"%q\" %H %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" tosiem
LogLevel info
ErrorLog syslog:local4
CustomLog "|/usr/bin/logger -p local4.info -t apache" tosiem
```

### Скрытие информации о сервере

**Решение:** Минимизировать заголовки `Server` и отключить подписи.

```apacheconf
ServerTokens Prod
ServerSignature Off
TraceEnable Off
```

### Реализация политики безопасности контента (CSP)

```apacheconf
<Directory "/var/www/html/admin">
    Header set Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'"
</Directory>
```

### Настройка SSL/TLS

**Решение:** Разрешить только TLS 1.2 и 1.3 с надежными шифрами.

```apacheconf
SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
SSLCipherSuite HIGH:!aNULL:!MD5
SSLHonorCipherOrder on
```

### Отключение ненужных HTTP-методов

```apacheconf
<Directory "/var/www/html">
    <LimitExcept GET POST HEAD>
        Require all denied
    </LimitExcept>
</Directory>
```

## Дополнительная информация

*   **[Укрепление безопасности Nginx](../Nginx/Security/nginx_security_guide.md)** — сравнение подходов.
*   **[Обзор WAF](../../Security/ApplicationSecurity/waf.md)** — глубокая инспекция L7.
