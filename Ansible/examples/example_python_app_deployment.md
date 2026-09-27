# Развертывание Python-приложения с помощью Ansible

## Определения

**Виртуальное окружение (venv)** — изолированная среда исполнения Python, позволяющая устанавливать зависимости проекта независимо от системных библиотек. Использование `venv` является обязательным в современных дистрибутивах (PEP 668). Синтаксис: `python3 -m venv /path/to/env`. Активация: `source /path/to/env/bin/activate`.

**WSGI (Web Server Gateway Interface)** — стандартный интерфейс (PEP 3333) взаимодействия между веб-сервером и Python-приложениями. Определяет, как веб-сервер передает HTTP-запросы приложению и как приложение возвращает ответы. Flask и Django являются WSGI-приложениями.

**ASGI (Asynchronous Server Gateway Interface)** — асинхронный интерфейс для приложений на `asyncio`. Используется в Django 3.1+ для асинхронных маршрутов и в FastAPI/Starlette. Серверы: `uvicorn`, `daphne`. Flask не поддерживает ASGI нативно.

**Gunicorn** — WSGI-сервер, выступающий прослойкой между веб-сервером (Nginx) и Python-кодом. Обеспечивает параллельную обработку запросов через модель воркеров (preforking). Ключевые параметры: `--workers`, `--bind`, `--timeout`, `--access-logfile`, `--error-logfile`, `--max-requests`, `--preload`.

**Flask** — легковесный веб-фреймворк для Python, построенный на WSGI. Минималистичный, расширяемый через библиотеки (Flask-SQLAlchemy, Flask-Login, Flask-Migrate). Подходит для API и небольших приложений.

**Django** — полнотекстовый веб-фреймворк для Python с встроенной ORM, системой миграций, админ-панелью и multisite. Работает через WSGI (`django.core.wsgi.wsgi_application`) или ASGI (`django.core.asgi.get_asgi_application()`).

**Nginx** — высокопроизводительный веб-сервер, работающий как обратный прокси (reverse proxy) и сервер статических файлов. Принимает внешние HTTP/HTTPS-запросы и перенаправляет их на Gunicorn через Unix-сокет или TCP-порт.

**Reverse Proxy (Обратный прокси)** — роль Nginx, при которой он принимает внешние HTTP-запросы и перенаправляет их на приложение через Unix-сокет или TCP-порт. Обеспечивает балансировку, кэширование, сжатие, TLS-терминацию, раздачу статики.

**proxy_params** — встроенный файл конфигурации Nginx (обычно `/etc/nginx/proxy_params`), содержащий стандартные заголовки `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `Host`.

**Systemd-юнит** — файл конфигурации (`.service`), описывающий правила запуска приложения как системной службы (автозапуск, лимиты ресурсов, логирование). Управляется через `systemctl`.

**Worker (воркер)** — процесс Gunicorn, обрабатывающий HTTP-запросы. Модель preforking: master-процесс forks воркеров при старте. Рекомендуемое количество: `2 * CPU_cores + 1`. Каждый воркер — отдельный процесс с собственным пространством памяти.

**Preload app (`--preload`)** — параметр Gunicorn, загружающий код приложения в master-процесс перед форком воркеров. Экономит память (copy-on-write) и ускоряет старт воркеров. Требует осторожности при использовании с database connections.

**Демонизация (`--daemon`)** — параметр Gunicorn, переводящий процесс в фоновый режим. В systemd используется `--daemon off` (foreground), чтобы systemd мог управлять жизненным циклом.

**Environment Variables (переменные окружения)** — способ передачи конфигурации приложению (DATABASE_URL, SECRET_KEY, DEBUG). В Ansible задаются через `environment:` в плейбуке или `Environment=` в systemd-юните.

**Health Check (проверка работоспособности)** — HTTP-эндпоинт (обычно `/health`, `/healthz`), возвращающий HTTP 200 при работоспособном приложении. Используется для мониторинга и балансировщиков нагрузки.

**Static Files (статические файлы)** — CSS, JS, изображения, шрифты. Рекомендуется раздавать напрямую через Nginx, не перенаправляя на Gunicorn.

**no_log** — параметр задачи Ansible, предотвращающий запись чувствительных данных (пароли, ключи, токены) в логи и вывод консоли.

**ansible_python_interpreter** — переменная инвентаря, указывающая путь к Python на целевом хосте. Критична при различии версий Python между Control Node и Managed Node.

**Пользователь приложения (app_user)** — отдельный системный пользователь (например, `webapp`), от имени которого запускается приложение. Обеспечивает изоляцию и контроль доступа.

## Базовые концепции

### Архитектура стека

Стандартный стек для развертывания Python-приложения:

```
[Internet] → [Nginx :80/443] → [Unix-сокет] → [Gunicorn :8000] → [Flask/Django app]
```

1. **Nginx** — принимает внешние запросы, раздает статику, обеспечивает TLS, кэширует.
2. **Gunicorn** — WSGI-сервер, обрабатывающий динамические запросы через пул воркеров.
3. **Python-приложение** — бизнес-логика (Flask, Django, FastAPI через uvicorn).

### WSGI vs ASGI

| Характеристика | WSGI | ASGI |
|---|---|---|
| Модель | Синхронная | Асинхронная |
| Примеры серверов | Gunicorn, uWSGI | Uvicorn, Daphne, Hypercorn |
| Примеры фреймворков | Flask, Django (sync) | Django (async), FastAPI, Starlette |
| Когда использовать | Традиционные web-приложения | WebSocket, long-polling, высокая concurrency |

Для большинства Flask/приложений используется **Gunicorn + WSGI**. ASGI необходим при наличии асинхронных маршрутов или WebSocket.

### Модель воркеров (Preforking)

Gunicorn использует модель preforking:

```
Master Process (master)
├── Worker 1 (request handler)
├── Worker 2 (request handler)
└── Worker N (request handler)
```

**Формула расчета воркеров:** `workers = 2 * CPU_cores + 1`

| Параметр | Описание | Рекомендация |
|---|---|---|
| `--workers` | Количество воркеров | `2 * CPU + 1` (max 4-8 на shared host) |
| `--worker-class` | Тип воркера | `sync` (default), `gthread`, `gevent`, `uvicorn.workers.UvicornWorker` |
| `--threads` | Потоки на воркер (gthread) | 4-8 (для I/O-bound задач) |
| `--timeout` | Таймаут запроса (сек) | 30 (default), увеличить для long-running tasks |
| `--max-requests` | Рестарт воркера после N запросов | 1000-4000 (защита от утечек памяти) |
| `--preload` | Загрузка кода в master перед fork | Экономит память, ускоряет старт |

### Unix-сокеты vs TCP-порты

| Аспект | Unix-сокет | TCP-порт |
|---|---|---|
| Производительность | Выше (нет сетевого стека) | Ниже (TCP overhead) |
| Безопасность | Только локальные процессы | Сетевой доступ (firewall) |
| Балансировка | Невозможна | Возможна (Nginx upstream) |
| Многомашинная | Невозможна | Возможна |
| Рекомендация | Один сервер, один app | Кластер, несколько app |

Для одномашинной конфигурации рекомендуются **Unix-сокеты**. Подробнее о反向-проксировании в Nginx: **[Интеграция Nginx с Gunicorn/uWSGI](../../WebServers/Nginx/Core/Location/integration_examples.md)**.

### Статические файлы

Раздача статики через Gunicorn неэффективна. Рекомендуется:

```jinja2
# Nginx: статика напрямую
location /static/ {
    alias /opt/{{ app_name }}/static/;
    expires 30d;
    add_header Cache-Control "public, immutable";
}

# Динамические запросы — на Gunicorn
location / {
    include proxy_params;
    proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
}
```

В Django: `collectstatic` собирает все статические файлы в `STATIC_ROOT`. В Flask: статика обычно в `static/` внутри проекта.

### Переменные окружения и конфигурация

Правильный способ передачи конфигурации приложению — через переменные окружения:

```jinja2
# В systemd-юните
[Service]
Environment="DATABASE_URL=postgresql://user:pass@localhost/mydb"
Environment="SECRET_KEY={{ vault_secret_key }}"
Environment="DEBUG=false"
```

```yaml
# В плейбуке Ansible
- name: Deploy application
  ansible.builtin.template:
    src: templates/app.service.j2
    dest: "/etc/systemd/system/{{ app_name }}.service"
  environment:
    DATABASE_URL: "postgresql://{{ db_user }}:{{ db_password }}@{{ db_host }}/{{ db_name }}"
  no_log: true
```

В приложении чтение: `os.environ.get('DATABASE_URL', 'default')`.

### Health Check

Эндпоинт проверки работоспособности:

```python
# Flask
@app.route('/health')
def health():
    return {'status': 'ok'}, 200
```

```jinja2
# Nginx: health check без проксирования
location = /health {
    access_log off;
    proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
}
```

### Обработка изменений

Любое изменение в коде или конфигурации требует перезапуска зависимых компонентов:
1. Изменение `.service` файла: `systemctl daemon-reload` и перезапуск приложения.
2. Обновление кода/зависимостей: `systemctl restart <app>`.
3. Изменение конфигурации прокси: `systemctl reload nginx`.
4. Обновление зависимостей (`requirements.txt`): пересоздание venv или `pip install -r requirements.txt`.

В Ansible эти действия выносятся в `handlers` для обеспечения строгой идемпотентности.

### Безопасность при деплое

1. **Изоляция**: Приложение запускается от отдельного пользователя, не от `root`. Подробнее: **[Управление пользователями и идентификацией в Ansible](../ansible-identity-management.md)**.
2. **Права на файлы**: Конфиденциальные файлы (`.env`, `secrets.py`) — `0600`, владелец `app_user`.
3. **Nginx**: Скрытие версии (`server_tokens off`), защита от DDoS (`limit_req`).
4. **TLS**: HTTPS обязателен для production. Nginx terminated TLS, Gunicorn получает HTTP.
5. **no_log**: Секреты не попадают в логи Ansible.
6. **Общая стратегия**: Подробнее: **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)**.

---

## Практические сценарии

### Предусловия и требования

| Компонент | Минимальная версия | Рекомендуемая | Проверка | Примечание |
|---|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 2.20 | `ansible --version` | Управляющий узел |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` | Control Node |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` | Managed Node |
| ansible-lint | 26.x+ | ≥ 26.8.0 | `ansible-lint --version` | Линтинг плейбуков |
| Gunicorn | 21.0+ | 22.0+ | `venv/bin/gunicorn --version` | Устанавливается через pip в venv |
| Nginx | 1.18+ | 1.24+ | `nginx -v` | Обратный прокси и статика |
| `ansible.builtin.pip` | — | — | Проверка в плейбуке | Для управления Python-зависимостями |
| SSH-доступ | — | — | `ssh user@host echo OK` | Проверка подключения |
| `ansible_python_interpreter` | — | — | `ansible all -m setup -a "filter=ansible_python_version"` | Если Python не по умолчанию |

**Проверка окружения перед запуском:**

```bash
# На Control Node
ansible --version
# → ansible [core 2.18.2]
python3 --version
# → Python 3.12.4

# На Managed Node (через Ansible)
ansible web_servers -m shell -a "python3 --version && which nginx"
# → server1 | CHANGED | rc=0 > Python 3.12.4
# → server1 | CHANGED | rc=0 > /usr/sbin/nginx
ansible web_servers -m setup -a "filter=ansible_python_version"
# → server1 | SUCCESS => {"ansible_python_version": {"version": "3.12.4", ...}}
```

### Сценарий 1: Развертывание Flask + Gunicorn + Nginx

Комплексный сценарий включает подготовку ОС, настройку изоляции приложения, создание systemd-юнита и конфигурацию обратного прокси.

#### Структура проекта

```text
.
├── ansible.cfg
├── inventory/
│   └── production/
│       ├── hosts.yml
│       └── group_vars/
│           └── web_servers.yml
├── files/
│   └── app/
│       ├── main.py             # Flask-приложение
│       └── requirements.txt    # Зависимости (flask, gunicorn)
├── templates/
│   ├── app.service.j2          # Systemd-юнит
│   └── nginx.conf.j2           # Конфиг Nginx для приложения
└── playbook.yml                # Сценарий деплоя
```

Рекомендуемая структура проекта: **[Типовая структура проекта Ansible](example_project_layout.md)**.

#### Шаблоны конфигураций

**Шаблон systemd (`templates/app.service.j2`):**

Обратите внимание на `Group=www-data`. Это позволяет веб-серверу Nginx читать Unix-сокет, созданный Gunicorn.

```jinja2
[Unit]
Description=Gunicorn service for {{ app_name }}
After=network.target

[Service]
User={{ app_user }}
Group=www-data
WorkingDirectory=/opt/{{ app_name }}
Environment="PATH=/opt/{{ app_name }}/venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/{{ app_name }}/venv/bin/gunicorn \
    --workers {{ gunicorn_workers | default(3) }} \
    --bind unix:/opt/{{ app_name }}/{{ app_name }}.sock \
    --timeout {{ gunicorn_timeout | default(30) }} \
    --max-requests {{ gunicorn_max_requests | default(1000) }} \
    --access-logfile /var/log/{{ app_name }}/access.log \
    --error-logfile /var/log/{{ app_name }}/error.log \
    -m 007 \
    main:app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Шаблон Nginx (`templates/nginx.conf.j2`):**

```jinja2
server {
    listen 80;
    server_name {{ server_domain }};

    # Статика — напрямую, без Gunicorn
    location /static/ {
        alias /opt/{{ app_name }}/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Health check
    location = /health {
        access_log off;
        proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
    }

    # Динамические запросы — на Gunicorn
    location / {
        include proxy_params;
        proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
    }
}
```

Подробнее о конфигурации Nginx как反向-прокси: **[Интеграция Nginx с Gunicorn/uWSGI](../../WebServers/Nginx/Core/Location/integration_examples.md)**.

#### Плейбук развертывания

```yaml
---
- name: Deploy Python Web App
  hosts: web_servers
  become: true
  vars:
    app_name: "flaskapp"
    app_user: "webapp"
    python_version: "python3.12"
    server_domain: "api.my-site.local"
    gunicorn_workers: 3
    gunicorn_timeout: 30
    gunicorn_max_requests: 1000

  tasks:
    - name: Install system dependencies
      ansible.builtin.package:
        name:
          - "{{ python_version }}"
          - "{{ python_version }}-venv"
          - nginx
        state: present

    - name: Create application user
      ansible.builtin.user:
        name: "{{ app_user }}"
        shell: /bin/bash
        create_home: yes
        system: yes

    - name: Create project directory
      ansible.builtin.file:
        path: "/opt/{{ app_name }}"
        state: directory
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0750'

    - name: Create log directory
      ansible.builtin.file:
        path: "/var/log/{{ app_name }}"
        state: directory
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0750'

    - name: Sync application files
      ansible.builtin.copy:
        src: files/app/
        dest: "/opt/{{ app_name }}/"
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0640'
      notify: Restart application

    - name: Setup virtualenv and install pip requirements
      ansible.builtin.pip:
        requirements: "/opt/{{ app_name }}/requirements.txt"
        virtualenv: "/opt/{{ app_name }}/venv"
        virtualenv_command: "{{ python_version }} -m venv"

    - name: Configure systemd service
      ansible.builtin.template:
        src: templates/app.service.j2
        dest: "/etc/systemd/system/{{ app_name }}.service"
      notify:
        - Reload systemd
        - Restart application

    - name: Configure Nginx reverse proxy
      ansible.builtin.template:
        src: templates/nginx.conf.j2
        dest: "/etc/nginx/sites-available/{{ app_name }}.conf"
      notify: Reload Nginx

    - name: Enable Nginx site
      ansible.builtin.file:
        src: "/etc/nginx/sites-available/{{ app_name }}.conf"
        dest: "/etc/nginx/sites-enabled/{{ app_name }}.conf"
        state: link
      notify: Reload Nginx

    - name: Remove default Nginx site (optional)
      ansible.builtin.file:
        path: /etc/nginx/sites-enabled/default
        state: absent
      notify: Reload Nginx

    - name: Start and enable application service
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: started
        enabled: yes

    - name: Ensure Nginx is started
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: yes

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Restart application
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: restarted

    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

Подробнее о модуле `ansible.builtin.pip` и управлении виртуальными окружениями: **[Управление Python-пакетами в Ansible](../Modules/ansible_package_management_modules.md)**.  
Подробнее о создании пользователей: **[Управление пользователями и идентификацией в Ansible](../ansible-identity-management.md)**.

#### Верификация и отладка

Проверьте работоспособность приложения после выполнения `ansible-playbook`:

```bash
# Просмотр логов в реальном времени
journalctl -u flaskapp -f
# → лог вывода Gunicorn с информацией о старте воркеров

# Проверка прав на Unix-сокет
ls -l /opt/flaskapp/flaskapp.sock
# → srwxrwx--- 1 webapp www-data 0 Jul 18 10:00 /opt/flaskapp/flaskapp.sock

# Проверка ответа через Nginx
curl -I http://api.my-site.local
# → HTTP/1.1 200 OK

# Проверка health check
curl http://api.my-site.local/health
# → {"status": "ok"}

# Проверка статуса сервиса
systemctl status flaskapp
# → active (running) — Gunicorn запущен

# Проверка количества воркеров
ps aux | grep gunicorn | grep -v grep | wc -l
# → 4 (1 master + 3 workers)

# Проверка статики
curl -I http://api.my-site.local/static/style.css
# → HTTP/1.1 200 OK, Content-Type: text/css
```

### Сценарий 2: Развертывание Django + PostgreSQL + Nginx

Дополняет Flask-сценарий интеграцией с PostgreSQL и Django-специфичными шагами (миграции, collectstatic).

#### Структура проекта

```text
.
├── ansible.cfg
├── inventory/
│   └── production/
│       ├── hosts.yml
│       └── group_vars/
│           └── web_servers.yml
├── files/
│   └── app/
│       ├── manage.py
│       ├── requirements.txt
│       └── myproject/          # Django-проект
│           ├── settings.py
│           ├── urls.py
│           └── wsgi.py
├── templates/
│   ├── app.service.j2
│   ├── nginx.conf.j2
│   └── env.j2
└── playbook.yml
```

#### Плейбук

```yaml
---
- name: Deploy Django + PostgreSQL App
  hosts: web_servers
  become: true
  vars:
    app_name: "djangoapp"
    app_user: "webapp"
    python_version: "python3.12"
    server_domain: "app.my-site.local"
    db_name: "myapp"
    db_user: "myapp_user"
    db_password: "{{ vault_db_password }}"
    django_secret_key: "{{ vault_django_secret }}"

  tasks:
    - name: Install system dependencies
      ansible.builtin.package:
        name:
          - "{{ python_version }}"
          - "{{ python_version }}-venv"
          - nginx
          - libpq-dev
          - python3-psycopg2
        state: present

    - name: Create PostgreSQL database
      community.postgresql.postgresql_db:
        name: "{{ db_name }}"
        encoding: UTF-8
        lc_collate: C
        lc_ctype: C
      become_user: postgres

    - name: Create PostgreSQL user
      community.postgresql.postgresql_user:
        name: "{{ db_user }}"
        password: "{{ db_password }}"
        db: "{{ db_name }}"
        priv: "ALL"
      become_user: postgres
      no_log: true

    - name: Create application user
      ansible.builtin.user:
        name: "{{ app_user }}"
        shell: /bin/bash
        create_home: yes
        system: yes

    - name: Create project directory
      ansible.builtin.file:
        path: "/opt/{{ app_name }}"
        state: directory
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0750'

    - name: Sync application files
      ansible.builtin.copy:
        src: files/app/
        dest: "/opt/{{ app_name }}/"
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0640'
      notify: Restart application

    - name: Setup virtualenv and install requirements
      ansible.builtin.pip:
        requirements: "/opt/{{ app_name }}/requirements.txt"
        virtualenv: "/opt/{{ app_name }}/venv"
        virtualenv_command: "{{ python_version }} -m venv"

    - name: Create Django environment file
      ansible.builtin.template:
        src: templates/env.j2
        dest: "/opt/{{ app_name }}/.env"
        owner: "{{ app_user }}"
        group: "www-data"
        mode: '0600'
      no_log: true
      notify: Restart application

    - name: Run Django migrations
      ansible.builtin.command: >
        /opt/{{ app_name }}/venv/bin/python manage.py migrate --noinput
      args:
        chdir: "/opt/{{ app_name }}"
      become_user: "{{ app_user }}"
      notify: Restart application

    - name: Collect static files
      ansible.builtin.command: >
        /opt/{{ app_name }}/venv/bin/python manage.py collectstatic --noinput
      args:
        chdir: "/opt/{{ app_name }}"
      become_user: "{{ app_user }}"

    - name: Configure systemd service
      ansible.builtin.template:
        src: templates/app.service.j2
        dest: "/etc/systemd/system/{{ app_name }}.service"
      notify:
        - Reload systemd
        - Restart application

    - name: Configure Nginx
      ansible.builtin.template:
        src: templates/nginx.conf.j2
        dest: "/etc/nginx/sites-available/{{ app_name }}.conf"
      notify: Reload Nginx

    - name: Enable Nginx site
      ansible.builtin.file:
        src: "/etc/nginx/sites-available/{{ app_name }}.conf"
        dest: "/etc/nginx/sites-enabled/{{ app_name }}.conf"
        state: link
      notify: Reload Nginx

    - name: Start and enable services
      ansible.builtin.service:
        name: "{{ item }}"
        state: started
        enabled: yes
      loop:
        - "{{ app_name }}"
        - nginx

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Restart application
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: restarted

    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

**Шаблон `.env` (`templates/env.j2`):**

```jinja2
DJANGO_SETTINGS_MODULE=myproject.settings
DJANGO_SECRET_KEY={{ django_secret_key }}
DATABASE_URL=postgresql://{{ db_user }}:{{ db_password }}@localhost/{{ db_name }}
DEBUG=false
ALLOWED_HOSTS={{ server_domain }}
```

Подробнее о настройке PostgreSQL: **[Развертывание и настройка PostgreSQL через Ansible](example_postgresql_setup.md)**.

### Сценарий 3: Обновление приложения (Rolling Update)

Безостановочное обновление кода с проверкой работоспособности:

```yaml
---
- name: Rolling Update Python App
  hosts: web_servers
  become: true
  serial: 1  # Обновление по одному серверу
  max_fail_percentage: 0  # Остановка при любой ошибке
  vars:
    app_name: "flaskapp"

  pre_tasks:
    - name: Disable server in Nginx upstream
      ansible.builtin.lineinfile:
        path: /etc/nginx/upstream.conf
        regexp: "server.*{{ inventory_hostname }}"
        line: "# server {{ inventory_hostname }}:8000; # disabled"
      delegate_to: "{{ groups['load_balancer'][0] }}"
      notify: Reload Nginx

    - name: Wait for connections to drain
      ansible.builtin.wait_for:
        timeout: 10

  tasks:
    - name: Sync new application code
      ansible.builtin.copy:
        src: files/app/
        dest: "/opt/{{ app_name }}/"
        owner: "webapp"
        group: "www-data"
      notify: Restart application

    - name: Update pip requirements
      ansible.builtin.pip:
        requirements: "/opt/{{ app_name }}/requirements.txt"
        virtualenv: "/opt/{{ app_name }}/venv"

  post_tasks:
    - name: Wait for application to be healthy
      ansible.builtin.uri:
        url: "http://{{ inventory_hostname }}/health"
        method: GET
        status_code: 200
      retries: 30
      delay: 2

    - name: Enable server in Nginx upstream
      ansible.builtin.lineinfile:
        path: /etc/nginx/upstream.conf
        regexp: "# server {{ inventory_hostname }}:8000; # disabled"
        line: "server {{ inventory_hostname }}:8000;"
      delegate_to: "{{ groups['load_balancer'][0] }}"
      notify: Reload Nginx

  handlers:
    - name: Restart application
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: restarted

    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

---

## Операции и команды

### Основные команды управления плейбуками

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbook.yml --syntax-check` |
| `ansible-playbook playbook.yml --check --diff` | Dry-run с показом изменений | `ansible-playbook playbook.yml --check --diff` |
| `ansible-playbook playbook.yml --list-tasks` | Просмотр задач без выполнения | `ansible-playbook playbook.yml --list-tasks` |
| `ansible-playbook playbook.yml --step` | Пошаговое выполнение | `ansible-playbook playbook.yml --step` |
| `ansible-playbook playbook.yml --start-at-task` | Запуск с конкретной задачи | `ansible-playbook playbook.yml --start-at-task="Deploy"` |
| `ansible <host> -m setup` | Сбор фактов | `ansible web1 -m setup -a "filter=ansible_python_version"` |
| `ansible <host> -m ping` | Проверка доступности | `ansible all -m ping` |

### Команды для управления системными сервисами

| Команда | Назначение | Пример |
|---|---|---|
| `systemctl daemon-reload` | Перезагрузка конфигурации systemd | `systemctl daemon-reload` |
| `systemctl restart <app>` | Перезапуск приложения | `systemctl restart flaskapp` |
| `systemctl reload nginx` | Горячая перезагрузка Nginx | `systemctl reload nginx` |
| `systemctl status <app>` | Проверка статуса сервиса | `systemctl status flaskapp` |
| `systemctl enable <app>` | Включение автозапуска | `systemctl enable flaskapp` |
| `journalctl -u <app> -f` | Просмотр логов в реальном времени | `journalctl -u flaskapp -f` |

### Команды для работы с виртуальными окружениями

| Команда | Назначение | Пример |
|---|---|---|
| `python3 -m venv /path/to/venv` | Создание venv | `python3 -m venv /opt/flaskapp/venv` |
| `source /path/to/venv/bin/activate` | Активация venv | `source /opt/flaskapp/venv/bin/activate` |
| `pip install -r requirements.txt` | Установка зависимостей | `/opt/flaskapp/venv/bin/pip install -r requirements.txt` |
| `pip list` | Просмотр установленных пакетов | `/opt/flaskapp/venv/bin/pip list` |
| `gunicorn --check-config main:app` | Проверка конфигурации Gunicorn | `venv/bin/gunicorn --check-config main:app` |

### Команды для работы с Nginx

| Команда | Назначение | Пример |
|---|---|---|
| `nginx -t` | Проверка синтаксиса конфигурации | `nginx -t` |
| `nginx -T` | Просмотр объединенного конфига | `sudo nginx -T \| grep proxy_pass` |
| `systemctl reload nginx` | Горячая перезагрузка конфигурации | `systemctl reload nginx` |

### Команды для валидации развертывания

| Команда | Назначение | Пример |
|---|---|---|
| `curl -I http://domain` | Проверка HTTP-заголовков | `curl -I http://api.my-site.local` |
| `curl http://domain/health` | Проверка health check | `curl http://api.my-site.local/health` |
| `ls -la /path/to/app.sock` | Проверка прав на Unix-сокет | `ls -l /opt/flaskapp/flaskapp.sock` |
| `ps aux \| grep gunicorn` | Проверка запущенных воркеров | `ps aux \| grep gunicorn \| grep -v grep \| wc -l` |
| `ss -xlnp \| grep sock` | Проверка Unix-сокетов | `ss -xlnp \| grep flaskapp` |
| `ansible-lint playbooks/` | Линтинг плейбуков | `ansible-lint playbooks/` |

---

## Устранение типичных неполадок

### Проблема: `502 Bad Gateway`

**Симптом:** Nginx возвращает `502 Bad Gateway` при обращении к приложению.

**Причина:** Gunicorn не запущен, Unix-сокет недоступен или права на сокет некорректны.

**Диагностика и решение:**

```bash
# Проверка статуса сервиса
systemctl status flaskapp
# → active (running) или inactive (dead)

# Проверка наличия сокета
ls -l /opt/flaskapp/flaskapp.sock
# → srwxrwx--- 1 webapp www-data 0 Jul 18 10:00 /opt/flaskapp/flaskapp.sock

# Проверка прав (Nginx должен читать сокет)
# Если права 660 — добавьте Nginx в группу www-data
sudo usermod -aG www-data www-data
systemctl restart nginx

# Проверка логов Gunicorn
journalctl -u flaskapp -f
# → [CRITICAL] WORKER TIMEOUT
```

### Проблема: `UNREACHABLE! Permission denied (publickey)`

**Симптом:** `fatal: [server1]: UNREACHABLE! msg: Permission denied (publickey,password)`.

**Причина:** SSH-ключ не добавлен на целевой хост или `ansible_user` не указан.

**Диагностика и решение:**

```bash
# Проверка подключения
ssh -i ~/.ssh/id_ed25519 ansible-deploy@server1 echo OK
# → OK

# Проверка ansible_python_interpreter
ansible web_servers -m setup -a "filter=ansible_python_version"
# → server1 | SUCCESS => {"ansible_python_version": {"version": "3.12.4", ...}}
```

### Проблема: `Permission denied` при выполнении задачи

**Симптом:** `fatal: [server1]: FAILED! => {"changed": false, "msg": "Permission denied"}`.

**Причина:** `become: true` не установлен или пользователь не имеет прав sudo.

**Диагностика и решение:**

```bash
# Проверка прав sudo
ansible web_servers -m shell -a "sudo -l"
# → (ALL : ALL) ALL

# Если NOPASSWD не настроен — добавьте:
echo 'webapp ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/webapp
# → /etc/sudoers.d/webapp: parsed OK
```

### Проблема: `sudo: a password is required`

**Симптом:** `fatal: [server1]: FAILED! => {"msg": "sudo: a password is required"}`.

**Причина:** `become: true` без `NOPASSWD` в sudoers.

**Диагностика и решение:**

```bash
# Проверка прав
ansible web_servers -m shell -a "sudo -l"
# → (ALL : ALL) ALL

# Если NOPASSWD не настроен — добавьте:
echo 'webapp ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/webapp
# → /etc/sudoers.d/webapp: parsed OK
```

### Проблема: Зависание после правок (ControlPersist)

**Симптом:** После изменения конфигурации SSH не подключается или подключается к старому сокету.

**Причина:** ControlPersist кэширует соединение.

**Диагностика и решение:**

```bash
# Проверка активных сокетов
ps aux | grep ssh | grep ControlMaster
# → user   12345 ssh -o ControlMaster=auto -o ControlPersist=600s ...

# Сброс сокетов
rm -f ~/.ssh/ansible-ctrl/ansible-ctrl@server1:22

# В ansible.cfg можно уменьшить время жизни
# [ssh_connection]
# ControlPersist = 30s
```

### Проблема: Обработчик SSH не выполняется

**Симптом:** `notify: Restart application` не срабатывает.

**Причина:** `notify` находится не на том уровне с задачей.

**Диагностика и решение:**

```bash
# Убедитесь, что notify находится на одном уровне с задачей
# Проверка обработчиков
ansible-playbook playbook.yml --list-handlers
```

### Проблема: SELinux блокирует SSH-ключ

**Симптом:** `Permission denied (publickey)` при корректном ключе.

**Причина:** Неправильные контексты SELinux на `.ssh` и `authorized_keys`.

**Диагностика и решение:**

```bash
# Проверка контекстов
ls -laZ /home/ansible-deploy/.ssh/
# → unconfined_u:object_r:user_home_t:s0 authorized_keys

# Восстановление контекстов
restorecon -Rv /home/ansible-deploy/.ssh

# Проверка логов SELinux
ausearch -m avc -ts recent
# → type=AVC msg=audit(...): avc:  denied  { read } for  pid=1234 comm="sshd" name="authorized_keys" dev="dm-0" ino=12345 scontext=system_u:system_r:sshd_t:s0 tcontext=unconfined_u:object_r:user_home_t:s0 tclass=file
```

### Проблема: Частичный деплой при миграции

**Симптом:** Обновление прерывается midway, часть серверов обновлена, часть нет.

**Причина:** Отсутствие `serial` или `max_fail_percentage` в плейбуке.

**Диагностика и решение:**

```bash
# Используйте serial для последовательного обновления
# serial: 1
# max_fail_percentage: 0

# Проверка статуса после сбоя
ansible web_servers -m shell -a "systemctl status flaskapp"
```

---

## Рекомендации

### Best Practices

1. **Идемпотентность**: Плейбук должен быть безопасным для повторного запуска. Используйте `state: present` вместо `state: latest` для системных пакетов.
2. **Принцип минимальных привилегий**: Приложение запускается от отдельного пользователя, не от `root`. Права на файлы — минимально необходимые.
3. **Изоляция секретов**: Используйте Ansible Vault для хранения паролей, ключей API. Передавайте через переменные окружения, не хардкодьте в конфигах.
4. **Проверка перед перезапуском**: Всегда проверяйте конфигурацию перед перезапуском сервисов (`nginx -t`, `systemctl daemon-reload`).
5. **Health check**: Обязательно наличие эндпоинта `/health` для мониторинга и балансировщиков.
6. **Ротация логов**: Настройте `logrotate` для статических файлов логов или используйте journald с `MaxRetentionSec`.
7. **Резервное копирование**: Базы данных — регулярные дампы. Конфигурация — в Git. Секреты — в Vault.
8. **Версионирование**: Используйте теги Git для отслеживания версий деплоя. Добавляйте метаданные версии в переменные окружения.
9. **Тестирование на staging**: Все изменения сначала на staging-сервере, затем в production.
10. **Rolling update**: Используйте `serial: 1` для обновления по одному серверу без простоя.
11. **no_log для секретов**: Все задачи с секретами должны иметь `no_log: true`.
12. **FQCN модулей**: Используйте полные имена модулей (`ansible.builtin.template` вместо `template`).

### Безопасность

- **Управление секретами**: Для защиты конфиденциальных данных (пароли, TLS-ключи, `SECRET_KEY`) всегда используйте шифрование. Подробнее: **[Основы Ansible Vault](../Vault/basics.md)**.
- **Минимизация привилегий**: Используйте отдельного пользователя `app_user` для запуска приложения. Не выполняйте приложение от `root`.
- **Права на файлы**: Конфиденциальные файлы (`.env`, `secrets.py`) — `0600`, владелец `app_user`.
- **Nginx hardening**: Скрытие версии (`server_tokens off`), защита от DDoS (`limit_req`).
- **TLS**: HTTPS обязателен для production. Nginx terminated TLS, Gunicorn получает HTTP.
- **no_log**: Секреты не попадают в логи Ansible. Подробнее: **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)**.

### Производительность и стабильность

- **Connection Pooling**: Для высоконагруженных сред используйте **PgBouncer** или **Pgpool-II** для управления пулом подключений к PostgreSQL.
- **Тюнинг воркеров**: Настройте `workers = 2 * CPU + 1` через переменные. Для shared hosting ограничьте 4-8 воркерами.
- **Лимиты ресурсов**: Настройте `LimitNOFILE` в systemd-юните для увеличения лимита открытых файлов.
- **Мониторинг**: Включите health check `/health` и `/metrics` (если используется Prometheus) для отслеживания состояния.
- **Check Mode**: Модули `ansible.builtin.package`, `ansible.builtin.service`, `ansible.builtin.file` поддерживают `check_mode`. Используйте `--check` для предварительной проверки.

### Граничные случаи и ограничения

1. **Минимальные образы**: Пакеты `python3-venv`, `nginx` могут отсутствовать. Добавьте их установку в bootstrap-плейбук.
2. **PEP 668 (Ubuntu 24.04+, Debian 12+)**: Прямая установка через `pip` в системный интерпретатор заблокирована. Обязательно используйте `venv`.
3. **Windows-хосты**: Gunicorn не работает на Windows. Используйте `waitress` или WSL2.
4. **FreeBSD/OpenBSD**: Отличаются пути конфигурации Nginx (`/usr/local/etc/nginx/`). Используйте conditionals в шаблонах.
5. **Высокая нагрузка**: При >1000 одновременных запросах рассмотрите `gevent` worker class или кластер с балансировщиком.
6. **Long-running tasks**: Задачи >30 сек вызывают timeout Gunicorn. Выносите в фоновые задачи (Celery, RQ).
7. **WebSocket**: Требует ASGI (Uvicorn, Daphne), Gunicorn не поддерживает WebSocket.
8. **Многопоточность**: Gunicorn с `gthread` worker class подходит для I/O-bound задач. Увеличьте `--threads` до 4-8.

### Тестирование конфигурации перед production

1. **Синтаксис**: `ansible-playbook playbook.yml --syntax-check`
2. **Check Mode (Dry Run)**: `ansible-playbook playbook.yml --check --diff`
3. **Limit Hosts**: `ansible-playbook playbook.yml --limit staging`
4. **Verbose Mode**: `ansible-playbook playbook.yml -vvv` для детальной отладки
5. **Валидация конфигов**:
   ```bash
   nginx -t
   # → nginx: configuration file /etc/nginx/nginx.conf syntax is ok
   systemctl daemon-reload
   venv/bin/gunicorn --check-config main:app
   # → [INFO] Loaded config from /path/to/gunicorn.conf.py
   ```
6. **Проверка health check**:
   ```bash
   curl -sf http://localhost/health && echo "OK" || echo "FAILED"
   # → OK
   ```
7. **Проверка логов после деплоя**:
   ```bash
   journalctl -u flaskapp --since "5 min ago" | grep -i error
   # → (пусто = ошибок нет)
   ```

---

## Дополнительная информация

### Управление логами

По умолчанию Gunicorn выводит логи в `stdout/stderr`, которые перехватываются подсистемой `journald`. Для ротации логов и централизованного сбора рекомендуется:
1. Использовать `ansible.builtin.copy` для настройки `logrotate`, если вы переопределяете вывод в статические файлы (`--access-logfile`, `--error-logfile`).
2. Настроить `vector` или `fluent-bit` для отправки логов из `journald` в централизованное хранилище.
3. Структурированные логи (JSON) упрощают парсинг: `--log-config` или кастомный форматтер.

### Смотрите также

- **[Интеграция Nginx с Gunicorn/uWSGI](../../WebServers/Nginx/Core/Location/integration_examples.md)** — конфигурация `proxy_pass`, `uwsgi_pass`, раздача статики.
- **[Управление Python-пакетами в Ansible](../Modules/ansible_package_management_modules.md)** — модуль `ansible.builtin.pip`, виртуальные окружения, PEP 668.
- **[Ansible: Рекомендации по безопасности](../ansible_security_best_practices.md)** — общая стратегия защиты, настройка выделенного пользователя, Vault, аудит.
- **[Ansible: Настройка производительности](../ansible_performance_tuning.md)** — тюнинг Gunicorn, Nginx, кеширование, CDN.

### Дополнительный сценарий: Настройка производительности и мониторинга

Для production-окружения рекомендуется настроить базовый мониторинг и оптимизировать конфигурацию Gunicorn и Nginx.

```yaml
---
- name: Настройка производительности Python-приложения
  hosts: web_servers
  become: true
  vars:
    app_name: "flaskapp"
    app_user: "webapp"
    cpu_cores: "{{ ansible_processor_cores }}"
    gunicorn_workers: "{{ [2 * ansible_processor_cores | int + 1, 8] | min }}"
    gunicorn_threads: 4
    gunicorn_timeout: 30
    gunicorn_max_requests: 1000
    nginx_worker_processes: "{{ ansible_processor_cores }}"
    nginx_worker_connections: 1024

  tasks:
    - name: Настройка systemd-юнита с оптимизированными параметрами
      ansible.builtin.template:
        src: templates/app.service.j2
        dest: "/etc/systemd/system/{{ app_name }}.service"
      notify:
        - Reload systemd
        - Restart application

    - name: Настройка Nginx с оптимизацией производительности
      ansible.builtin.template:
        src: templates/nginx.conf.j2
        dest: "/etc/nginx/sites-available/{{ app_name }}.conf"
      notify: Reload Nginx

    - name: Включение кеширования статики
      ansible.builtin.template:
        src: templates/nginx-cache.conf.j2
        dest: "/etc/nginx/conf.d/cache.conf"
      notify: Reload Nginx

    - name: Настройка лимитов systemd
      ansible.builtin.copy:
        content: |
          [Service]
          LimitNOFILE=65536
          LimitNPROC=65536
          TasksMax=infinity
        dest: "/etc/systemd/system/{{ app_name }}.service.d/limits.conf"
      notify: Reload systemd

    - name: Установка Prometheus exporter для Gunicorn
      ansible.builtin.pip:
        requirements: "/opt/{{ app_name }}/requirements-monitoring.txt"
        virtualenv: "/opt/{{ app_name }}/venv"
        virtualenv_command: "{{ python_version }} -m venv"

    - name: Добавление health check эндпоинта
      ansible.builtin.copy:
        content: |
          from flask import Flask, jsonify
          app = Flask(__name__)

          @app.route('/health')
          def health():
              return jsonify({'status': 'ok'}), 200

          @app.route('/metrics')
          def metrics():
              # Здесь можно добавить кастомные метрики
              return jsonify({
                  'workers': {{ gunicorn_workers }},
                  'threads': {{ gunicorn_threads }}
              }), 200
        dest: "/opt/{{ app_name }}/health.py"
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0644'
      notify: Restart application

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

    - name: Restart application
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: restarted

    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

**Шаблон Nginx с кешированием (`templates/nginx.conf.j2`):**

```jinja2
worker_processes {{ nginx_worker_processes }};
events {
    worker_connections {{ nginx_worker_connections }};
    use epoll;
    multi_accept on;
}

http {
    # Кеширование статики
    proxy_cache_path /var/cache/nginx levels=1:2 keys_zone=api_cache:10m inactive=60m;

    # Сжатие
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/json;

    server {
        listen 80;
        server_name {{ server_domain }};

        # Кеширование API ответов
        location / {
            proxy_cache api_cache;
            proxy_cache_valid 200 5m;
            proxy_cache_key "$scheme$request_method$host$request_uri";
            include proxy_params;
            proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
        }

        # Статика с долгим кешированием
        location /static/ {
            alias /opt/{{ app_name }}/static/;
            expires 30d;
            add_header Cache-Control "public, immutable";
            add_header X-Content-Type-Options "nosniff";
        }

        # Health check
        location = /health {
            access_log off;
            proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
        }

        # Metrics endpoint (защищенный)
        location = /metrics {
            allow 10.0.0.0/8;
            deny all;
            proxy_pass http://unix:/opt/{{ app_name }}/{{ app_name }}.sock;
        }
    }
}
```

**Шаблон systemd-юнита с оптимизациями (`templates/app.service.j2`):**

```jinja2
[Unit]
Description=Gunicorn service for {{ app_name }}
After=network.target

[Service]
User={{ app_user }}
Group=www-data
WorkingDirectory=/opt/{{ app_name }}
Environment="PATH=/opt/{{ app_name }}/venv/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=/opt/{{ app_name }}/venv/bin/gunicorn \
    --workers {{ gunicorn_workers }} \
    --threads {{ gunicorn_threads }} \
    --bind unix:/opt/{{ app_name }}/{{ app_name }}.sock \
    --timeout {{ gunicorn_timeout }} \
    --max-requests {{ gunicorn_max_requests }} \
    --max-requests-jitter 50 \
    --preload \
    --access-logfile /var/log/{{ app_name }}/access.log \
    --error-logfile /var/log/{{ app_name }}/error.log \
    -m 007 \
    main:app
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Валидация производительности:**

```bash
# Проверка количества воркеров
systemctl status flaskapp | grep "Main PID"
# → показывает PID master процесса

ps aux | grep gunicorn | grep -v grep | wc -l
# → количество процессов (1 master + N workers)

# Проверка health check
curl -s http://localhost/health | jq .
# → {"status": "ok"}

# Проверка метрик
curl -s http://localhost/metrics | jq .
# → {"workers": 3, "threads": 4}

# Проверка кеширования Nginx
curl -I http://localhost/
# → X-Cache-Status: MISS (первый запрос)
# → X-Cache-Status: HIT (второй запрос)

# Проверка сжатия
curl -s -H "Accept-Encoding: gzip" http://localhost/ | wc -c
# → сжатый размер меньше, чем оригинал

# Проверка лимитов
systemctl show flaskapp | grep LimitNOFILE
# → LimitNOFILE=65536
```
