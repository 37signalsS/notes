# Ansible: переменные и факты

## Определения

**Переменные (Variables)** — именованные значения, используемые для параметризации плейбуков и ролей. Позволяют адаптировать код под разные окружения (dev/staging/prod) и типы систем без изменения логики задач. Могут содержать строки, числа, логические значения, списки и словари.

**Факты (Facts)** — системные данные об управляемом хосте (ОС, IP-адреса, диски, память, пакетный менеджер), которые Ansible автоматически собирает перед выполнением задач через модуль `ansible.builtin.setup`. Доступны через глобальный словарь `ansible_facts`.

**Магические переменные (Magic Variables)** — зарезервированные внутренние переменные Ansible (например, `inventory_hostname`, `hostvars`, `groups`), значения которых вычисляются автоматически движком и не могут быть напрямую переопределены пользователем.

**Область видимости (Scope)** — уровень доступности переменной в рамках жизненного цикла выполнения. Различают глобальную область (global), область плея (play), хоста (host) и локальные области (role, task, block).

**Кеширование фактов (Fact Caching)** — механизм сохранения собранных данных о хостах во внешнее хранилище (Redis, memcached, jsonfile) для ускорения последующих запусков и межхостового взаимодействия без повторного сбора.

**Переменные регистрации (Registered Variables)** — переменные, создаваемые директивой `register` для сохранения результата выполнения задачи. Содержат полную структуру результата: `stdout`, `stderr`, `rc`, `changed`, `failed` и др.

**Динамические переменные (set_fact)** — переменные, создаваемые или переопределяемые во время выполнения плейбука через модуль `ansible.builtin.set_fact`. Сохраняются на уровне хоста и доступны во всех последующих задачах текущего плея.

**Безопасное логирование (no_log)** — директива, предотвращающая запись секретных данных в лог Ansible. Устанавливается на уровне задачи или блока.

**Делегирование фактов (delegate_facts)** — механизм, позволяющий собранные факты хоста сохранить у делегированного хоста (обычно балансировщика или сервера мониторинга) вместо целевого.

**Директива vars_files** — указание YAML-файлов с переменными для подключения в начале плея. Поддерживает глобальную видимость и динамические пути через Jinja2-шаблоны.

**Директива vars_prompt** — интерактивный ввод переменных при запуске плейбука. Поддерживает скрытие ввода (`private: yes`), валидацию и значения по умолчанию.

## Базовые концепции

### Иерархия приоритетов (Variable Precedence)

Ansible использует систему приоритетов для разрешения конфликтов имен переменных. Знание этой иерархии критично для управления конфигурациями в крупных инфраструктурах.

**Полная иерархия приоритетов (от низшего к высшему):**

| # | Уровень | Источник | Пример |
| :--- | :--- | :--- | :--- |
| 1 | Role defaults | `roles/x/defaults/main.yml` | `swap_size: 1g` |
| 2 | Inventory vars (group) | `group_vars/all.yml` | `app_version: "2.1"` |
| 3 | Inventory vars (host) | `host_vars/host1.yml` | `ansible_host: 10.0.0.1` |
| 4 | Play vars | `vars:` в play | `vars: { debug: true }` |
| 5 | Role vars | `roles/x/vars/main.yml` | `nginx_worker_processes: 4` |
| 6 | Include vars | `include_vars` в задаче | `include_vars: os_vars.yml` |
| 7 | Set facts / registered | `set_fact`, `register` | `set_fact: { cache_ttl: 300 }` |
| 8 | Role params | `role:` с `vars:` | `role: { role: x, vars: {} }` |
| 9 | Include params | `include_role`, `include_tasks` | `include_role: { name: x }` |
| 10 | Extra vars | `-e "var=value"` CLI | `ansible-playbook site.yml -e env=prod` |

> **Примечание:** `extra_vars` (уровень 10) имеют **абсолютный приоритет** и переопределяют всё остальное. `set_fact` и `registered vars` находятся на одном уровне (7).

**Практические правила приоритетов для SRE:**

- Используйте `defaults/main.yml` для безопасных значений по умолчанию, которые легко переопределять через inventory.
- Избегайте `vars/main.yml` роли для переопределяемых настроек — они имеют высокий приоритет и конфликтуют с inventory.
- `extra_vars` идеальны для временных переопределений в аварийных ситуациях, но опасны для долгосрочных настроек.
- При аудите конфигураций проверяйте `group_vars/` и `host_vars/` первыми — это наиболее частые источники неожиданных переопределений.

### Опции переопределения в CLI

```bash
# Extra vars (абсолютный приоритет)
ansible-playbook site.yml -e "app_version=v2.3.1"
ansible-playbook site.yml -e @vars/override.yml

# Переопределение через --extra-vars с stdin
echo '{"app_debug": false}' | ansible-playbook site.yml -e @-

# Список итоговых переменных для хоста
ansible-playbook site.yml --list-variables -l webserver1
# → {
#     "app_version": "v2.3.1",
#     "app_port": 8080,
#     "ansible_facts": { ... }
#   }
```

### Работа с фактами (ansible_facts)

По умолчанию сбор фактов происходит в начале каждого плея (`gather_facts: true`) с использованием модуля `ansible.builtin.setup`.

**Современный синтаксис:** Всегда используйте словарь `ansible_facts['os_family']` вместо устаревшего плоского формата `ansible_os_family`. Начиная с ansible-core 2.24, плоский формат будет отключен по умолчанию.

**Селективный сбор фактов:**

```yaml
- name: Сбор только сетевых фактов
  ansible.builtin.setup:
    filter: "ansible_net*"

- name: Сбор фактов о дисках
  ansible.builtin.setup:
    filter: "ansible_devices*"

- name: Сбор фактов о нескольких модулях
  ansible.builtin.setup:
    gather_subset:
      - network
      - hardware
```

**Подключаемые факты (Connected Facts):**

Факты, собираемые модулем `setup` автоматически, включают информацию о сетевых интерфейсах, дисках, процессорах и ОС. Доступны через `ansible_facts`:

```yaml
# ОС и семейство
- ansible_facts['distribution']        # Ubuntu, CentOS, Debian
- ansible_facts['distribution_major_version']  # 22, 8, 12
- ansible_facts['os_family']           # Debian, RedHat

# Сеть
- ansible_facts['default_ipv4']['address']  # Основной IP
- ansible_facts['interfaces']              # Список интерфейсов

# Диски
- ansible_facts['mounts'][0]['mount']  # Точка монтирования
- ansible_facts['devices']['sda']['size']  # Размер диска

# Процессоры
- ansible_facts['processor_cores']  # Ядра
- ansible_facts['processor_count']  # Количество процессоров
```

**Добавленные факты (`added_facts`):**

Начиная с Ansible 2.15, модуль `setup` позволяет добавлять пользовательские факты через `added_facts`:

```yaml
- name: Добавить кастомный факт
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - '!min'
    added_facts:
      custom_role: "webserver"
      environment: "production"
```

### Жизненный цикл переменной

**Глобальная область (Global):**
Переменные, определенные через `-e` или в `group_vars/all.yml`, доступны во всех плеях плейбука.

**Область плея (Play):**
Переменные, определенные в `vars:` или `vars_files:` внутри плея, доступны всем задачам этого плея.

**Область хоста (Host):**
`set_fact` и `register` сохраняются на уровне хоста и доступны во всех последующих задачах текущего плея. При `cacheable: yes` факт сохраняется в кеш и доступен в последующих запусках.

**Локальная область (Local):**
Переменные внутри `block`, `include_tasks` или `include_role` имеют ограниченную область видимости.

**Время жизни Registered Variables:**

```yaml
- name: Пример времени жизни register
  ansible.builtin.command: uname -a
  register: os_info

- name: Переменная доступна в последующих задачах
  ansible.builtin.debug:
    var: os_info.stdout
```

### Магические переменные

| Переменная | Описание | Пример использования |
| :--- | :--- | :--- |
| `inventory_hostname` | Имя хоста в инвентаре | `{{ inventory_hostname }}` |
| `hostvars` | Переменные и факты других хостов | `{{ hostvars['db']['ansible_facts']['eth0']['ipv4']['address'] }}` |
| `groups` | Список групп и хостов | `{{ groups['web_servers'] }}` |
| `group_names` | Группы текущего хоста | `{{ group_names }}` |
| `ansible_check_mode` | Режим проверки `--check` | `when: not ansible_check_mode` |
| `ansible_diff_mode` | Режим дифференциального вывода `--diff` | `when: ansible_diff_mode` |
| `ansible_play_hosts_all` | Все хосты текущего плея | `{{ ansible_play_hosts_all }}` |
| `ansible_version` | Версия Ansible | `{{ ansible_version.full }}` |
| `omit` | Игнорирование параметра модуля | `param: "{{ my_var | default(omit) }}"` |

### Типизация и фильтры Jinja2

Для полного списка фильтров Jinja2 в Ansible см. [Шаблонизация Jinja2](../ansible_jinja_templating.md).

**Базовые фильтры для повседневной работы:**

| Фильтр | Назначение | Пример |
| :--- | :--- | :--- |
| `default(value)` | Значение по умолчанию | `{{ port | default(8080) }}` |
| `default(omit)` | Игнорирование параметра | `param: "{{ var | default(omit) }}"` |
| `combine(dict, recursive=True)` | Слияние словарей | `{{ a | combine(b, recursive=True) }}` |
| `dict2items` / `items2dict` | Преобразование словаря ↔ список | `{{ services | dict2items }}` |
| `selectattr` / `rejectattr` | Фильтрация списков | `{{ list \| selectattr('active', 'equalto', true) \| list }}` |
| `map(attribute)` | Извлечение атрибута | `{{ hosts \| map(attribute='ip') \| list }}` |
| `regex_replace` | Замена по regex | `{{ name \| regex_replace('^old', 'new') }}` |
| `json_query` | JMESPath-запросы | `{{ data \| json_query('[?port > `8080`].name') }}` |
| `type_debug` | Отладка типа данных | `{{ var \| type_debug }}` |

### Кеширование фактов (Fact Caching)

Настройка кеша в `ansible.cfg` позволяет избежать повторного сбора фактов. Детальные конфигурации для Redis, Memcached и jsonfile описаны в [Оптимизация производительности](../ansible_performance_tuning.md).

```ini
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_cache
fact_caching_timeout = 86400
```

> **Примечание:** При включенном кешировании секреты, сохраненные через `set_fact`, могут быть записаны на диск в открытом виде. Используйте `no_log: true` для задач с секретами.

### Валидация через argument_specs

Начиная с Ansible 2.11, рекомендуется описывать интерфейс роли в `meta/argument_specs.yml`. Это обеспечивает автоматическую проверку типов, обязательности и разрешенных значений переменных до выполнения первой задачи.

## Практические сценарии

### Сценарий 1: Динамическое подключение переменных (include_vars)

Загрузка специфичных для ОС или окружения файлов переменных во время выполнения.

**Базовый вариант:**

```yaml
- name: Загрузка конфигурации ОС
  ansible.builtin.include_vars:
    file: "{{ ansible_facts['os_family'] | lower }}_params.yml"
    name: os_specific_vars
```

**Расширенный вариант с first_found:**

```yaml
- name: Загрузка переменных из нескольких источников
  ansible.builtin.include_vars:
    file: "{{ lookup('first_found', params) }}"
    name: merged_config
  vars:
    params:
      files:
        - "{{ ansible_facts['os_family'] }}_{{ ansible_facts['distribution'] }}.yml"
        - "{{ ansible_facts['os_family'] }}.yml"
        - "default.yml"
      paths:
        - "../vars"
        - "vars"
      skip: true
```

**Валидация переменных после загрузки:**

```yaml
- name: Загрузка и проверка переменных
  block:
    - name: Загрузка переменных окружения
      ansible.builtin.include_vars:
        file: "{{ env }}_vars.yml"
      register: vars_loaded

    - name: Проверка обязательных переменных
      ansible.builtin.assert:
        that:
          - app_port is defined
          - app_version is defined
          - db_host is defined
        fail_msg: "Не все обязательные переменные определены в {{ env }}_vars.yml"
      when: vars_loaded is not failed
```

### Сценарий 2: Использование данных другого хоста (hostvars)

Оркестрация межхостового взаимодействия (например, получение IP-адреса БД из inventory).

```yaml
- name: Настройка строки подключения к БД
  ansible.builtin.template:
    src: app_config.j2
    dest: /etc/app/config.json
  vars:
    db_host: "{{ hostvars['db_node']['ansible_facts']['default_ipv4']['address'] }}"
```

### Сценарий 3: Условная параметризация и default(omit)

Написание универсальных задач, где параметры передаются только при их наличии.

```yaml
- name: Создание пользователя
  ansible.builtin.user:
    name: "{{ user_name }}"
    state: present
    uid: "{{ user_id | default(omit) }}"
    groups: "{{ user_groups | default(omit) }}"
```

### Сценарий 4: Создание фактов на лету (set_fact)

Вычисление и сохранение значений для использования в последующих задачах.

**Базовый вариант:**

```yaml
- name: Определение лимита памяти
  ansible.builtin.set_fact:
    java_heap_size: "{{ (ansible_facts['memtotal_mb'] * 0.7) | int }}m"

- name: Запуск приложения с вычисленным лимитом
  ansible.builtin.systemd:
    name: my_service
    environment:
      JAVA_OPTS: "-Xmx{{ java_heap_size }}"
```

**Кеширование фактов между плейбуками:**

```yaml
- name: Сохранить версию приложения
  ansible.builtin.set_fact:
    app_installed_version: "v2.3.1"
    cacheable: yes
    cache_timeout: 3600
```

**Создание сложных структур данных:**

```yaml
- name: Формирование словаря конфигурации
  ansible.builtin.set_fact:
    app_config:
      server:
        port: "{{ app_port | default(8080) }}"
        host: "0.0.0.0"
      database:
        host: "{{ db_host }}"
        port: "{{ db_port | default(5432) }}"
        name: "{{ db_name }}"
      logging:
        level: "{{ log_level | default('INFO') }}"
        file: "/var/log/{{ app_name }}/app.log"
```

**set_fact для условной логики:**

```yaml
- name: Определение типа ОС
  ansible.builtin.set_fact:
    package_manager: "{{ 'apt' if ansible_facts['os_family'] == 'Debian' else 'yum' }}"
    service_manager: "{{ 'systemd' if ansible_facts['distribution_major_version'] | int >= 7 else 'service' }}"

- name: Установка пакетов
  ansible.builtin.package:
    name: "{{ item }}"
    state: present
  loop: "{{ required_packages }}"
  environment:
    http_proxy: "{{ proxy_url | default(omit) }}"
```

### Сценарий 5: Работа с кастомными фактами (ansible_local)

Использование состояния, сохраненного на самом узле.

```yaml
- name: Проверка версии локальной инициализации
  ansible.builtin.debug:
    msg: "Версия инициализации: {{ ansible_facts.ansible_local.custom_app.version }}"
  when: ansible_facts.ansible_local.custom_app is defined
```

### Сценарий 6: Глубокое слияние настроек через combine

Объединение словарей с приоритетом переопределения.

**Базовый вариант:**

```yaml
- name: Формирование финального конфига
  ansible.builtin.set_fact:
    app_config: "{{ default_config | combine(user_overrides, recursive=True) }}"
  vars:
    default_config:
      port: 8080
      features: { debug: false, auth: true }
    user_overrides:
      features: { debug: true }
```

**Результат:** `features: { debug: true, auth: true }` — рекурсивное слияние сохраняет ключи из обоих словарей.

**Множественное слияние:**

```yaml
- name: Слияние нескольких источников конфигурации
  ansible.builtin.set_fact:
    final_config: "{{ config_base | combine(config_env, config_local, recursive=True) }}"
  vars:
    config_base:
      listen: "0.0.0.0:8080"
      workers: 4
    config_env:
      workers: 8
    config_local:
      listen: "127.0.0.1:8080"
```

### Сценарий 7: vars_files и vars_prompt

Динамическое подключение файлов переменных и интерактивный ввод.

**vars_files с условными путями:**

```yaml
---
- name: Конфигурация с vars_files
  hosts: all
  vars_files:
    - "vars/common.yml"
    - "vars/{{ ansible_facts['os_family'] | lower }}.yml"
    - "vars/{{ env | default('dev') }}.yml"
  tasks:
    - name: Вывод переменных
      ansible.builtin.debug:
        msg: "Окружение: {{ env }}, Порт: {{ app_port }}"
```

**vars_prompt для интерактивного ввода:**

```yaml
---
- name: Деплой с интерактивным подтверждением
  hosts: all
  vars_prompt:
    - name: deploy_version
      prompt: "Введите версию для деплоя (например, v2.3.1)"
      private: false
      default: "latest"

    - name: deploy_env
      prompt: "Целевое окружение"
      private: false
      choices:
        - dev
        - staging
        - production
      default: "dev"

    - name: deploy_password
      prompt: "Пароль для SSH ключа"
      private: true
      encrypt: "sha512_crypt"

  tasks:
    - name: Деплой указанной версии
      ansible.builtin.debug:
        msg: "Деплой {{ deploy_version }} в {{ deploy_env }}"
```

### Сценарий 8: Registered переменные и сложная условная логика

Использование `register` для хранения результатов задач и построения сложной логики.

**Базовый register и проверка:**

```yaml
- name: Проверка наличия сервиса
  ansible.builtin.command: systemctl is-active nginx
  register: nginx_status
  ignore_errors: true

- name: Запуск Nginx, если не запущен
  ansible.builtin.systemd:
    name: nginx
    state: started
  when: nginx_status.rc != 0
```

**Использование changed_when и failed_when:**

```yaml
- name: Проверка версии пакета
  ansible.builtin.command: dpkg-query -W -f='${Version}' nginx
  register: nginx_version
  changed_when: false
  failed_when: false

- name: Установка обновления, если версия старая
  ansible.builtin.apt:
    name: nginx
    state: latest
  when:
    - nginx_version.rc == 0
    - nginx_version.stdout is version('1.18.0', '<')
```

**Цикл с register и результирующим анализом:**

```yaml
- name: Проверка доступности всех серверов
  ansible.builtin.command: "ping -c 1 {{ item }}"
  loop: "{{ groups['all'] }}"
  register: ping_results
  ignore_errors: true

- name: Вывод результатов пинга
  ansible.builtin.debug:
    msg: "Сервер {{ item.item }}: {{ 'доступен' if item.rc == 0 else 'НЕДОСТУПЕН' }}"
  loop: "{{ ping_results.results }}"

- name: Ошибка, если есть недоступные серверы
  ansible.builtin.fail:
    msg: "Недоступные серверы: {{ ping_results.results | selectattr('rc', 'ne', 0) | map(attribute='item') | list }}"
  when: ping_results.results | selectattr('rc', 'ne', 0) | list | length > 0
```

**Извлечение данных из register:**

```yaml
- name: Сбор фактов о системе
  ansible.builtin.setup:
  register: setup_result

- name: Вывод информации о памяти
  ansible.builtin.debug:
    msg: "Объем памяти: {{ setup_result.ansible_facts.memtotal_mb }} MB"

- name: Вывод информации о дисках
  ansible.builtin.debug:
    msg: "Диск {{ item.key }}: {{ item.value.size }}"
  loop: "{{ setup_result.ansible_facts.devices | dict2items }}"
```

### Сценарий 9: Делегирование фактов (delegate_facts)

Сохранение собранных фактов на делегированном хосте (балансировщик, сервер мониторинга).

**Базовый delegate_facts:**

```yaml
- name: Регистрация сервера в HAProxy
  community.general.haproxy:
    state: enabled
    host: "{{ inventory_hostname }}"
    backend: app_backend
  delegate_to: "{{ groups['load_balancers'][0] }}"
  delegate_facts: true
```

**Сбор фактов и делегирование на сервер мониторинга:**

```yaml
- name: Сбор фактов о хосте
  ansible.builtin.setup:

- name: Регистрация в Zabbix
  ansible.builtin.uri:
    url: "https://zabbix.example.com/api_jsonrpc.php"
    method: POST
    body_format: json
    body:
      jsonrpc: "2.0"
      method: "host.create"
      params:
        host: "{{ inventory_hostname }}"
        interfaces:
          - type: 1
            main: 1
            ip: "{{ ansible_facts['default_ipv4']['address'] }}"
  delegate_to: "{{ groups['monitoring'][0] }}"
  delegate_facts: true
  run_once: true
```

### Сценарий 10: Валидация переменных через assert

Проверка обязательных переменных и их значений перед выполнением критичных задач.

**Валидация обязательных переменных:**

```yaml
- name: Проверка обязательных переменных
  ansible.builtin.assert:
    that:
      - app_name is defined
      - app_name | length > 0
      - app_port is defined
      - app_port | int > 0 and app_port | int < 65535
      - db_host is defined
      - env in ['dev', 'staging', 'production']
    fail_msg: "Не все обязательные переменные определены или имеют некорректные значения"
    success_msg: "Все переменные прошли валидацию"
```

**Валидация переменных окружения:**

```yaml
- name: Валидация переменных окружения
  ansible.builtin.assert:
    that:
      - ansible_facts['distribution'] in ['Ubuntu', 'Debian', 'CentOS', 'Rocky', 'AlmaLinux']
      - ansible_facts['distribution_major_version'] | int >= 20
    fail_msg: "Неподдерживаемая ОС: {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_major_version'] }}"
```

**Валидация с использованием regex:**

```yaml
- name: Валидация формата версии
  ansible.builtin.assert:
    that:
      - app_version is match('^v[0-9]+\.[0-9]+\.[0-9]+$')
    fail_msg: "app_version должен быть в формате vX.Y.Z (например, v2.3.1)"
```

### Сценарий 11: no_log и безопасная работа с секретами

Предотвращение утечки паролей и ключей в логи Ansible.

**Базовый no_log:**

```yaml
- name: Создание пользователя с паролем
  ansible.builtin.user:
    name: "{{ db_user }}"
    password: "{{ db_password | password_hash('sha512') }}"
    state: present
  no_log: true
```

**no_log на уровне блока:**

```yaml
- name: Настройка безопасного сервиса
  block:
    - name: Копирование ключа SSH
      ansible.builtin.copy:
        src: "{{ private_key_path }}"
        dest: "/home/{{ deploy_user }}/.ssh/id_rsa"
        mode: '0600'

    - name: Копирование сертификата
      ansible.builtin.copy:
        src: "{{ ssl_cert_path }}"
        dest: "/etc/ssl/private/{{ app_name }}.pem"
        mode: '0600'
  no_log: true
```

**Безопасная работа с vault-переменными:**

```yaml
- name: Создание БД
  community.postgresql.postgresql_user:
    name: "{{ vault_db_user }}"
    password: "{{ vault_db_password }}"
    state: present
  no_log: true
  become: true
  become_user: postgres
```

> **Примечание:** `no_log: true` скрывает stdout и stderr задачи, но **не скрывает** саму задачу и её имя. Если секрет передается через `register`, он будет скрыт только если `no_log: true` установлен на задаче, создавшей переменную.

### Сценарий 12: Сложное слияние и преобразование данных

Продвинутые техники работы со словарями и списками.

**Слияние словарей с удалением ключей:**

```yaml
- name: Формирование конфигурации
  ansible.builtin.set_fact:
    app_config: >-
      {{ default_config
         | combine(user_overrides, recursive=True)
         | combine({'temp_key': omit}, recursive=True) }}
  vars:
    default_config:
      port: 8080
      debug: false
      temp_key: "удалится"
    user_overrides:
      port: 9090
```

**Преобразование словаря в список и обратно:**

```yaml
- name: Конвертация словаря в список для loop
  ansible.builtin.debug:
    msg: "Сервис {{ item.key }}: порт {{ item.value.port }}"
  loop: "{{ services | dict2items }}"

- name: Конвертация списка обратно в словарь
  ansible.builtin.set_fact:
    services_dict: "{{ services_list | items2dict(key='name', value='config') }}"
  vars:
    services_list:
      - name: nginx
        config: { port: 80, ssl: true }
      - name: redis
        config: { port: 6379 }
```

**Извлечение данных из вложенных структур:**

```yaml
- name: Получение списка IP-адресов всех серверов
  ansible.builtin.debug:
    msg: >-
      {{ groups['all']
         | map('extract', hostvars)
         | map(attribute='ansible_facts.default_ipv4.address')
         | list }}

- name: Фильтрация серверов по атрибуту
  ansible.builtin.debug:
    msg: >-
      {{ groups['all']
         | map('extract', hostvars)
         | selectattr('ansible_facts.distribution', 'equalto', 'Ubuntu')
         | map(attribute='inventory_hostname')
         | list }}
```

**Работа с JSON-данными через json_query:**

```yaml
- name: Извлечение данных через JMESPath
  ansible.builtin.debug:
    msg: >-
      {{ services | json_query('[?port > `8080`].name') }}

- name: Группировка данных
  ansible.builtin.debug:
    msg: >-
      {{ servers | group_by('environment') | dict2items }}
```

### Сценарий 13: Управление переменными в гетерогенном парке (SRE)

Работа с переменными при управлении большим числом разнородных систем (Linux, Windows, BSD) из одного inventory.

**Динамический inventory с переменными:**

```yaml
# inventory/aws_ec2.yml (пример динамического inventory)
plugin: aws_ec2
regions:
  - us-east-1
  - eu-west-1
keyed_groups:
  - key: tags.Environment
    prefix: env
  - key: tags.Role
    prefix: role
  - key: ansible_facts['os_family']
    prefix: os
hostnames:
  - tag:Name
  - ip-address
```

**Использование переменных из динамического inventory:**

```yaml
- name: Конфигурация серверов по тегам
  ansible.builtin.debug:
    msg: "Сервер {{ inventory_hostname }}: окружение {{ env }}, роль {{ role }}"
  when: "'webserver' in role"
```

**Снижение дублирования через group_vars в гетерогенном парке:**

```text
inventory/
├── group_vars/
│   ├── all.yml           # Общие переменные
│   ├── web_servers.yml   # Веб-серверы
│   ├── db_servers.yml    # Базы данных
│   └── windows_servers.yml # Windows-специфичные
├── host_vars/
│   ├── web01.yml         # Переопределения для конкретного хоста
│   └── db01.yml
└── hosts.yml
```

### Сценарий 14: Аудит и snapshot переменных (SRE)

Фиксация состояния переменных и фактов для аудита изменений конфигурации.

**Создание snapshot переменных:**

```yaml
- name: Сбор всех переменных хоста
  ansible.builtin.setup:
  register: full_facts

- name: Сохранение snapshot в файл
  ansible.builtin.copy:
    content: "{{ full_facts.ansible_facts | to_nice_json }}"
    dest: "/var/tmp/audit/{{ inventory_hostname }}_facts_{{ ansible_date_time.date }}.json"
  delegate_to: localhost
  run_once: true
```

**Сравнение текущих переменных с эталоном:**

```yaml
- name: Загрузка эталонных переменных
  ansible.builtin.include_vars:
    file: "baseline_{{ env }}.yml"
    name: baseline

- name: Сравнение с эталоном
  ansible.builtin.assert:
    that:
      - ansible_facts['distribution'] == baseline.expected_distribution
      - ansible_facts['distribution_major_version'] | int == baseline.expected_version
    fail_msg: "Дрейф конфигурации: ожидается {{ baseline.expected_distribution }} {{ baseline.expected_version }}, найдено {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_major_version'] }}"
```

## Операции и команды

### Просмотр переменных и фактов

```bash
# Просмотр переменных конкретного хоста
ansible-inventory --host webserver1
# → ansible_facts={
#     "ansible_facts": {
#       "os_family": "Debian",
#       "distribution": "Ubuntu",
#       ...
#     },
#     "app_port": 8080
#   }

# Просмотр всех переменных плейбука для хоста
ansible-playbook site.yml --list-variables -l webserver1
# → {
#     "app_version": "v2.3.1",
#     "app_port": 8080,
#     "ansible_facts": { ... }
#   }

# Просмотр инвентаря в JSON
ansible-inventory --list | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d['_meta']['hostvars'], indent=2))"
# → {
#     "webserver1": {
#       "ansible_host": "10.0.0.1",
#       "ansible_facts": { ... }
#     }
#   }

# Визуализация групп инвентаря
ansible-inventory --graph
# → @all:
#   ├── @ungrouped:
#   └── web_servers:
#       ├── web01
#       └── web02
```

### Проверка фактов и debug

```bash
# Сбор фактов локального хоста
ansible localhost -m ansible.builtin.setup -a "filter=ansible_os_family*"
# → "ansible_facts": { "os_family": "Debian" }

# Проверка типа переменной
ansible localhost -m ansible.builtin.debug -a "msg={{ '{{ app_port | type_debug }}' }}"
# → "msg": "int"

# Анализ конфликтов переменных
ansible-playbook site.yml -e "debug_vars=true" -l webserver1
# → TASK [debug] ****************************************************************
#   ok: [webserver1] => {
#     "app_port": "Переопределено в group_vars/web_servers.yml"
#   }
```

### Отладка выполнения

```bash
# Запуск с началом на конкретной задаче
ansible-playbook site.yml --start-at-task="Debug переменной" -l webserver1
# → PLAY [web_servers] *********************************************************
#   TASK [Debug переменной] ****************************************************
#   ok: [webserver1] => {
#     "my_variable": "ожидаемое значение"
#   }

# Проверка подключения и сбора фактов
ansible web_servers -m ansible.builtin.ping
# → web01 | SUCCESS => {
#     "changed": false,
#     "ping": "pong"
#   }

# Выполнение с ограничением по группе
ansible-playbook site.yml -l web_servers
# → PLAY [web_servers] *********************************************************
#   TASK [Gathering Facts] *****************************************************
#   ok: [web01]
```

### Валидация синтаксиса

```bash
# Проверка синтаксиса плейбука
ansible-playbook site.yml --syntax-check
# → syntax check: ok!

# Проверка конкретного inventory
ansible-playbook site.yml -i inventory/prod --syntax-check
# → syntax check: ok!
```

### Проверка переменных из CLI

```bash
# Переопределение переменной для однократного запуска
ansible-playbook site.yml -e "app_version=v2.3.1"
# → PLAY [web_servers] *********************************************************
#   TASK [Установка приложения] ************************************************
#   changed: [web01]

# Загрузка переменных из файла
ansible-playbook site.yml -e @vars/override.yml
# → PLAY [web_servers] *********************************************************
#   TASK [Загрузка конфигурации] ***********************************************
#   ok: [web01]

# Комбинация нескольких источников
ansible-playbook site.yml -e "@vars/override.yml" -e "debug=true"
# → PLAY [web_servers] *********************************************************
#   TASK [Применение конфигурации] *********************************************
#   changed: [web01]
```

## Типичные ошибки и troubleshooting

### Ошибка: "Undefined variable"

**Причина:** Переменная не определена в текущей области видимости или имеет опечатку.

**Решение:**
```bash
# Проверить наличие переменной
ansible-inventory --host webserver1 | grep -i variable_name
# → app_port: 8080

# Проверить файлы переменных
grep -r "variable_name:" group_vars/ host_vars/ vars/
# → group_vars/web_servers.yml:variable_name: значение
```

### Ошибка: "Variable has no attribute" / "is not a dictionary"

**Причина:** Попытка обратиться к несуществующему ключу словаря или использование метода списка как словаря.

**Решение:**
```yaml
# Безопасное обращение через default()
- name: Безопасный доступ
  ansible.builtin.debug:
    msg: "{{ my_dict | default({}) | default({'key': 'default_value'}) }}"
```

### Ошибка: "Conflicting variables" / приоритет переменных

**Причина:** Переменная переопределена в нескольких местах с разным приоритетом.

**Решение:**
```bash
# Просмотр всех источников переменной
ansible-inventory --host webserver1 | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2))"
# → {
#     "app_port": 8080,
#     "_ansible_facts": { ... }
#   }

# Проверка group_vars
cat group_vars/all.yml group_vars/web_servers.yml
```

### Ошибка: Переменная не видна в include_tasks / include_role

**Причина:** `include_tasks` выполняется динамически и может не видеть переменные из `register` или `set_fact`.

**Решение:**
```yaml
# Используйте include_tasks вместо import_tasks для динамических переменных
- name: Динамическое включение
  ansible.builtin.include_tasks:
    file: "{{ task_file }}"
  vars:
    task_file: "{{ registered_var.result }}"
```

### Ошибка: "no_log не скрывает секрет"

**Причина:** Секрет выводится через `debug` или `register` в другой задаче.

**Решение:**
```yaml
# no_log должно быть на ВСЕХ задачах, которые работают с секретом
- name: Получение секрета
  ansible.builtin.set_fact:
    db_password: "{{ vault_db_password }}"
  no_log: true

- name: Использование секрета
  ansible.builtin.template:
    src: db.conf.j2
    dest: /etc/app/db.conf
  no_log: true
```

### Ошибка: Дрейф переменных в динамическом inventory

**Причина:** Динамический inventory возвращает разные переменные при каждом запуске из-за изменений в инфраструктуре.

**Решение:**
```yaml
- name: Фиксация переменных inventory
  ansible.builtin.set_fact:
    static_inventory_hostname: "{{ inventory_hostname }}"
    static_inventory_ip: "{{ ansible_host | default(inventory_hostname) }}"
  cacheable: yes
```

## Лучшие практики

### Именование и структура переменных

1. **Используйте snake_case** для имен переменных (`app_port`, не `appPort` или `AppPort`).
2. **Префикс роли**: Обеспечивает уникальность и предотвращает конфликты (`nginx_worker_count`, не `worker_count`).
3. **Группируйте переменные** в словарях, а не используйте плоскую структуру: `nginx: { workers: 4, port: 80 }`.
4. **Избегайте `hash_behaviour: merge`** в `ansible.cfg` — он deprecated и непредсказуем. Используйте `combine`.

### Значения по умолчанию и безопасность

5. **`defaults/main.yml` для переопределяемых значений.** Высокий приоритет `vars/main.yml` делает их неподходящими для пользовательских настроек.
6. **`default(omit)` для необязательных параметров.** Модуль полностью проигнорирует параметр.
7. **`no_log: true` для секретов.** Скрывайте пароли, ключи и токены от логов.
8. **Валидация через `assert`.** Проверяйте типы, форматы и обязательность переменных перед критичными задачами.

### Работа с фактами

9. **`gather_facts: false` на больших инвентарях.** Собирайте факты только там, где они необходимы.
10. **Селективный сбор** через `filter` или `gather_subset` ускоряет выполнение.
11. **Используйте `ansible_facts`** вместо устаревшего `ansible_*` (плоский формат).
12. **Кешируйте факты** через `set_fact: cacheable: yes` для межхостового взаимодействия.

### Управление переменными в крупных инфраструктурах (SRE)

13. **Единый источник правды:** Для переменных окружения используйте `group_vars/all.yml` + `host_vars/`. Избегайте хаотичного распределения переменных по ролям.
14. **Версионируйте переменные:** Храните `group_vars/` и `host_vars/` в Git. Изменения должны проходить код-ревью.
15. **Динамические inventory:** При использовании динамических источников (CMDB, мониторинг) кешируйте факты, чтобы снизить нагрузку на источники данных.
16. **Аудит переменных:** Периодически сравнивайте актуальные переменные с эталоном (snapshot) для обнаружения дрейфа.
17. **Изоляция секретов:** Храните секреты в Ansible Vault или внешних системах (HashiCorp Vault, CyberArk). Никогда не коммитьте открытые секреты в репозиторий.
18. **Documentation через `argument_specs`:** Для каждой роли описывайте интерфейс в `meta/argument_specs.yml`. Это упрощает аудит и переиспользование.

### Диагностика и отладка

19. **`debug: var=variable`** для быстрого вывода значения переменной.
20. **`ansible-inventory --host`** для проверки итоговых переменных хоста.
21. **`--list-variables`** для просмотра всех переменных плейбука.
22. **`changed_when` / `failed_when`** для корректной отчетности о статусе задач.

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — базовые директивы и место переменных в иерархии.
* [Управление ходом выполнения](flow_control.md) — использование переменных в `loop` и `when`.
* [Продвинутые возможности плейбуков](advanced.md) — делегирование и асинхронные задачи.
* [Валидация и тестирование структуры плейбуков](testing_and_validation.md) — статический анализ, dry-run и идемпотентность.
* [Шаблонизация Jinja2](../ansible_jinja_templating.md) — продвинутая обработка данных (JMESPath, сложные фильтры и lookups).
* [Оптимизация производительности](../ansible_performance_tuning.md) — `gather_facts`, `fact_caching`, `strategy`, `forks`.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки в именовании и структурах данных.
* [Кроссплатформенные концепции](../CrossPlatform/concepts.md) — работа с `ansible_facts` в гетерогенных парках Linux/Windows/BSD.
