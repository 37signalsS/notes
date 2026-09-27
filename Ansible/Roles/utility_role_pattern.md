# Паттерн "Utility Role" в Ansible

## Определения

**Паттерн "Utility Role" (Служебная роль)** — методология проектирования [ролей Ansible](../ansible_roles.md), при которой создается специализированная роль-библиотека. Она не предназначена для прямого назначения хостам в секции `roles:` плейбука. Её единственная цель — инкапсуляция и предоставление общих компонентов (задач, обработчиков, переменных, плагинов) для других ролей проекта.

**Общие компоненты (Shared Components)** — атомарные и переиспользуемые фрагменты кода, вынесенные в отдельную структуру для реализации принципа DRY (Don't Repeat Yourself) и обеспечения единообразия инфраструктуры.

---

## Предварительные требования

### Системные требования

*   **Python:** 3.12+ для control node (Ansible 2.21+), 3.9+ для target nodes
*   **Ansible:** 2.10+ (базовая функциональность), 2.17+ для параметра `public` в `include_role`, 2.18+ для `meta: end_role`
*   **Git:** Для версионирования и совместной разработки utility ролей

### Инструменты

```bash
# Проверка версий
ansible --version
python3 --version

# Просмотр установленных ролей
ansible-galaxy role list

# Тестирование валидации argument_specs
ansible-playbook test.yml --syntax-check

# Проверка синтаксиса roles
ansible-lint roles/
```

### Необходимые знания

*   Понимание разницы между `import_role` и `include_role`
*   Знание структуры роли Ansible (tasks, handlers, defaults, vars, meta)
*   Основы `meta/argument_specs.yml` для описания интерфейса роли
*   Понимание принципов DRY и YAGNI (You Aren't Gonna Need It)

---

## Основные концепции

### Архитектурная роль и преимущества

В сложных проектах Utility Role выступает как "инфраструктурный клей" или "стандартная библиотека":

1.  **Библиотека функций:** Инкапсуляция часто повторяющихся действий (например, регистрация в мониторинге, ротация логов, настройка репозиториев).
2.  **Изоляция сложности:** Сложные вычисления фактов или взаимодействие с внешними API скрываются за простым интерфейсом параметров роли.
3.  **Глобальная доступность плагинов:** Пользовательские фильтры, тесты и lookup-плагины, размещенные в `plugins/` или `filter_plugins/` служебной роли, автоматически становятся доступными всему плейбуку после её подключения.
4.  **Единый интерфейс (Contract):** Использование `meta/argument_specs.yml` позволяет четко определить "контракт" взаимодействия с библиотекой.

### Механизмы подключения и область видимости (Ansible 2.17+)

Выбор метода подключения определяет, как переменные и ресурсы будут видны в вызывающем контексте.

*   **`ansible.builtin.import_role` (Статический):**
    *   **Время:** Обрабатывается на этапе парсинга плейбука.
    *   **Область видимости:** Переменные из `defaults/` и `vars/` экспортируются глобально (по умолчанию `public: true` в 2.17+).
    *   **Назначение:** Роли-инициализаторы, определяющие глобальные переменные для всего парка серверов.
*   **`ansible.builtin.include_role` (Динамический):**
    *   **Время:** Загружается во время выполнения (Runtime).
    *   **Изоляция:** По умолчанию переменные инкапсулированы внутри роли.
    *   **Параметр `public: true`:** Позволяет экспортировать переменные служебной роли для последующих задач в текущем Play.
    *   **Назначение:** Условное выполнение служебных задач (например, `when: is_first_run`) или циклы по списку ресурсов.

### Когда НЕ использовать паттерн Utility Role

Паттерн Utility Role решает конкретные проблемы переиспользования. Он добавляет сложности, поэтому его использование оправдано только при выполнении минимум двух из следующих условий:

1.  **Код дублируется в ≥3 ролях:** Если фрагмент логики повторяется менее чем в трех местах, извлечение в отдельную роль обычно не окупает накладных расходов на поддержку.
2.  **Изменения затрагивают все роли одновременно:** Например, изменение политики мониторинга требует обновления в 12 ролях. Utility Role позволяет внести правку в одном месте.
3.  **Интерфейс стабилен:** Utility Role имеет четко определенный `argument_specs.yml`. Если интерфейс постоянно меняется, паттерн добавляет ненужный слой абстракции.
4.  **Команда разработчиков ≥3 человек:** При большой команде Utility Role снижает вероятность рассинхронизации изменений.
5.  **Уровень абстракции обоснован:** Utility Role не должна скрывать слишком много логики. Если роль требует 10+ параметров для выполнения простой задачи, возможно, стоит пересмотреть декомпозицию.

**Антипаттерны:**

*   **God Utility Role:** Utility Role, которая делает всё: от создания пользователей до бэкапа базы. Решение: разбиение по доменам (`lib_system`, `lib_network`, `lib_monitoring`).
*   **Tight Coupling через hostvars:** Utility Role обращается к `hostvars` других хостов напрямую. Решение: вынос общих данных в `group_vars`.
*   **Deep Dependencies:** Цепочка зависимостей A → B → C → D. Решение: переход к явным вызовам `include_role` в основном плейбуке.
*   **Circular Dependencies:** Role A зависит от Role B, а Role B зависит от Role A. Решение: вынос общей логики в Role C.
*   **Hardcoded Secrets в defaults/main.yml:** Хранение паролей в `defaults/main.yml`. Решение: использование Ansible Vault или lookup-плагинов.
*   **God Play (Плейбук-Бог):** Плейбук, который делает всё. Решение: разбиение на отдельные playbooks для каждого домена.

### DRY vs YAGNI в контексте Ansible Roles

При проектировании Utility Roles возникает типичный для DevOps/SRE/Sysadmin конфликт между DRY (не повторяйся) и YAGNI (не реализуй то, что пока не нужно).

| Критерий | DRY (Utility Role оправдана) | YAGNI (Utility Role избыточна) |
| :--- | :--- | :--- |
| **Частота изменений** | Код меняется редко, но изменения затрагивают все роли | Код меняется часто, интерфейс нестабилен |
| **Количество потребителей** | ≥3 роли используют фрагмент | 1-2 роли используют фрагмент |
| **Сложность логики** | Высокая (≥50 строк, ≥3 модулей) | Низкая (≤20 строк, 1 модуль) |
| **Ожидаемая жизнь** | ≥6 месяцев | ≤3 месяца |

**Практическое правило для SRE/Sysadmin:** Начинайте с YAGNI. Если фрагмент кода продублирован ≤2 раз — оставьте его в роли. Если фрагмент продублирован ≥3 раз и затрагивает логику мониторинга, безопасности или настройки окружения — выделите Utility Role.

---

## Практические сценарии

### Сценарий 1: Централизованные обработчики (Shared Handlers)

Использование механизма `listen` позволяет служебной роли предоставлять обработчики, на которые могут подписываться любые другие роли.

**`roles/lib_common/handlers/main.yml`:**
```yaml
---
- name: global restart webserver
  ansible.builtin.service:
    name: "{{ web_service_name | default('nginx') }}"
    state: restarted
  listen: "restart_webserver"
```

**Подключение в основной роли (`roles/app/tasks/main.yml`):**
```yaml
---
- name: Подключение базовых обработчиков
  ansible.builtin.import_role:
    name: lib_common

- name: Обновление конфигурации приложения
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/myapp/app.conf
  notify: "restart_webserver"
```

### Сценарий 2: "Library Interface" через argument_specs (2.17+)

Служебная роль может валидировать входные данные, обеспечивая "защитное программирование".

**`roles/util_facts/meta/argument_specs.yml`:**
```yaml
argument_specs:
  main:
    short_description: "Сбор корпоративных фактов об окружении"
    options:
      target_env:
        type: str
        choices: ['prod', 'stage', 'dev']
        required: true
        description: "Тип целевого окружения"
        context:
          monitoring_policy: "strict" # Метаданные для внешних систем
```

**`roles/util_facts/tasks/main.yml`:**
```yaml
---
- name: Установка глобальных фактов
  ansible.builtin.set_fact:
    is_prod: "{{ target_env == 'prod' }}"
    internal_registry: "reg.corp.example.com/{{ target_env }}"
```

### Сценарий 3: "Sanity Checks" с использованием `meta: end_role` (2.18+)

Utility Role может выступать в роли "стража", прерывая свое выполнение (или выполнение всей цепочки), если условия безопасности не соблюдены.

```yaml
# roles/util_security_gate/tasks/main.yml
- name: Проверка наличия SSH-ключа в агенте
  ansible.builtin.command: "ssh-add -l"
  register: ssh_agent_status
  failed_when: false
  changed_when: false

- name: Прекратить выполнение роли, если ключ отсутствует
  ansible.builtin.meta: end_role
  when: ssh_agent_status.rc != 0
```

### Сценарий 4: Общие плагины в составе коллекций

В современных проектах (Ansible 2.10+) Utility Roles часто эволюционируют в коллекции. В этом случае плагины выносятся в корень коллекции:

```text
my_namespace/
└── infra_utils/
    ├── plugins/
    │   ├── filter/
    │   │   └── net_tools.py  # Фильтр my_var | my_namespace.infra_utils.ip_to_hex
    │   └── lookup/
    │       └── vault_get.py
    └── roles/
        └── shared_tasks/
            └── tasks/main.yml
```
*Преимущество:* Плагины доступны по FQCN без необходимости предварительного подключения роли.

### Сценарий 5: Централизованный мониторинг и логирование

Utility роль для универсальной установки агентов мониторинга и настройки логирования на всех серверах.

**`roles/lib_monitoring/tasks/main.yml`:**
```yaml
---
- name: Установка агента мониторинга
  ansible.builtin.package:
    name: "{{ monitoring_agent_package }}"
    state: present
  when: monitoring_enabled | default(true)

- name: Настройка агента мониторинга
  ansible.builtin.template:
    src: agent.conf.j2
    dest: "{{ monitoring_config_path }}"
    owner: root
    group: root
    mode: '0644'
  notify: "restart monitoring agent"
  when: monitoring_enabled | default(true)

- name: Регистрация сервера в мониторинге
  ansible.builtin.uri:
    url: "{{ monitoring_api_url }}/register"
    method: POST
    body_format: json
    body:
      hostname: "{{ inventory_hostname }}"
      env: "{{ target_env }}"
      services: "{{ registered_services }}"
    headers:
      Authorization: "Bearer {{ monitoring_api_token }}"
  delegate_to: localhost
  run_once: true
  when: monitoring_enabled | default(true)
```

**`roles/lib_monitoring/defaults/main.yml`:**
```yaml
---
monitoring_enabled: true
monitoring_agent_package: "node_exporter"
monitoring_config_path: "/etc/node_exporter/config.yml"
monitoring_api_url: "https://monitoring.internal/api/v1"
monitoring_api_token: "{{ vault_monitoring_token }}"
registered_services: []
```

**Использование в основной роли:**
```yaml
---
- name: Настройка веб-сервера
  ansible.builtin.include_role:
    name: lib_monitoring
  vars:
    monitoring_enabled: true
    registered_services: ["nginx", "php-fpm"]
```

### Сценарий 6: Фабрика конфигураций для разных окружений

Utility роль для генерации конфигурационных файлов на основе окружения (dev/stage/prod).

**`roles/lib_config_factory/meta/argument_specs.yml`:**
```yaml
---
argument_specs:
  main:
    short_description: "Генерация конфигураций для разных окружений"
    options:
      app_name:
        type: str
        required: true
        description: "Название приложения"
      env_type:
        type: str
        choices: ['dev', 'stage', 'prod']
        required: true
        description: "Тип окружения"
      config_template:
        type: str
        required: true
        description: "Путь к шаблону конфигурации"
      config_dest:
        type: str
        required: true
        description: "Путь для сохранения конфигурации"
```

**`roles/lib_config_factory/tasks/main.yml`:**
```yaml
---
- name: Генерация конфигурации для окружения
  ansible.builtin.template:
    src: "{{ config_template }}"
    dest: "{{ config_dest }}"
    owner: "{{ config_owner | default('root') }}"
    group: "{{ config_group | default('root') }}"
    mode: "{{ config_mode | default('0644') }}"
  vars:
    env_config: "{{ lookup('file', role_path + '/defaults/' + env_type + '.yml') | from_yaml }}"
  notify: "restart {{ app_name }}"
```

**Использование:**
```yaml
---
- name: Генерация конфигураций для всех окружений
  ansible.builtin.include_role:
    name: lib_config_factory
  vars:
    app_name: "myapp"
    env_type: "{{ target_env }}"
    config_template: "myapp.conf.j2"
    config_dest: "/etc/myapp/config.yml"
```

### Сценарий 7: Utility роль для A/B деплоев

Паттерн для поэтапного развертывания изменений на часть серверов.

**`roles/lib_ab_deploy/tasks/main.yml`:**
```yaml
---
- name: Определение группы серверов для деплоя
  ansible.builtin.set_fact:
    deploy_group: "{{ groups['all'] | shuffle(deploy_percentage | default(50)) }}"

- name: Проверка текущей версии на серверах
  ansible.builtin.uri:
    url: "http://{{ inventory_hostname }}:{{ app_port }}/version"
    return_content: yes
  register: current_version
  failed_when: false
  delegate_to: localhost

- name: Вывод текущей версии
  ansible.builtin.debug:
    msg: "Текущая версия на {{ inventory_hostname }}: {{ current_version.content | default('unknown') }}"
  delegate_to: localhost
  run_once: true

- name: Пропуск деплоя если версия актуальна
  ansible.builtin.meta: end_play
  when:
    - current_version.status | default(500) == 200
    - current_version.content | default('') == target_version
```

**`roles/lib_ab_deploy/defaults/main.yml`:**
```yaml
---
deploy_percentage: 50
app_port: 8080
target_version: "latest"
```

**Использование:**
```yaml
---
- name: A/B деплой на 30% серверов
  ansible.builtin.include_role:
    name: lib_ab_deploy
  vars:
    deploy_percentage: 30
    target_version: "v2.1.0"
```

### Сценарий 8: Паттерн управления общими секретами

Utility роль для безопасного получения и распределения секретов из Vault.

**`roles/lib_secrets/meta/argument_specs.yml`:**
```yaml
---
argument_specs:
  main:
    short_description: "Получение секретов из Vault"
    options:
      secret_paths:
        type: list
        elements: str
        required: true
        description: "Список путей к секретам в Vault"
      secret_engine:
        type: str
        default: "secret"
        description: "Движок секретов Vault"
      secret_format:
        type: str
        choices: ['json', 'env', 'yaml']
        default: 'env'
        description: "Формат вывода секретов"
```

**`roles/lib_secrets/tasks/main.yml`:**
```yaml
---
- name: Получение секретов из Vault
  community.hashi_vault.vault_read:
    secret: "{{ secret_engine }}/{{ item }}"
    auth_method: token
    token: "{{ vault_token }}"
  loop: "{{ secret_paths }}"
  register: vault_secrets
  no_log: true

- name: Форматирование секретов
  ansible.builtin.set_fact:
    formatted_secrets: "{{ vault_secrets.results | map(attribute='secret.data') | list }}"
  when: secret_format == 'json'

- name: Сохранение секретов в файл
  ansible.builtin.copy:
    content: "{{ formatted_secrets | to_nice_json }}"
    dest: "/tmp/secrets.json"
    mode: '0600'
  when: secret_format == 'json'
  become: true
```

**Использование:**
```yaml
---
- name: Получение всех необходимых секретов
  ansible.builtin.include_role:
    name: lib_secrets
  vars:
    secret_paths:
      - "database/creds/app_user"
      - "api/creds/service_account"
    secret_format: "json"
```

### Сценарий 9: Универсальная установка пакетов для разных дистрибутивов

Utility роль для абстракции различий между дистрибутивами Linux (Debian/Ubuntu vs RHEL/CentOS/Fedora).

**`roles/lib_package/meta/argument_specs.yml`:**
```yaml
---
argument_specs:
  main:
    short_description: "Установка пакетов для разных дистрибутивов"
    options:
      packages:
        type: list
        elements: str
        required: true
        description: "Список пакетов для установки"
      package_manager:
        type: str
        choices: ['auto', 'apt', 'yum', 'dnf', 'apk']
        default: 'auto'
        description: "Менеджер пакетов"
      update_cache:
        type: bool
        default: true
        description: "Обновить кэш пакетов перед установкой"
```

**`roles/lib_package/tasks/main.yml`:**
```yaml
---
- name: Определение менеджера пакетов
  ansible.builtin.set_fact:
    detected_pkg_mgr: "{{ 'apt' if ansible_facts['os_family'] == 'Debian' else 'yum' if ansible_facts['os_family'] == 'RedHat' else 'apk' if ansible_facts['os_family'] == 'Alpine' else 'unknown' }}"
  when: package_manager == 'auto'

- name: Обновление кэша пакетов (Debian)
  ansible.builtin.apt:
    update_cache: true
    cache_valid_time: 3600
  when:
    - update_cache | default(true)
    - (package_manager | default('auto')) in ['auto', 'apt']

- name: Установка пакетов (Debian)
  ansible.builtin.apt:
    name: "{{ packages }}"
    state: present
  when: (package_manager | default('auto')) in ['auto', 'apt']

- name: Установка пакетов (RHEL/CentOS/Fedora)
  ansible.builtin.yum:
    name: "{{ packages }}"
    state: present
  when: (package_manager | default('auto')) in ['auto', 'yum']

- name: Установка пакетов (Alpine)
  ansible.builtin.apk:
    name: "{{ packages }}"
    state: present
  when: (package_manager | default('auto')) in ['auto', 'apk']
```

**Использование:**
```yaml
---
- name: Установка базовых пакетов
  ansible.builtin.include_role:
    name: lib_package
  vars:
    packages:
      - "curl"
      - "wget"
      - "jq"
```

### Сценарий 10: Управление операциями с большими парками серверов

Utility роль для пакетного применения операций (обновление пакетов, перезагрузка, сброс SSH) с ограничениями и валидацией.

**`roles/lib_ops/tasks/main.yml`:**
```yaml
---
- name: Сбор списка серверов для операции
  ansible.builtin.group_by:
    key: "ops_target"
  when: target_hosts is not defined

- name: Проверка доступности серверов
  ansible.builtin.ping:
  register: ping_results
  failed_when: false
  delegate_to: "{{ item }}"
  loop: "{{ groups['ops_target'] }}"

- name: Пропуск недоступных серверов
  ansible.builtin.meta: end_host
  when: ping_results is failed

- name: Применение операции с throttle
  ansible.builtin.include_role:
    name: "{{ operation_role }}"
  vars:
    operation_params: "{{ operation_vars | default({}) }}"
  throttle: "{{ max_concurrent | default(10) }}"
  when: ping_results is succeeded
```

**`roles/lib_ops/defaults/main.yml`:**
```yaml
---
max_concurrent: 10
target_hosts: []
operation_role: "lib_package"
operation_vars: {}
```

**Использование:**
```yaml
---
- name: Безопасное обновление пакетов
  ansible.builtin.include_role:
    name: lib_ops
  vars:
    target_hosts: "{{ groups['all'] | difference(groups['maintenance']) }}"
    operation_role: "lib_package"
    operation_vars:
      packages: ["*"]
      state: "latest"
      update_cache: true
    max_concurrent: 5
```

### Сценарий 11: Аварийное развертывание исправлений (Emergency Patch)

Utility роль для быстрого применения критических исправлений с откатом и валидацией.

**`roles/lib_emergency_patch/tasks/main.yml`:**
```yaml
---
- name: Создание снапшота состояния перед исправлением
  ansible.builtin.command: "tar czf /var/backups/pre_patch_{{ ansible_date_time.date }}.tar.gz /etc"
  register: backup_result
  changed_when: true
  failed_when: false

- name: Применение критического исправления
  ansible.builtin.copy:
    src: "{{ patch_source | default('/opt/patches/critical.j2') }}"
    dest: "{{ patch_dest }}"
    owner: root
    group: root
    mode: '0644'
  notify: "restart {{ patch_service }}"
  register: patch_applied
  failed_when: patch_applied is failed

- name: Валидация исправления
  ansible.builtin.uri:
    url: "{{ patch_validation_url }}"
    method: GET
    return_content: yes
  register: validation_result
  failed_when: false
  delegate_to: localhost

- name: Откат исправления при провале валидации
  ansible.builtin.command: "tar xzf /var/backups/pre_patch_{{ ansible_date_time.date }}.tar.gz -C /"
  when:
    - validation_result is failed
    - patch_auto_revert | default(false)
  register: revert_result
  notify: "restart {{ patch_service }}"

- name: Остановка выполнения при провале валидации
  ansible.builtin.fail:
    msg: "Критическое исправление не прошло валидацию. Откат выполнен."
  when:
    - validation_result is failed
    - patch_auto_revert | default(false)
```

**Использование:**
```yaml
---
- name: Аварийное развертывание исправления CVE-2024-1234
  ansible.builtin.include_role:
    name: lib_emergency_patch
  vars:
    patch_source: "/opt/patches/cve-2024-1234.j2"
    patch_dest: "/etc/app/critical.conf"
    patch_service: "app"
    patch_validation_url: "http://localhost:8080/health"
    patch_auto_revert: true
```

### Сценарий 12: Процесс реагирования на инциденты (Incident Response)

Utility роль для автоматизации типовых операций реагирования на инциденты.

**`roles/lib_incident/tasks/main.yml`:**
```yaml
---
- name: Сбор артефактов инцидента
  ansible.builtin.command: "journalctl -u {{ incident_service }} --since '{{ incident_start }}' --no-pager"
  register: journal_logs
  changed_when: false
  failed_when: false

- name: Сохранение артефактов
  ansible.builtin.copy:
    content: "{{ journal_logs.stdout }}"
    dest: "/var/log/incidents/{{ incident_id }}/journal_{{ ansible_hostname }}.log"
    mode: '0640'
  become: true

- name: Отключение проблемного сервиса
  ansible.builtin.service:
    name: "{{ incident_service }}"
    state: stopped
  when: incident_action | default('gather') == 'mitigate'

- name: Переключение на резервный сервис
  ansible.builtin.service:
    name: "{{ incident_fallback_service }}"
    state: started
  when:
    - incident_action | default('gather') == 'mitigate'
    - incident_fallback_service is defined

- name: Уведомление команды реагирования
  ansible.builtin.uri:
    url: "{{ incident_webhook_url }}"
    method: POST
    body_format: json
    body:
      incident_id: "{{ incident_id }}"
      host: "{{ ansible_hostname }}"
      action: "{{ incident_action | default('gather') }}"
      service: "{{ incident_service }}"
  delegate_to: localhost
```

**Использование:**
```yaml
---
- name: Реагирование на инцидент INC-2024-001
  ansible.builtin.include_role:
    name: lib_incident
  vars:
    incident_id: "INC-2024-001"
    incident_service: "payment-api"
    incident_start: "1 hour ago"
    incident_action: "mitigate"
    incident_fallback_service: "payment-api-fallback"
    incident_webhook_url: "https://hooks.slack.com/services/XXX/YYY/ZZZ"
```

### Сценарий 13: Управление соответствием требованиям (Compliance)

Utility роль для автоматизации проверок соответствия политикам безопасности (CIS, PCI-DSS, HIPAA).

**`roles/lib_compliance/tasks/main.yml`:**
```yaml
---
- name: Проверка парольной политики
  ansible.builtin.command: "grep -E '^PASS_MAX_DAYS' /etc/login.defs"
  register: pass_max_days
  changed_when: false
  failed_when: false

- name: Проверка SELinux
  ansible.builtin.command: "getenforce"
  register: selinux_status
  changed_when: false
  failed_when: false

- name: Сбор артефактов compliance
  ansible.builtin.copy:
    content: |
      PASS_MAX_DAYS: {{ pass_max_days.stdout }}
      SELinux: {{ selinux_status.stdout }}
    dest: "/var/log/compliance/{{ ansible_hostname }}.txt"
    mode: '0640'
  become: true

- name: Уведомление о нарушении политики
  ansible.builtin.fail:
    msg: "Сервер {{ ansible_hostname }} не соответствует политике PASS_MAX_DAYS"
  when: pass_max_days.stdout is not search('90')
```

### Сценарий 14: Восстановление после сбоев (Disaster Recovery)

Utility роль для автоматизации процедур восстановления после сбоев инфраструктуры.

**`roles/lib_dr/tasks/main.yml`:**
```yaml
---
- name: Проверка доступности резервной копии
  ansible.builtin.stat:
    path: "{{ dr_backup_path }}"
  register: backup_stat

- name: Восстановление из резервной копии
  ansible.builtin.command: "tar xzf {{ dr_backup_path }} -C /"
  when: backup_stat.stat.exists
  register: restore_result
  become: true

- name: Перезапуск сервисов после восстановления
  ansible.builtin.service:
    name: "{{ item }}"
    state: restarted
  loop: "{{ dr_services | default(['nginx', 'app']) }}"
  when: restore_result is succeeded

- name: Уведомление команды восстановления
  ansible.builtin.uri:
    url: "{{ dr_webhook_url }}"
    method: POST
    body_format: json
    body:
      host: "{{ ansible_hostname }}"
      result: "{{ 'success' if restore_result is succeeded else 'failed' }}"
  delegate_to: localhost
```

---

## Операции и команды

| Команда / Операция | Описание | Пример с ожидаемым выводом |
| :--- | :--- | :--- |
| `ansible-galaxy role list` | Просмотр установленных utility ролей | `ansible-galaxy role list \| grep lib_` |
| `ansible.builtin.include_role` | Динамическое подключение utility роли | См. Practical Scenarios |
| `ansible.builtin.import_role` | Статическое подключение utility роли | См. Practical Scenarios |
| `ansible.builtin.meta: end_role` | Досрочное завершение utility роли | См. Scenario 3 |
| `ansible.builtin.meta: end_play` | Досрочное завершение всего плейбука | См. Troubleshooting |
| `--list-variables` | Просмотр переменных utility роли | `ansible-playbook site.yml --list-variables -l host1` |
| `--list-tasks` | Просмотр порядка выполнения | `ansible-playbook site.yml --list-tasks \| grep lib_` |
| `-vvvv` | Максимальная отладка выполнения | `ansible-playbook site.yml -vvvv` |
| `molecule test` | Тестирование utility роли | `cd roles/lib_common && molecule test` |
| `ansible-lint roles/` | Проверка качества utility ролей | `ansible-lint roles/` |

---

## Troubleshooting

### Проблема: Переменные из utility role не видны в вызывающей роли

**Причина:** По умолчанию `include_role` изолирует переменные.

**Диагностика:**
```bash
# Запуск с максимальной отладкой
ansible-playbook site.yml -vvvv --list-tasks

# Просмотр собранных переменных
ansible-playbook site.yml --list-variables -l host1
```

**Решение:**
```yaml
# Использование public: true для экспорта переменных
- name: Подключение utility роли
  ansible.builtin.include_role:
    name: lib_common
    public: true  # Экспорт переменных в вызывающий контекст
```

### Проблема: Конфликт имен переменных между utility ролями

**Причина:** Разные utility роли используют одинаковые имена переменных.

**Диагностика:**
```bash
# Просмотр переменных конкретной роли
ansible-playbook site.yml --list-variables -l host1
```

**Решение:**
```yaml
# Использование namespace для переменных
roles:
  - name: lib_monitoring
    vars:
      lib_monitoring_port: 9100
  - name: lib_logging
    vars:
      lib_logging_port: 514

# Или использование dictionary для группировки
roles:
  - name: lib_common
    vars:
      lib_common_monitoring:
        port: 9100
      lib_common_logging:
        port: 514
```

### Проблема: `import_role` не работает с условиями

**Причина:** `import_role` обрабатывается на этапе парсинга, условия не работают.

**Диагностика:**
```bash
# Проверка порядка выполнения
ansible-playbook site.yml --list-tasks
```

**Решение:**
```yaml
# Использование include_role для условного выполнения
- name: Условное подключение utility роли
  ansible.builtin.include_role:
    name: lib_security
  when: enable_security | default(true)

# Или использовать block/always/rescue
- block:
    - name: Подключение utility роли
      ansible.builtin.include_role:
        name: lib_security
  when: enable_security | default(true)
```

### Проблема: `end_role` прерывает выполнение всего плейбука

**Причина:** `end_role` останавливает выполнение текущей роли, но не плейбука.

**Диагностика:**
```bash
# Запуск с отладкой
ansible-playbook site.yml -vvvv
```

**Решение:**
```yaml
# Использование end_play для остановки всего плейбука
- name: Прекратить выполнение плейбука
  ansible.builtin.meta: end_play
  when: critical_error | default(false)

# Или использовать fail с assert
- name: Проверка критических условий
  ansible.builtin.assert:
    that:
      - required_variable is defined
      - required_variable | length > 0
    fail_msg: "Критическая ошибка: required_variable не определена"
```

### Проблема: Utility роль не находит файлы шаблонов

**Причина:** Неправильный путь к файлам в role_path.

**Диагностика:**
```bash
# Проверка пути role_path
ansible-playbook site.yml --list-variables -l host1 | grep role_path
```

**Решение:**
```yaml
# Использование role_path для указания пути
- name: Копирование шаблона
  ansible.builtin.template:
    src: "{{ role_path }}/templates/config.j2"
    dest: /etc/app/config.yml

# Проверка пути role_path
- name: Отладка пути роли
  ansible.builtin.debug:
    var: role_path
```

### Проблема: Utility роль выполняется дважды в плейбуке

**Причина:** Дублирование вызовов в `meta/main.yml` и `tasks/main.yml`.

**Диагностика:**
```bash
# Просмотр порядка выполнения
ansible-playbook site.yml --list-tasks | grep lib_
```

**Решение:**
```yaml
# Использование allow_duplicates: false в meta/main.yml
# Или удаление дублирующих вызовов из плейбука
```

### Проблема: Циклические зависимости между utility ролями

**Причина:** Role A зависит от Role B, а Role B зависит от Role A.

**Диагностика:**
```bash
# Проверка зависимостей
ansible-galaxy role info lib_role_a
ansible-galaxy role info lib_role_b

# Просмотр порядка выполнения
ansible-playbook site.yml --list-tasks
```

**Решение:**
```bash
# Вынос общей логики в Role C
# Role A -> Role C
# Role B -> Role C
# Role C не зависит от A и B
```

---

## Best Practices

### Именование и структура

1. **Используйте префиксы:** `lib_`, `util_`, `shared_` для визуального отделения utility ролей
2. **Разделяйте по доменам:** `lib_system`, `lib_network`, `lib_monitoring`, `lib_security`
3. **Избегайте "God Role":** Не создавайте одну роль `common`, в которую сваливается всё
4. **Минимальная ответственность:** Каждая utility роль должна отвечать за одну конкретную область

### Документирование

1. **README.md:** Опишите назначение, входные параметры, примеры использования
2. **argument_specs.yml:** Формально опишите интерфейс роли
3. **Примеры:** Включите готовые примеры вызова в README
4. **Зависимости:** Укажите required Python packages и Ansible collections

### Тестирование

1. **Molecule:** Используйте Molecule для тестирования utility ролей
2. **Syntax check:** Всегда проверяйте синтаксис перед коммитом
3. **Интеграционные тесты:** Проверяйте интеграцию с другими ролями
4. **Unit-тесты:** Тестируйте кастомные модули и плагины

**Пример Molecule теста:**
```yaml
# molecule/default/molecule.yml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: quay.io/centos/centos:stream9
provisioner:
  name: ansible
verifier:
  name: ansible
```

### Версионирование

1. **Семантическое версионирование:** MAJOR.MINOR.PATCH
2. **Теги:** Используйте Git-теги для релизов (`v1.0.0`)
3. **CHANGELOG.md:** Документируйте изменения в каждом релизе
4. **Обратная совместимость:** Избегайте breaking changes в MINOR/PATCH релизах

### Безопасность

1. **No log:** Используйте `no_log: true` для секретов
2. **Vault:** Храните секреты в Ansible Vault, не в plain-text
3. **Минимальные привилегии:** Используйте `become` только когда необходимо
4. **Проверка подписей:** Используйте `signatures` для коллекций (Ansible 2.17+)

### Отладка и диагностика

1. **Включите отладку:** Используйте `-vvvv` для просмотра порядка выполнения
2. **Просмотр переменных:** Используйте `--list-variables` для проверки видимости переменных
3. **Просмотр задач:** Используйте `--list-tasks` для проверки порядка выполнения
4. **Синтаксический чек:** Используйте `--syntax-check` для проверки синтаксиса
5. **Dry-run:** Используйте `--check --diff` для проверки изменений без применения

### Чистка и обслуживание

1. **Регулярный аудит:** Удаляйте неиспользуемые utility роли, обновляйте устаревшие зависимости
2. **Стандартизация имен:** Используйте префиксы для утилитарных ролей (`lib_`, `util_`)
3. **Единый стиль:** Придерживайтесь соглашений по именованию переменных (`snake_case`)
4. **Архивация версий:** Не удаляйте старые версии из Git; используйте теги

### Change Management

1. **Изменения через PR:** Все изменения в utility ролях проходят через код-ревью и CI/CD
2. **Семантическое версионирование:** MAJOR.MINOR.PATCH с четко определенными правилами breaking changes
3. **Уведомление команд:** При изменении `argument_specs` или поведения уведомляйте все команды, использующие роль
4. **Канареечные деплои:** Внедряйте изменения постепенно, начиная с не критичной инфраструктуры
5. **Откат:** Поддерживайте процедуру отката до предыдущей версии utility роли

### Наблюдаемость и аудит

1. **Логирование вызовов:** Включите отладку utility ролей в CI/CD пайплайнах
2. **Метрики:** Собирайте метрики времени выполнения, количества хостов, ошибок
3. **Аудит изменений:** Ведите историю изменений в CHANGELOG.md с привязкой к тикетам
4. **Валидация:** Используйте `--syntax-check` и `ansible-lint` в pre-commit хуках
5. **Документация:** Автоматически генерируйте документацию из `argument_specs.yml`

### Disaster Recovery для utility ролей

1. **Резервное копирование:** Храните utility роли в отдельном Git-репозитории с регулярными бэкапами
2. **Версионирование:** Фиксируйте версии utility ролей в `requirements.yml` для каждого проекта
3. **Изоляция:** Utility роли не должны зависеть от конкретного окружения (dev/stage/prod)
4. **Восстановление:** Поддерживайте процедуру быстрого развертывания utility роли из Git-тега
5. **Тестирование:** Регулярно проверяйте восстановление utility ролей на изолированном стенде

---

## Сравнение паттернов

| Критерий | Utility Role | Custom Module | Plugin (Filter/Lookup) | include_tasks |
| :--- | :--- | :--- | :--- | :--- |
| **Назначение** | Библиотека задач, handlers, переменных | Кастомная логика на Python | Расширение шаблонизатора | Переиспользование задач |
| **Язык** | YAML (tasks) | Python | Python | YAML (tasks) |
| **Сложность** | Низкая | Высокая | Средняя | Низкая |
| **Тестируемость** | Molecule | pytest | pytest | Molecule |
| **Документирование** | README + argument_specs | Документация модуля | Документация плагина | README |
| **Версионирование** | Git-теги | Git-теги | Git-теги | Git-теги |
| **Пример** | `lib_monitoring` | `module_utils/monitoring.py` | `filter_plugins/monitoring.py` | `tasks/monitoring.yml` |

**Когда использовать:**
- **Utility Role:** Библиотека задач, handlers, переменных для других ролей
- **Custom Module:** Сложная логика, взаимодействие с API, нестандартные операции
- **Plugin:** Расширение шаблонизатора (фильтры, lookup, тесты)
- **include_tasks:** Простое переиспользование набора задач

---

## Edge Cases

### Циклические зависимости

**Проблема:** Role A -> Role B -> Role C -> Role A

**Решение:**
```yaml
# Вынос общей логики в отдельную роль
# Вместо:
#   lib_a -> lib_b (общий код)
#   lib_c -> lib_b (общий код)

# Создать:
#   lib_common (общий код)
#   lib_a -> lib_common
#   lib_c -> lib_common
```

### Конфликт имен переменных

**Проблема:** Две utility роли определяют переменную `port`.

**Решение:**
```yaml
# Использование unique prefix
roles:
  - name: lib_monitoring
    vars:
      lib_monitoring_port: 9100
  - name: lib_logging
    vars:
      lib_logging_port: 514
```

### Производительность

**Проблема:** Множественные `include_role` замедляют выполнение.

**Решение:**
```yaml
# Группировка вызовов
- name: Подключение всех utility ролей
  ansible.builtin.include_role:
    name: "{{ item }}"
  loop:
    - lib_monitoring
    - lib_logging
    - lib_security
  vars:
    monitoring_enabled: true
    logging_enabled: true
    security_enabled: true
```

### Версионирование utility ролей

**Проблема:** Разные проекты используют разные версии одной utility роли.

**Решение:**
```yaml
# Фиксация версий в requirements.yml
roles:
  - name: lib_common
    src: git@github.com:org/role-common.git
    version: v1.2.0  # Конкретный тег

# Использование семантического версионирования
# MAJOR: Breaking changes
# MINOR: Новые фичи (обратно совместимо)
# PATCH: Исправления (обратно совместимо)
```

### Условное включение плагинов

**Проблема:** Utility роль содержит плагины, которые конфликтуют с другими ролями.

**Решение:**
```yaml
# Использование FQCN для плагинов
- name: Использование кастомного фильтра
  ansible.builtin.debug:
    msg: "{{ my_var | my_namespace.infra_utils.custom_filter }}"

# Вместо:
# - msg: "{{ my_var | custom_filter }}"
```

### Отказоустойчивость utility роли

**Проблема:** Utility роль падает на одном хосте, останавливая выполнение всего плейбука.

**Решение:**
```yaml
# Использование ignore_errors для продолжения выполнения
- name: Применение utility роли с отказоустойчивостью
  ansible.builtin.include_role:
    name: lib_monitoring
  vars:
    monitoring_enabled: true
  ignore_errors: true
  register: monitoring_result

# Уведомление о провале
- name: Проверка результата применения
  ansible.builtin.assert:
    that:
      - monitoring_result is succeeded
    fail_msg: "Utility роль lib_monitoring не применена на {{ ansible_hostname }}"
    success_msg: "Utility роль lib_monitoring успешно применена"
```

### Различия между дистрибутивами Linux

**Проблема:** Utility роль работает на RHEL, но падает на Debian из-за различий в путях и командах.

**Решение:**
```yaml
# Адаптация под дистрибутив
- name: Установка пакета
  ansible.builtin.package:
    name: "{{ packages }}"
    state: present

# Или использование when для дистрибутивов
- name: Установка через apt
  ansible.builtin.apt:
    name: "{{ packages }}"
    state: present
  when: ansible_facts['os_family'] == 'Debian'

- name: Установка через yum
  ansible.builtin.yum:
    name: "{{ packages }}"
    state: present
  when: ansible_facts['os_family'] == 'RedHat'
```

### Обработка больших парков серверов

**Проблема:** Utility роль выполняется на 1000+ хостах, превышая лимиты API и таймауты.

**Решение:**
```yaml
# Использование throttle для ограничения параллелизма
- name: Применение utility роли с throttle
  ansible.builtin.include_role:
    name: lib_config
  vars:
    config_template: "app.conf.j2"
    config_dest: "/etc/app/config.yml"
  throttle: 10  # Максимум 10 хостов одновременно

# Использование delegate_to для операций с API
- name: Вызов API с delegate_to
  ansible.builtin.uri:
    url: "https://api.internal/v1/config"
    method: POST
  delegate_to: localhost
  run_once: true
```

---

## Дополнительная информация

### См. также

*   [Стратегии проектирования ролей](strategies.md) — выбор между Component-based и Composite подходами.
*   [Структура роли](structure.md) — детали каталогов и SSoT по `argument_specs`.
*   [Создание и использование ролей](../Roles/usage.md) — техническая реализация подключения (`import_role`, `include_role`).

---


