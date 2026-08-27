# Паттерн "Utility Role" в Ansible

## Определения

**Паттерн "Utility Role" (Служебная роль)** — методология проектирования [ролей Ansible](../ansible_roles.md), при которой создается специализированная роль-библиотека. Она не предназначена для прямого назначения хостам в секции `roles:` плейбука. Её единственная цель — инкапсуляция и предоставление общих компонентов (задач, обработчиков, переменных, плагинов) для других ролей проекта.

**Общие компоненты (Shared Components)** — атомарные и переиспользуемые фрагменты кода, вынесенные в отдельную структуру для реализации принципа DRY (Don't Repeat Yourself) и обеспечения единообразия инфраструктуры.

---

## Предварительные требования

### Системные требования

*   **Python:** 3.10+ для control node (Ansible 2.17+), 3.8+ для target nodes
*   **Ansible:** 2.17+ для использования `argument_specs`, `end_role`, `public` в `include_role`
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
*   Понимание принципов DRY и SSoT (Single Source of Truth)

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

Utility роль для统一 установки агентов мониторинга и настройки логирования на всех серверах.

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
  community.hashi_vault.hashi_vault_read:
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

---

## Дополнительная информация

### Troubleshooting

#### Проблема: Переменные из utility role не видны в вызывающей роли

**Причина:** По умолчанию `include_role` изолирует переменные.

**Решение:**
```yaml
# Использование public: true для экспорта переменных
- name: Подключение utility роли
  ansible.builtin.include_role:
    name: lib_common
    public: true  # Экспорт переменных в вызывающий контекст
```

#### Проблема: Конфликт имен переменных между utility ролями

**Причина:** Разные utility роли используют одинаковые имена переменных.

**Решение:**
```yaml
# Использование namespace для переменных
roles:
  - name: lib_monitoring
    vars:
      monitoring_port: 9100
  - name: lib_logging
    vars:
      logging_port: 514

# Или использование dictionary для группировки
roles:
  - name: lib_common
    vars:
      lib_common_monitoring:
        port: 9100
      lib_common_logging:
        port: 514
```

#### Проблема: `import_role` не работает с条件ями

**Причина:** `import_role` обрабатывается на этапе парсинга, условия не работают.

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

#### Проблема: `end_role` прерывает выполнение всего плейбука

**Причина:** `end_role` останавливает выполнение текущей роли, но не плейбука.

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

#### Проблема: Utility роль не находит файлы шаблонов

**Причина:** Неправильный путь к файлам в role_path.

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

#### Проблема: Циклические зависимости между utility ролями

**Причина:** Role A зависит от Role B, а Role B зависит от Role A.

**Решение:**
```bash
# Проверка зависимостей
ansible-galaxy role info lib_role_a
ansible-galaxy role info lib_role_b

# Решение: вынести общую логику в Role C
# Role A -> Role C
# Role B -> Role C
# Role C не зависит от A и B
```

### Best Practices

#### Именование и структура

1. **Используйте префиксы:** `lib_`, `util_`, `shared_` для визуального отделения utility ролей
2. **Разделяйте по доменам:** `lib_system`, `lib_network`, `lib_monitoring`, `lib_security`
3. **Избегайте "God Role":** Не создавайте одну роль `common`, в которую сваливается всё
4. **Минимальная ответственность:** Каждая utility роль должна отвечать за одну конкретную область

#### Документирование

1. **README.md:** Опишите назначение, входные параметры, примеры использования
2. **argument_specs.yml:** Формально опишите интерфейс роли
3. **Примеры:** Включите готовые примеры вызова в README
4. **Зависимости:** Укажите required Python packages и Ansible collections

#### Тестирование

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

#### Версионирование

1. **Семантическое версионирование:** MAJOR.MINOR.PATCH
2. **Теги:** Используйте Git-теги для релизов (`v1.0.0`)
3. **CHANGELOG.md:** Документируйте изменения в каждом релизе
4. **Обратная совместимость:** Избегайте breaking changes в MINOR/PATCH релизах

#### Безопасность

1. **No log:** Используйте `no_log: true` для секретов
2. **Vault:** Храните секреты в Ansible Vault, не в plain-text
3. **Минимальные привилегии:** Используйте `become` только когда необходимо
4. **Проверка подписей:** Используйте `signatures` для коллекций (Ansible 2.17+)

### Edge Cases

#### Циклические зависимости

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

#### Конфликт имен переменных

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

#### Производительность

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

#### Версионирование utility ролей

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

#### Условное включение плагинов

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

### Сравнение паттернов

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

### См. также

1.  **Именование:** Используйте префиксы `lib_`, `util_` или `shared_` (например, `lib_auth`). Это отделяет "библиотеки" от "действий" в общем списке ролей.
2.  **Избегайте "God Role":** Не создавайте одну роль `common`, в которую сваливается всё. Разделяйте их по доменам: `lib_system`, `lib_network`, `lib_monitoring`.
3.  **Безопасные пути:** При вызове ресурсов из служебной роли используйте `role_path` для указания на файлы внутри самой роли:
    ```yaml
    - name: Копирование общего скрипта
      ansible.builtin.copy:
        src: "{{ role_path }}/files/healthcheck.sh"
        dest: /usr/local/bin/
    ```
4.  **Python Requirements:** Если служебная роль содержит кастомные фильтры, явно указывайте зависимости в `README.md`. Для Ansible 2.17+ требуется Python 3.10+ на контроллере.

### См. также

*   [Стратегии проектирования ролей](strategies.md) — выбор между Component-based и Composite подходами.
*   [Структура роли](structure.md) — детали каталогов и SSoT по `argument_specs`.
*   [Кроссплатформенность](../CrossPlatform/concepts.md) — использование Utility Role для разделения логики по ОС.
*   [Антипаттерны](../ansible_bad_practices.md) — риски "God Role" и жесткой связности.
*   [Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md) — подробное сравнение `import_role` и `include_role`.
