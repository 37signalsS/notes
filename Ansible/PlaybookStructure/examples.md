# Ansible: практические примеры структуры плейбуков

## Определения

**Практические примеры структуры плейбуков** — набор проверенных архитектурных паттернов организации кода, демонстрирующих способы параметризации, оркестрации и переиспользования задач для создания гибких и отказоустойчивых сценариев автоматизации.

**Оркестрация (Orchestration)** — координация нескольких ролей и задач на различных группах серверов (балансировщики, веб-серверы, базы данных) в рамках одного плейбука с учетом их зависимостей и порядка выполнения.

**Паттерн «Zero-Downtime»** — методология обновления инфраструктуры, при которой приложение остается доступным на протяжении всего процесса деплоя за счет поочередного (rolling) обновления узлов.

**Rolling Update** — стратегия обновления, при которой изменения применяются к подмножеству серверов последовательно (через `serial`), что позволяет обнаружить ошибки на ранней стадии и остановить обновление до того, как пострадает весь кластер.

**Canary Deployment** — стратегия деплоя, при которой изменения сначала применяются к одному или минимальному количеству хостов (`serial: 1`), и только при успешной проверке распространяются на остальные серверы.

**Иерархия переменных** — порядок приоритетов, в котором Ansible ищет значения переменных (от role defaults до extra_vars). Правильное понимание иерархии критично для параметризации ролей и окружений. Подробнее: **[Переменные и факты](variables.md)**.

**Стратегия выполнения (Strategy)** — алгоритм, определяющий порядок обработки хостов Ansible. Основные стратегии: `linear` (синхронная), `free` (независимая), `host_pinned` (с фиксированным числом хостов). Подробнее: **[Выполнение плейбука: база](basics.md)**.

**Обработчик (Handler)** — специальная задача, выполняемая только один раз после завершения всех задач в плее, если хотя бы одна задача отправила уведомление (`notify`). Используется для перезапуска сервисов и reload конфигурации.

**Теги (Tags)** — метки, позволяющие запускать или исключать определенные задачи через CLI (`--tags`, `--skip-tags`). Позволяют точечно применять изменения без полного выполнения плейбука.

**Drift Detection** — процесс обнаружения расхождений между фактическим состоянием инфраструктуры и состоянием, описанным в коде. Ansible обнаруживает дрейф автоматически при каждом запуске благодаря идемпотентности модулей.

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

> **Примечание:** Использование `meta: flush_handlers` позволяет принудительно запустить все накопленные обработчики в любой момент внутри секции задач. Это критично, если нужно применить изменения до продолжения выполнения. Подробнее: **[Продвинутые возможности](advanced.md)**.

### Жизненный цикл плейбука

1. **Парсинг** — чтение YAML, проверка синтаксиса.
2. **Сбор фактов** — `gather_facts: true` опрашивает хосты через facts modules.
3. **Загрузка переменных** — role defaults → group_vars → host_vars → extra_vars.
4. **Импорт/включение** — `import_*` выполняется на этапе парсинга, `include_*` — во время выполнения.
5. **Выполнение задач** — в соответствии с выбранной стратегией (`linear`, `free`, `host_pinned`).
6. **Обработчики** — запускаются после секции задач, если были уведомления `notify`.
7. **Очистка** — `post_tasks`, отключение от хостов, запись логов.

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

### Сценарий 2: Многоуровневая оркестрация (Multi-tier Orchestration)

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

### Сценарий 3: Управление контейнерами через Systemd (Podman)

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

### Сценарий 4: Адаптация под окружения (Environment-aware Structure)

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

### Сценарий 5: Обнаружение и исправление дрейфа конфигурации (Drift Detection)

Configuration drift — отклонение реального состояния сервера от описанного в коде. Ansible обнаруживает дрейф автоматически при каждом запуске благодаря идемпотентности модулей.

**Анализ дрейфа через `--check --diff`:**

```bash
# Проверка текущего состояния без изменений
ansible-playbook site.yml --check --diff 2>&1 | tee drift_report_$(date +%Y%m%d).log
# → Показывает все расхождения между текущим состоянием и кодом

# Анализ: задачи со статусом changed = потенциальный дрейф
grep "changed:" drift_report_20240115.log
# → web_01               : changed=1
# → web_02               : changed=0
```

**Автоматический drift report:**

```yaml
---
- name: Configuration drift detection
  hosts: all
  become: true
  tasks:
    - name: Проверка критичных файлов конфигурации
      ansible.builtin.stat:
        path: "{{ item }}"
      register: file_states
      loop:
        - /etc/ssh/sshd_config
        - /etc/nginx/nginx.conf
        - /etc/sysconfig/network-scripts/ifcfg-eth0

    - name: Generate drift report
      ansible.builtin.copy:
        content: |
          Drift Report: {{ inventory_hostname }} — {{ ansible_date_time.iso8601 }}
          {% for item in file_states.results %}
          {{ item.item }}: {{ item.stat.checksum }}
          {% endfor %}
        dest: "/var/log/drift_report_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0644"
      when: file_states.results | selectattr('changed') | list | length > 0

- name: Collect drift reports from all hosts
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Gather drift reports
      ansible.builtin.find:
        paths: /var/log
        patterns: "drift_report_*.log"
      delegate_to: "{{ item }}"
      loop: "{{ groups['all'] }}"
      register: report_files
      ignore_errors: true

    - name: Aggregate drift data
      ansible.builtin.set_fact:
        drifted_hosts: >-
          {{ report_files.results |
             selectattr('failed', 'equalto', false) |
             selectattr('files', 'length', 'gt', 0) |
             map(attribute='item') |
             list }}

    - name: Report drifted hosts
      ansible.builtin.debug:
        msg: "Drift detected on: {{ drifted_hosts | join(', ') }}"
```

### Сценарий 6: Стратегии выполнения (Strategy Patterns)

Подробный разбор стратегий выполнения, их влияния на производительность и выбор параметров `forks`/`serial` приведен в **[Оптимизация производительности](../ansible_performance_tuning.md)**.

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

> **Примечание:** Подробнее о `listen`, `force_handlers` и тонкостях обработчиков в разделе **[Продвинутые возможности](advanced.md)**.

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
# → PLAY [Настройка сервера] ****************************************************

# Выполнить несколько тегов
ansible-playbook site.yml --tags "install,config"
# → PLAY [Настройка сервера] ****************************************************

# Исключить задачи с тегом "ssl"
ansible-playbook site.yml --skip-tags "ssl"
# → PLAY [Настройка сервера] ****************************************************

# Посмотреть все доступные теги
ansible-playbook site.yml --list-tags
# → TASK TAGS  *******************************************************************
# → [install]        : Установка пакетов
# → [config]         : Конфигурация Nginx
# → [ssl]            : Настройка SSL
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

> **Примечание:** Подробнее о тегах на уровне ролей и `import_role`/`include_role` в разделе **[Роли Ansible](../ansible_roles.md)**. Сравнение `import_role` vs `include_role` и наследование тегов: **[Создание и использование ролей](../Roles/usage.md)**.

## Операции и команды

### Статический анализ и проверка синтаксиса

```bash
ansible-playbook site.yml --syntax-check
# → ERROR! Syntax Error while loading YAML.
# → или: PLAY RECAP ***************************************************************** (если ошибок нет)

ansible-lint site.yml
# → ansible-lint . [WARNING]: No config files found; using defaults
# → 1 succeeded, 0 failed, 0 warnings
```

### Просмотр без выполнения

```bash
ansible-playbook site.yml --list-tasks
# → play #1: Деплой веб-приложения
# →   tasks:
# →     - Установка пакетов
# →     - Копирование конфигурации

ansible-playbook site.yml --list-tags
# → TASK TAGS: [always, config, deploy, verify]

ansible-playbook site.yml --list-hosts
# → play #1: Деплой веб-приложения
# →   host count (3):
# →     web_01
# →     web_02
# →     web_03
```

### Режим проверки и отладки

```bash
ansible-playbook site.yml --check
# → PLAY RECAP ********************************************************************
# → web_01                    : ok=5    changed=2    unreachable=0    failed=0

ansible-playbook site.yml --check --diff
# → PLAY RECAP ********************************************************************
# → web_01                    : ok=5    changed=2    unreachable=0    failed=0
# → --- before
# → +++ after
# → @@ -1,3 +1,3 @@
# → - timeout 60;
# → + timeout 120;

ansible-playbook site.yml --step
# → PLAY [Деплой веб-приложения] *************************************************
# → Perform task: Установка пакетов (y/n/c):
# → y

ansible-playbook site.yml --start-at-task="Выполнить миграцию"
# → PLAY [Деплой веб-приложения] *************************************************
# → TASK [Выполнить миграцию] ****************************************************

ansible-playbook site.yml -vvv
# → <web_01> ESTABLISH SSH CONNECTION FOR USER: deploy
# → <web_01> SSH: EXEC ssh -C -o ControlMaster=auto -o ControlPersist=60s ...

ansible-playbook site.yml --start-at-task="Деплой" --step
# → PLAY [Деплой веб-приложения] *************************************************
# → Perform task: Деплой (y/n/c):
# → y
```

### Проверка подключения и сбор фактов

```bash
ansible all -m ping
# → web_01 | SUCCESS => {
# →     "ansible_facts": {
# →         "discovered_interpreter_python": "/usr/bin/python3"
# →     },
# →     "changed": false
# → }

ansible all -m ansible.builtin.setup -a "filter=ansible_os*"
# → web_01 | SUCCESS => {
# →     "ansible_facts": {
# →         "ansible_os_family": "Debian",
# →         "ansible_distribution": "Ubuntu",
# →         "ansible_distribution_version": "22.04"
# →     },
# →     "changed": false
# → }

ansible-inventory --list
# → {
# →     "_meta": {
# →         "hostvars": {
# →             "web_01": {
# →                 "ansible_host": "192.168.1.10"
# →             }
# →         }
# →     },
# →     "web_servers": {
# →         "hosts": ["web_01", "web_02"]
# →     }
# → }

ansible-inventory --graph
# → @all:
# →  |_@ungrouped:
# →  |_web_servers:
# →     |_web_01
# →     |_web_02
```

### Просмотр инвентаря

```bash
ansible-inventory --list --yaml
# → all:
# →   hosts:
# →     web_01:
# →       ansible_host: 192.168.1.10

ansible-doc -l | wc -l
# → 3366

ansible-doc ansible.builtin.systemd
# → > SYSTEMD    (/usr/lib/python3/dist-packages/ansible/modules/service_systemd.py)
# →
# →  Manage systemd units.
```

### Отладка переменных и фактов

```yaml
# Вывод конкретной переменной
- name: Отладка переменной
  ansible.builtin.debug:
    var: my_variable
# → ok: [web_01] => {
# →     "my_variable": "production"
# → }

# Вывод сообщения с интерполяцией
- name: Отладка сообщения
  ansible.builtin.debug:
    msg: "Значение: {{ my_variable }}"
# → ok: [web_01] => {
# →     "msg": "Значение: production"
# → }

# Вывод всех фактов хоста
- name: Все факты
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]
# → ok: [web_01] => {
# →     "hostvars": {
# →         "inventory_hostname": "web_01",
# →         "ansible_host": "192.168.1.10",
# →         ...
# →     }
# → }
```

## Типичные ошибки и troubleshooting

### Ошибка: "Could not match supplied host pattern"

**Причина:** Группа не определена в инвентаре или имя группы указано неверно.

**Решение:**
```bash
ansible-inventory --list  # Просмотр всех групп и хостов
# → {"web_servers": {"hosts": ["web_01"]}, ...}
ansible-inventory --graph  # Визуализация структуры инвентаря
# → @all:
# →  |_web_servers:
# →     |_web_01
```

### Ошибка: "FAILED! => {'msg': 'The field X is not allowed'}"

**Причина:** Использование несуществующего параметра модуля или устаревший синтаксис.

**Решение:** Проверьте документацию модуля через `ansible-doc`:
```bash
ansible-doc ansible.builtin.systemd
# → Проверьте допустимые параметры
```

### Ошибка: "Undefined variable" при использовании `import_tasks`

**Причина:** `import_tasks` не может обратиться к переменной, которая еще не собрана (факты не собраны или переменная определена ниже по файлу).

**Решение:** Убедитесь, что переменная определена до `import_tasks`, или используйте `gather_facts: true`.

### Ошибка: "No such file or directory" при `include_tasks`

**Причина:** Путь к файлу задач указан неверно или переменная, формирующая путь, пуста.

**Решение:**
```bash
# Проверить существование файла
ls -la tasks/{{ ansible_facts['os_family'] | lower }}_install.yml

# Вывести значение переменной для отладки
ansible-playbook site.yml -e "debug_var=true" -vvv
```

### Ошибка: "Handler 'X' not found"

**Причина:** Обработчик вызван через `notify`, но не определен в секции `handlers` или included роли.

**Решение:**
```bash
# Проверить наличие handlers в плейбуке и ролях
grep -r "handlers:" playbooks/ roles/
# Убедиться, что имя в notify совпадает с именем в handlers
```

### Ошибка: "Unexpected failure during module execution" при async

**Причина:** Фоновая задача (`async`) не завершилась за отведенное время или Control Node потерял связь с хостом.

**Решение:** Увеличьте `async` или проверьте статус задачи через `async_status`:
```yaml
- name: Проверка статуса фоновой задачи
  ansible.builtin.async_status:
    jid: "{{ async_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 10
```

### Ошибка: `delegate_to` на недоступный хост

**Причина:** Хост, на который делегирована задача, недоступен или не указан в инвентаре.

**Решение:** Проверьте доступность делегированного хоста:
```bash
ansible load_balancers -m ping
# → web_lb | SUCCESS => {"changed": false}
```

### Ошибка: `strategy: free` с разделяемым состоянием

**Причина:** При `strategy: free` задачи на разных хостах выполняются независимо, но общие переменные (`set_fact`) не синхронизируются между хостами.

**Решение:** Используйте `run_once: true` с `delegate_to: localhost` для сбора данных, или вернитесь на `linear`.

### Ошибка: `async` задача потеряна после перезапуска Control Node

**Причина:** Идентификатор фоновой задачи (`ansible_job_id`) хранится в переменной плейбука и теряется при прерывании.

**Решение:** Сохраняйте `jid` в файл или внешнее хранилище:
```yaml
- name: Сохранить JID для последующего опроса
  ansible.builtin.copy:
    content: "{{ async_job.ansible_job_id }}"
    dest: "/tmp/jid_{{ inventory_hostname }}"
  delegate_to: localhost
```

### Ошибка: `include_role` в цикле вызывает каскадные ошибки

**Причина:** `include_role` внутри `loop` создает отдельный экземпляр роли для каждого элемента, что может привести к race conditions или превышению лимитов.

**Решение:** Используйте `block` с одной ролью и передавайте данные через `vars`, или замените на `import_role` если логика статична.

## Лучшие практики

### Структура и архитектура

1. **Один плей = одна цель.** Не смешивайте установку, конфигурацию и деплой в одном плее.
2. **Плейбуки-оркестраторы.** Верхнеуровневые плейбуки должны вызывать роли через `import_playbook` или `roles`, а не содержать задачи напрямую.
3. **FQCN.** Всегда используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`).
4. **Идиоматичность.** Используйте специализированные модули вместо `shell`/`command` для обеспечения идемпотентности.

### Rolling Updates и Zero-Downtime

5. **`serial` для критичных обновлений.** Всегда используйте пакетную обработку при деплое на продакшен. Подробнее: **[Стратегии деплоя и rolling updates](../ansible_deployment_strategies.md)**.
6. **`max_fail_percentage`.** Устанавливайте порог падений для остановки при массовых сбоях.
7. **`any_errors_fatal: true`** для Canary-хоста. Остановка при ошибке на первом хосте.
8. **Health check после обновления.** Проверяйте работоспособность до возврата в балансировщик.

### Обработчики и теги

9. **`notify` вместо прямого рестарта.** Используйте обработчики для условного перезапуска сервисов.
10. **`meta: flush_handlers`** когда нужно применить изменения до продолжения.
11. **`force_handlers: true`** для критичных сервисов. Обработчики должны выполняться даже при ошибках.
12. **Теги для точечных изменений.** Позволяйте запускать отдельные части плейбука через `--tags`.

### Безопасность и надежность

13. **`no_log: true`** для задач с секретами. Скрывайте пароли и ключи от логов.
14. **`changed_when` / `failed_when`** для точной отчетности о статусе задач.
15. **Dry-run перед деплоем.** Всегда проверяйте `--check --diff` перед применением на продакшене.
16. **Drift detection.** Регулярно запускайте плейбуки в `--check` для обнаружения несанкционированных изменений.
17. **Аудит.** Настройте `log_path` в `ansible.cfg` и callback-плагины для централизованного логирования. Подробнее: **[Безопасность Ansible](../ansible_security_best_practices.md)**.

### Импорты и включения

18. **`import_*` для фиксированной структуры.** Используйте `import_role` и `import_tasks` когда логика известна на этапе парсинга.
19. **`include_*` для гибкой логики.** Используйте `include_role` и `include_tasks` когда выбор зависит от фактов или переменных.
20. **Явные пути.** Избегайте относительных путей без указания `paths:` в `lookup('first_found', ...)`.

### Сценарий 9: Организация множества плейбуков в крупном проекте

При росте числа ролей и окружений единый `site.yml` становится монолитом. Правильная структура каталога `playbooks/` и выбор между `import_playbook` и отдельными запусками определяют поддерживаемость проекта.

```
project/
├── ansible.cfg
├── inventories/
│   ├── dev/
│   ├── staging/
│   └── prod/
├── playbooks/
│   ├── site.yml                 # Оркестратор верхнего уровня
│   ├── provision.yml            # Базовое подключение хостов
│   ├── deploy_app.yml           # Деплой приложения
│   ├── deploy_db.yml            # Миграции БД
│   ├── rollback.yml             # Откат последнего деплоя
│   ├── drift_detection.yml      # Детект дрейфа
│   ├── health_check.yml         # Проверка здоровья после деплоя
│   └── cleanup.yml              # Очистка артефактов
├── roles/
└── collections/
    └── requirements.yml
```

**Правила именования:**
- `site.yml` — оркестратор, вызывает остальные плейбуки.
- `deploy_*.yml` — деплой конкретного сервиса.
- `rollback.yml` — универсальный откатный плейбук.
- `*_check.yml` — проверки без изменений.

**Паттерн 1: Оркестратор через `import_playbook` (статическая композиция)**

```yaml
# playbooks/site.yml
---
- name: Этап 1: Подготовка инфраструктуры
  ansible.builtin.import_playbook: provision.yml

- name: Этап 2: Деплой приложения
  ansible.builtin.import_playbook: deploy_app.yml

- name: Этап 3: Миграции базы данных
  ansible.builtin.import_playbook: deploy_db.yml

- name: Этап 4: Проверка здоровья
  ansible.builtin.import_playbook: health_check.yml
```

`import_playbook` выполняется на этапе парсинга. Подходит, когда структура известна заранее и не требуется условная логика между этапами.

**Паттерн 2: Условная композиция через `include_playbook` (динамическая)**

```yaml
# playbooks/site.yml
---
- name: Деплой с условным откатом
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Деплой приложения
      ansible.builtin.include_playbook: deploy_app.yml

    - name: Проверка здоровья
      ansible.builtin.include_playbook: health_check.yml

    - name: Откат при проблемах
      ansible.builtin.include_playbook: rollback.yml
      when: deployment_failed | default(false)
```

`include_playbook` выполняется во время выполнения. Позволяет использовать факты и переменные для выбора плейбука.

**Паттерн 3: Независимые запуски через CI/CD (рекомендуется для production)**

Вместо одного оркестратора каждый этап запускается отдельной командой. Это дает максимальную устойчивость и понятные артефакты выполнения:

```bash
# Этап 1: Проверка и подготовка
ansible-playbook -i inventories/prod/hosts.yml playbooks/provision.yml --check --diff

# Этап 2: Деплой БД (остановка при ошибке)
ansible-playbook -i inventories/prod/hosts.yml playbooks/deploy_db.yml \
  --tags migrate \
  --extra-vars "db_version=v2.3.1"

# Этап 3: Деплой приложения (rolling update)
ansible-playbook -i inventories/prod/hosts.yml playbooks/deploy_app.yml \
  --serial "25%" \
  --max_fail_percentage 10

# Этап 4: Проверка здоровья
ansible-playbook -i inventories/prod/hosts.yml playbooks/health_check.yml

# При ошибке на этапе 3 или 4 — откат
ansible-playbook -i inventories/prod/hosts.yml playbooks/rollback.yml \
  --extra-vars "target_version=v2.2.0"
```

**Преимущества отдельных запусков:**
- Каждый этап имеет отдельный лог и статус в CI/CD.
- При падении этапа 3 не нужно перезапускать этап 1.
- Легче ограничивать blast radius через `serial` и `max_fail_percentage` на уровне отдельного плейбука.
- Артефакты (логи, статусы) не смешиваются.

**Когда использовать единый оркестратор:**
- Малый проект (до 10 хостов), где все этапы логически связаны.
- Необходимость атомарного отката всего деплоя через `block/rescue` на уровне оркестратора.
- Ограниченная инфраструктура CI/CD (один джоб вместо нескольких).

**Критерии разделения плейбуков:**

| Критерий | Рекомендация |
| :--- | :--- |
| Количество хостов | >50 — разделяйте на этапы |
| Количество ролей | >8 — каждый сервис = отдельный плейбук |
| Частота изменений | БД меняется реже, чем приложение — разделите |
| Риск операции | Миграции БД — отдельный плейбук с `any_errors_fatal: true` |
| Время выполнения | >30 минут — разделите на этапы с сохранением состояния |

### Сценарий 10: Версионирование и отслеживание изменений плейбуков

В production-среде каждое изменение плейбука должно быть прослеживаемо. Git является стандартом хранения, но требует дисциплины.

**Структура Git-репозитория:**

```
infrastructure/
├── ansible/
│   ├── ansible.cfg
│   ├── playbooks/
│   ├── roles/
│   ├── collections/
│   │   └── requirements.yml
│   └── .gitignore
├── terraform/                  # Если используется IaC
└── README.md
```

**Версионирование плейбуков:**
- Храните плейбуки в Git с подписанными коммитами (`git commit -S`).
- Используйте ветки: `main` — production, `develop` — staging, `feature/*` — разработка.
- Каждый деплой привязан к коммиту или тегу: `git checkout v1.2.3 && ansible-playbook site.yml`.
- Для ролей фиксируйте версии в `requirements.yml`:

```yaml
# collections/requirements.yml
collections:
  - name: community.general
    version: ">=6.0.0,<7.0.0"
  - name: ansible.posix
    version: ">=1.5.0,<2.0.0"
```

**Аудит изменений:**
- Включите `log_path = ./logs/ansible.log` в `ansible.cfg`.
- Используйте callback-плагины для отправки событий в SIEM.
- Никогда не коммитьте открытые секреты. Используйте `git diff --cached` и pre-commit hooks.

### Сценарий 11: Валидация структуры плейбуков

Перед запуском в production выполните статический анализ:

```bash
# 1. Проверка синтаксиса YAML
ansible-playbook playbooks/site.yml --syntax-check

# 2. Линтинг (включая security-профиль)
ansible-lint playbooks/ roles/ --profile security

# 3. Проверка целостности инвентаря
ansible-inventory -i inventories/prod/hosts.yml --list | python3 -m json.tool > /dev/null

# 4. Dry-run с diff
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml --check --diff
```

**Интеграция в CI/CD (GitHub Actions пример):**

```yaml
# .github/workflows/ansible-lint.yml
name: Ansible Lint
on: [push, pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint playbooks
        run: ansible-lint playbooks/ roles/ --profile security
      - name: Syntax check
        run: |
          for pb in playbooks/*.yml; do
            ansible-playbook "$pb" --syntax-check
          done
```

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты плейбука (roles, pre_tasks, post_tasks).
* [Продвинутые возможности](advanced.md) — `include_playbook`, `vars_prompt`, callback-плагины, делегирование.
* [Валидация и тестирование структуры плейбуков](testing_and_validation.md) — статический анализ, dry-run, идемпотентность и CI/CD.
* [Стратегии деплоя и rolling updates](../ansible_deployment_strategies.md) — Blue-Green, Canary, Rolling Update.
* [Оптимизация производительности](../ansible_performance_tuning.md) — `strategy`, `throttle`, `forks`, `async`.
* [Роли Ansible](../ansible_roles.md) — `import_role`/`include_role`, структура ролей, теги.
* [Управление мультисредами](../ansible_multi_environment_management.md) — изоляция dev/staging/prod.
* [Тестирование с Molecule](../ansible_testing_with_molecule.md) — тестирование ролей на изолированных окружениях.
