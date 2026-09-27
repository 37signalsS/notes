# Создание и использование ролей Ansible

## Определения

**Роль (Role)** — основной механизм декомпозиции и переиспользования кода в Ansible. Она позволяет объединять задачи, переменные, файлы и шаблоны в логические блоки для настройки конкретных сервисов или компонентов системы.

**Использование роли** — процесс интеграции роли в плейбук одним из трех способов: через классическую директиву `roles`, статическое импортирование (`ansible.builtin.import_role`) или динамическое включение (`ansible.builtin.include_role`).

**Статическое импортирование (`ansible.builtin.import_role`)** — механизм, при котором роль вставляется в плейбук на этапе парсинга (до начала выполнения). Все задачи роли становятся частью основного списка задач. Это аналогично вставке кода (inline) в место вызова.

**Динамическое включение (`ansible.builtin.include_role`)** — механизм, при котором роль подключается непосредственно во время выполнения плейбука, когда очередь доходит до соответствующего шага.

**Спецификация аргументов (`argument_spec`)** — декларативное описание входных параметров роли в файле `meta/argument_specs.yml`, позволяющее Ansible автоматически проверять типы и обязательность переменных.

**SRE (Site Reliability Engineering)** — дисциплина, сочетающая принципы software engineering с системным администрированием для обеспечения надежности, масштабируемости и наблюдаемости сервисов.

---

## Основные концепции / Архитектура / Принципы работы

### Жизненный цикл роли в плейбуке

Понимание жизненного цикла критично для SRE и sysadmin при отладке инцидентов:

1. **Обнаружение (Discovery):** Ansible ищет роль в директориях из `roles_path` (по умолчанию `./roles` рядом с плейбуком, `~/.ansible/roles`, `/usr/share/ansible/roles`). Поддерживается FQCN (`namespace.collection.role_name`).
2. **Загрузка зависимостей:** Выполняются роли из `meta/main.yml → dependencies` до основной роли.
3. **Загрузка переменных:** Сначала `defaults/main.yml` (низкий приоритет), затем внешние переменные переопределяют их.
4. **Выполнение задач:** Задачи из `tasks/main.yml` выполняются последовательно.
5. **Обработчики:** Выполняются после секций задач, если были уведомления через `notify`.

### Изоляция и область видимости

Роли инкапсулируют свою логику, но переменные могут пересекаться:
- **`defaults/main.yml`:** Низкий приоритет, безопасно для переопределения.
- **`vars/main.yml`:** Высокий приоритет, внутренние константы.
- **`public` параметр:** Управляет экспортом переменных за пределы роли (Ansible 2.15+ для `import_role`, 2.15+ для `include_role`).

### Версионирование и воспроизводимость

Для SRE критически важно, чтобы автоматизация была воспроизводимой:
- **Git-теги:** Версионируйте роли через Git (`v1.0.0`, `v1.1.0`).
- **`requirements.yml`:** Фиксируйте версии ролей и коллекций.
- **Collections:** Используйте семантическое версионирование для коллекций.

### Создание и инициализация роли

Процесс создания каркаса роли и подробное описание её внутренней структуры (каталоги, назначение файлов, валидация аргументов) вынесены в отдельный раздел:

*   **[Структура роли Ansible](structure.md)** — инициализация через `ansible-galaxy`, назначение каталогов `tasks`, `meta`, `defaults`, `vars` и др.

---

## Установка и настройка / Практические сценарии

### Версии программного обеспечения

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Python (контрольный узел)** | 3.12 (Ansible 2.21) | 3.14+ |
| **Python (управляемые узлы)** | 3.9 (Ansible 2.21) | 3.12+ |
| **ansible-core** | 2.21.4 | 2.21+ |
| **ansible-galaxy** | Входит в ansible-core | Последняя стабильная версия |
| **ansible-lint** | 26.x | Последняя стабильная версия (v26.8.0) |
| **Molecule** (опционально) | 26.x | Последняя стабильная версия (v26.9.0+) |

### Начальная настройка

```bash
# Установка Ansible (через pip)
pip install ansible-core  # → Successfully installed ansible-core-2.21.x

# Проверка версии
ansible --version  # → ansible [core 2.21.x]

# Инициализация структуры проекта
mkdir -p roles/ && cd roles/
ansible-galaxy role init my_first_role  # → роль успешно создана
```

### Структура проекта

Рекомендуемая структура для проекта с ролями:

```text
project/
├── ansible.cfg          # Конфигурация Ansible
├── inventory/
│   ├── production/
│   │   ├── hosts.yml    # Инвентарий production
│   │   └── group_vars/
│   │       └── all.yml  # Групповые переменные
│   └── staging/
├── roles/
│   ├── common/          # Базовая роль
│   ├── nginx/           # Роль веб-сервера
│   └── app/             # Роль приложения
├── playbooks/
│   ├── site.yml         # Основной плейбук
│   └── webservers.yml   # Плейбук для веб-серверов
└── requirements.yml     # Зависимости (Galaxy, collections)
```

### Способы подключения ролей

#### 1. Классический способ (`roles:`)

Роли выполняются в самом начале плейбука (после `pre_tasks`). Это наиболее простой метод, но он обладает наименьшей гибкостью в управлении порядком выполнения относительно других задач.

```yaml
- hosts: webservers
  roles:
    - common
    - role: nginx
      nginx_port: 80
```

#### 2. Статическое использование (`ansible.builtin.import_role`)

Роль обрабатывается при запуске плейбука (parsing time).
- **Плюсы:**
    - Теги внутри роли видны сразу. Можно запустить плейбук с `--tags "some_inner_tag"`.
    - Обработчики (`handlers`) роли доступны всему плейбуку.
    - Высокая производительность (нет накладных расходов на runtime-загрузку).
- **Минусы:**
    - Нельзя использовать циклы (`loop`) на уровне вызова.
    - Нельзя использовать переменные, определенные в ходе выполнения (факты), в имени роли.

```yaml
tasks:
  - name: Import monitoring role
    ansible.builtin.import_role:
      name: monitoring
```

#### 3. Динамическое использование (`ansible.builtin.include_role`)

Роль загружается «на лету» во время исполнения (runtime).
- **Плюсы:**
    - Полная поддержка циклов (`loop`).
    - Поддержка условий (`when`) на уровне всего включения (если условие ложно, роль не загружается, что экономит ресурсы).
    - Имя роли может быть переменной, вычисленной во время выполнения (например, на основе фактов об ОС).
- **Минусы:**
    - Теги внутренних задач не видны до момента выполнения задачи `include_role`.
    - По умолчанию переменные роли изолированы (требуется `public: true` для экспорта).

```yaml
tasks:
  - name: Include role for each application
    ansible.builtin.include_role:
      name: "{{ item.role_name }}"
    loop: "{{ applications }}"
```

### Сценарий 1: Условное выполнение роли на основе фактов

Динамический выбор роли в зависимости от операционной системы:

```yaml
tasks:
  - name: Setup OS specific role
    ansible.builtin.include_role:
      name: "{{ ansible_facts['os_family'] | lower }}_setup"
    when: ansible_facts['os_family'] in ['Debian', 'RedHat', 'Suse', 'Archlinux']
```

### Сценарий 2: Использование тегов для фильтрации

Теги позволяют запускать только определенные части автоматизации. При использовании `roles:` или `import_role` теги можно задавать прямо при вызове:

```yaml
roles:
  - role: security
    tags: ["hardening", "security"]
  - role: webserver
    tags: ["nginx", "web"]
```

Запуск только задач безопасности:
```bash
ansible-playbook site.yml --tags "security"  # → выполнение только роли security
```

### Сценарий 3: Передача переменных с экспортом (`public: true`)

Если роль `my_app` определяет версию, которую нужно использовать в других ролях:

```yaml
tasks:
  - name: Install and export vars
    ansible.builtin.include_role:
      name: my_app
      public: true

  - name: Use var from role
    ansible.builtin.debug:
      msg: "Installed version: {{ my_app_version }}"
```

### Сценарий 4: Полная параметризация через group_vars

Рекомендуемый способ управления настройками для разных окружений без изменения кода ролей.
**Структура:** `group_vars/production.yml` → `playbook.yml` → `roles/nginx/`.

```yaml
# group_vars/production.yml
nginx_port: 443

# playbook.yml
- hosts: production
  roles:
    - nginx
```

### Сценарий 5: Вызов роли из коллекции (FQCN)

Для ролей, поставляемых в составе коллекций, необходимо использовать полное имя:

```yaml
tasks:
  - name: Install Postgres from community collection
    ansible.builtin.include_role:
      name: community.postgresql.postgres_install
```

### Сценарий 6: Тестирование ролей через ansible-lint

Перед использованием ролей рекомендуется проверять их качество:

```bash
# Установка ansible-lint
pip install ansible-lint  # → Successfully installed ansible-lint-26.x.x

# Проверка конкретной роли
ansible-lint roles/nginx/  # → No errors found

# Проверка с профилем (рекомендуется)
ansible-lint roles/nginx/ --profile production  # → No errors found
```

Пример конфигурации `.ansible-lint` в корне проекта:

```yaml
# .ansible-lint
profile: production  # Использовать профиль production
skip_list:
  - yaml[truthy]     # Разрешить yes/no в YAML
  - name[template]   # Разрешить шаблоны в именах задач
enable_list:
  - fqcn             # Требовать FQCN для всех модулей
```

### Сценарий 7: Работа с секретами в ролях

Секреты в роли хранятся в зашифрованном виде через Ansible Vault, но **вне** `defaults/`. Причина: зашифрованный файл в `defaults/` требует Vault-пароль уже на этапе разбора плейбука, а без него даже обычный `defaults/main.yml` этой роли становится недоступен. Теория шифрования и работа с паролями — в [Ansible Vault](../Vault/basics.md).

**Правильная структура роли:**

```text
roles/myapp/
├── defaults/
│   └── main.yml            # Только несекретные значения, объявленные по умолчанию
├── vars/
│   ├── main.yml            # Несекретные значения с высоким приоритетом
│   └── vault.yml           # Зашифрованные секреты (коммитится в Git)
├── tasks/
│   └── main.yml
└── .gitignore
```

```yaml
# roles/myapp/defaults/main.yml — объявляет интерфейс, секретов не содержит
myapp_db_host: localhost
myapp_db_user: myapp
myapp_db_password: ""          # Будет переопределено из vars/vault.yml
myapp_api_token: ""
```

```yaml
# roles/myapp/vars/vault.yml — зашифрован (ansible-vault encrypt)
# Значения имеют приоритет уровня vars (3) и переопределяют defaults (1)
myapp_db_password: "s3cr3t-p4ssw0rd"
myapp_api_token: "ghp_xxxxxxxxxxxxxxxx"
```

```yaml
# roles/myapp/tasks/main.yml — no_log на задачах, где секрет попадает в вывод
- name: Создать пользователя БД
  ansible.builtin.mysql_user:
    name: "{{ myapp_db_user }}"
    password: "{{ myapp_db_password }}"
    state: present
  no_log: true
```

```bash
# Шифрование файла с секретами
ansible-vault encrypt roles/myapp/vars/vault.yml
# → Encryption successful

# Проверка содержимого без расшифровки (видны только имена переменных)
ansible-vault view roles/myapp/vars/vault.yml
# → myapp_db_password: VALUE_SPECIFIED_IN_NO_LOG_PARAMETER
# → myapp_api_token: VALUE_SPECIFIED_IN_NO_LOG_PARAMETER

# Проверка целостности и алгоритма шифрования
ansible-vault view --decrypt roles/myapp/vars/vault.yml --vault-password-file ~/.vault_pass
# → myapp_db_password: s3cr3t-p4ssw0rd

# Запуск с расшифровкой
ansible-playbook site.yml --ask-vault-pass
# → Vault password: ****
# → playbook completed: ok=15 changed=3

# Запуск с файлом пароля (в CI — через переменную окружения, не в коде)
ansible-playbook site.yml --vault-password-file ~/.vault_pass
# → playbook completed: ok=15 changed=3
```

**Правила безопасности ролей с секретами:**

1.  `no_log: true` на любой задаче, где секрет передаётся в модуль — иначе значение попадёт в вывод и в лог CI.
2.  Не используйте `ansible.builtin.debug` с `var:`, выводящим секреты, — `no_log` не спасает от отдельного `debug`.
3.  Файл пароля Vault не хранится в репозитории; передавайте путь через `ANSIBLE_VAULT_PASSWORD_FILE` или `--vault-password-file`.
4.  `--list-variables` и `--list-tasks` не показывают значения секретов, но `--list-variables` покажет имена — имена секретов сами по себе не чувствительны.
5.  При `fact_caching` включённом факты, созданные из секретов через `set_fact`, могут быть записаны в кеш на диск в открытом виде. Для таких случаев используйте внешний источник секретов (HashiCorp Vault) вместо `set_fact`.

Полный разбор работы с секретами в ролях — в [Паттерн Utility Role](utility_role_pattern.md), методика — в [Ansible Vault: лучшие практики](../Vault/best_practices.md).

### Сценарий 8: Интеграция ролей в CI/CD

Пример использования ролей в GitLab CI:

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - deploy

ansible-lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint roles/ --profile production  # → No errors found

molecule-test:
  stage: test
  image: quay.io/ansible/molecule
  services:
    - docker:dind
  script:
    - cd roles/nginx
    - molecule test
  only:
    - merge_requests

deploy-production:
  stage: deploy
  image: cytopia/ansible
  script:
    - ansible-playbook -i inventory/production site.yml  # → playbook completed: ok=15 changed=3
  environment:
    name: production
  when: manual
  only:
    - main
```

### Сценарий 9: Отладка выполнения ролей

Отладка роли — обширная тема со своей терминологией: границы директив уровня Role, `run_once` + `delegate_to` + `set_fact`, `delegate_facts`, интерактивный `debugger`, чтение временных файлов модулей на удалённых хостах, `check_mode`/`diff` в роли и диагностика порядка выполнения.

Полный разбор — в [Управление выполнением и отладка ролей](task-execution-and-debugging.md). Базовые приёмы отладки инвентаря и переменных — в [Примеры отладки](../examples/debugging_examples.md), интерактивный отладчик — в [Отладка playbook'ов](../PlaybookStructure/advanced.md).

Краткий чек-лист для быстрой диагностики:

```bash
# Порядок задач в плейбуке без выполнения
ansible-playbook site.yml --list-tasks
# → play #1 (web_server) (web-01)
# →   TASK [web_server : Собрать версию nginx] ***

# Интерактивный отладчик на упавшей задаче
ansible-playbook site.yml --start-at-task="web_server : Проверить конфигурацию"
# → fatal: [web01]: FAILED! => {"msg": "..."}
# → Debugger invoked

# Отладчик только для одной роли
ANSIBLE_DEBUG=1 ansible-playbook site.yml --step
```

Отладка переменных в задачах роли:

```yaml
# roles/web_server/tasks/debug.yml — включается по тегу, а не всегда
- name: Показать все переменные текущего хоста
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]
  tags: [never]

- name: Показать конкретную переменную
  ansible.builtin.debug:
    msg: "nginx_port is {{ nginx_port | default('NOT SET') }}"
  tags: [never]
```

```bash
# Вызов отладочных задач роли по тегу
ansible-playbook site.yml --tags never -e ansible_debug=true
# → ok: [web-01] => {
# →   "msg": "nginx_port is 80"
# → }
```

### Сценарий 10: Оптимизация производительности

Для больших инфраструктур и ролей с ресурсоемкими задачами:

```yaml
# Параллельное выполнение с ограничением
- name: Install updates on all servers
  ansible.builtin.include_role:
    name: system_update
  throttle: 5  # Максимум 5 хостов одновременно

# Асинхронное выполнение длительных задач
- name: Run database backup
  ansible.builtin.include_role:
    name: db_backup
  async: 3600  # Таймаут 1 час
  poll: 0      # Не ждать завершения
  register: backup_job

# Проверка статуса асинхронной задачи
- name: Wait for backup to complete
  ansible.builtin.async_status:
    jid: "{{ backup_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

Настройка `ansible.cfg` для оптимизации:

```ini
[defaults]
forks = 20          # Количество параллельных потоков
timeout = 30        # Таймаут подключения
gathering = smart   # Сбор фактов только при необходимости
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400

[ssh_connection]
pipelining = True   # Включить pipelining для ускорения
```

### Сценарий 11: Автоматизация реагирования на инциденты (SRE)

Для SRE-практик важно иметь возможность быстро запускать роли для восстановления сервисов:

```yaml
# playbooks/incident_response.yml
- name: Emergency Nginx restart
  hosts: "{{ target_hosts | default('webservers') }}"
  become: true
  tasks:
    - name: Restart and verify Nginx
      ansible.builtin.include_role:
        name: nginx
        apply:
          tags: [restart, emergency]
      when: incident_type == "service_down"

    - name: Rollback previous release
      ansible.builtin.include_role:
        name: app_deploy
        vars:
          app_version: "{{ previous_version }}"
        apply:
          tags: [rollback]
      when: rollback_required | default(false)
```

Запуск с ограничением по хостам и тегами:
```bash
ansible-playbook incident_response.yml --limit "webserver[1:3]" --tags "restart" --check
```

### Сценарий 12: Версионирование ролей через Git

Для соблюдения принципа Infrastructure as Code роли должны храниться в Git с семантическим версионированием:

```bash
# Тегирование роли
git tag -a v1.2.0 -m "Add PostgreSQL 16 support"
git push origin v1.2.0

# requirements.yml с фиксацией версий
# requirements.yml
---
roles:
  - name: geerlingguy.nginx
    version: "3.3.0"
  - name: internal_common
    src: git@github.com:myorg/ansible-roles.git
    scm: git
    version: main
    path: roles/
```

### Сценарий 13: Работа с несколькими ОС

```yaml
tasks:
  - name: Load OS-specific variables
    ansible.builtin.include_vars: "{{ lookup('first_found', params) }}"
    vars:
      params:
        files:
          - "{{ ansible_facts['os_family'] }}.yml"
          - "default.yml"
        paths:
          - "../vars"

  - name: Include OS-specific tasks
    ansible.builtin.include_tasks: "{{ lookup('first_found', params) }}"
    vars:
      params:
        files:
          - "{{ ansible_facts['os_family'] | lower }}.yml"
          - "default.yml"
        paths:
          - "../tasks"
```

#### Условное включение зависимостей

```yaml
# meta/main.yml
dependencies:
  - role: nginx
    when: install_webserver | default(false)
```

**Примечание:** Условия в `meta/main.yml` поддерживаются с Ansible 2.18+.

### Сценарий 14: Передача фактов и данных между хостами через роль

Роль, которая читает данные с одного узла и применяет на другом, должна явно управлять тем, к какому хосту привязываются факты. По умолчанию факты, собранные при делегировании, сохраняются для делегированного хоста, а не для целевого.

```yaml
# roles/frontend_sync/tasks/main.yml
- name: Убедиться, что группа балансировщиков существует в инвентаре
  ansible.builtin.assert:
    that:
      - groups['load_balancers'] is defined
      - groups['load_balancers'] | length > 0
    fail_msg: "Роль frontend_sync требует непустую группу load_balancers в инвентаре"

- name: Получить состав upstream с балансировщика
  ansible.builtin.setup:
    filter: "ansible_facts.packages"
  delegate_to: "{{ groups['load_balancers'][0] }}"
  delegate_facts: true      # факт привязывается к текущему хосту, а не к балансировщику
  run_once: true            # один запрос на пакет, а не на каждый хост
  register: lb_packages

- name: Применить конфигурацию на текущем хосте
  ansible.builtin.template:
    src: upstream.conf.j2
    dest: /etc/myapp/upstream.conf
  vars:
    upstreams: "{{ lb_packages.ansible_facts.packages | list }}"
  notify: reload app
```

**Особенности поведения:**

| Конструкция | Без `delegate_facts` | С `delegate_facts: true` |
| :--- | :--- | :--- |
| `setup` с `delegate_to` | Факт попадает в `hostvars['балансировщик']` | Факт попадает в `hostvars['текущий хост']` |
| Модули без фактов (`slurp`, `uri`, `command`) | `register` пишет в текущего хоста | То же — `delegate_facts` не нужен |
| `run_once: true` | Выполняется на первом хосте пакета | Тот же результат раздаётся всем хостам пакета |

Модули, не создающие факты, не требуют `delegate_facts` — им достаточно `register`. `delegate_facts` нужен ровно для `ansible.builtin.setup` и модулей, порождающих факты.

Полный разбор делегирования и `set_fact` — в [Переменные и факты](../PlaybookStructure/variables.md).

### Сценарий 15: Обёртывание роли в pre- и post-логику

Роль выполняется в секции `roles:` — то есть **до** `tasks:` плейбука. Если вокруг неё нужны подготовительные и заключительные шаги, есть три способа, и выбор зависит от требуемой семантики.

```yaml
# Способ 1 (рекомендуемый): pre_tasks/post_tasks в плейбуке
- name: Управление конфигурацией
  hosts: webservers
  pre_tasks:
    - name: Создать рабочие каталоги
      ansible.builtin.file:
        path: /var/lib/myapp
        state: directory
  roles:
    - role: web_server
  post_tasks:
    - name: Отправить событие в шину
      ansible.builtin.uri:
        url: "{{ events_api }}/deployed"
        method: POST
```

```yaml
# Способ 2: include_role внутри блока — роль становится частью композиции
- name: Управление конфигурацией
  hosts: webservers
  tasks:
    - name: Подготовительные шаги
      ansible.builtin.file:
        path: /var/lib/myapp
        state: directory

    - name: Основная роль
      ansible.builtin.include_role:
        name: web_server

    - name: Заключительные шаги
      ansible.builtin.uri:
        url: "{{ events_api }}/deployed"
        method: POST
```

```yaml
# Способ 3: подготовительные и заключительные шаги ВНУТРИ самой роли
# roles/web_server/tasks/main.yml
- name: Создать рабочий каталог до настройки
  ansible.builtin.file:
    path: /var/lib/myapp
    state: directory

- name: Основная логика роли
  ansible.builtin.include_tasks: configure.yml

- name: Уведомить систему мониторинга
  ansible.builtin.uri:
    url: "{{ vault_monitoring_api }}/roles/completed"
    method: POST
    body_format: json
    body:
      role: web_server
      host: "{{ inventory_hostname }}"
  no_log: true
```

**Критерий выбора:** если шаг нужен только при конкретном сценарии применения — способ 1 или 2. Если шаг является неотъемлемой частью ответственности роли (создать каталог, снять метрику, отправить отчёт) — способ 3.

**Ограничения, о которых стоит помнить:**

*   Директива `roles:` не поддерживает собственные `pre_tasks`/`post_tasks` — это ключевые слова уровня Play.
*   `import_role` разворачивается на парсинге, поэтому его задачи попадут в позицию вызова; `include_role` выполняется в момент достижения и позволяет применять `when` и `loop`.
*   Задачи в секции `roles:` не могут использовать значения, вычисленные в `tasks:` плейбука, — они выполняются раньше.

### Сценарий 16: Роль для Windows-хостов

Роль для Windows-хоста отличается от Linux-роли по подключению, повышению привилегий, путям и набору модулей.

```yaml
# roles/windows_features/tasks/main.yml
- name: Установить компоненты Windows
  ansible.windows.win_feature:
    name:
      - RSAT-AD-PowerShell
      - Web-WebSockets
    state: present
  become: true
  become_method: runas
  ansible_become_pass: "{{ vault_admin_password }}"
  no_log: true

- name: Создать каталог приложения
  ansible.windows.win_file:
    path: C:\Apps\myapp
    state: directory

- name: Развернуть конфигурацию из шаблона
  ansible.windows.win_template:
    src: "templates/app.config.j2"
    dest: 'C:\Apps\myapp\app.config'
  notify: restart app service

- name: Настроить службу
  ansible.windows.win_service:
    name: MyApp
    path: C:\Apps\myapp\service.exe
    start_mode: auto
    state: started
  notify: restart app service
```

```yaml
# roles/windows_features/meta/main.yml
collections:
  - ansible.windows
```

**Ключевые отличия Windows-роли от Linux-роли:**

| Аспект | Linux-роль | Windows-роль |
| :--- | :--- | :--- |
| Подключение | `ssh` по умолчанию | `winrm` (HTTP/HTTPS) |
| Повышение привилегий | `become: true` (sudo) | `become_method: runas` + `ansible_become_pass` |
| Пути | `/etc/app/config.yml` | `C:\Apps\myapp\app.config` |
| Модули | `ansible.builtin.*` | `ansible.windows.*` |
| Перенос строк | `LF` | `CRLF` |
| Планировщик | `ansible.builtin.cron` | `ansible.windows.win_scheduled_task` |
| Коллекции в роли | наследуются от плейбука | **не наследуются** — указывать в `meta/main.yml` |

Полный разбор кроссплатформенных ролей — в [Кроссплатформенные концепции](../CrossPlatform/concepts.md).

---

## Операции и команды

### Сравнение механизмов подключения

| Характеристика | `import_role` (Static) | `include_role` (Dynamic) |
| :--- | :--- | :--- |
| **Время обработки** | При парсинге плейбука | Во время выполнения (Runtime) |
| **Циклы (`loop`)** | Не поддерживаются | Полная поддержка |
| **Условия (`when`)** | Применяются к каждой задаче внутри | Проверяется один раз для всей роли |
| **Теги из CLI** | Видны и доступны для фильтрации | Не видны до выполнения |
| **Обработчики (`handlers`)** | Глобально доступны | Доступны после выполнения роли |
| **Python Requirements** | N/A (Control Node) | Python 3.9+ (Target Node для 2.21+), 3.12+ рекомендуется |

### Область видимости переменных (`public`)

Параметр `public` определяет, становятся ли переменные роли (`vars` и `defaults`) доступными для последующих задач в плейбуке.

*   **Ansible 2.17+**: Параметр `public` теперь доступен и для `import_role`. Ранее он работал только для `include_role`.
*   **`public: true`**:
    *   Для `import_role` (по умолчанию): Переменные экспортируются на этапе **парсинга**. Это означает, что они могут быть видны даже задачам, стоящим в плейбуке *выше* вызова роли.
    *   Для `include_role`: Переменные экспортируются только в момент **выполнения** задачи.
*   **`public: false`**: Переменные инкапсулированы внутри роли. Полезно для предотвращения конфликтов имен.
*   **Глобальная настройка**: В `ansible.cfg` параметр `DEFAULT_PRIVATE_ROLE_VARS = true` делает все роли приватными по умолчанию.

### Использование `apply` для передачи параметров

При динамическом включении через `include_role` можно использовать ключевое слово `apply`, чтобы применить атрибуты (теги, `become`, `ignore_errors`, `delegate_to`) ко всем задачам внутри роли.

```yaml
- name: Run database maintenance with tags
  ansible.builtin.include_role:
    name: db_maintenance
    apply:
      tags: [db, maintenance]
      become: true
```

### Порядок выполнения и зависимости

Ansible выполняет элементы плейбука в строгом порядке:
1. `pre_tasks` — задачи, выполняемые до ролей.
2. `roles` — роли, указанные в секции `roles:`.
3. `tasks` — основные задачи плейбука (включая `import_role` и `include_role` в порядке их следования).
4. `post_tasks` — задачи, выполняемые после завершения всех основных действий.
5. `handlers` — выполняются после каждой секции задач, если были уведомления через `notify`.

#### Зависимости ролей

Роли могут зависеть от других ролей. Это описывается в файле `meta/main.yml`. При вызове основной роли Ansible сначала выполнит все её зависимости. 

**Важные нюансы:**
* По умолчанию зависимая роль выполняется только один раз, даже если она указана как зависимость для нескольких ролей.
* Чтобы разрешить повторное выполнение зависимости, используйте `allow_duplicates: true` в `meta/main.yml` зависимой роли.
* **Рекомендация:** Для современных проектов (Ansible 2.10+) часто лучше использовать явные вызовы `include_role` в `tasks/main.yml` основной роли вместо классических зависимостей в `meta`.

---

## Устранение неполадок

### Распространенные ошибки

1. **Использование циклов с `import_role`** — приведет к критической ошибке на этапе парсинга. Для циклов всегда используйте `include_role`.
2. **Путаница в путях** — Ansible ищет роли в папке `roles/` рядом с плейбуком или в путях, указанных в `ansible.cfg` (`roles_path`).
3. **Забытый `become: true`** — если роль выполняет системные задачи, убедитесь, что права повышены. Лучшая практика — использовать `apply` с `become` при динамическом включении.
4. **Конфликт имен переменных** — если две роли используют переменную `port`, экспорт через `public: true` может привести к непредсказуемым результатам. Используйте префиксы (например, `nginx_port`).
5. **Шаблоны в условиях `when`** — в Ansible 2.17+ использование `{{ }}` в `when` может вызвать предупреждения или ошибки безопасности (CVE-2023-5764). Используйте: `when: my_var == "value"`.
6. **Контрольный узел и Python** — для Ansible 2.21+ требуется Python 3.12+ на управляющей машине, Python 3.9+ на управляемых.

### Типичные ошибки и решения

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `ERROR! 'roles' is not a valid attribute` | Секция `roles:` не в том месте | Проверьте структуру плейбука |
| `ERROR! the role 'xxx' was not found` | Роль не найдена в `roles_path` | Проверьте `ansible.cfg` и структуру каталогов |
| `ERROR! Conflicting action detected` | Смешивание `import_role` и `tasks` | Не используйте `import_role` после `tasks` |
| `ERROR! 'include_role' is not a valid attribute` | Старая версия Ansible | Обновите до Ansible 2.9+ |
| `ERROR! Undefined variable` | Переменная не определена | Проверьте `defaults/main.yml` и `group_vars/` |
| `ERROR! Vault password not set` | Отсутствует пароль Vault | Используйте `--ask-vault-pass` или `--vault-password-file` |
| `ERROR! Conflicting action 'import_role' with 'when'` | `when` на уровне плейбука + `import_role` | Вынесите условие внутрь задачи |
| `ERROR! Conflicting variable scope` | Переопределение vars в meta/main.yml | Используйте `defaults/main.yml` для переопределяемых переменных |
| `WARNING: Skipping duplicate role` | Дублирование роли в разных путях | Проверьте `ANSIBLE_ROLES_PATH` |

### Диагностические команды

```bash
# Проверка поиска ролей
ansible --version | grep "roles_path"

# Просмотр всех переменных роли
ansible-inventory --host webserver-01 -e "@roles/nginx/defaults/main.yml"

# Тестовый запуск с выводом переменных
ansible-playbook site.yml --check --diff -vvv

# Проверка синтаксиса
ansible-playbook site.yml --syntax-check

# Просмотр задач без выполнения
ansible-playbook site.yml --list-tasks

# Просмотр тегов
ansible-playbook site.yml --list-tags

# Проверка линтингом
ansible-lint roles/nginx/
ansible-lint roles/nginx/ --profile production
```

### Решение специфических проблем

#### Проблема: Теги не работают с `include_role`

**Симптом:** Запуск `ansible-playbook site.yml --tags "deploy"` не выполняет задачи внутри роли.

**Причина:** `include_role` не наследует теги из CLI автоматически.

**Решение:** Используйте `apply` для передачи тегов:

```yaml
- name: Deploy application
  ansible.builtin.include_role:
    name: app_deploy
    apply:
      tags: [deploy]
  tags: [deploy]  # Тег для самого include_role
```

#### Проблема: Переменные роли не видны после выполнения

**Симптом:** Ошибка `undefined variable` при обращении к переменной роли в последующих задачах.

**Причина:** По умолчанию переменные ролей изолированы.

**Решение:** Установите `public: true`:

```yaml
- name: Configure and export vars
  ansible.builtin.include_role:
    name: my_config
    public: true
```

#### Проблема: Роль выполняется несколько раз

**Симптом:** Зависимость выполняется повторно, хотя уже была вызвана.

**Причина:** По умолчанию `allow_duplicates: false`, но при явных вызовах это может работать иначе.

**Решение:** Контролируйте выполнение через `when` или используйте `allow_duplicates`:

```yaml
# В meta/main.yml зависимой роли
allow_duplicates: true
```

```yaml
# Или контролируйте через условие
- name: Run role only if not already applied
  ansible.builtin.include_role:
    name: my_role
  when: not my_role_applied | default(false)
```

#### Проблема: Медленное выполнение плейбуков с ролями

**Симптом:** Длительное время выполнения, особенно на большом количестве хостов.

**Причина:** Неправильные настройки parallelism или отсутствие кэширования.

**Решение:** Оптимизируйте `ansible.cfg`:

```ini
[defaults]
forks = 50              # Увеличьте количество параллельных потоков
gathering = smart       # Собирайте факты только при необходимости
fact_caching = redis    # Используйте Redis для кэширования
fact_caching_timeout = 86400

[ssh_connection]
pipelining = True       # Ускоряет выполнение на 30-50%
control_path_dir = /tmp/.ansible-ssh-%%h-%%p-%%r
```

---

## Лучшие практики

### Структура и проектирование

1. **Единая ответственность:** Одна роль = один компонент (nginx, postgresql, app).
2. **Интерфейс через `argument_specs`:** Описывайте все входные параметры в `meta/argument_specs.yml`.
3. **Префиксы переменных:** Все переменные роли должны начинаться с имени роли (`nginx_port`, `app_path`).
4. **FQCN:** Всегда используйте полные имена модулей (`ansible.builtin.template`).

### Безопасность

1. **Секреты в Vault:** Никогда не храните пароли в открытом виде.
2. **`no_log: true`:** Скрывайте чувствительные данные в задачах.
3. **Минимальные права:** Используйте `become` только где необходимо.
4. **Проверка зависимостей:** Валидируйте роли из Galaxy перед использованием.

### Производительность

1. **`pipelining`:** Включайте в `ansible.cfg` для ускорения SSH-соединений.
2. **Факты:** Используйте `gathering: smart` или `lazy` для уменьшения количества запросов.
3. **Кэширование:** Используйте Redis или JSON-file для кэширования фактов.
4. **Throttle:** Ограничивайте параллельное выполнение для ресурсоемких ролей.

### Тестирование

1. **ansible-lint:** Проверяйте роли перед коммитом.
2. **Molecule:** Пишите интеграционные тесты для критических ролей.
3. **Check mode:** Тестируйте роли с `--check` перед реальным применением.
4. **Dry run:** Используйте `--diff` для просмотра изменений.

### DevOps и SRE практики

1. **Git как источник истины:** Храните роли в Git, используйте ветки для изменений, pull request для review.
2. **Change Management:** Встраивайте роли в процессы изменения (Change Advisory Board, approval gates).
3. **Toil Reduction:** Автоматизируйте повторяющиеся операционные задачи через роли, отслеживайте время, затраченное на ручные операции.
4. **Incident Response:** Подготовьте роли для быстрого восстановления (restart, rollback, config restore).
5. **Observability:** Интегрируйте роли с системами мониторинга (callback plugins, notifications).
6. **Compliance as Code:** Используйте роли для enforcement политик безопасности и compliance требований.
7. **Disaster Recovery:** Автоматизируйте процедуры восстановления после сбоев через роли.
8. **Blue/Green и Canary:** Используйте параметры ролей для поэтапного внедрения изменений.

### Обработка ошибок в ролях (block/rescue/always)

Роли должны обеспечивать безопасные и откатываемые изменения. Используйте `block`/`rescue`/`always` внутри `tasks/main.yml` для обработки ошибок на уровне роли.

```yaml
# roles/app_deploy/tasks/main.yml
---
- name: Деплой приложения
  block:
    - name: Остановка старого контейнера
      ansible.builtin.docker_container:
        name: "{{ app_name }}"
        state: stopped

    - name: Запуск нового контейнера
      ansible.builtin.docker_container:
        name: "{{ app_name }}"
        image: "{{ app_image }}:{{ app_version }}"
        state: started
      register: deploy_result

    - name: Проверка работоспособности
      ansible.builtin.uri:
        url: "http://localhost:{{ app_port }}/health"
        status_code: 200
      register: health_check

  rescue:
    - name: Откат к предыдущей версии
      ansible.builtin.include_role:
        name: app_rollback
      vars:
        previous_version: "{{ app_previous_version }}"

    - name: Уведомление команды о проблеме
      ansible.builtin.debug:
        msg: "Deploy failed, rolled back to {{ app_previous_version }}"

  always:
    - name: Очистка временных файлов
      ansible.builtin.file:
        path: "/tmp/{{ app_name }}_deploy.log"
        state: absent
```

> **См. также:** [Управление ходом выполнения](../PlaybookStructure/flow_control.md) — общая теория `block`/`rescue`/`always`.

### Отладка переменных ролей

Для диагностики конфликтов переменных используйте комбинацию команд:

```bash
# Просмотр всех переменных для конкретной роли
ansible-playbook site.yml --list-variables -l webserver1

# Просмотр переменных инвентаря
ansible-inventory -i inventory/production --host webserver1 --list

# Граф групп и переменных
ansible-inventory -i inventory/production --graph --vars

# Проверка приоритетов переменных
ansible-playbook site.yml -e "debug_var_priority=true" -e "{{ lookup('vars', 'nginx_port') }}"
```

```yaml
# tasks/debug.yml
---
- name: Debug - show all role variables
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]
    verbosity: 1

- name: Debug - show specific variable with source
  ansible.builtin.debug:
    msg: "nginx_port={{ nginx_port }} (source: {{ nginx_port | default('NOT SET') }})"
```

> **См. также:** [Переменные и факты](../PlaybookStructure/variables.md) — полная иерархия приоритетов.

### Безопасность ролей (become, no_log, least privilege)

Роли должны следовать принципу минимальных привилегий:

```yaml
# roles/myapp/tasks/main.yml
---
- name: Создание пользователя приложения
  ansible.builtin.user:
    name: "{{ app_user }}"
    system: true
    shell: /usr/sbin/nologin
  become: true
  become_method: sudo
  no_log: true  # Скрыть имя пользователя из логов

- name: Установка пароля
  ansible.builtin.user:
    name: "{{ app_user }}"
    password: "{{ app_password_hash }}"
  become: true
  no_log: true  # Скрыть хэш пароля

- name: Развертывание конфигурации
  ansible.builtin.template:
    src: app.conf.j2
    dest: "/etc/{{ app_name }}/app.conf"
    owner: "{{ app_user }}"
    group: "{{ app_group }}"
    mode: '0640'
  become: true
  notify: restart app
```

**Принципы:**
- Используйте `become: true` только на уровне задачи, а не playbook.
- Устанавливайте `no_log: true` для всех задач с секретами.
- Разделяйте `become_method` (sudo, runas, pbrun) в зависимости от окружения.
- Никогда не храните пароли/ключи в `defaults/main.yml`.

> **См. также:** [Рекомендации по безопасности](../ansible_security_best_practices.md) — общая безопасность Ansible.

### Наблюдаемость ролей (callback-плагины, метрики)

Роли должны генерировать структурированные логи для интеграции с системами мониторинга:

```yaml
# roles/monitoring_agent/tasks/main.yml
---
- name: Установка агента мониторинга
  ansible.builtin.package:
    name: prometheus-node-exporter
    state: present
  register: install_result
  notify: restart node_exporter

- name: Отправка метрики установки
  ansible.builtin.debug:
    msg: "prometheus_node_exporter_installed={{ install_result.changed | lower }}"
  when: install_result is defined

- name: Проверка доступности метрик
  ansible.builtin.uri:
    url: "http://localhost:9100/metrics"
    status_code: 200
  register: metrics_check
  retries: 3
  delay: 5
  until: metrics_check.status == 200
```

**Интеграция с callback-плагинами:**
- Настройте `json` или `yaml` callback для отправки результатов в централизованный лог-агрегатор.
- Используйте `register` для сохранения результатов задач, которые можно агрегировать в Prometheus/Grafana.
- Добавляйте `tags` для фильтрации задач при анализе логов.

> **См. также:** [Callback-плагины для мониторинга](../ansible_monitoring_callbacks.md) — разработка callback-плагинов.

### Execution Environments и роли

При использовании Execution Environments (EE) роли упаковываются через `ansible-builder`:

```yaml
# execution-environment.yml
version: 3
build_arg_defaults:
  ansible_runner_image: quay.io/ansible/creator-ee:latest
dependencies:
  galaxy: requirements.yml
  python: requirements.txt
  system: []
options:
  package_manager: pip
```

```bash
# Сборка EE с ролями
ansible-builder build -t my-custom-ee:latest

# Проверка
podman images | grep my-custom-ee
```

> **См. также:** [Execution Environments](../ansible-execution-environments.md) — общая информация об EE.

---

## Дополнительная информация

### Приоритет переменных

Переменные, переданные при вызове роли, имеют приоритет над значениями в `defaults/main.yml`. 
Общий порядок переопределения (от низшего к высшему):
1. `defaults/main.yml` роли.
2. Переменные групп инвентаря (`group_vars/all`, затем конкретные группы).
3. Переменные хоста (`host_vars`).
4. `vars/main.yml` роли.
5. Параметры, переданные при вызове роли (inline vars).
6. Переменные с флагом `-e` (extra vars) — абсолютный приоритет.

Полная таблица приоритетов — в **[PlaybookStructure/variables.md](../PlaybookStructure/variables.md)**.

### См. также

- [Структура роли](structure.md) — назначение каталогов, README и проверки качества
- [Управление выполнением и отладка ролей](task-execution-and-debugging.md) — `run_once`, `delegate_facts`, `debugger`, `check_mode`
- [Стратегии и паттерны](strategies.md) — рекомендации по проектированию
- [Компоненты роли](../ansible_roles.md) — базовые определения, Galaxy и коллекции
- [PlaybookStructure/flow_control.md](../PlaybookStructure/flow_control.md) — `serial`, `any_errors_fatal`, `throttle`, `block`
- [PlaybookStructure/variables.md](../PlaybookStructure/variables.md) — `set_fact`, `delegate_facts`, `no_log`
- [PlaybookStructure/advanced.md](../PlaybookStructure/advanced.md) — `force_handlers`, `ignore_unreachable`, `debugger`
- [Ansible Vault: лучшие практики](../Vault/best_practices.md) — методика работы с секретами
- [Кроссплатформенные концепции](../CrossPlatform/concepts.md) — Windows- и multi-OS-роли
- [Примеры отладки](../examples/debugging_examples.md) — диагностика инвентаря и переменных
- [ansible-lint](../ansible_lint_guide.md) — статический анализ ролей
- [Идемпотентность](../../Concepts/idempotency.md) — критерий готовности роли к production
- [Паттерн Utility Role](utility_role_pattern.md) — роли-библиотеки без побочных эффектов
