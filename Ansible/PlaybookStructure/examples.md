# Ansible: практические примеры структуры плейбуков

## Определения

**Практические примеры структуры плейбуков** — набор проверенных паттернов организации кода, демонстрирующих способы параметризации, оркестрации и переиспользования задач для создания гибких и отказоустойчивых сценариев автоматизации.

**Параметризация** — отделение логики (задач) от данных (переменных), позволяющее использовать один и тот же код для разных окружений или конфигураций.

## Базовые концепции

*   **Иерархия переменных**: Использование `defaults` внутри ролей для базовых настроек и `group_vars` для специфичных переопределений.
*   **Идиоматичность**: Использование встроенных модулей Ansible вместо выполнения Shell-команд везде, где это возможно.
*   **Оркестрация**: Координация нескольких ролей и задач в рамках одного плейбука для достижения сложного целевого состояния.

## Практические сценарии

### Сценарий 1: Многоуровневая параметризация роли

Пример реализации настраиваемого swap-файла, где логика едина, а параметры зависят от группы серверов.

1.  **Логика задачи** (`roles/swap/tasks/main.yml`):
    ```yaml
    - name: Создать swap-файл
      ansible.builtin.command:
        cmd: "fallocate -l {{ swap_size }} /swapfile"
        creates: /swapfile
    ```

2.  **Значение по умолчанию** (`roles/swap/defaults/main.yml`):
    ```yaml
    # Безопасный минимум для всех
    swap_size: 1g
    ```

3.  **Переопределение для группы** (`group_vars/db_servers.yml`):
    ```yaml
    # Больше памяти для серверов баз данных
    swap_size: 4g
    ```

### Сценарий 2: Управление контейнерами через шаблоны Systemd

Идиоматичный подход к управлению Docker-контейнерами как системными сервисами, что обеспечивает автозапуск и стандартное управление через `systemctl`.

**Шаблон сервиса** (`templates/container.service.j2`):
```ini
[Unit]
Description=Контейнер {{ item.name }}
Requires=docker.service
After=docker.service

[Service]
Restart=always
ExecStartPre=-/usr/bin/docker stop {{ item.name }}
ExecStartPre=-/usr/bin/docker rm {{ item.name }}
ExecStart=/usr/bin/docker run --rm --name {{ item.name }} \
    {% if item.ports is defined %}{% for port in item.ports %} -p {{ port }} {% endfor %}{% endif %} \
    {{ item.image }}
ExecStop=/usr/bin/docker stop {{ item.name }}

[Install]
WantedBy=multi-user.target
```

**Плейбук для развертывания**:
```yaml
- name: Управление контейнерами приложений
  hosts: app_nodes
  vars:
    containers:
      - { name: 'web-app', image: 'nginx:latest', ports: ['80:80'] }
      - { name: 'redis-cache', image: 'redis:alpine' }

  tasks:
    - name: Создать unit-файлы для контейнеров
      ansible.builtin.template:
        src: container.service.j2
        dest: "/etc/systemd/system/{{ item.name }}.service"
        mode: '0644'
      loop: "{{ containers }}"
      notify: Перезагрузить systemd

    - name: Убедиться, что сервисы запущены
      ansible.builtin.systemd:
        name: "{{ item.name }}"
        state: started
        enabled: true
      loop: "{{ containers }}"

  handlers:
    - name: Перезагрузить systemd
      ansible.builtin.systemd:
        daemon_reload: true
```

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты и иерархия выполнения
* [Переменные в Ansible](variables.md) — детальный разбор приоритетов (22 уровня)
* [Типовая структура проекта](../examples/example_project_layout.md) — организация файлов и каталогов
