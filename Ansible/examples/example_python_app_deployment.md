# Развертывание Python-приложения с помощью Ansible

## Определения

**Виртуальное окружение (venv)** — изолированная среда исполнения Python, позволяющая устанавливать зависимости проекта независимо от системных библиотек. Использование `venv` является обязательным в современных дистрибутивах (PEP 668). Синтаксис: `python3 -m venv /path/to/env`. Активация: `source /path/to/env/bin/activate`.

**WSGI (Web Server Gateway Interface)** — стандартный интерфейс (PEP 3333) взаимодействия между веб-сервером и Python-приложениями. Определяет, как веб-сервер передает HTTP-запросы приложению и как приложение возвращает ответы. Flask и Django являются WSGI-приложениями.

**ASGI (Asynchronous Server Gateway Interface)** — асинхронный аналог WSGI (PEP 6641) для приложений на `asyncio`. Используется в Django 3.1+ для асинхронных маршрутов. Серверы: `uvicorn`, `daphne`. Flask пока не поддерживает ASGI нативно.

**Gunicorn** — WSGI (Web Server Gateway Interface) сервер, выступающий прослойкой между веб-сервером (Nginx) и Python-кодом. Обеспечивает параллельную обработку запросов через модель воркеров (preforking). Ключевые параметры: `--workers` (количество воркеров), `--bind` (адрес и порт/сокет), `--timeout` (таймаут запроса), `--access-logfile`, `--error-logfile`.

**Flask** — легковесный веб-фреймворк для Python, построенный на WSGI. Минималистичичный, расширяемый через библиотеки (Flask-SQLAlchemy, Flask-Login, Flask-Migrate). Подходит для API и небольших приложений.

**Django** — полнотекстовый веб-фреймворк для Python с встроенной ORM, системой миграций, админ-панелью и multisite. Тяжелее Flask, но включает все необходимое «из коробки». Работает через WSGI (`django.core.wsgi.wsgi_application`) или ASGI (`django.core.asgi.get_asgi_application()`).

**Nginx** — высокопроизводительный веб-сервер, работающий как обратный прокси (reverse proxy) и сервер статических файлов. Принимает внешние HTTP/HTTPS-запросы и перенаправляет их на Gunicorn через Unix-сокет или TCP-порт.

**Reverse Proxy (Обратный прокси)** — роль Nginx, при которой он принимает внешние HTTP-запросы и перенаправляет их на Gunicorn через Unix-сокет или TCP-порт. Обеспечивает: балансировку, кэширование, сжатие, TLS-терминацию, раздачу статики.

**proxy_params** — встроенный файл конфигурации Nginx (обычно `/etc/nginx/proxy_params`), содержащий стандартные заголовки `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto`, `Host`. Подключается через `include proxy_params;` для корректной передачи информации о клиенте.

**Systemd-юнит** — файл конфигурации (`.service`), описывающий правила запуска приложения как системной службы (автозапуск, лимиты ресурсов, логирование). Управляется через `systemctl`.

**Worker (воркер)** — процесс Gunicorn, обрабатывающий HTTP-запросы. Модель preforking: master-процесс forks воркеров при старте. Рекомендуемое количество: `2 * CPU_cores + 1`. Каждый воркер — отдельный процесс с собственным пространством памяти.

**Preload app (`--preload`)** — параметр Gunicorn, загружающий код приложения в master-процесс перед форком воркеров. Экономит память (fork-on-write) и ускоряет старт воркеров. Требует小心ness при использовании с database connections.

**Демонизация (`--daemon`)** — параметр Gunicorn, переводящий процесс в фоновый режим. В контейнерах и systemd используется `--daemon off` (foreground), чтобы systemd мог управлять жизненным циклом.

**Environment Variables (переменные окружения)** — способ передачи конфигурации приложению (数据库 URL, SECRET_KEY, DEBUG). В Ansible задаются через `environment:` в плейбуке или `Environment=` в systemd-юните.

**Health Check (проверка работоспособности)** — HTTP-эндпоинт (обычно `/health`, `/healthz`), возвращающий HTTP 200 при работоспособном приложении. Используется для мониторинга и балансировщиков нагрузки.

**Static Files (статические файлы)** — CSS, JS, изображения, шрифты. Рекомендуется раздавать напрямую через Nginx, не перенаправляя на Gunicorn, для снижения нагрузки.

**no_log** — параметр задачи Ansible, предотвращающий запись чувствительных данных (пароли, ключи, токены) в логи и вывод консоли.

**ansible_python_interpreter** — переменная инвентаря, указывающая путь к Python на целевом хосте. Критична при различии версий Python между Control Node и Managed Node.

**Пользователь приложения (app_user)** — отдельный системный пользователь (например, `webapp`), от имени которого запускается приложение. Обеспечивает изоляцию и контроль доступа.

## Базовые концепции

### Архитектура стека

Стандартный стек для развертывания Python-приложения:

```
[Internet] → [Nginx :80/443] → [Unix-сокет] → [Gunicorn :8000] → [Flask/Django app]
```

1. **Nginx** — принимает внешние запросы, раздает статику, кэширует, обеспечивает TLS.
2. **Gunicorn** — WSGI-сервер, обрабатывающий динамические запросы.
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

Для одномашинной конфигурации рекомендуются **Unix-сокеты**.

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
4. Обновление зависимостей (requirements.txt): пересоздание venv или `pip install -r requirements.txt`.

В Ansible эти действия выносятся в `handlers` для обеспечения строгой идемпотентности.

### Безопасность при деплое

1. **Изоляция**: Приложение запускается от отдельного пользователя, не от `root`.
2. **Права на файлы**: Конфиденциальные файлы (`.env`, `secrets.py`) — `0600`, владелец `app_user`.
3. **Nginx**: Скрытие версии (`server_tokens off`), защита от DDoS (`limit_req`).
4. **TLS**: HTTPS обязателен для production. Nginx terminated TLS, Gunicorn получает HTTP.
5. **no_log**: Секреты не попадают в логи Ansible.

---

## Практические сценарии

### Предусловия и требования

| Компонент | Минимальная версия | Проверка | Примечание |
|---|---|---|---|
| Python | 3.10+ | `python3 --version` | На Control Node и Managed Node |
| `python3-venv` | — | `dpkg -l python3-venv` | Обязателен для PEP 668 |
| `python3-pip` | — | `dpkg -l python3-pip` | Для установки зависимостей в venv |
| Nginx | 1.18+ | `nginx -v` | Обратный прокси и статика |
| Gunicorn | 21.0+ | `venv/bin/gunicorn --version` | Устанавливается через pip в venv |
| `ansible.builtin.pip` | — | Проверка в плейбуке | Для управления Python-зависимостями |
| SSH-доступ | — | `ssh user@host echo OK` | Проверка подключения |
| `ansible_python_interpreter` | — | `ansible all -m setup -a "filter=ansible_python_version"` | Если Python не по умолчанию |

**Проверка окружения перед запуском:**

```bash
# На Control Node
ansible --version && python3 --version

# На Managed Node (через Ansible)
ansible web_servers -m shell -a "python3 --version && which nginx"
ansible web_servers -m setup -a "filter=ansible_python_version"
```

### Сценарий: Развертывание Flask + Gunicorn + Nginx

Комплексный сценарий включает подготовку ОС, настройку изоляции приложения, создание Systemd-юнита и конфигурацию обратного прокси.

#### 1. Структура проекта

```text
.
├── files/
│   └── app/
│       ├── main.py             # Flask-приложение
│       └── requirements.txt    # Зависимости (flask, gunicorn)
├── templates/
│   ├── app.service.j2          # Systemd-юнит
│   └── nginx.conf.j2           # Конфиг Nginx для приложения
└── playbook.yml                # Сценарий деплоя
```

#### 2. Шаблоны конфигураций

**Шаблон Systemd (`templates/app.service.j2`):**

Обратите внимание на `Group=www-data`. Это позволяет веб-серверу Nginx (который обычно работает от имени пользователя `www-data`) читать Unix-сокет, созданный Gunicorn.

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

#### 3. Плейбук развертывания

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

#### 4. Верификация и отладка

Проверьте работоспособность приложения после выполнения `ansible-playbook`:

```bash
# Просмотр логов в реальном времени
journalctl -u flaskapp -f
# → Результат: лог вывода Gunicorn с информацией о старте воркеров

# Проверка прав на Unix-сокет
ls -l /opt/flaskapp/flaskapp.sock
# → Результат: srwxrwx--- 1 webapp www-data 0 Jul 18 10:00 /opt/flaskapp/flaskapp.sock

# Проверка ответа через Nginx
curl -I http://api.my-site.local
# → Результат: HTTP/1.1 200 OK

# Проверка health check
curl http://api.my-site.local/health
# → Результат: {"status": "ok"}

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

### Сценарий: Развертывание Django + PostgreSQL + Nginx

Дополняет Flask-сценарий интеграцией с PostgreSQL и Django-специфичными шагами (миграции, collectstatic).

#### 1. Структура проекта

```text
.
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
│   └── nginx.conf.j2
└── playbook.yml
```

#### 2. Плейбук

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

### Сценарий: Обновление приложения (Rolling Update)

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

## Дополнительная информация

### Управление логами

По умолчанию Gunicorn выводит логи в `stdout/stderr`, которые перехватываются подсистемой `journald`. Для ротации логов и централизованного сбора рекомендуется:
1. Использовать `ansible.builtin.copy` для настройки `logrotate`, если вы переопределяете вывод в статические файлы (`--access-logfile`, `--error-logfile`).
2. Настроить `vector` или `fluent-bit` для отправки логов из `journald` напрямую в ELK/OpenSearch.
3. Структурированные логи (JSON) упрощают парсинг: `--log-config` или кастомный форматтер.

### Лучшие практики

1. **Идемпотентность**: Плейбук должен быть безопасным для повторного запуска. Используйте `state: present` вместо `state: latest` для системных пакетов.
2. **Принцип минимальных привилегий**: Приложение запускается от отдельного пользователя, не от `root`. Права на файлы — минимально необходимые.
3. **Изоляция секретов**: Используйте Ansible Vault для хранения паролей, ключей API. Передавайте через переменные окружения, не хардкодьте в конфигах.
4. **Проверка перед перезапуском**: Всегда проверяйте конфигурацию перед перезапуском сервисов (nginx -t, systemctl daemon-reload).
5. **Health check**: Обязательно наличие эндпоинта `/health` для мониторинга и балансировщиков.
6. **Ротация логов**: Настройте `logrotate` для статических файлов логов или используйте journald с MaxRetentionSec.
7. **Резервное копирование**: Базы данных — регулярные дампы. Конфигурация — в Git. Секреты — в Vault.
8. **Версионирование**: Используйте теги Git для отслеживания версий деплоя. Добавляйте метаданные версии в переменные окружения.
9. **Тестирование на staging**: Все изменения сначала на staging-сервере, затем в production.
10. **Rolling update**: Используйте `serial: 1` для обновления по одному серверу без простоя.

### Граничные случаи и ограничения

1. **Минимальные образы (Docker, Alpine)**: Пакеты `python3-venv`, `nginx` могут отсутствовать. Добавьте их установку в bootstrap-плейбук.
2. **PEP 668 (Ubuntu 24.04+, Debian 12+)**: Прямая установка через `pip` в системный интерпретатор заблокирована. Обязательно используйте `venv`.
3. **Windows-хосты**: Gunicorn не работает на Windows. Используйте `waitress` или Docker.
4. **FreeBSD/OpenBSD**: Отличаются пути конфигурации Nginx (`/usr/local/etc/nginx/`). Используйте conditionals в шаблонах.
5. **Высокая нагрузка**: При >1000 одновременных запросах рассмотрите `gevent` worker class или кластер с балансировщиком.
6. **Long-running tasks**: Задачи >30 сек вызывают timeout Gunicorn. Выносите в фоновые задачи (Celery, RQ).
7. **Static files + CDN**: В production статика раздается через CDN, не через Nginx напрямую.
8. **WebSocket**: Требует ASGI (Uvicorn, Daphne), Gunicorn не поддерживает WebSocket.

### Типичные ошибки и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
|---|---|---|---|
| `502 Bad Gateway` | Gunicorn не запущен или сокет недоступен | `ls -la /opt/app/app.sock`, `systemctl status app` | Проверьте логи: `journalctl -u app -f` |
| `Permission denied` (Unix-сокет) | Nginx не может прочитать сокет | `ls -la /opt/app/app.sock` | `chmod 660 app.sock`, добавьте Nginx в группу `www-data` |
| `Worker timeout` | Запрос выполняется дольше `--timeout` | `journalctl -u app \| grep timeout` | Увеличьте `--timeout` или оптимизируйте код |
| `ModuleNotFoundError` | Зависимости не установлены в venv | `venv/bin/pip list` | `pip install -r requirements.txt` в venv |
| `Address already in use` | Предыдущий процесс не завершился | `ss -tlnp \| grep :8000` | `kill` старый процесс или измените порт |
| `500 Internal Server Error` | Ошибка в коде приложения | `journalctl -u app -f`, логи приложения | Проверьте `DEBUG=true` временно, исправьте код |
| `STATIC_ROOT not set` | Django: `collectstatic` не настроен | `python manage.py collectstatic --noinput` | Добавьте `STATIC_ROOT` в `settings.py` |
| `Bad Request (400)` | Django: `ALLOWED_HOSTS` не включает домен | Проверьте `settings.py` | Добавьте домен в `ALLOWED_HOSTS` |
| `Connection refused` (Nginx) | Nginx не запущен или конфиг сломан | `nginx -t`, `systemctl status nginx` | Исправьте конфиг, перезапустите Nginx |
| `上游超时` (upstream timeout) | Gunicorn обрабатывает медленно | `tail -f /var/log/nginx/error.log` | Увеличьте `proxy_read_timeout` в Nginx |

### Тестирование конфигурации перед production

1. **Синтаксис**: `ansible-playbook playbook.yml --syntax-check`
2. **Check Mode (Dry Run)**: `ansible-playbook playbook.yml --check --diff`
3. **Limit Hosts**: `ansible-playbook playbook.yml --limit staging`
4. **Verbose Mode**: `ansible-playbook playbook.yml -vvv` для детальной отладки
5. **Валидация конфигов**:
   ```bash
   nginx -t                    # → nginx: configuration file /etc/nginx/nginx.conf syntax is ok
   systemctl daemon-reload     # → перезагрузка systemd
   venv/bin/gunicorn --check-config main:app  # проверка конфига Gunicorn
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

## Смотрите также

- [Интеграция Nginx с Gunicorn/uWSGI](../../WebServers/Nginx/Core/Location/integration_examples.md)
- [Шаблонизация конфигураций в Ansible](../ansible_jinja_templating.md)
- [Типовая структура проекта Ansible](example_project_layout.md)
