# Ansible: переменные и факты

## Определения

**Переменные (Variables)** — именованные значения, используемые для параметризации плейбуков и ролей. Позволяют адаптировать код под разные окружения (dev/prod) без изменения самой логики задач. Могут содержать строки, числа, логические значения, списки и словари.

**Факты (Facts)** — системные данные об управляемом хосте (ОС, IP-адреса, диски, память), которые Ansible автоматически собирает перед выполнением задач. Доступны через глобальный словарь `ansible_facts`.

**Магические переменные (Magic Variables)** — зарезервированные внутренние переменные Ansible (например, `inventory_hostname`, `hostvars`), значения которых вычисляются автоматически движком и не могут быть напрямую переопределены пользователем.

**Область видимости (Scope)** — уровень доступности переменной в рамках жизненного цикла выполнения. Различают глобальную область (global), область плея (play), хоста (host) и локальные области (role, task, block).

**Кеширование фактов (Fact Caching)** — механизм сохранения собранных данных о хостах во внешнее хранилище (Redis, memcached, jsonfile) для ускорения последующих запусков и межхостового взаимодействия без повторного сбора.

**Переменные регистрации (Registered Variables)** — переменные, создаваемые модулем `register` для сохранения результата выполнения задачи. Содержат полную структуру результата: `stdout`, `stderr`, `rc`, `changed`, `failed` и др. Позволяют реализовывать условную логику и обработку ошибок.

**Динамические переменные (set_fact)** — переменные, создаваемые или переопределяемые во время выполнения плейбука через модуль `ansible.builtin.set_fact`. Сохраняются на уровне хоста и доступны во всех последующих задачах текущего плея.

**Безопасное логирование (no_log)** — директива, предотвращающая запись секретных данных в лог Ansible. Устанавливается на уровне задачи или блока. При `no_log: true` ни stdout, ни stderr задачи не попадают в вывод.

**Делегирование фактов (delegate_facts)** — механизм, позволяющий собранные факты хоста сохранить у делегированного хоста (обычно балансировщика или сервера мониторинга) вместо целевого. Используется совместно с `delegate_to`.

**Директива vars_files** — указание YAML-файлов с переменными для подключения в начале плея. Поддерживает глобальную видимость и динамические пути через Jinja2-шаблоны.

**Директива vars_prompt** — интерактивный ввод переменных при запуске плейбука. Поддерживает скрытие ввода (`private: yes`), валидацию через `encrypt` и значения по умолчанию.

## Базовые концепции

### Иерархия приоритетов (Variable Precedence)

Ansible использует сложную систему приоритетов (официально 22 уровня) для разрешения конфликтов имен. Знание этой иерархии критично для управления конфигурациями и отладки.

*Полная иерархия приоритетов (от низшего к высшему):*

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

> **Примечание:** Переменные окружения (`ansible_*`), `set_fact` и `registered vars` имеют одинаковый приоритет (уровень 7). `extra_vars` (уровень 10) имеют **абсолютный приоритет** и переопределяют всё остальное.

**Практические правила приоритетов:**

- Используйте `defaults/main.yml` для безопасных значений по умолчанию, которые легко переопределять.
- Избегайте `vars/main.yml` роли для переопределяемых настроек — они имеют высокий приоритет.
- `extra_vars` идеальны для временных переопределений, но опасны для долгосрочных настроек.
- `set_fact` и `register` имеют одинаковый приоритет — последняя определенная побеждает.

### Опции переопределения в CLI

```bash
# Extra vars (абсолютный приоритет)
ansible-playbook site.yml -e "app_version=v2.3.1"
ansible-playbook site.yml -e @vars/override.yml

# Установка переменной окружения
export ANSIBLE_EXTRA_VARS="env=prod"
ansible-playbook site.yml

# Переопределение через --extra-vars с stdin
echo '{"app_debug": false}' | ansible-playbook site.yml -e @-
```

### Работа с фактами (ansible_facts)

По умолчанию сбор фактов происходит в начале каждого плея (`gather_facts: true`) с использованием модуля `ansible.builtin.setup`.
*   **Современный синтаксис**: Всегда используйте словарь `ansible_facts['os_family']` вместо устаревшего плоского формата `ansible_os_family`.
*   **Оптимизация**: Для экономии времени на больших инвентарях сбор можно отключать (`gather_facts: false`), собирая факты только там, где необходимо, через модуль `setup`.
*   **Кастомные факты (`ansible_local`)**: Текстовые (INI/JSON) или исполняемые файлы в `/etc/ansible/facts.d/*.fact`. Их вывод доступен через `ansible_facts.ansible_local`.

**Селективный сбор фактов:**

Сбор только нужных подмножеств фактов значительно ускоряет выполнение на больших инвентарях.

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

Факты, собираемые модулями `setup` автоматически, включают информацию о сетевых интерфейсах, дисках, процессорах и ОС. Доступны через `ansible_facts`:

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

### Кеширование фактов (Fact Caching)

Настройка кеша в `ansible.cfg` позволяет избежать повторного сбора фактов при каждом запуске:
```ini
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_cache
fact_caching_timeout = 86400 # 24 часа
```
**Безопасность**: Будьте осторожны с секретами, сохраняемыми через `set_fact` — при включенном кешировании они могут быть записаны на диск в открытом виде.

### Валидация через argument_specs

Начиная с Ansible 2.11, рекомендуется описывать интерфейс роли в `meta/argument_specs.yml`. Это обеспечивает автоматическую проверку типов, обязательности и разрешенных значений переменных до выполнения первой задачи. В 2.17+ поддерживается поле `context` для расширенной метаинформации.

### Полезные магические переменные

*   `inventory_hostname`: Имя хоста в инвентаре (может отличаться от системного `hostname`).
*   `hostvars`: Доступ к переменным и фактам *других* хостов. Пример: `hostvars['db']['ansible_facts']['eth0']['ipv4']['address']`.
*   `groups`: Список всех групп и хостов в них. Полезно для генерации конфигов балансировщиков.
*   `group_names`: Список групп, в которые входит текущий хост.
*   `ansible_check_mode`: `true` если плейбук выполняется в режиме проверки (`--check`). Используется для пропуска задач, которые не поддерживают дри_RUN.
*   `ansible_diff_mode`: `true` если включен режим дифференциального вывода (`--diff`).
*   `groups_all`: Список всех хостов во всех группах. Отличается от `groups['all']` тем, что включает даже игнорируемые хосты.
*   `play_hosts`: Список хостов, попавших в текущий play (deprecated: используйте `ansible_play_hosts_all`).
*   `ansible_play_hosts_all`: Список всех хостов текущего play.
*   `ansible_version`: Словарь с версией Ansible (`ansible_version.full`, `ansible_version.major`, `ansible_version.minor`).
*   `omit`: Специальная переменная,指示 модулю полностью игнорировать параметр (используется с `default(omit)`).

### Типизация и фильтры Jinja2

Используйте фильтры для безопасной и гибкой обработки данных:
*   `default(value)`: Значение по умолчанию, если переменная не определена.
*   `default(omit)`: Полное игнорирование параметра модуля, если переменная отсутствует.
*   `combine`: Слияние словарей (особенно полезно для глубокого слияния настроек).
*   `type_debug`: Отладка типа данных.
*   `to_json` / `from_yaml`: Преобразование форматов данных.
*   `dict2items` / `items2dict`: Преобразование словарей в список и обратно (для циклической обработки ключей).
*   `selectattr` / `rejectattr`: Фильтрация списков словарей по атрибуту.
*   `map` / `map(attribute)`: Извлечение или трансформация значений из списка словарей.
*   `regex_replace`: Замена по регулярному выражению.
*   `regex_search` / `regex_match`: Поиск по регулярному выражению.
*   `json_query`: Запросы к JSON-данным с помощью JMESPath (требуется `community.general`).

**Примеры использования фильтров:**

```yaml
# Извлечение списка IP-адресов из hostvars
- name: Получить все IP веб-серверов
  ansible.builtin.debug:
    msg: "{{ groups['web_servers'] | map('extract', hostvars, ['ansible_facts', 'default_ipv4', 'address']) | list }}"

# Фильтрация списка хостов по атрибуту
- name: Только живые серверы
  ansible.builtin.debug:
    msg: "{{ groups['all'] | map('extract', hostvars) | selectattr('ansible_facts.distribution', 'equalto', 'Ubuntu') | map(attribute='inventory_hostname') | list }}"

# Преобразование словаря в список для loop
- name: Вывести каждый сервис
  ansible.builtin.debug:
    msg: "Сервис: {{ item.key }} -> {{ item.value }}"
  loop: "{{ services | dict2items }}"
```

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

**Расширенный вариант с first_found и значениями по умолчанию:**

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
        skip: true  # Не падать, если файл не найден
```

**Загрузка из словаря (dict):**

```yaml
- name: Загрузка переменных из встроенного словаря
  ansible.builtin.include_vars:
    content: |
      app_port: 8080
      app_debug: false
    name: inline_config
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

Оркестрация межхостового взаимодействия (например, получение IP-адреса БД).

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
# Сохранение факта для использования в других плейбуках
- name: Сохранить версию приложения
  ansible.builtin.set_fact:
    app_installed_version: "v2.3.1"
    cacheable: yes  # Сохраняется в fact cache
    cache_timeout: 3600  # Время жизни в секундах (только для jsonfile)
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

- name: Использование словаря в шаблоне
  ansible.builtin.template:
    src: app.conf.j2
    dest: /etc/app/config.yml
```

**set_fact для условной логики (uso de `when`):**

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

**Множественное слияние с списком словарей:**

```yaml
- name: Слияние нескольких источников конфигурации
  ansible.builtin.set_fact:
    final_config: "{{ config_base | combine(config_env, config_local, recursive=True) }}"
  vars:
    config_base:
      listen: "0.0.0.0:8080"
      workers: 4
    config_env:
      workers: 8  # Переопределение для продакшена
    config_local:
      listen: "127.0.0.1:8080"  # Локальная разработка
```

**Слияние с удалением ключей:**

```yaml
- name: Удаление ключа из словаря
  ansible.builtin.set_fact:
    app_config: "{{ app_config | combine({'debug': omit}, recursive=True) }}"
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
      private: false  # Показывать ввод
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
      private: true  # Скрывать ввод
      encrypt: "sha512_crypt"  # Хеширование

  tasks:
    - name: Деплой указанной версии
      ansible.builtin.debug:
        msg: "Деплой {{ deploy_version }} в {{ deploy_env }}"
```

**Комбинация vars_prompt и vars_files:**

```yaml
---
- name: Гибкая конфигурация
  hosts: all
  vars_prompt:
    - name: config_profile
      prompt: "Профиль конфигурации"
      private: false
      default: "standard"
      choices: ["minimal", "standard", "full"]
  vars_files:
    - "vars/profiles/{{ config_profile }}.yml"
  tasks:
    - name: Применение профиля
      ansible.builtin.debug:
        msg: "Профиль: {{ config_profile }}, Рабочие процессы: {{ nginx_workers }}"
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

**Использование `changed_when` и `failed_when`:**

```yaml
- name: Проверка версии пакета
  ansible.builtin.command: dpkg-query -W -f='${Version}' nginx
  register: nginx_version
  changed_when: false  # Команда только читает, не меняет состояние
  failed_when: false   # Не падать, если пакет не установлен

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
  delegate_facts: true  # Сохранить факты у делегата
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
  no_log: true  # Скрыть пароль из логов
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
  no_log: true  # Весь блок скрыт из логов
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

- name: Создание базы данных
  community.postgresql.postgresql_db:
    name: "{{ db_name }}"
    owner: "{{ vault_db_user }}"
  become: true
  become_user: postgres
```

> **Примечание:** `no_log: true` скрывает.stdout и.stderr задачи, но **не скрывает** саму задачу и её имя. Если секрет передается через `register`, он будет скрыт только если `no_log: true` установлен на задаче, создавшей переменную.

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

## Валидация и отладка переменных

### Просмотр переменных в плейбуке

```bash
# Просмотр переменных конкретного хоста
ansible-inventory --host webserver1

# Просмотр переменных из CLI
ansible-playbook site.yml --list-variables

# Просмотр переменных группы
ansible-inventory --list | python3 -c "import sys, json; d=json.load(sys.stdin); print(json.dumps(d['_meta']['hostvars'], indent=2))"

# Просмотр всех групп
ansible-inventory --graph
```

### Отладка переменных в задачах

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

# Вывод только одной переменной из hostvars
- name: Конкретный факт
  ansible.builtin.debug:
    var: hostvars[inventory_hostname]['ansible_facts']['default_ipv4']
```

### Проверка типов и значений

```yaml
# Проверка типа переменной
- name: Проверка типа
  ansible.builtin.assert:
    that:
      - my_variable is defined
      - my_variable is string
      - my_variable | length > 0
    fail_msg: "my_variable не определена или пуста"

# Проверка версии
- name: Проверка версии
  ansible.builtin.assert:
    that:
      - app_version is version('2.0.0', '>=')
      - app_version is version('3.0.0', '<')
    fail_msg: "app_version должна быть >= 2.0.0 и < 3.0.0"

# Проверка по regex
- name: Проверка формата
  ansible.builtin.assert:
    that:
      - ip_address is match('^(\\d{1,3}\\.){3}\\d{1,3}$')
    fail_msg: "ip_address должен быть в формате IPv4"
```

### Диагностика конфликтов приоритетов

```bash
# Просмотр итоговых переменных для конкретного хоста
ansible-playbook site.yml --list-variables -l webserver1

# Вывод переменных с highest precedence
ansible-playbook site.yml -e "debug_vars=true" -l webserver1

# Проверка, откуда берется переменная
ansible-playbook site.yml --start-at-task="Debug переменной" -l webserver1
```

## Типичные ошибки и troubleshooting

### Ошибка: "Undefined variable"

**Причина:** Переменная не определена в текущей области видимости или имеет опечатку.

**Решение:**
```bash
# Проверить наличие переменной
ansible-inventory --host webserver1 | grep variable_name

# Проверить файлы переменных
grep -r "variable_name:" group_vars/ host_vars/ vars/
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
  no_log: true  # Обязательно

- name: Использование секрета
  ansible.builtin.template:
    src: db.conf.j2
    dest: /etc/app/db.conf
  no_log: true  # И здесь тоже
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

### Диагностика и отладка

13. **`debug: var=variable`** для быстрого вывода значения переменной.
14. **`ansible-inventory --host`** для проверки итоговых переменных хоста.
15. **`--list-variables`** для просмотра всех переменных плейбука.
16. **`changed_when` / `failed_when`** для корректной отчетности о статусе задач.

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — базовые директивы и место переменных в иерархии.
* [Управление ходом выполнения](flow_control.md) — использование переменных в `loop` и `when`.
* [Продвинутые возможности плейбуков](advanced.md) — делегирование и асинхронные задачи.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки в именовании и структурах данных.
* [Шаблонизация Jinja2](../ansible_jinja_templating.md) — продвинутая обработка данных (JMESPath, сложные фильтры и lookups).
