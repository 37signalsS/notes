# Ansible: Пример развертывания Python-приложения

## Определения

- **Виртуальное окружение (virtualenv)** — изолированная среда для установки Python-зависимостей, предотвращающая конфликты между проектами и системными библиотеками.
- **Gunicorn** — WSGI (Web Server Gateway Interface) сервер для запуска Python-веб-приложений в промышленном (production) окружении.
- **Systemd-юнит** — файл конфигурации сервиса для системы инициализации systemd, управляющий запуском, остановкой и автоматической загрузкой приложения.

## Базовые концепции

### Изоляция зависимостей

Надежное развертывание Python-приложений требует изоляции зависимостей. Использование модуля `ansible.builtin.pip` с параметрами `virtualenv` и `virtualenv_command` позволяет создать независимое окружение для каждого приложения. Общие принципы управления Python-зависимостями в различных операционных системах (ОС) описаны в руководстве по **[кроссплатформенным плейбукам](../CrossPlatform/lamp-example.md#работа-с-python-зависимостями-pip-и-venv)**.

### Управление интерпретатором

В некоторых устаревших версиях ОС (например, CentOS 7) системным интерпретатором по умолчанию может являться Python 2. Для корректной работы современных приложений необходимо явно указывать путь к Python 3 через переменную `ansible_python_interpreter`.

### Оркестрация через systemd

Процесс управления жизненным циклом приложения в Ansible обычно состоит из трех этапов:
1. Создание конфигурационного файла юнита из шаблона (`.j2`) в директории `/etc/systemd/system/`.
2. Обновление конфигурации менеджера системных служб (`systemctl daemon-reload`) через механизм обработчиков (handlers).
3. Управление состоянием службы (запуск и включение автозагрузки) с помощью модуля `ansible.builtin.service`.

---

## Практические сценарии

### Сценарий: Развертывание связки Flask + Gunicorn

Данный сценарий демонстрирует полный цикл: от создания пользователя и подготовки директорий до настройки автозапуска веб-приложения.

#### 1. Структура проекта

```text
/ansible
├── files/
│   └── app/
│       ├── main.py             # Код приложения Flask
│       └── requirements.txt    # Зависимости (flask, gunicorn)
├── templates/
│   └── app.service.j2          # Шаблон systemd-юнита
└── playbook.yml                # Основной плейбук
```

#### 2. Шаблон службы (`templates/app.service.j2`)

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

#### 3. Плейбук развертывания (`playbook.yml`)

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

---

## Дополнительная информация

### Верификация результата

После завершения работы плейбука проверьте состояние сервиса и доступность сокета на целевом хосте:

```bash
# Проверка статуса в systemd
systemctl status mywebapp

# Проверка ответа приложения через Unix-сокет
curl --unix-socket /apps/mywebapp/app/mywebapp.sock http://localhost
```

### Связанные документы

- **[Кроссплатформенные плейбуки: Концепции](../CrossPlatform/concepts.md)** — базовые принципы переносимости кода.
- **[Пример LAMP (Python-окружения)](../CrossPlatform/lamp-example.md#работа-с-python-зависимостями-pip-и-venv)** — детализация работы с `pip` и `venv`.
- **[Шаблонизация Jinja2](../ansible_jinja_templating.md)** — руководство по созданию динамических конфигураций.
- **[Модули управления файлами](../Modules/ansible_file_management_modules.md)** — описание модулей `copy`, `template`, `file`.
- **[Модули управления пакетами](../Modules/ansible_package_management_modules.md)** — подробности работы модуля `pip`.
