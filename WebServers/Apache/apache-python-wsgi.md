# Apache: Интеграция Python (mod_wsgi) и серверов приложений

**Актуально для:** Apache httpd 2.4.x, mod_wsgi 4.9.x / 5.0.x, Python 3.10+ / 3.12+, uWSGI 2.0.x

---

## Определения

**WSGI (Web Server Gateway Interface)** — стандарт интерфейса между веб-сервером и Python-приложением ([PEP 3333](https://peps.python.org/pep-3333/)). Сервер передает в вызываемый объект приложения словарь переменных запроса (`environ`) и функцию инициализации HTTP-ответа (`start_response`), а приложение возвращает итерируемый объект с телом ответа.

**ASGI (Asynchronous Server Gateway Interface)** — асинхронный стандарт интерфейса для Python (FastAPI, Starlette, Django Channels), пришедший на смену WSGI для поддержки событийных циклов (`asyncio`), WebSockets и HTTP/2. `mod_wsgi` не поддерживает ASGI нативно; в таких сценариях Apache выступает обратным прокси (`mod_proxy_http`) к выделенным ASGI-серверам (Uvicorn, Hypercorn, Daphne).

**mod_wsgi** — специализированный C-модуль веб-сервера Apache HTTP Server, реализующий интерфейс WSGI и обеспечивающий хостинг Python-приложений. Поддерживает два режима работы: встроенный (**Embedded mode**) и режим демона (**Daemon mode**).

**Embedded Mode (Встроенный режим)** — режим работы `mod_wsgi`, при котором среда исполнения Python инициализируется непосредственно внутри рабочих процессов MPM Apache (`httpd`). Запросы обрабатываются потоками или процессами самого Apache.

**Daemon Mode (Режим демона)** — промышленный стандарт развертывания `mod_wsgi`, при котором Python-приложения исполняются в изолированном пуле выделенных процессов операционной системы, управляемых супервизором `mod_wsgi`. Взаимодействие между воркерами Apache и демонами происходит через локальные UNIX domain сокеты.

**WSGIDaemonProcess** — директива конфигурации Apache, определяющая пул процессов демона `mod_wsgi`, параметры виртуального окружения, системного пользователя/группу, число процессов и потоков, лимиты памяти и таймауты.

**WSGIProcessGroup** — директива, связывающая контекст виртуального хоста или каталога с конкретным именованным пулом `WSGIDaemonProcess`.

**WSGIScriptAlias** — директива, сопоставляющая URL-префикс запроса с файловой точкой входа приложения (`.wsgi` скриптом), автоматически назначая обработчик WSGI.

**WSGIApplicationGroup** — директива изоляции сред исполнения Python внутри процесса. Значение `%{GLOBAL}` принудительно запускает приложение в контексте главного интерпретатора CPython, предотвращая сбои C-расширений.

**WSGIPassAuthorization** — директива, разрешающая проброс HTTP-заголовка `Authorization` (Bearer-токены, Basic Auth) в WSGI-словарь `environ['HTTP_AUTHORIZATION']`. По умолчанию Apache перехватывает этот заголовок для внутренних модулей аутентификации.

**WSGISocketPrefix** — директива уровня сервера, задающая путь к каталогу для размещения служебных UNIX-сокетов межпроцессного взаимодействия (IPC) между воркерами Apache и демонами `mod_wsgi`.

**mod_proxy_uwsgi** — модуль Apache для передачи запросов на сервер приложений uWSGI по компактному бинарному протоколу `uwsgi`.

**Phusion Passenger (`mod_passenger`)** — альтернативный многоязычный менеджер приложений (Python/Ruby/Node.js) для Apache с динамическим масштабированием процессов.

---

## Основные концепции и архитектура

### Архитектура взаимодействия и топология запроса

В современной инфраструктуре Apache перед Python-приложениями выступает в роли фронтенда (Edge/Reverse Proxy/Web Server), отвечающего за терминацию TLS, обслуживание статических файлов, защиту от перегрузок и маршрутизацию:

```
[ Клиент (HTTP/HTTPS) ]
         │
         ▼
[ Apache HTTPD (event MPM) ]
   ├── Статика: Alias /static/ ──► [ Файловая система (без вызова Python) ]
   │
   ├── Сценарий A: mod_wsgi daemon mode
   │   └── UNIX Domain Socket ──► [ mod_wsgi daemon pool ] ──► [ WSGI App (Flask/Django) ]
   │
   ├── Сценарий B: Reverse Proxy к Gunicorn/Uvicorn
   │   └── mod_proxy_http (UDS/TCP) ──► [ Gunicorn / Uvicorn (Systemd) ] ──► [ WSGI/ASGI App ]
   │
   └── Сценарий C: Reverse Proxy к uWSGI
       └── mod_proxy_uwsgi (UDS/TCP) ──► [ uWSGI Master/Workers ] ──► [ WSGI App ]
```

### Сравнение архитектур: Embedded vs Daemon vs Standalone Proxy

| Критерий | `mod_wsgi` Embedded | `mod_wsgi` Daemon | Apache + Standalone (Gunicorn/uWSGI) |
|---|---|---|---|
| **Где живет код Python** | Внутри воркеров Apache `httpd` | В выделенных процессах `mod_wsgi` | В независимом системном сервисе (systemd) |
| **Совместимость с MPM** | Требует `prefork` (тяжелый) | Полная с `event` и `worker` MPM | Полная с `event` и `worker` MPM |
| **Потребление памяти** | Катастрофическое (каждый поток `httpd` раздут CPython) | Фиксированное (память ограничена пулом демонов) | Фиксированное (память сервиса изолирована) |
| **Изоляция прав (UID/GID)** | Только под пользователем Apache (`www-data`) | Произвольный системный пользователь (`user=...`) | Полная изоляция через systemd (`User=...`) |
| **Перезагрузка кода** | Полный рестарт всего Apache | `touch script.wsgi` (без разрыва соединений) | `systemctl reload` или HUP сигнал |
| **Поддержка ASGI/FastAPI** | Нет | Нет | Да (через Uvicorn worker в Gunicorn) |
| **Рекомендация для Production** | **Запрещено** | **Рекомендуется для WSGI On-Premise** | **Рекомендуется для микросервисов и ASGI** |

### Почему Embedded-режим не применяется в Production

1. **Раздувание оперативной памяти (Memory Bloat):** В embedded-режиме модуль CPython загружается во все процессы Apache. Если веб-сервер настроен на обслуживание сотен параллельных соединений (Keep-Alive, отдача статики), каждый процесс `httpd` разрастается со стандартных 5–10 МБ до 100–300 МБ из-за загруженных библиотек Python, что приводит к исчерпанию RAM и OOM Killer.
2. **Конфликт MPM и потокобезопасности:** `event MPM` использует многопоточность. Не все сторонние C-расширения Python потокобезопасны. В Embedded-режиме аварийное завершение CPython (Segmentation Fault) приводит к падению рабочего процесса Apache со всеми обслуживаемыми клиентскими соединениями.
3. **Безопасность:** Встроенный режим вынуждает приложение выполняться с правами системного пользователя Apache (`www-data` или `apache`). Компрометация одного сайта дает доступ ко всем остальным VirtualHost сервера.

### Многопоточность, процессы и GIL (Global Interpreter Lock)

CPython использует глобальную блокировку интерпретатора (GIL), которая разрешает выполнять байткод Python только одному потоку в рамках одного процесса операционной системы в каждый момент времени. Это определяет выбор архитектуры пула `WSGIDaemonProcess`:

*   **I/O-bound профиль нагрузки (веб-приложения, API, запросы к PostgreSQL, Redis, внешним API):**
    Потоки эффективно освобождают GIL во время ожидания сетевых и дисковых операций. Оптимальна конфигурация с умеренным числом процессов и большим числом потоков:
    `processes=4 threads=15` (дает емкость в 60 параллельных запросов при небольшом расходе памяти).
*   **CPU-bound профиль нагрузки (генерация тяжелых отчетов, обработка изображений, парсинг):**
    Многопоточность внутри одного процесса упрется в GIL и приведет к деградации задержек (latency spike). Требуется многопроцессная модель с минимальным числом потоков на процесс:
    `processes=8 threads=1` (число процессов подбирается под количество физических ядер CPU).

### Проблема C-расширений и субинтерпретаторы (`WSGIApplicationGroup`)

По умолчанию `mod_wsgi` изолирует приложения в так называемых **субинтерпретаторах** CPython (`sub-interpreters`). Это позволяет запускать несколько приложений в рамках одного процесса демона без конфликта глобальных переменных.

Однако популярные C-расширения (`numpy`, `scipy`, `pandas`, `grpc`, `lxml`, `cryptography`) полагаются на глобальные статические переменные в C-коде, которые не дублируются между субинтерпретаторами. При вызове таких библиотек во втором субинтерпретаторе возникают дедлоки GIL, сбои импорта или `SIGSEGV`.

**Инфраструктурное правило:** Для любых production-приложений на Django/Flask/ML всегда задавайте:
```apacheconf
WSGIApplicationGroup %{GLOBAL}
```
Это гарантирует исполнение кода в основном (главном) контексте интерпретатора CPython (`__main__`).

### Жизненный цикл процессов демона и утечки памяти

В долгоживущих Python-процессах неизбежна фрагментация памяти аллокатором `glibc` (`ptmalloc`) и утечки из-за циклических ссылок. Директива `WSGIDaemonProcess` предоставляет встроенные защитные механизмы:

*   `maximum-requests=5000` — процесс демона плавно завершается и перезапускается после обработки указанного числа запросов.
*   `request-timeout=60` — принудительное завершение демона, если обработка единичного запроса зависла дольше 60 секунд.
*   `inactivity-timeout=300` — завершение незадействованных процессов при отсутствии нагрузки (актуально для экономии памяти на dev/staging).
*   `shutdown-timeout=15` — время, выделяемое процессу на корректное закрытие сокетов и транзакций перед отправкой жесткого `SIGKILL`.

---

## Практические сценарии

### Сценарий 1: Продакшн-развертывание Django/Flask через `mod_wsgi` Daemon Mode

Сценарий реализует запуск под выделенным сервисным пользователем `myapp` с виртуальным окружением `venv`, строгой изоляцией прав, раздачей статики через Apache и защитой от утечек памяти.

#### 1. Подготовка ОС и окружения (Debian/Ubuntu или RHEL/Rocky)

```bash
# Ubuntu / Debian:
sudo apt-get update && sudo apt-get install -y apache2 libapache2-mod-wsgi-py3 python3-venv

# RHEL 9 / Rocky Linux 9:
sudo dnf install -y httpd python3-mod_wsgi python3
sudo setsebool -P httpd_can_network_connect 1

# Создание сервисного пользователя без оболочки
sudo useradd -r -s /usr/sbin/nologin -d /opt/myapp myapp

# Подготовка структуры каталогов
sudo mkdir -p /opt/myapp/{app,static,media,logs,venv}
sudo python3 -m venv /opt/myapp/venv

# Установка зависимостей в venv
sudo /opt/myapp/venv/bin/pip install --upgrade pip
sudo /opt/myapp/venv/bin/pip install django gunicorn

# Назначение прав: владелец myapp, группа www-data (чтение для Apache)
sudo chown -R myapp:www-data /opt/myapp
sudo chmod 750 /opt/myapp
sudo chmod -R 750 /opt/myapp/app
sudo chmod -R 755 /opt/myapp/static
```

#### 2. Создание точки входа WSGI (`/opt/myapp/app/wsgi.py`)

```python
import os
import sys

# Добавление корня приложения в путь поиска модулей
sys.path.insert(0, '/opt/myapp/app')

# Настройка окружения Django (или Flask)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

#### 3. Глобальная конфигурация `mod_wsgi` (`/etc/apache2/conf-available/mod-wsgi-global.conf` или `/etc/httpd/conf.d/wsgi-global.conf`)

```apacheconf
# Запрет небезопасного встроенного режима во всем сервере
WSGIRestrictEmbedded On

# Каталог для сокетов IPC (должен находиться в tmpfs /run с правами для Apache)
# Debian/Ubuntu: /var/run/apache2/wsgi
# RHEL/CentOS:   /run/httpd/wsgi
WSGISocketPrefix /var/run/apache2/wsgi
```

#### 4. Виртуальный хост Apache (`/etc/apache2/sites-available/myapp.conf`)

```apacheconf
<VirtualHost *:80>
    ServerName app.example.com
    ServerAdmin admin@example.com

    DocumentRoot /opt/myapp/app

    # Настройка пула процессов демона mod_wsgi
    WSGIDaemonProcess myapp \
        user=myapp \
        group=www-data \
        processes=4 \
        threads=10 \
        python-home=/opt/myapp/venv \
        python-path=/opt/myapp/app \
        display-name=%{GROUP} \
        maximum-requests=5000 \
        request-timeout=60 \
        inactivity-timeout=300 \
        shutdown-timeout=15 \
        listen-backlog=100

    # Привязка виртуального хоста к пулу демона
    WSGIProcessGroup myapp

    # Принудительное выполнение в главном интерпретаторе Python
    WSGIApplicationGroup %{GLOBAL}

    # Проброс заголовков авторизации (Bearer JWT / Basic)
    WSGIPassAuthorization On

    # Точка входа приложения
    WSGIScriptAlias / /opt/myapp/app/wsgi.py

    <Directory /opt/myapp/app>
        <Files wsgi.py>
            Require all granted
        </Files>
    </Directory>

    # Обслуживание статических файлов силами Apache (в обход Python)
    Alias /static/ /opt/myapp/static/
    <Directory /opt/myapp/static>
        Require all granted
        Options -Indexes -FollowSymLinks
        
        # Кэширование статики на клиенте
        <IfModule mod_expires.c>
            ExpiresActive On
            ExpiresDefault "access plus 30 days"
        </IfModule>
        <IfModule mod_headers.c>
            Header append Cache-Control "public, immutable"
        </IfModule>
    </Directory>

    # Загружаемые медиа-файлы (запрет исполнения любых скриптов)
    Alias /media/ /opt/myapp/media/
    <Directory /opt/myapp/media>
        Require all granted
        Options -Indexes
        AllowOverride None
        Header set X-Content-Type-Options "nosniff"
    </Directory>

    # Логирование
    ErrorLog ${APACHE_LOG_DIR}/myapp_error.log
    CustomLog ${APACHE_LOG_DIR}/myapp_access.log combined
    LogLevel warn
</VirtualHost>
```

Активация и запуск:
```bash
sudo a2enconf mod-wsgi-global
sudo a2ensite myapp.conf
sudo apache2ctl configtest
# → Syntax OK
sudo systemctl reload apache2
```

---

### Сценарий 2: Архитектура Apache + Gunicorn/Uvicorn через UNIX Domain Socket

Для современных асинхронных фреймворков (FastAPI, Starlette) или при стандартизации микросервисов в systemd Apache настраивается как высокопроизводительный обратный прокси. Связь через UNIX Domain Socket устраняет оверхед TCP-стека и повышает безопасность.

#### 1. Systemd-сервер Gunicorn/Uvicorn (`/etc/systemd/system/myapp-gunicorn.service`)

```ini
[Unit]
Description=Gunicorn WSGI Application Server for myapp
After=network.target

[Service]
Type=notify
User=myapp
Group=www-data
WorkingDirectory=/opt/myapp/app
RuntimeDirectory=myapp-gunicorn
ExecStart=/opt/myapp/venv/bin/gunicorn \
    --workers 4 \
    --threads 2 \
    --worker-class gthread \
    --bind unix:/run/myapp-gunicorn/gunicorn.sock \
    --umask 007 \
    --access-logfile - \
    --error-logfile - \
    myproject.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=15
PrivateTmp=true
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp-gunicorn.service
```

#### 2. Конфигурация виртуального хоста Apache (`/etc/apache2/sites-available/myapp-proxy.conf`)

```apacheconf
<VirtualHost *:80>
    ServerName api.example.com

    # Требуются модули: proxy, proxy_http
    ProxyPreserveHost On
    ProxyRequests Off

    # Передача клиентских заголовков
    RequestHeader set X-Forwarded-Proto "http"
    RequestHeader set X-Forwarded-Port "80"

    # Проксирование через Unix Domain Socket
    ProxyPass / "unix:/run/myapp-gunicorn/gunicorn.sock|http://localhost/" retry=1 acquire=3000 timeout=60
    ProxyPassReverse / "unix:/run/myapp-gunicorn/gunicorn.sock|http://localhost/"

    # Статика обслуживается локально
    ProxyPass /static/ !
    Alias /static/ /opt/myapp/static/
    <Directory /opt/myapp/static>
        Require all granted
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/myapp_proxy_error.log
    CustomLog ${APACHE_LOG_DIR}/myapp_proxy_access.log combined
</VirtualHost>
```

---

### Сценарий 3: Интеграция с uWSGI через `mod_proxy_uwsgi`

Протокол `uwsgi` является бинарным протоколом передачи данных, оптимизированным для низкого потребления ресурсов процессора.

#### 1. Конфигурация uWSGI (`/etc/uwsgi/apps-available/myapp.ini`)

```ini
[uwsgi]
project = myapp
base = /opt/myapp

chdir = %(base)/app
home = %(base)/venv
module = myproject.wsgi:application

master = true
processes = 4
threads = 2

uid = myapp
gid = www-data

socket = /run/uwsgi/%(project).sock
chmod-socket = 660
vacuum = true

max-requests = 5000
harakiri = 60
die-on-term = true
```

#### 2. Конфигурация виртуального хоста Apache

```apacheconf
<VirtualHost *:80>
    ServerName uwsgi.example.com

    # Требуется: mod_proxy, mod_proxy_uwsgi
    ProxyPass /static/ !
    Alias /static/ /opt/myapp/static/

    # Проксирование uwsgi через UNIX сокет
    ProxyPass / "unix:/run/uwsgi/myapp.sock|uwsgi://localhost/"
    ProxyPassReverse / "unix:/run/uwsgi/myapp.sock|uwsgi://localhost/"

    <Directory /opt/myapp/static>
        Require all granted
    </Directory>

    ErrorLog ${APACHE_LOG_DIR}/uwsgi_error.log
</VirtualHost>
```

---

### Сценарий 4: Бесшовный деплой и перезагрузка (Zero-Downtime Reload)

Супервизор `mod_wsgi` отслеживает время модификации (mtime) точки входа WSGI. Это позволяет обновлять код без перезагрузки веб-сервера Apache:

```bash
# 1. Точечный перезапуск конкретного WSGI-приложения через touch:
# Супервизор обнаружит изменение mtime и перезапустит воркеры после завершения текущих запросов
sudo touch /opt/myapp/app/wsgi.py

# 2. Плавный перезапуск через отправку сигнала конкретному процессу демона:
# Находим PID процесса с отображаемым именем (display-name=%{GROUP}):
pgrep -f "myapp" | xargs sudo kill -SIGINT

# 3. Graceful перезапуск Apache (перезагружает все пулы и конфиги без сброса TCP):
sudo apachectl -k graceful
# или через systemd:
sudo systemctl reload apache2
```

---

### Сценарий 5: Харденинг безопасности и изоляция ОС

1. **Запрет записи в директорию с кодом:** Процесс `mod_wsgi` должен иметь доступ только на чтение к Python-файлам. Запись разрешается строго в каталог `media` или локальные временные хранилища.
   ```bash
   # Владелец кода - отдельный пользователь сборки (deploy), Apache и myapp могут только читать:
   sudo chown -R root:myapp /opt/myapp/app
   sudo find /opt/myapp/app -type d -exec chmod 750 {} +
   sudo find /opt/myapp/app -type f -exec chmod 640 {} +
   ```
2. **SELinux в RHEL/Rocky Linux:**
   ```bash
   # Разрешение Apache обращаться к сокетам и локальным сервисам
   sudo setsebool -P httpd_can_network_connect 1

   # Назначение контекста для статических файлов и WSGI-скрипта
   sudo semanage fcontext -a -t httpd_sys_content_t "/opt/myapp/app(/.*)?"
   sudo semanage fcontext -a -t httpd_sys_content_t "/opt/myapp/static(/.*)?"
   sudo semanage fcontext -a -t httpd_sys_rw_content_t "/opt/myapp/media(/.*)?"
   sudo restorecon -Rv /opt/myapp
   ```
3. **Безопасность сокетов:** Запретить размещение сокетов `WSGISocketPrefix` в `/tmp` или `/var/tmp`, так как в общедоступных каталогах возможна атака типа symlink traversal. Использовать строго подкаталоги `/run` или `/var/run`, доступные только `root` и группе `www-data`/`apache`.

---

## Операции и команды

| Команда | Назначение | Ожидаемый результат / вывод |
|---|---|---|
| `apache2ctl -M \| grep -E 'wsgi\|proxy'` | Проверка загруженных модулей | `wsgi_module (shared)`<br>`proxy_module (shared)` |
| `ps aux -H \| grep -E 'apache2\|httpd\|mod_wsgi'` | Дерево процессов Apache и пула демонов | `www-data 1234 ... apache2`<br>`myapp 1235 ... (wsgi:myapp) -k start` |
| `ls -la /var/run/apache2/wsgi.*` | Проверка наличия и прав IPC-сокета | `srwx------ 1 www-data www-data 0 ... wsgi.1234.0.1.sock` |
| `sudo touch /opt/myapp/app/wsgi.py` | Плавная перезагрузка приложения без рестарта Apache | Изменение mtime файла; в `error.log`: `Reloading WSGI script '/opt/myapp/app/wsgi.py'` |
| `apachectl -t` | Проверка синтаксиса конфигурации Apache | `Syntax OK` |
| `curl -Iv http://app.example.com/` | Проверка статус-кода и заголовков ответа | `HTTP/1.1 200 OK`<br>`Server: Apache/2.4.x` |
| `sudo tail -f /var/log/apache2/myapp_error.log` | Мониторинг ошибок выполнения и трассировок Python | Вывод исключений `Traceback (most recent call last):` в реальном времени |

---

## Диагностика и устранение неполадок

| Симптом / Ошибка | Причина | Диагностика | Решение |
|---|---|---|---|
| **HTTP 500**<br>`ModuleNotFoundError: No module named 'django'` | `python-home` указывает на неверный venv или venv собран для другой версии Python | Проверить путь: `ls -la /opt/myapp/venv/lib/` и вывод `head -n1 /opt/myapp/venv/bin/pip` | Указать корректный `python-home=/opt/myapp/venv` в `WSGIDaemonProcess`. Проверить, совпадает ли версия Python в venv с версией `mod_wsgi`. |
| **HTTP 500**<br>Падение процессов демона (`SIGSEGV` / Deadlock) при импорте C-библиотек | Попытка исполнения NumPy/Pandas/gRPC внутри sub-interpreter | В логах: `Premature end of script headers: wsgi.py` или тихий рестарт воркера | Добавить в VirtualHost директиву `WSGIApplicationGroup %{GLOBAL}`. |
| **HTTP 403 Forbidden**<br>`client denied by server configuration` | Не настроен блок `<Directory>` для пути к `wsgi.py` или статике | `tail -n 20 error.log` | Добавить `<Directory /opt/myapp/app><Files wsgi.py>Require all granted</Files></Directory>`. |
| **HTTP 403 Forbidden**<br>`Permission denied: /opt/myapp/...` | Недостаточно прав ОС на каталоги приложения для пользователя демона | `sudo -u myapp stat /opt/myapp/app/wsgi.py` | Проверить права `rx` на всем пути: `chmod 750 /opt/myapp`, `chown -R myapp:www-data /opt/myapp`. |
| **HTTP 504 Gateway Timeout**<br>`Script timed out before returning headers` | Запрос выполняется дольше лимита `request-timeout` (блокировка в БД или долгий расчет) | Поиск медленных запросов в `access.log` и логах БД | Оптимизировать запрос в приложении; увеличить `request-timeout=120` в `WSGIDaemonProcess`; вынести тяжелые задачи в очереди (Celery). |
| Заголовок `Authorization` пуст в Python (`environ['HTTP_AUTHORIZATION']`) | Apache по умолчанию перехватывает заголовок для внутренних модулей | В приложении `request.META.get('HTTP_AUTHORIZATION')` возвращает `None` | Добавить `WSGIPassAuthorization On` в блок `<VirtualHost>`. |
| Ошибка запуска Apache:<br>`Failed to create/bind to daemon socket` | Неверные права на каталог `WSGISocketPrefix` или каталог не существует | `ls -ld /var/run/apache2/wsgi` | Создать каталог, назначить владельцем пользователя Apache (`chown www-data:www-data`), прописать `WSGISocketPrefix` в конфиге. |
| **HTTP 503 Service Unavailable**<br>`No space left on device` при создании сокета | Переполнение дескрипторов или памяти в `tmpfs` (`/run`) | `df -h /run` и `df -i /run` | Очистить осиротевшие сокеты, увеличить размер монтирования `tmpfs` в `/etc/fstab`. |
| Деградация производительности и утечки памяти | Постепенный рост RSS-памяти воркеров из-за фрагментации CPython | `ps -eo pid,user,%mem,rss,cmd \| grep wsgi` | Задать `maximum-requests=3000` в `WSGIDaemonProcess` для автоматической ротации воркеров. |

---

## Лучшие практики

1. **Исключительно Daemon-режим:** Задавайте `WSGIRestrictEmbedded On` на глобальном уровне Apache для предотвращения случайного запуска приложений в процессах MPM.
2. **Соблюдение правила `WSGIApplicationGroup %{GLOBAL}`:** Всегда используйте основной интерпретатор для предотвращения скрытых дедлоков в C-расширениях.
3. **Разделение динамики и статики:** Отдавайте статику и пользовательские медиа-файлы напрямую через Apache директивой `Alias` с кэширующими заголовками. Запросы статики никогда не должны достигать Python-интерпретатора.
4. **Ротация воркеров против утечек памяти:** Обязательно задавайте параметр `maximum-requests` (от 1000 до 5000) для плавного перезапуска процессов без прерывания соединений.
5. **Выделенные сервисные аккаунты:** Никогда не запускайте `WSGIDaemonProcess` от пользователя `root` или общего `www-data`/`apache`. Для каждого приложения создавайте изолированного системного пользователя (`user=myapp group=myapp`).
6. **Выбор между mod_wsgi и Reverse Proxy:**
   * Если приложение использует традиционный WSGI (Django, Flask) и развертывается в классической On-Premise инфраструктуре с Apache — `mod_wsgi daemon mode` обеспечивает максимальную интеграцию и минимальные накладные расходы.
   * Если приложение использует асинхронный стек (FastAPI, WebSockets, ASGI) или стандартизировано под запуск через systemd — используйте связку Apache (`mod_proxy_http`) + Gunicorn/Uvicorn через UNIX Domain Socket.
7. **Размещение сокетов IPC:** Путь `WSGISocketPrefix` должен указывать на директорию в оперативной памяти (`tmpfs`, например `/run/apache2/wsgi`), защищенную правами доступа от сторонних локальных пользователей.

---

## Дополнительная информация

### См. также

* [Обзор Apache HTTP Server](./apache_overview.md) — общая архитектура, модули и базовые директивы.
* [Apache: Настройка производительности](./apache_performance_tuning.md) — тюнинг MPM `event` и `worker`, лимиты `MaxRequestWorkers` и оптимизация Scoreboard.
* [Apache: Обратное проксирование — продвинутые сценарии](./apache-reverse-proxy-advanced.md) — конфигурация `ProxyPass`, `ProxyPassReverse` и балансировка.
* [Apache: Безопасность и харденинг](./apache_hardening.md) — изоляция прав, скрытие версий и заголовки безопасности.
* [uWSGI, SCGI, WSGI, FastCGI: интерфейсы бэкендов](../Concepts/uwsgi_scgi.md) — детальное сравнение протоколов межсерверного взаимодействия.
* [Управление Python-окружениями в Linux](../../Linux/Development/python_management.md) — развертывание виртуальных окружений, защита системного Python и PEP 668.