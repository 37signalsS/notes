# Создание и использование ролей Ansible

## Определения

**Роль (Role)** — основной механизм декомпозиции и переиспользования кода в Ansible. Она позволяет объединять задачи, переменные, файлы и шаблоны в логические блоки для настройки конкретных сервисов или компонентов системы.

**Использование роли** — процесс интеграции роли в плейбук одним из трех способов: через классическую директиву `roles`, статическое импортирование (`import_role`) или динамическое включение (`include_role`).

**Статическое импортирование (`ansible.builtin.import_role`)** — механизм, при котором роль вставляется в плейбук на этапе парсинга (до начала выполнения). Все задачи роли становятся частью основного списка задач. Это аналогично вставке кода (inline) в место вызова.

**Динамическое включение (`ansible.builtin.include_role`)** — механизм, при котором роль подключается непосредственно во время выполнения плейбука, когда очередь доходит до соответствующего шага.

**Спецификация аргументов (`argument_spec`)** — декларативное описание входных параметров роли в файле `meta/argument_specs.yml`, позволяющее Ansible автоматически проверять типы и обязательность переменных.

## Предварительные требования

Для работы с ролями Ansible необходимо выполнение следующих условий:

### Версии программного обеспечения

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Python (контрольный узел)** | 3.10 (Ansible 2.17) | 3.11+ (Ansible 2.18+) |
| **Python (управляемые узлы)** | 3.8 (Ansible 2.18) | 3.11+ |
| **ansible-core** | 2.17 | 2.18+ |
| **ansible-galaxy** | Входит в ansible-core | Последняя стабильная версия |

### Начальная настройка

```bash
# Установка Ansible (через pip)
pip install ansible-core

# Проверка версии
ansible --version  # → ansible [core 2.18.x]

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

## Основные концепции

### Создание и инициализация роли

Процесс создания каркаса роли и подробное описание её внутренней структуры (каталоги, назначение файлов, валидация аргументов) вынесены в отдельный раздел:

*   **[Структура роли Ansible](structure.md)** — инициализация через `ansible-galaxy`, назначение каталогов `tasks`, `meta`, `defaults`, `vars` и др.

### Способы подключения ролей

В современном Ansible рекомендуется использовать полное имя модуля (FQCN) — `ansible.builtin.*`. Существует три основных способа интеграции ролей:

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

---

## Технические детали и возможности

### Сравнение механизмов подключения

| Характеристика | `import_role` (Static) | `include_role` (Dynamic) |
| :--- | :--- | :--- |
| **Время обработки** | При парсинге плейбука | Во время выполнения (Runtime) |
| **Циклы (`loop`)** | Не поддерживаются | Полная поддержка |
| **Условия (`when`)** | Применяются к каждой задаче внутри | Проверяется один раз для всей роли |
| **Теги из CLI** | Видны и доступны для фильтрации | Не видны до выполнения |
| **Обработчики (`handlers`)** | Глобально доступны | Доступны после выполнения роли |
| **Python Requirements** | N/A (Control Node) | Python 3.8+ (Target Node для 2.18+), 3.11+ рекомендуется |

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



## Порядок выполнения и зависимости

### Очередность выполнения в плейбуке

Если в плейбуке используются все типы задач, Ansible выполняет их в строгом порядке:
1. `pre_tasks` — задачи, выполняемые до ролей.
2. `roles` — роли, указанные в секции `roles:`.
3. `tasks` — основные задачи плейбука (включая `import_role` и `include_role` в порядке их следования).
4. `post_tasks` — задачи, выполняемые после завершения всех основных действий.
5. `handlers` — выполняются после каждой секции задач, если были уведомления через `notify`.

### Зависимости ролей

Роли могут зависеть от других ролей. Это описывается в файле `meta/main.yml`. При вызове основной роли Ansible сначала выполнит все её зависимости. 

**Важные нюансы:**
* По умолчанию зависимая роль выполняется только один раз, даже если она указана как зависимость для нескольких ролей.
* Чтобы разрешить повторное выполнение зависимости, используйте `allow_duplicates: true` в `meta/main.yml` зависимой роли.
* **Рекомендация:** Для современных проектов (Ansible 2.10+) часто лучше использовать явные вызовы `include_role` в `tasks/main.yml` основной роли вместо классических зависимостей в `meta`.

---

## Практические сценарии

### Сценарий 1: Условное выполнение роли на основе фактов

Динамический выбор роли в зависимости от операционной системы:

```yaml
tasks:
  - name: Setup OS specific role
    ansible.builtin.include_role:
      name: "{{ ansible_facts['os_family'] | lower }}_setup"
    when: ansible_facts['os_family'] in ['Debian', 'RedHat']
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
pip install ansible-lint

# Проверка конкретной роли
ansible-lint roles/nginx/

# Проверка с профилем (рекомендуется)
ansible-lint roles/nginx/ --profile production
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

Использование Ansible Vault для хранения секретов в ролях:

```bash
# Шифрование переменных
ansible-vault encrypt roles/myapp/defaults/vault.yml

# Запуск плейбука с расшифровкой
ansible-playbook site.yml --ask-vault-pass

# Использование файла пароля
ansible-playbook site.yml --vault-password-file ~/.vault_pass
```

СтруктураROLE для секретов:

```text
roles/myapp/
├── defaults/
│   ├── main.yml        # Обычные переменные
│   └── vault.yml       # Зашифрованные секреты (не коммитить!)
├── vars/
│   └── vault.yml       # Секреты с высоким приоритетом
└── tasks/
    └── main.yml
```

Рекомендация: выносите секреты в `defaults/vault.yml` (низкий приоритет, переопределяется).

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
    - ansible-lint roles/ --profile production

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
    - ansible-playbook -i inventory/production site.yml
  environment:
    name: production
  when: manual
  only:
    - main
```

### Сценарий 9: Отладка выполнения ролей

Методы диагностики проблем при выполнении ролей:

```bash
# Вывод всех задач без выполнения
ansible-playbook site.yml --list-tasks

# Запуск с увеличенной детализацией
ansible-playbook site.yml -vvv  # Очень подробный вывод

# Запуск конкретной роли по тегу
ansible-playbook site.yml --tags "nginx" --check  # Режим проверки

# Ограничение по хостам
ansible-playbook site.yml --limit "webserver1"

# Вывод переменных роли
ansible-playbook site.yml -e "ansible_debug=true"
```

Отладка переменных в задачах:

```yaml
tasks:
  - name: Debug - show all role variables
    ansible.builtin.debug:
      var: hostvars[inventory_hostname]
      verbosity: 1  # Показать только с -v

  - name: Debug - show specific variable
    ansible.builtin.debug:
      msg: "nginx_port is {{ nginx_port | default('NOT SET') }}"
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

### Распространенные ошибки

1. **Использование циклов с `import_role`** — приведет к критической ошибке на этапе парсинга. Для циклов всегда используйте `include_role`.
2. **Путаница в путях** — Ansible ищет роли в папке `roles/` рядом с плейбуком или в путях, указанных в `ansible.cfg` (`roles_path`).
3. **Забытый `become: true`** — если роль выполняет системные задачи, убедитесь, что права повышены. Лучшая практика — использовать `apply` с `become` при динамическом включении.
4. **Конфликт имен переменных** — если две роли используют переменную `port`, экспорт через `public: true` может привести к непредсказуемым результатам. Используйте префиксы (например, `nginx_port`).
5. **Шаблоны в условиях `when`** — в Ansible 2.17+ использование `{{ }}` в `when` может вызвать предупреждения или ошибки безопасности (CVE-2023-5764). Используйте: `when: my_var == "value"`.
6. **Контрольный узел и Python** — для Ansible 2.18+ требуется Python 3.11+ на управляющей машине, Python 3.8+ на управляемых.

### Troubleshooting

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

# Или контролируйте через条件
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

### Best Practices

#### Структура и проектирование

1. **Единая ответственность:** Одна роль = один компонент (nginx, postgresql, app).
2. **Интерфейс через `argument_specs`:** Описывайте все входные параметры в `meta/argument_specs.yml`.
3. **Префиксы переменных:** Все переменные роли должны начинаться с имени роли (`nginx_port`, `app_path`).
4. **FQCN:** Всегда используйте полные имена модулей (`ansible.builtin.template`).

#### Безопасность

1. **Секреты в Vault:** Никогда не храните пароли в открытом виде.
2. **`no_log: true`:** Скрывайте чувствительные данные в задачах.
3. **Минимальные права:** Используйте `become` только где необходимо.
4. **Проверка зависимостей:** Валидируйте роли из Galaxy перед использованием.

#### Производительность

1. **`pipelining`:** Включайте в `ansible.cfg` для ускорения SSH-соединений.
2. **Факты:** Используйте `gathering: smart` или `lazy` для уменьшения количества запросов.
3. **Кэширование:** Используйте Redis или JSON-file для кэширования фактов.
4. **Throttle:** Ограничивайте параллельное выполнение для ресурсоемких ролей.

#### Тестирование

1. **ansible-lint:** Проверяйте роли перед коммитом.
2. **Molecule:** Пишите интеграционные тесты для критических ролей.
3. **Check mode:** Тестируйте_roles с `--check` перед реальным применением.
4. **Dry run:** Используйте `--diff` для просмотра изменений.

### Edge Cases

#### Работа с несколькими ОС

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

#### Динамические роли на основе фактов

```yaml
tasks:
  - name: Select role based on cloud provider
    ansible.builtin.include_role:
      name: "{{ cloud_provider }}_setup"
    vars:
      cloud_provider: "{{ ansible_facts['ec2']['tags']['cloud_provider'] | default('aws') }}"
    when: ansible_facts['ec2'] is defined
```

### См. также

- [Структура роли](structure.md) — назначение каталогов и файлов
- [Компоненты роли](../ansible_roles.md) — базовые определения и концепции
- [Стратегии и паттерны](strategies.md) — рекомендации по проектированию
- [Продвинутые возможности плейбуков](../PlaybookStructure/advanced.md) — подробнее об `import` и `include`
- [Паттерн Utility Role](utility_role_pattern.md) — использование ролей в качестве библиотек
- [Тестирование через Molecule](../ansible_testing_with_molecule.md) — современный подход к тестированию
