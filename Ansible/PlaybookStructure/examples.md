# Ansible: практические примеры структуры плейбуков

## Определения

**Практические примеры структуры плейбуков** — набор проверенных архитектурных паттернов организации кода, демонстрирующих способы параметризации, оркестрации и переиспользования задач для создания гибких и отказоустойчивых сценариев автоматизации.

**Оркестрация (Orchestration)** — координация нескольких ролей и задач на различных группах серверов (балансировщики, веб-серверы, базы данных) в рамках одного плейбука с учетом их зависимостей и порядка выполнения.

**Паттерн «Zero-Downtime»** — методология обновления инфраструктуры, при которой приложение остается доступным на протяжении всего процесса деплоя за счет поочередного (rolling) обновления узлов.

**Rolling Update** — стратегия обновления, при которой изменения применяются к подмножеству серверов последовательно (через `serial`), что позволяет обнаружить ошибки на ранней стадии и остановить обновление до того, как пострадает весь кластер.

**Canary Deployment** — стратегия деплоя, при которой изменения сначала применяются к одному или минимальному количеству хостов (`serial: 1`), и только при успешной проверке распространяются на остальные серверы.

**Иерархия переменных** — порядок приоритетов, в котором Ansible ищет значения переменных (от role defaults до extra_vars). Правильное понимание иерархии критично для параметризации ролей и окружений. Подробнее: **[Переменные и факты](variables.md)**.

**Стратегия выполнения (Strategy)** — алгоритм, определяющий порядок обработки хостов Ansible. Основные стратегии: `linear` (синхронная), `free` (независимая), `host_pinned` (с фиксированным числом хостов). Подробнее: **[Выполнение плейбука: база](basics.md)**.

**Обработчик (Handler)** — специальная задача, выполняемая только один раз после завершения всех задач в плее, если хотя бы одна задача отправила уведомление (`notify`). Используется для перезапуска сервисов и_reload конфигурации.

**Теги (Tags)** — метки, позволяющие запускать или исключать определенные задачи через CLI (`--tags`, `--skip-tags`). Позволяют точечно применять изменения без полного выполнения плейбука.

## Базовые концепции

При проектировании плейбуков следует опираться на следующие принципы:

1.  **Иерархия переменных**: Использование `defaults/` внутри ролей для безопасных базовых настроек и `group_vars/` / `host_vars/` для их переопределения в конкретных окружениях. Подробнее: **[Переменные и факты](variables.md)**.
2.  **FQCN (Fully Qualified Collection Name)**: Использование полных имен модулей (например, `ansible.builtin.template`) для исключения конфликтов имен и повышения переносимости.
3.  **Идиоматичность**: Использование специализированных модулей вместо `ansible.builtin.shell` везде, где это возможно, для обеспечения идемпотентности.
4.  **Декларативность**: Описание целевого состояния системы, а не последовательности императивных команд.
5.  **Разделение логики и данных**: Инкапсуляция логики в ролях, а конфигурации (переменных) — в инвентаре или внешних хранилищах.

### Архитектурные паттерны

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Плейбук-оркестратор** | Верхнеуровневый плейбук вызывает роли через `import_playbook` или `roles`, не содержит задач напрямую. | Масштабируемые проекты с переиспользуемыми ролями. |
| **Плейбук-сценарий** | Плейбук содержит задачи напрямую для конкретного технического сценария. | Небольшие проекты, одноразовые задачи, PoC. |
| **Компонентная модель** | Каждая роль = один технический сервис (nginx, postgresql). | Рекомендуемый стандарт для большинства проектов. |
| **Слойная модель** | Разделение на уровни: ОС → Runtime → Приложение. | Enterprise-стандарты с общими требованиями. |
| **Utility Role** | Узкоспециализированная роль для одной задачи (установка сертификата, настройка репозитория). | Переиспользование в разных проектах. |

### Порядок выполнения задач в плейбуке

Ansible строго следует порядку выполнения секций внутри плея:

1.  `pre_tasks` — задачи до подключения ролей
2.  `handlers` — обработчики, уведомленные в `pre_tasks`
3.  `roles` — подключенные роли
4.  `tasks` — основные задачи
5.  `post_tasks` — финальные задачи
6.  `handlers` — все оставшиеся обработчики

> **Примечание:** Использование `meta: flush_handlers` позволяет принудительно запустить все накопленные обработчики в любой момент внутри секции задач. Это критично, если нужно применить изменения до продолжения выполнения.

## Практические сценарии

### Сценарий 1: Многоуровневая параметризация компонента

Пример реализации настраиваемого swap-файла, где логика едина, а размер выделяемой памяти зависит от группы серверов (БД vs Web).

**Иерархия переменных для данного сценария:**

| Уровень | Файл | Значение `swap_size` | Приоритет |
| :--- | :--- | :--- | :--- |
| Role defaults | `roles/swap/defaults/main.yml` | `1g` | Низший |
| Group vars (all) | `group_vars/all.yml` | `2g` | Средний |
| Group vars (db_servers) | `group_vars/db_servers.yml` | `4g` | Высокий |
| Extra vars (CLI) | `-e swap_size=8g` | `8g` | Абсолютный |

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

**Валидация параметра:**

```yaml
- name: Валидация размера swap
  ansible.builtin.assert:
    that:
      - swap_size is match('^[0-9]+[kmgt]?$')
      - swap_size | regex_replace('[^0-9]', '') | int >= 512
    fail_msg: "swap_size должен быть числом с суффиксом (k/m/g/t), минимум 512m"
    success_msg: "Параметр swap_size={{ swap_size }} корректен"
```

> **Примечание:** Детальная иерархия приоритетов переменных (22 уровня) описана в разделе **[Переменные и факты](variables.md)**.

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

**Вариант с прогрессивным `serial` (Canary + масштабирование):**

```yaml
- name: Прогрессивный деплой
  hosts: web_servers
  become: true
  serial: [1, 5, "50%"]  # Сначала 1 хост (canary), затем 5, затем 50%
  max_fail_percentage: 10  # Остановка при 10%+ ошибок

  pre_tasks:
    - name: Вывести из балансировки
      community.general.haproxy:
        state: disabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: "{{ groups['load_balancers'][0] }}"

  roles:
    - role: app_deploy

  post_tasks:
    - name: Проверка здоровья приложения
      block:
        - name: HTTP health check
          ansible.builtin.uri:
            url: "http://localhost:8080/health"
            status_code: 200
          register: health
          until: health.status == 200
          retries: 10
          delay: 5

        - name: Вернуть в балансировщик
          community.general.haproxy:
            state: enabled
            host: "{{ inventory_hostname }}"
            backend: app_backend
          delegate_to: "{{ groups['load_balancers'][0] }}"
      rescue:
        - name: Каталог ошибки
          ansible.builtin.debug:
            msg: "FAILED: {{ inventory_hostname }} не прошел health check"

        - name: Уведомление в Slack
          ansible.builtin.uri:
            url: "{{ slack_webhook_url }}"
            method: POST
            body_format: json
            body:
              text: "Ansible: {{ inventory_hostname }} FAILED health check after deploy"
          delegate_to: localhost
          run_once: true
```

**Вариант с `strategy: free` (независимое выполнение):**

```yaml
- name: Быстрый деплой без ожидания синхронизации
  hosts: web_servers
  become: true
  strategy: free  # Каждый хост выполняется независимо
  serial: "25%"   # Но по 25% за раз

  tasks:
    - name: Обновление кода
      ansible.builtin.git:
        repo: "https://github.com/app/repo.git"
        dest: /opt/app
        version: "{{ app_version }}"

    - name: Рестарт сервиса
      ansible.builtin.systemd:
        name: myapp
        state: restarted
```

> **Примечание:** Подробнее о стратегиях выполнения (`linear`, `free`, `host_pinned`) и пакетной обработке (`serial`) в разделе **[Выполнение плейбука: база](basics.md)**.

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

**Расширенный вариант с проверкой здоровья и откатом:**

```yaml
- name: Деплой обновленного контейнера
  hosts: compute_nodes
  vars:
    new_image: "myapp:{{ app_version }}"
  tasks:
    - name: Проверка текущего образа
      ansible.builtin.command: podman inspect --format '{{ "{{" }}.Config.Image{{ "}}" }}' myapp
      register: current_image
      changed_when: false
      failed_when: false

    - name: Остановка и удаление старого контейнера
      block:
        - name: Остановить старый контейнер
          ansible.builtin.command: podman stop myapp
          failed_when: false

        - name: Удалить старый контейнер
          ansible.builtin.command: podman rm myapp
          failed_when: false

        - name: Запустить новый контейнер
          ansible.builtin.command: >
            podman run -d --name myapp
            -p 8080:80
            --restart=always
            {{ new_image }}
          register: deploy_result

        - name: Проверка здоровья нового контейнера
          ansible.builtin.uri:
            url: "http://localhost:8080/health"
            status_code: 200
          register: health
          until: health.status == 200
          retries: 10
          delay: 5

      rescue:
        - name: Откат к старому образу
          ansible.builtin.command: >
            podman run -d --name myapp
            -p 8080:80
            --restart=always
            {{ current_image.stdout | default('myapp:latest') }}
          when: current_image.stdout is defined

        - name: Оповещение об откате
          ansible.builtin.debug:
            msg: "Откат к {{ current_image.stdout }} из-за ошибки health check"
```

> **Примечание:** Использование `ExecStartPre` с префиксом `-` (тире) гарантирует, что команда не завершится ошибкой, если контейнер не запущен. Это обеспечивает идемпотентность.

### Сценарий 4: Многоуровневая оркестрация (Multi-tier Orchestration)

Координация между базой данных и приложением в одном плейбуке с контролем порядка и обработкой ошибок.

**Базовый вариант:**

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

**Расширенный вариант с обработкой ошибок и зависимостями:**

```yaml
---
# Этап 1: База данных (выполняется одна миграция на кластере)
- name: Миграция базы данных
  hosts: db_masters
  become: true
  serial: 1  # Последовательно для кворума
  max_fail_percentage: 0  # Любая ошибка = остановка
  tasks:
    - name: Проверка доступности БД
      ansible.builtin.command: pg_isready -U {{ db_user }}
      register: db_ready
      until: db_ready.rc == 0
      retries: 10
      delay: 5

    - name: Бэкап перед миграцией
      ansible.builtin.command: /opt/scripts/db_backup.sh
      register: backup
      changed_when: "' Backup complete' in backup.stdout"

    - name: Выполнить миграции
      ansible.builtin.command: /opt/app/scripts/migrate.sh
      register: migration
      changed_when: "'Applied' in migration.stdout"

# Этап 2: Приложение (обновление с rolling strategy)
- name: Обновление приложения
  hosts: app_servers
  become: true
  serial: "25%"
  max_fail_percentage: 10
  pre_tasks:
    - name: Вывести из балансировки
      community.general.haproxy:
        state: disabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: "{{ groups['load_balancers'][0] }}"
  roles:
    - role: backend_api
      vars:
        app_version: "{{ app_version | default('latest') }}"
  post_tasks:
    - name: Health check
      ansible.builtin.uri:
        url: "http://localhost:8080/health"
        status_code: 200
      register: health
      until: health.status == 200
      retries: 10
      delay: 5

    - name: Вернуть в балансировку
      community.general.haproxy:
        state: enabled
        host: "{{ inventory_hostname }}"
        backend: app_backend
      delegate_to: "{{ groups['load_balancers'][0] }}"

# Этап 3: Очистка (выполняется один раз)
- name: Очистка артефактов
  hosts: localhost
  become: false
  tasks:
    - name: Удаление временных файлов
      ansible.builtin.file:
        path: "{{ item }}"
        state: absent
      loop:
        - /tmp/db_backup_*.sql.gz
        - /tmp/app_artifacts
      run_once: true
```

**Вариант с `import_playbook` для оркестрации (стиль):**

```yaml
# site.yml — Главный файл-оркестратор
---
- name: Оркестрация полного деплоя
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Этап 1: Обновление БД
      ansible.builtin.import_playbook: playbooks/db_migrate.yml

    - name: Этап 2: Обновление приложения
      ansible.builtin.import_playbook: playbooks/app_deploy.yml

    - name: Этап 3: Проверка
      ansible.builtin.import_playbook: playbooks/health_check.yml
```

> **Примечание:** `import_playbook` выполняется статически на этапе парсинга. Если нужна условная логика, используйте `include_playbook` (через `ansible.builtin.include_tasks` с `apply`). Подробнее: **[Продвинутые возможности](advanced.md)**.

### Сценарий 5: Адаптация под окружения (Environment-aware Structure)

Использование динамических включений для разделения логики Stage и Production.

**Базовый вариант:**

```yaml
- name: Применение специфичных настроек окружения
  ansible.builtin.include_tasks: "{{ env_type }}_configuration.yml"
  # Переменная env_type определяется в инвентаре (group_vars/all.yml)
```

**Структура каталогов для разных окружений:**

```text
project/
├── inventory/
│   ├── production/
│   │   ├── hosts.yml          # Инвентарь продакшена
│   │   ├── group_vars/
│   │   │   ├── all.yml        # Общие переменные
│   │   │   ├── db_servers.yml # Специфичные переменные БД
│   │   │   └── vault.yml      # Секреты (зашифрованы)
│   │   └── host_vars/
│   └── staging/
│       ├── hosts.yml
│       ├── group_vars/
│       │   └── all.yml        # Менее ресурсоемкие настройки
│       └── host_vars/
├── roles/
│   ├── nginx/
│   │   ├── tasks/main.yml
│   │   ├── templates/
│   │   └── defaults/main.yml
│   └── app/
│       ├── tasks/main.yml
│       └── vars/
│           ├── production.yml  # Продакшен-переменные
│           └── staging.yml     # Стейджинг-переменные
└── playbooks/
    ├── site.yml               # Оркестратор
    ├── provision.yml
    └── deploy.yml
```

**Динамическое подключение переменных по окружению:**

```yaml
# playbooks/deploy.yml
---
- name: Деплой приложения
  hosts: app_servers
  become: true
  tasks:
    - name: Загрузка переменных окружения
      ansible.builtin.include_vars:
        file: "{{ env_type }}_vars.yml"
        # Файл: vars/production.yml или vars/staging.yml

    - name: Установка зависимостей
      ansible.builtin.package:
        name: "{{ app_dependencies }}"
        state: present

    - name: Конфигурация приложения
      ansible.builtin.template:
        src: "app_config_{{ env_type }}.j2"
        dest: /etc/app/config.yml
```

**Динамическое подключение задач по ОС:**

```yaml
# Использование first_found для выбора задач по семейству ОС
- name: Установка пакетов
  ansible.builtin.include_tasks:
    file: "{{ lookup('first_found', task_files) }}"
  vars:
    task_files:
      files:
        - "{{ ansible_facts['os_family'] | lower }}_install.yml"
        - "default_install.yml"
      paths:
        - "tasks"
```

> **Примечание:** Подробнее о динамических включениях и `first_found` в разделе **[Продвинутые возможности](advanced.md)**.

### Сценарий 6: Стратегии выполнения (Strategy Patterns)

Демонстрация различных стратегий выполнения и их применения.

**`strategy: free` — независимое выполнение хостов:**

```yaml
- name: Сбор фактов со всех серверов (быстро)
  hosts: all
  strategy: free
  gather_facts: true
  tasks:
    - name: Проверка дискового пространства
      ansible.builtin.command: df -h
      register: disk_usage
      changed_when: false
```

**`strategy: free` + `throttle` — контроль нагрузки:**

```yaml
- name: Регистрация серверов во внешнем API
  hosts: app_servers
  strategy: free
  tasks:
    - name: Регистрация в сервисе
      ansible.builtin.uri:
        url: "https://api.example.com/register"
        method: POST
        body_format: json
        body:
          host: "{{ inventory_hostname }}"
          ip: "{{ ansible_default_ipv4.address }}"
      throttle: 5  # Максимум 5 одновременных запросов
```

**`serial` + `max_fail_percentage` — безопасные обновления:**

```yaml
- name: Обновление с контролем ошибок
  hosts: web_servers
  become: true
  serial: "30%"
  max_fail_percentage: 5  # Остановка при 5%+ ошибок
  tasks:
    - name: Обновление пакетов
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes

    - name: Рестарт сервиса
      ansible.builtin.systemd:
        name: nginx
        state: restarted
```

**Прогрессивный `serial` (Canary → Scale):**

```yaml
- name: Прогрессивное обновление
  hosts: web_servers
  become: true
  serial: [1, 5, "50%", "100%"]
  # 1. Один хост (canary)
  # 2. Пять хостов
  # 3. 50% от остатка
  # 4. Все оставшиеся
  tasks:
    - name: Обновление кода
      ansible.builtin.git:
        repo: "{{ app_repo }}"
        dest: "{{ app_dir }}"
        version: "{{ app_version }}"
```

> **Примечание:** Подробнее о стратегиях в разделе **[Выполнение плейбука: база](basics.md)**. Оптимизация производительности: **[Оптимизация производительности](../ansible_performance_tuning.md)**.

### Сценарий 7: Обработчики (Handlers) и уведомления

Использование обработчиков для условного перезапуска сервисов.

**Базовый обработчик:**

```yaml
- name: Настройка Nginx
  hosts: web_servers
  become: true
  tasks:
    - name: Установить Nginx
      ansible.builtin.apt:
        name: nginx
        state: present

    - name: Скопировать конфигурацию
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
      notify: Restart Nginx

    - name: Скопировать конфигурацию сайта
      ansible.builtin.template:
        src: site.conf.j2
        dest: /etc/nginx/sites-available/default
      notify: Reload Nginx

  handlers:
    - name: Restart Nginx
      ansible.builtin.systemd:
        name: nginx
        state: restarted

    - name: Reload Nginx
      ansible.builtin.systemd:
        name: nginx
        state: reloaded
```

**Обработчик с `listen` (группировка обработчиков):**

```yaml
tasks:
  - name: Обновление конфига
    ansible.builtin.template:
      src: nginx.conf.j2
      dest: /etc/nginx/nginx.conf
    notify: Restart Web Services

  - name: Обновление SSL
    ansible.builtin.copy:
      src: "{{ item }}"
      dest: "/etc/nginx/ssl/{{ item }}"
    loop:
      - cert.pem
      - key.pem
    notify: Restart Web Services

handlers:
  - name: Restart Web Services
    ansible.builtin.systemd:
      name: nginx
      state: restarted
    listen: "restart web services"

  - name: Reload Web Services
    ansible.builtin.systemd:
      name: nginx
      state: reloaded
    listen: "restart web services"
```

**Принудительный запуск обработчиков (`meta: flush_handlers`):**

```yaml
tasks:
  - name: Применить конфигурацию
    ansible.builtin.template:
      src: app.conf.j2
      dest: /etc/app/config.yml
    notify: Restart App

  - name: Принудительно запустить обработчики сейчас
    ansible.builtin.meta: flush_handlers

  - name: Проверка работоспособности (после рестарта)
    ansible.builtin.uri:
      url: "http://localhost:8080/health"
      status_code: 200
```

**`force_handlers` — запуск обработчиков даже при ошибках:**

```yaml
---
- name: Пример с force_handlers
  hosts: app_servers
  become: true
  force_handlers: true  # Обработчики выполнятся даже при ошибке в задаче
  tasks:
    - name: Критичная задача, которая может упасть
      ansible.builtin.command: /usr/local/bin/risky_operation.sh
      register: risky_result
      ignore_errors: true

    - name: Скопировать конфиг (notify сработает)
      ansible.builtin.template:
        src: app.conf.j2
        dest: /etc/app/config.yml
      notify: Restart App

  handlers:
    - name: Restart App
      ansible.builtin.systemd:
        name: myapp
        state: restarted
```

> **Примечание:** Обработчики выполняются только один раз и только в конце секции, если хотя бы одна задача изменила состояние (`changed`). Подробнее: **[Выполнение плейбука: база](basics.md)**.

### Сценарий 8: Теги и условное включение

Использование тегов для точечного применения изменений.

**Базовое использование тегов:**

```yaml
- name: Настройка сервера
  hosts: web_servers
  become: true
  tasks:
    - name: Установка пакетов
      ansible.builtin.apt:
        name:
          - nginx
          - certbot
        state: present
      tags: [install, packages]

    - name: Конфигурация Nginx
      ansible.builtin.template:
        src: nginx.conf.j2
        dest: /etc/nginx/nginx.conf
      tags: [config, nginx]
      notify: Restart Nginx

    - name: Настройка SSL
      ansible.builtin.command: certbot certonly --nginx -d {{ domain }}
      tags: [ssl, certbot]
      when: ssl_enabled | default(false)

  handlers:
    - name: Restart Nginx
      ansible.builtin.systemd:
        name: nginx
        state: restarted
```

**Запуск и исключение тегов через CLI:**

```bash
# Выполнить только задачи с тегом "config"
ansible-playbook site.yml --tags "config"

# Выполнить несколько тегов
ansible-playbook site.yml --tags "install,config"

# Исключить задачи с тегом "ssl"
ansible-playbook site.yml --skip-tags "ssl"

# Посмотреть все доступные теги
ansible-playbook site.yml --list-tags
```

**Динамические теги через `tags` на уровне play:**

```yaml
- name: Play с глобальными тегами
  hosts: all
  tags: [provision]  # Все задачи в play получат этот тег
  tasks:
    - name: Задача 1
      ansible.builtin.debug:
        msg: "Provisioning"
      tags: [always]  # Всегда выполняется, даже с --skip-tags
```

### Сценарий 9: CI/CD интеграция (GitLab CI)

Интеграция Ansible в пайплайн CI/CD с линтингом, проверкой синтаксиса и безопасным деплоем.

**`.gitlab-ci.yml`:**

```yaml
stages:
  - lint
  - test
  - deploy

variables:
  ANSIBLE_FORCE_COLOR: "true"
  ANSIBLE_HOST_KEY_CHECKING: "False"

ansible_lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint playbooks/
    - ansible-lint roles/

syntax_check:
  stage: lint
  image: cytopia/ansible
  script:
    - ansible-playbook playbooks/site.yml --syntax-check
    - ansible-playbook playbooks/site.yml --list-tasks

deploy_staging:
  stage: test
  image: cytopia/ansible
  script:
    - ansible-playbook playbooks/site.yml -i inventory/staging/hosts.yml --check --diff
  only:
    - branches

deploy_production:
  stage: deploy
  image: cytopia/ansible
  script:
    - ansible-playbook playbooks/site.yml -i inventory/production/hosts.yml
  when: manual
  only:
    - main
  environment:
    name: production
```

**Проверка перед деплоем:**

```bash
# Синтаксис
ansible-playbook site.yml --syntax-check

# Линтинг
ansible-lint site.yml

# Просмотр задач
ansible-playbook site.yml --list-tasks

# Dry-run
ansible-playbook site.yml --check --diff -i inventory/production/hosts.yml
```

## Валидация и отладка

### Статический анализ

```bash
ansible-playbook site.yml --syntax-check
# → Проверка синтаксиса YAML и структуры плейбука

ansible-lint site.yml
# → Проверка по правилам ansible-lint (включая best practices)
```

### Просмотр без выполнения

```bash
ansible-playbook site.yml --list-tasks
# → Показать все задачи без выполнения

ansible-playbook site.yml --list-tags
# → Показать все доступные теги

ansible-playbook site.yml --list-hosts
# → Показать хосты, затронутые плейбуком
```

### Режим проверки и отладки

```bash
ansible-playbook site.yml --check
# → Dry-run: показать какие изменения были бы сделаны

ansible-playbook site.yml --check --diff
# → Dry-run с показом разницы в файлах

ansible-playbook site.yml --step
# → Пошаговое выполнение с интерактивным подтверждением каждой задачи

ansible-playbook site.yml --start-at-task="Выполнить миграцию"
# → Начать выполнение с указанной задачи

ansible-playbook site.yml -vvv
# → Подробный вывод (максимальная детализация -vvvv)

ansible-playbook site.yml --start-at-task="Деплой" --step
# → Начать с конкретной задачи и подтверждать каждую шаг
```

### Отладка переменных и фактов

```yaml
# Вывод конкретной переменной
- name: Отладка переменной
  ansible.builtin.debug:
    var: my_variable

# Вывод сообщения с интерполяцией
- name: Отладка сообщения
  ansible.builtin.debug:
    msg: "Значение: {{ my_variable }}"

# Вывод всех фактов хоста
- name: Все факты
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]
```

## Типичные ошибки и troubleshooting

### Ошибка: "No handler found" / "The requested handler 'X' was not found"

**Причина:** Обработчик вызван через `notify`, но не определен в секции `handlers` или вcluded роли.

**Решение:**
```bash
# Проверить наличие handlers в плейбуке и ролях
grep -r "handlers:" playbooks/ roles/
# Убедиться, что имя в notify совпадает с именем в handlers
```

### Ошибка: "Could not match supplied host pattern"

**Причина:** Группа не определена в инвентаре или имя группы указано неверно.

**Решение:**
```bash
ansible-inventory --list  # Просмотр всех групп и хостов
ansible-inventory --graph  # Визуализация структуры инвентаря
```

### Ошибка: "Undefined variable" при использовании `include_tasks`

**Причина:** `include_tasks` не может обратиться к переменной, которая еще не собрана (факты не собраны или переменная определена ниже по файлу).

**Решение:** Убедитесь, что переменная определена до `include_tasks`, или используйте `gather_facts: true`.

### Ошибка: "ERROR! 'serial' is not a valid attribute for a Play"

**Причина:** `serial` используется на уровне задачи вместо уровня play.

**Решение:** `serial` задается на уровне play, а не задачи:
```yaml
# ПРАВИЛЬНО
- name: Пример
  hosts: all
  serial: 1
  tasks: ...

# НЕПРАВИЛЬНО
- name: Пример
  hosts: all
  tasks:
    - name: Задача
      serial: 1  # ОШИБКА
```

### Ошибка: Теги не применяются к задачам внутри роли

**Причина:** Теги на `include_role` не видны вложенным задачам (в отличие от `import_role`).

**Решение:** Используйте `import_role` для наследования тегов, или добавляйте теги напрямую к задачам внутри роли.

## Лучшие практики

### Структура и архитектура

1. **Один плей = одна цель.** Не смешивайте установку, конфигурацию и деплой в одном плее.
2. **Плейбуки-оркестраторы.** Верхнеуровневые плейбуки должны вызывать роли через `import_playbook` или `roles`, а не содержать задачи напрямую.
3. **FQCN.** Всегда используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`).
4. **Идиоматичность.** Используйте специализированные модули вместо `shell`/`command` для обеспечения идемпотентности.

### Rolling Updates и Zero-Downtime

5. **`serial` для критичных обновлений.** Всегда используйте пакетную обработку при деплое на продакшен.
6. **`max_fail_percentage`.** Устанавливайте порог падений для остановки при массовых сбоях.
7. **`any_errors_fatal: true`** для Canary-хоста. Остановка при ошибке на первом хосте.
8. **Health check после обновления.** Проверяйте работоспособность до возврата в балансировщик.

### Обработчики и теги

9. **`notify` вместо прямого рестарта.** Используйте обработчики для условного перезапуска сервисов.
10. **`listen` для группировки.** Объединяйте связанные обработчики через `listen`.
11. **`meta: flush_handlers`** когда нужно применить изменения до продолжения.
12. **Теги для точечных изменений.** Позволяйте запускать отдельные части плейбука через `--tags`.

### Безопасность и надежность

13. **`force_handlers: true`** для критичных сервисов. Обработчики должны выполняться даже при ошибках.
14. **`no_log: true`** для задач с секретами. Скрывайте пароли и ключи от логов.
15. **`changed_when` / `failed_when`** для точной отчетности о статусе задач.
16. **Dry-run перед деплоем.** Всегда проверяйте `--check --diff` перед применением на продакшене.

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты плейбука (roles, pre_tasks, post_tasks).
* [Продвинутые возможности](advanced.md) — подробнее о делегировании, асинхронности и обработке ошибок.
* [Переменные в Ansible](variables.md) — детальный разбор приоритетов (22 уровня).
* [Типовая структура проекта](../examples/example_project_layout.md) — организация файлов и каталогов.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки проектирования сложных структур.
