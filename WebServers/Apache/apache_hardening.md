# Укрепление безопасности Apache

---

## Определения

**Укрепление безопасности Apache (Apache hardening)** — это процесс настройки веб-сервера с целью уменьшения его поверхности атаки и защиты от распространенных уязвимостей. Основная задача — минимизировать риски путем отключения ненужных функций, ограничения доступа и контроля над системными ресурсами.

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

Выбор модуля обработки запросов (MPM) напрямую влияет на поверхность атаки, изоляцию процессов и устойчивость сервера к DoS-атакам. Рекомендуется использовать `event` MPM для лучшей обработки большого количества соединений. Детальное сравнение приведено в **[Обзор Apache](./apache_overview.md)**.

## Практические сценарии

### Безопасность файловой системы

**Проблема:** Неправильные права доступа позволяют злоумышленнику, захватившему веб-процесс, изменять код сайта или читать конфиденциальные файлы.

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

**Проблема:** Атаки типа Slowloris удерживают соединения открытыми, отправляя данные крайне медленно.

**Решение:** Использовать модуль `mod_reqtimeout`.

```apacheconf
<IfModule mod_reqtimeout.c>
    # Ждать заголовки 20-40 секунд, минимальная скорость 500 байт/с
    RequestReadTimeout header=20-40,MinRate=500
    # Ждать тело запроса 20 секунд, минимальная скорость 500 байт/с
    RequestReadTimeout body=20,MinRate=500
</IfModule>
```

### Дополнительные заголовки безопасности

**Проблема:** Отсутствие специальных заголовков делает пользователей уязвимыми для кликджекинга и XSS.

**Решение:** Использование `mod_headers`.

```apacheconf
# 1. HSTS — принудительный HTTPS на 2 года
Header always set Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

# 2. Защита от кликджекинга
Header always set X-Frame-Options "SAMEORIGIN"

# 3. Запрет MIME-sniffing
Header always set X-Content-Type-Options "nosniff"

# 4. Referrer Policy
Header always set Referrer-Policy "strict-origin-when-cross-origin"

# 5. Content Security Policy (CSP)
Header always set Content-Security-Policy "default-src 'self'; script-src 'self'; object-src 'none'"
```

### Защита от атак через символические ссылки

**Решение:** Заменить `FollowSymLinks` на `SymLinksIfOwnerMatch`.

```apacheconf
<Directory /var/www/html>
    Options -FollowSymLinks +SymLinksIfOwnerMatch
</Directory>
```

### Отключение листинга каталогов

**Решение:** Директива `Options -Indexes`.

```apacheconf
<Directory /var/www/html>
    Options -Indexes
</Directory>
```

### Защита конфиденциальных каталогов

**Решение:** Ограничить доступ по IP и добавить аутентификацию для служебных страниц.

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

**Решение:** Скрыть пути и версии через `ErrorDocument`.

```apacheconf
ErrorDocument 404 /custom404.html
ErrorDocument 500 /custom500.html
```

### Настройка и анализ журналов

**Решение:** Настройка структурированных логов для SIEM.

```apacheconf
LogFormat "%h \"%{X-Forwarded-For}i\" %A %p %u %f %t %m %V %U \"%q\" %H %>s %b \"%{Referer}i\" \"%{User-Agent}i\"" tosiem
LogLevel info
ErrorLog syslog:local4
CustomLog "|/usr/bin/logger -p local4.info -t apache" tosiem
```

### Скрытие информации о сервере

**Решение:** Минимизировать заголовки.

```apacheconf
ServerTokens Prod
ServerSignature Off
TraceEnable Off
```

### Настройка SSL/TLS

**Решение:** Разрешить только современные протоколы.

```apacheconf
SSLProtocol all -SSLv3 -TLSv1 -TLSv1.1
SSLCipherSuite HIGH:!aNULL:!MD5
SSLHonorCipherOrder on
```

### Отключение ненужных HTTP-методов

**Решение:** Ограничить методы через `<LimitExcept>`.

```apacheconf
<Directory "/var/www/html">
    <LimitExcept GET POST HEAD>
        Require all denied
    </LimitExcept>
</Directory>
```

### Укрепление через systemd (Новое)

**Решение:** Ограничить возможности процесса Apache на уровне ядра через unit-файл (`/etc/systemd/system/httpd.service.d/override.conf`).

```ini
[Service]
# Запрет доступа к /home, /root и /run/user
ProtectHome=true
# Доступ к /usr, /boot и /etc только на чтение
ProtectSystem=full
# Изолированный /tmp
PrivateTmp=true
# Запрет получения новых привилегий (suid и т.д.)
NoNewPrivileges=true
# Ограничение системных вызовов
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
```

### Интеграция с Fail2Ban (Новое)

**Решение:** Автоматическая блокировка IP при попытках подбора пароля или сканировании.

```ini
# /etc/fail2ban/jail.local
[apache-auth]
enabled = true
port    = http,https
filter  = apache-auth
logpath = /var/log/apache2/error.log
maxretry = 3
```

## Дополнительная информация

### Изоляция на уровне ОС

*   **SELinux**: В RHEL-системах необходимо проверять контексты файлов (`httpd_sys_content_t`). Подробнее: **[SELinux](../../Linux/Security/Mechanisms/SELinux.md)**.
*   **AppArmor**: В Ubuntu/Debian используются профили для ограничения доступа процесса к файловой системе.

### См. также

*   **[Обзор Apache](./apache_overview.md)** — архитектура и MPM.
*   **[Укрепление безопасности Nginx](../Nginx/Security/nginx_security_guide.md)** — сравнение подходов.
*   **[Обзор WAF](../../Security/ApplicationSecurity/waf.md)** — глубокая инспекция L7.
