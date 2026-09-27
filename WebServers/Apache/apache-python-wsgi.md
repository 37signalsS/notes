# Apache: Интеграция Python (mod_wsgi) и других языков

---

## Определения

**WSGI (Web Server Gateway Interface)** — стандарт интерфейса между веб-сервером и Python-приложением (PEP 3333): сервер вызывает callable-объект приложения, передавая `environ` (переменные запроса) и `start_response`.

**mod_wsgi** — модуль Apache, реализующий WSGI-сервер. Два режима: **embedded** (приложение живёт в процессе Apache) и **daemon** (выделенные процессы `mod_wsgi`, рекомендуемые для продакшена).

**WSGIDaemonProcess** — директива запуска отдельного daemon-процесса WSGI: изоляция процессов приложения от Apache, возможность задать пользователя, потоки, python-path.

**WSGIScriptAlias** — привязка URL к WSGI-скрипту-точке входа (обычно `application = ...`).

**mod_proxy_uwsgi** — проксирование на uWSGI (протокол uwsgi); часто используется, когда приложение запущено под uWSGI как отдельный сервер.

**Passenger (Phusion Passenger)** — альтернативный коннектор для Ruby/Python/Node.js поверх Apache (модуль `mod_passenger`).

---

## Основные концепции

### Схема развёртывания

```
Client ──► Apache (mod_wsgi daemon) ──► WSGI app (Django/Flask/FastAPI)
                  или
Client ──► Apache (mod_proxy_uwsgi) ──► uWSGI server ──► WSGI app
                  или
Client ──► Apache (mod_passenger) ──► Passenger ──► Ruby/Python/Node
```

### mod_wsgi: embedded vs daemon

| Аспект | Embedded | Daemon |
|---|---|---|
| Где живёт приложение | В воркерах Apache | Выделенный процесс `mod_wsgi` |
| Управление | Вместе с MPM | Свой пул потоков/процессов |
| Изоляция | Слабая | Полная (свой user, cwd, python) |
| Рекомендации | Dev/низкая нагрузка | Production |

Daemon-режим позволяет перезапускать приложение `apachectl graceful` (silent reload) без перезапуска Apache.

### Ключевые директивы daemon-режима

```apacheconf
WSGIDaemonProcess myapp \
    python-home=/opt/venvs/myapp \
    python-path=/opt/app \
    threads=5 processes=2 \
    user=www-data group=www-data \
    display-name=%{GROUP} \
    maximum-requests=1000

WSGIProcessGroup myapp
WSGIScriptAlias / /opt/app/app.wsgi
```

*   `python-home` — виртуальное окружение (venv); если не задан — системный Python.
*   `python-path` — каталоги, добавляемые в `sys.path`.
*   `maximum-requests` — рестарт процесса после N запросов (защита от утечек).
*   `WSGIPassAuthorization On` — передать заголовок `Authorization` приложению (иначе mod_wsgi может его съесть для Basic-аутентификации Apache).

### uWSGI и mod_proxy_uwsgi

Если Python-приложение запущено под uWSGI (часто вместе с `supervisord`/systemd), Apache проксирует по протоколу `uwsgi`:

```apacheconf
LoadModule proxy_uwsgi_module modules/mod_proxy_uwsgi.so
ProxyPass / uwsgi://127.0.0.1:3031/
ProxyPassReverse / uwsgi://127.0.0.1:3031/
```

Сокет: `uwsgi --socket 127.0.0.1:3031 --wsgi-file app.py --http` (HTTP-режим uwsgi можно также проксировать как обычный `http://`).

### Passenger

Установка `mod_passenger` связывает Apache с приложением через конфиг приложения Rack/WSGI/Rack::Builder. Используется реже, чем mod_wsgi, но встречается в Ruby-легаси.

---

## Практические сценарии

### 1. Django/Flask через mod_wsgi daemon (production)

```apacheconf
LoadModule wsgi_module modules/mod_wsgi.so

<VirtualHost *:80>
    ServerName app.example.com
    WSGIDaemonProcess myapp \
        python-home=/opt/venvs/myapp python-path=/opt/app \
        user=www-data group=www-data threads=5 processes=2 maximum-requests=1000
    WSGIProcessGroup myapp
    WSGIScriptAlias / /opt/app/app.wsgi

    <Directory "/opt/app">
        Require all granted
    </Directory>

    # Статику отдаёт Apache
    Alias /static/ /opt/app/static/
    <Directory "/opt/app/static">
        Require all granted
    </Directory>
</VirtualHost>
```

`/opt/app/app.wsgi` (Django):

```python
import os, sys
sys.path.insert(0, '/opt/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
```

### 2. uWSGI + Apache

```bash
# uWSGI (в venv)
pip install uwsgi
/opt/venvs/app/bin/uwsgi --http 127.0.0.1:3031 --wsgi-file /opt/app/app.py \
    --master --processes 4 --threads 2 --no-orphans
```

```apacheconf
LoadModule proxy_uwsgi_module modules/mod_proxy_uwsgi.so
<VirtualHost *:80>
    ServerName app.example.com
    ProxyPass / uwsgi://127.0.0.1:3031/
    ProxyPassReverse / uwsgi://127.0.0.1:3031/
</VirtualHost>
```

### 3. Перезагрузка приложения без рестарта Apache

```bash
sudo touch /opt/app/app.wsgi        # mod_wsgi следит за mtime
# или явно:
sudo apachectl graceful
```

### 4. Диагностика

```bash
# Модуль загружен?
apache2ctl -M | grep wsgi
# → wsgi_module (shared)

# Процессы daemon
ps aux | grep -i "mod_wsgi\|[w]sgi"
# → www-data ... /usr/sbin/apache2 ... mod_wsgi

# Логи приложения (500)
sudo tail -50 /var/log/httpd/error_log | grep -i wsgi
```

---

## Операции и команды

| Команда/проверка | Назначение | Пример вывода |
|---|---|---|
| `apache2ctl -M \| grep wsgi` | Проверка mod_wsgi | `wsgi_module (shared)` |
| `ps aux \| grep -i wsgi` | Daemon-процессы | `www-data ... mod_wsgi` |
| `curl -I http://app.example.com/` | Работоспособность | `HTTP/1.1 200 OK` |
| `tail error_log` | Ошибки WSGI-приложения | `ImportError: No module named ...` |
| `/opt/venvs/app/bin/uwsgi --help` | Справка uWSGI | — |

---

## Типичные ошибки и диагностика

| Симптом | Причина | Решение |
|---|---|---|
| `500` с `ImportError: No module named django` | `python-home`/`python-path` не указывают на venv | Задать правильный venv и путь; проверить версию Python |
| `403 Forbidden` | Права на каталог приложения не читаемы для `user` daemon | `chown -R www-data` каталога/скрипта |
| Приложение «медленно» стартует, тайм-аут на первом запросе | Первичная загрузка импортов | Увеличить `Timeout`; прогреть приложение |
| Авторизация не доходит до приложения | `WSGIPassAuthorization` не включён | `WSGIPassAuthorization On` |
| После деплоя не применяются изменения | daemon кэширует модуль | `touch app.wsgi` / `apachectl graceful`; `maximum-requests` |
| Ошибки времени выполнения видны клиенту | `WSGIApplicationGroup`/конфиг в dev-режиме | Включить режим daemon, скрыть stacktrace |

---

## Лучшие практики

1. В продакшене — только daemon-режим mod_wsgi; отладка — embedded + `WSGIApplicationGroup` на dev-стенде.
2. Разделять статику (Apache `Alias`) и динамику (WSGI): это резко снижает нагрузку на приложение.
3. Использовать `venv` и явно указывать `python-home`.
4. `maximum-requests` и `apachectl graceful` для плановых перезапусков без разрыва соединений.
5. Для FastAPI/Async приложений предпочитать прокси-схемы (uWSGI/HTTP), не встраивая асинхронность в Apache-воркеры.
6. Логировать через WSGI-логирование в SIEM; ошибки 500 отслеживать по `error_log`.

---

## Дополнительная информация

### См. также

*   [Обратное проксирование: продвинутые сценарии](./apache-reverse-proxy-advanced.md) — `ProxyPassReverse`, cookie-rewrite для WSGI-бэкендов.
*   [Управление Python-окружениями](../../Linux/Development/python_management.md) — venv, менеджеры версий.
*   [Интеграция PHP-FPM](./apache_overview.md) — аналогичный паттерн для динамических приложений.