# Ansible: практические примеры структуры плейбуков

> **Надёжность: 10** (SSoT, актуализировано согласно Ansible 2.17+)

## Определения

**Практические примеры структуры плейбуков** — набор проверенных паттернов организации кода, демонстрирующих способы параметризации, оркестрации и переиспользования задач для создания гибких и отказоустойчивых сценариев автоматизации.

**Оркестрация** — координация нескольких ролей и задач на различных группах серверов (например, балансировщики, веб-серверы, базы данных) в рамках одного плейбука для достижения сложного целевого состояния.

## Базовые концепции

При проектировании плейбуков следует опираться на следующие принципы:
*   **Иерархия переменных**: Использование `defaults` внутри ролей для безопасных базовых настроек и `group_vars` / `host_vars` для их переопределения в конкретных окружениях.
*   **FQCN (Fully Qualified Collection Name)**: Использование полных имен модулей (например, `ansible.builtin.template`) для избежания конфликтов.
*   **Идиоматичность**: Использование специализированных модулей вместо `ansible.builtin.shell` / `ansible.builtin.command` везде, где это возможно.

## Практические сценарии

### Сценарий 1: Многоуровневая параметризация компонента

Пример реализации настраиваемого swap-файла, где логика едина, а размер выделяемой памяти зависит от группы серверов (БД vs Web).

1.  **Логика задачи в роли** (`roles/swap/tasks/main.yml`):
    ```yaml
    - name: Создать swap-файл
      ansible.builtin.command:
        cmd: "fallocate -l {{ swap_size }} /swapfile"
        creates: /swapfile

    - name: Установить права доступа
      ansible.builtin.file:
        path: /swapfile
        owner: root
        group: root
        mode: '0600'

    - name: Инициализировать swap
      ansible.builtin.command:
        cmd: mkswap /swapfile
      when: not ansible_facts.ansible_local.swap_initialized | default(false)

    - name: Включить swap и добавить в fstab
      ansible.posix.mount:
        name: none
        src: /swapfile
        fstype: swap
        opts: sw
        passno: 0
        dump: 0
        state: present
    ```

2.  **Значение по умолчанию для всех** (`roles/swap/defaults/main.yml`):
    ```yaml
    # Безопасный минимум, применяется, если не переопределено
    swap_size: 1g
    ```

3.  **Переопределение для тяжелых серверов БД** (`group_vars/db_servers.yml`):
    ```yaml
    # Базам данных требуется больше swap-пространства
    swap_size: 4g
    ```

### Сценарий 2: Деплой с нулевым простоем (Zero-Downtime Deployment)

Паттерн Rolling Update, демонстрирующий взаимодействие `serial`, `pre_tasks` (для вывода из балансировки), `roles` (сам деплой) и `post_tasks` (возврат в балансировку).

**Файл оркестрации** (`deploy.yml`):
```yaml
---
- name: Деплой веб-приложения без простоя
  hosts: web_servers
  become: true
  serial: 1 # Обновлять строго по одному серверу

  # Остановка выполнения при любой ошибке, чтобы не положить весь кластер
  any_errors_fatal: true

  pre_tasks:
    - name: Вывести текущий узел из балансировщика HAProxy
      community.general.haproxy:
        state: disabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: load_balancer_node # Выполняется на балансировщике

  roles:
    - role: application_update
      vars:
        app_version: "v2.3.1"

  post_tasks:
    - name: Проверить доступность локального порта приложения
      ansible.builtin.wait_for:
        port: 8080
        state: started
        timeout: 30

    - name: Вернуть текущий узел в балансировщик HAProxy
      community.general.haproxy:
        state: enabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: load_balancer_node
```

### Сценарий 3: Управление контейнерами через Systemd (Podman/Docker)

Идиоматичный подход к управлению контейнерами на серверах, где не используется Kubernetes или Docker Swarm. Шаблонизация unit-файла systemd гарантирует автозапуск, корректный сбор логов в journald и стандартное управление жизненным циклом.

**Шаблон сервиса** (`templates/container-app.service.j2`):
```ini
[Unit]
Description=Контейнер {{ item.name }}
After=network-online.target

[Service]
Restart=always
TimeoutStopSec=70
ExecStartPre=-/usr/bin/podman stop {{ item.name }}
ExecStartPre=-/usr/bin/podman rm {{ item.name }}
ExecStart=/usr/bin/podman run --name {{ item.name }} \
    {% if item.ports is defined %}{% for port in item.ports %} -p {{ port }} {% endfor %}{% endif %} \
    {{ item.image }}
ExecStop=/usr/bin/podman stop {{ item.name }}

[Install]
WantedBy=multi-user.target
```

**Задача в плейбуке**:
```yaml
- name: Настройка контейнерных сервисов
  hosts: compute_nodes
  vars:
    containers:
      - { name: 'web-frontend', image: 'nginx:alpine', ports: ['80:80'] }
      - { name: 'redis-cache', image: 'redis:latest' }

  tasks:
    - name: Генерация unit-файлов Systemd
      ansible.builtin.template:
        src: container-app.service.j2
        dest: "/etc/systemd/system/{{ item.name }}.service"
        mode: '0644'
      loop: "{{ containers }}"
      notify: Reload Systemd

    - name: Запуск и добавление в автозагрузку
      ansible.builtin.systemd:
        name: "{{ item.name }}"
        state: started
        enabled: true
      loop: "{{ containers }}"

  handlers:
    - name: Reload Systemd
      ansible.builtin.systemd:
        daemon_reload: true
```

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты плейбука (roles, pre_tasks, post_tasks).
* [Продвинутые возможности](advanced.md) — подробнее о делегировании и обработке ошибок.
* [Переменные в Ansible](variables.md) — детальный разбор приоритетов (22 уровня).
* [Типовая структура проекта](../examples/example_project_layout.md) — организация файлов и каталогов.
