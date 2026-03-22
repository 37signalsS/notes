# Ansible: Пример развертывания Python-приложения

## Определения

- **Виртуальное окружение (virtualenv)** — изолированная среда для установки Python-зависимостей, предотвращающая конфликты между проектами.
- **Gunicorn** — WSGI-сервер для запуска Python-веб-приложений в production-окружении.
- **Systemd-юнит** — файл конфигурации сервиса для системы инициализации systemd, управляющий запуском, остановкой и автозагрузкой.

## Базовые концепции

### Изоляция зависимостей с `pip` и `virtualenv`

Ключевой аспект надежного развертывания — изоляция зависимостей с помощью виртуальных окружений. Подробное описание использования модуля `ansible.builtin.pip` с параметрами `virtualenv` и `virtualenv_command` находится в документе **[Кроссплатформенные плейбуки](../CrossPlatform/lamp-example.md#работа-с-python-окружениями)**.

### Управление интерпретатором Python

На некоторых ОС (например, CentOS 7) системным интерпретатором по умолчанию может быть Python 2. Чтобы Ansible корректно использовал Python 3, необходимо указать путь к интерпретатору через переменную `ansible_python_interpreter`. Подробнее об этом можно прочитать в **[этом разделе](../CrossPlatform/lamp-example.md#работа-с-python-окружениями)**.

### Управление сервисом с `systemd`

1. С помощью модуля `ansible.builtin.template` из шаблона (`.j2`) создается юнит-файл сервиса в `/etc/systemd/system/`.
2. Обработчик (`handler`), вызванный через `notify`, выполняет `systemctl daemon-reload`, чтобы `systemd` узнал о новом сервисе.
3. Модуль `ansible.builtin.service` используется для запуска и включения автозагрузки сервиса.

## Практический сценарий: Развертывание Flask + Gunicorn

### Структура проекта

```
/ansible
├── files/
│   └── app/
│       ├── main.py
│       └── requirements.txt
├── templates/
│   └── app.service.j2
└── playbook.yml
```

* `main.py`: Код Flask-приложения.
* `requirements.txt`: Зависимости (`flask`, `gunicorn`).
* `app.service.j2`: Jinja2-шаблон для systemd-юнита.

### Шаблон `templates/app.service.j2`

```j2
[Unit]
Description=Gunicorn instance to serve {{ app_name }}
After=network.target

[Service]
User={{ app_user }}
Group={{ app_user }}
WorkingDirectory=/apps/{{ app_name }}/app
ExecStart=/apps/{{ app_name }}/venv/bin/gunicorn --workers 3 --bind unix:{{ app_name }}.sock -m 007 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

> Обратите внимание, что `ExecStart` указывает на `gunicorn` внутри виртуального окружения.

### Плейбук `playbook.yml`

```yaml
---
- name: Deploy Python Web App with Gunicorn
  hosts: all
  become: true
  vars:
    app_name: "mywebapp"
    app_user: "webapp_user"
    ansible_python_interpreter: /usr/bin/python3

  tasks:
    - name: "Create a user for the application"
      ansible.builtin.user:
        name: "{{ app_user }}"
        shell: /bin/bash
        create_home: yes

    - name: "Create application directory"
      ansible.builtin.file:
        path: "/apps/{{ app_name }}"
        state: directory
        owner: "{{ app_user }}"
        group: "{{ app_user }}"
        mode: '0755'

    - name: "Copy application files"
      ansible.builtin.copy:
        src: files/app
        dest: "/apps/{{ app_name }}/"
        owner: "{{ app_user }}"
        group: "{{ app_user }}"

    - name: "Install dependencies into a virtualenv"
      ansible.builtin.pip:
        requirements: "/apps/{{ app_name }}/app/requirements.txt"
        virtualenv: "/apps/{{ app_name }}/venv"
        virtualenv_command: "/usr/bin/python3 -m venv"

    - name: "Create systemd service file from template"
      ansible.builtin.template:
        src: templates/app.service.j2
        dest: "/etc/systemd/system/{{ app_name }}.service"
      notify: Reload systemd

  handlers:
    - name: Reload systemd
      ansible.builtin.systemd:
        daemon_reload: yes

  post_tasks:
    - name: "Start and enable the application service"
      ansible.builtin.service:
        name: "{{ app_name }}"
        state: started
        enabled: yes
```

## Дополнительная информация

### Проверка результата

```bash
# На целевом сервере
systemctl status mywebapp
curl --unix-socket /apps/mywebapp/app/mywebapp.sock http
```

### См. также

- **[Кроссплатформенные плейбуки: Концепции](../CrossPlatform/concepts.md)** — базовые принципы кроссплатформенности
- **[Кроссплатформенные плейбуки: Пример LAMP](../CrossPlatform/lamp-example.md#работа-с-python-окружениями)** — работа с Python-окружениями
- **[Шаблонизация Jinja2](../ansible_jinja2_templating.md)** — создание динамических конфигураций
- **[Модули управления файлами](../Modules/ansible_file_management_modules.md)** — модули `copy`, `template`, `file`
- **[Модули управления пакетами](../Modules/ansible_package_management_modules.md)** — модуль `pip`
