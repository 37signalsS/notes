# Ansible: Пример развертывания Python-приложения

## Определения

**Развертывание Python-приложения с Ansible** — это процесс автоматизации полного цикла доставки приложения на целевой сервер. Он включает в себя:
*   Копирование исходного кода.
*   Установку системных и Python-зависимостей в изолированное окружение.
*   Настройку приложения как системного сервиса (например, `systemd`).
*   Управление конфигурацией и жизненным циклом сервиса.

## Базовые концепции

### Изоляция зависимостей с `pip` и `virtualenv`

Ключевой аспект надежного развертывания — изоляция зависимостей. Модуль `ansible.builtin.pip` позволяет устанавливать пакеты в виртуальное окружение, избегая конфликтов с системными библиотеками.

*   `virtualenv`: Путь, где будет создано или использовано виртуальное окружение.
*   `virtualenv_command`: Явное указание команды для создания `venv` (например, `/usr/bin/python3 -m venv`). Это критически важно для систем, где может быть несколько версий Python.

### Управление интерпретатором Python

На некоторых ОС (например, CentOS 7) системным интерпретатором по умолчанию может быть Python 2. Чтобы Ansible корректно использовал Python 3 для выполнения своих модулей, необходимо явно указать путь к интерпретатору через переменную `ansible_python_interpreter`.

```yaml
# playbook.yml
- hosts: all
  vars:
    ansible_python_interpreter: /usr/bin/python3
  tasks:
    # ...
```

### Управление сервисом с `systemd`

Для того чтобы приложение работало в фоновом режиме и автоматически запускалось после перезагрузки, его настраивают как `systemd`-сервис.
1.  С помощью модуля `ansible.builtin.template` из шаблона (`.j2`) создается юнит-файл сервиса в `/etc/systemd/system/`.
2.  Обработчик (`handler`), вызванный через `notify`, выполняет `systemctl daemon-reload`, чтобы `systemd` узнал о новом сервисе.
3.  Модуль `ansible.builtin.service` используется для запуска и включения автозагрузки сервиса.

## Практический сценарий: Развертывание Flask + Gunicorn

Этот плейбук развертывает простое Flask-приложение, которое будет обслуживаться production-ready сервером Gunicorn.

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

*   `main.py`: Код Flask-приложения.
*   `requirements.txt`: Зависимости (`flask`, `gunicorn`).
*   `app.service.j2`: Jinja2-шаблон для systemd-юнита.

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

После успешного выполнения плейбука вы можете проверить статус развернутого сервиса:
```bash
# На целевом сервере
systemctl status mywebapp
curl --unix-socket /apps/mywebapp/app/mywebapp.sock http
```

### Хранение секретов

Если вашему приложению требуется доступ к базе данных или другим защищенным ресурсам, пароли и ключи **необходимо** хранить в зашифрованном виде с помощью [Ansible Vault](../ansible_vault.md).
```yaml
# vars/main.yml
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  333234...
```
Запуск плейбука в этом случае потребует ключа: `ansible-playbook playbook.yml --ask-vault-pass`.