# Развертывание Python-приложения с помощью Ansible

## Определения

**Виртуальное окружение (venv)** — изолированная среда исполнения Python, позволяющая устанавливать зависимости проекта независимо от системных библиотек. Использование `venv` является обязательным в современных дистрибутивах (PEP 668).

**Gunicorn** — WSGI (Web Server Gateway Interface) сервер, выступающий прослойкой между веб-сервером (Nginx) и Python-кодом. Обеспечивает параллельную обработку запросов.

**Reverse Proxy (Обратный прокси)** — роль Nginx, при которой он принимает внешние HTTP-запросы и перенаправляет их на Gunicorn через Unix-сокет или TCP-порт.

**Systemd-юнит** — файл конфигурации, описывающий правила запуска приложения как системной службы (автозапуск, лимиты ресурсов, логирование).

## Базовые концепции

### Изоляция и менеджмент зависимостей

Современные стандарты безопасности (например, в Ubuntu 24.04 или Debian 12) запрещают установку пакетов через `pip` напрямую в системный интерпретатор. В Ansible это реализуется через модуль `ansible.builtin.pip` с указанием пути к `virtualenv`.

### Использование Unix-сокетов

Для взаимодействия Nginx и Gunicorn на одном хосте рекомендуется использовать Unix-сокеты вместо сетевых портов. Это снижает накладные расходы на сетевой стек и повышает безопасность, ограничивая доступ к приложению локальными процессами.

### Обработка изменений

Любое изменение в коде или конфигурации требует перезапуска зависимых компонентов:
1.  Изменение `.service` файла: `systemctl daemon-reload` и перезапуск приложения.
2.  Обновление кода/зависимостей: `systemctl restart <app>`.
3.  Изменение конфигурации прокси: `systemctl reload nginx`.

В Ansible эти действия выносятся в `handlers` для обеспечения строгой идемпотентности.

---

## Практические сценарии

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
ExecStart=/opt/{{ app_name }}/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/opt/{{ app_name }}/{{ app_name }}.sock \
    -m 007 \
    main:app

[Install]
WantedBy=multi-user.target
```

**Шаблон Nginx (`templates/nginx.conf.j2`):**

```jinja2
server {
    listen 80;
    server_name {{ server_domain }};

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

  tasks:
    - name: Install system dependencies
      ansible.builtin.package:
        name: ["{{ python_version }}", "{{ python_version }}-venv", "nginx"]
        state: present

    - name: Create application user
      ansible.builtin.user:
        name: "{{ app_user }}"
        shell: /bin/bash
        create_home: yes

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
```

---

## Дополнительная информация

### Управление логами

По умолчанию Gunicorn выводит логи в `stdout/stderr`, которые перехватываются подсистемой `journald`. Для ротации логов и централизованного сбора рекомендуется:
1.  Использовать `ansible.builtin.copy` для настройки `logrotate`, если вы переопределяете вывод в статические файлы (`--access-logfile`, `--error-logfile`).
2.  Настроить `vector` или `fluent-bit` для отправки логов из `journald` напрямую в ELK/OpenSearch.

## Смотрите также

- [Интеграция Nginx с Gunicorn/uWSGI](../../WebServers/Nginx/Core/Location/integration_examples.md)
- [Работа с Python-зависимостями (Pip и Venv)](../CrossPlatform/lamp-example.md#работа-с-python-зависимостями-pip-и-venv)
- [Шаблонизация конфигураций в Ansible](../ansible_jinja_templating.md)

---
**Reliability Score: 10** (Архитектура подтверждена стандартами деплоя WSGI приложений и лучшими практиками Ansible).