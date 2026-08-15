# Ansible: практические примеры структуры плейбуков

## Определения

**Практические примеры структуры плейбуков** — набор проверенных архитектурных паттернов организации кода, демонстрирующих способы параметризации, оркестрации и переиспользования задач для создания гибких и отказоустойчивых сценариев автоматизации.

**Оркестрация (Orchestration)** — координация нескольких ролей и задач на различных группах серверов (балансировщики, веб-серверы, базы данных) в рамках одного плейбука с учетом их зависимостей и порядка выполнения.

**Паттерн «Zero-Downtime»** — методология обновления инфраструктуры, при которой приложение остается доступным на протяжении всего процесса деплоя за счет поочередного (rolling) обновления узлов.

## Базовые концепции

При проектировании плейбуков следует опираться на следующие принципы:

1.  **Иерархия переменных**: Использование `defaults/` внутри ролей для безопасных базовых настроек и `group_vars/` / `host_vars/` для их переопределения в конкретных окружениях. Подробнее: **[Переменные и факты](variables.md)**.
2.  **FQCN (Fully Qualified Collection Name)**: Использование полных имен модулей (например, `ansible.builtin.template`) для исключения конфликтов имен и повышения переносимости.
3.  **Идиоматичность**: Использование специализированных модулей вместо `ansible.builtin.shell` везде, где это возможно, для обеспечения идемпотентности.
4.  **Декларативность**: Описание целевого состояния системы, а не последовательности императивных команд.
5.  **Разделение логики и данных**: Инкапсуляция логики в ролях, а конфигурации (переменных) — в инвентаре или внешних хранилищах.

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

Паттерн Rolling Update, демонстрирующий взаимодействие `serial`, `pre_tasks` (вывод из балансировки), `roles` (деплой) и `post_tasks` (возврат в балансировку).

**Файл оркестрации** (`deploy.yml`):
```yaml
---
- name: Деплой веб-приложения без простоя
  hosts: web_servers
  become: true
  serial: 1 # Обновлять строго по одному серверу
  any_errors_fatal: true # Остановка при любой ошибке

  pre_tasks:
    - name: Вывести текущий узел из балансировщика HAProxy
      community.general.haproxy:
        state: disabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: "{{ groups['load_balancers'][0] }}"

  roles:
    - role: application_update
      vars:
        app_version: "v2.3.1"

  post_tasks:
    - name: Проверка работоспособности после обновления
      block:
        - name: Проверить доступность локального порта приложения
          ansible.builtin.wait_for:
            port: 8080
            state: started
            timeout: 60

        - name: Вернуть текущий узел в балансировщик HAProxy
          community.general.haproxy:
            state: enabled
            host: "{{ inventory_hostname }}"
            backend: app_backend
          delegate_to: "{{ groups['load_balancers'][0] }}"
      rescue:
        - name: Оповещение о сбое Health Check
          ansible.builtin.debug:
            msg: "Узел {{ inventory_hostname }} не прошел проверку. Оставляю вне балансировки."
```

### Сценарий 3: Управление контейнерами через Systemd (Podman/Docker)

Идиоматичный подход к управлению контейнерами на серверах без внешних оркестраторов. Шаблонизация unit-файла systemd гарантирует автозапуск и корректное логирование.

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

### Сценарий 4: Многоуровневая оркестрация (Multi-tier Orchestration)

Координация между базой данных и приложением в одном плейбуке.

```yaml
---
- name: Обновление схемы базы данных
  hosts: db_masters
  become: true
  tasks:
    - name: Выполнить миграции БД
      ansible.builtin.command: /opt/app/scripts/migrate.sh
      run_once: true
      tags: [ database, migrations ]

- name: Обновление серверной части приложений
  hosts: app_servers
  become: true
  roles:
    - role: backend_api
  tags: [ app, backend ]
```

### Сценарий 5: Адаптация под окружения (Environment-aware Structure)

Использование динамических включений для разделения логики Stage и Production.

```yaml
- name: Применение специфичных настроек окружения
  ansible.builtin.include_tasks: "{{ env_type }}_configuration.yml"
  # Переменная env_type определяется в инвентаре (group_vars/all.yml)
```

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты плейбука (roles, pre_tasks, post_tasks).
* [Продвинутые возможности](advanced.md) — подробнее о делегировании, асинхронности и обработке ошибок.
* [Переменные в Ansible](variables.md) — детальный разбор приоритетов (22 уровня).
* [Типовая структура проекта](../examples/example_project_layout.md) — организация файлов и каталогов.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки проектирования сложных структур.
