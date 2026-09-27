# Ansible: роли и коллекции

## Определения

**Роль (Role)** — основной механизм декомпозиции и переиспользования кода в Ansible. Это автономная структура файлов и каталогов, которая инкапсулирует задачи, переменные, шаблоны и обработчики для автоматизации конкретного компонента системы (например, роль `ansible-role-nginx`). Роли позволяют создавать модульные, читаемые и легко обслуживаемые плейбуки.

**Коллекция (Collection)** — современный стандарт упаковки и распространения контента Ansible (внедрен в версии 2.10). Коллекция является «супер-набором», который может содержать роли, модули, плагины (фильтры, lookup, callback) и документацию. Это единственный способ поставки новых модулей и плагинов в экосистему без изменения ядра **ansible-core**.

**FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource`. Пример: `community.general.docker_container`. Использование FQCN является обязательным стандартом для предотвращения конфликтов имен.

**Ansible Galaxy** — официальный публичный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита командной строки для поиска, установки и управления контентом Ansible.

**Molecule** — фреймворк для автоматизированного тестирования ролей Ansible. Управляет всем циклом: создание изолированных окружений, проверка состояния и удаление тестовых стендов.

---

## Предварительные требования

### Версии программного обеспечения

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **Python (контрольный узел)** | 3.12 (Ansible 2.21) | 3.14+ |
| **Python (управляемые узлы)** | 3.9 (Ansible 2.21) | 3.12+ |
| **ansible-core** | 2.21 | 2.21+ |
| **ansible-galaxy** | Входит в ansible-core | Последняя стабильная версия |
| **ansible-lint** | 26.x | Последняя стабильная версия (v26.8.0+) |
| **Molecule** (опционально) | 26.x | Последняя стабильная версия (v26.9.0+) |

### Установка и проверка

```bash
# Установка Ansible + Molecule + lint
pip install ansible-core molecule ansible-lint

# Проверка версий
ansible --version        # → ansible [core 2.21.x]
ansible-lint --version   # → ansible-lint [core 26.x]
molecule --version       # → molecule 26.x

# Проверка доступных ролей/коллекций
ansible-galaxy role list
ansible-galaxy collection list
```

### Рекомендуемая структура проекта

```text
project/
├── ansible.cfg
├── inventory/
│   ├── production/
│   │   ├── hosts.yml
│   │   └── group_vars/
│   │       ├── all.yml
│   │       ├── webservers.yml
│   │       └── dbservers.yml
│   └── staging/
├── roles/
│   ├── common/           # Базовая роль (пользователи, ssh, NTP)
│   ├── nginx/            # Роль веб-сервера
│   ├── postgresql/       # Роль БД
│   ├── monitoring_agent/ # Роль агента мониторинга
│   └── app/              # Роль приложения
├── playbooks/
│   ├── site.yml          # Мастер-плейбук
│   ├── webservers.yml    # Плейбук для веб-серверов
│   └── dbservers.yml     # Плейбук для БД
├── collections/
│   └── requirements.yml  # Зависимости коллекций
└── requirements.yml      # Зависимости ролей
```

---

## Базовые концепции

### Роли: декомпозиция и изоляция

Роли решают проблему монолитных плейбуков, разделяя логику по функциональным областям. Это основной механизм переиспользования кода и обеспечения консистентности окружений в масштабах инфраструктуры.

*   **Иерархия поиска:** Ansible ищет ресурсы внутри роли (например, шаблоны в `templates/`) автоматически, избавляя от необходимости указывать полные пути.
*   **Валидация (`argument_specs.yml`):** Начиная с Ansible 2.11, роли поддерживают декларативное описание входных параметров с проверкой типов и значений по умолчанию в `meta/argument_specs.yml`. В 2.17+ поддерживается поле `context` для расширенной метаинформации, доступной в IDE и при автогенерации документации.
*   **Область видимости:** Переменные в `defaults/main.yml` имеют самый низкий приоритет, что делает роли максимально гибкими для настройки через внешние параметры.
*   **Идемпотентность:** Каждая задача роли должна converge к одному и тому же состоянию при повторном запуске. Используйте `changed_when` и `failed_when` для точного контроля.
*   **Производственная готовность:** Роли должны включать обработчики (`handlers/`) для перезапуска сервисов, валидацию конфигураций (`validate` в `template` модуле) и проверки работоспособности (`assert`, `wait_for`).

### Коллекции: расширение возможностей

Коллекции позволяют вендорам (Cisco, VMware, Juniper) и сообществу обновлять свои инструменты независимо от релизного цикла самого Ansible.

*   **Unified Layout (Ansible 2.14+):** Современный стандарт организации коллекций, где плагины выносятся в единую директорию `plugins/` на уровне коллекции, что упрощает их поиск и использование ролями внутри этой же коллекции.
*   **Версионирование:** В отличие от классических ролей, коллекции поддерживают строгое семантическое версионирование, что критично для воспроизводимости сред в CI/CD.
*   **FQCN (Fully Qualified Collection Name):** Полное имя ресурса в формате `namespace.collection.resource` (например, `community.general.docker_container`). Использование FQCN является обязательным стандартом для предотвращения конфликтов имен между коллекциями.
*   **Распространение:** Коллекции публикуются в Ansible Galaxy или внутренних репозиториях. Устанавливаются через `ansible-galaxy collection install`.

### Структура роли

Подробный разбор каждой директории, назначения файлов, примеры конфигураций и лучшие практики — в [Структура роли](./Roles/structure.md).

### Способы подключения ролей в плейбуке

#### 1. Классический способ (`roles:`)

Роли выполняются в самом начале плейбука (после `pre_tasks`). Наиболее простой метод с наименьшей гибкостью.

```yaml
---
- name: Настройка веб-серверов
  hosts: webservers
  become: true
  pre_tasks:
    - name: Обновление кэша пакетов
      ansible.builtin.apt:
        update_cache: true
        cache_valid_time: 3600
  roles:
    - role: common
    - role: nginx
      vars:
        nginx_worker_processes: 4
        nginx_worker_connections: 1024
    - role: monitoring_agent
      vars:
        monitoring_server: "https://monitoring.example.com"
  post_tasks:
    - name: Проверка доступности сервиса
      ansible.builtin.uri:
        url: "http://localhost:80/health"
        status_code: 200
```

#### 2. Статическое импортирование (`import_role`)

Вставляет роль в плейбук на этапе парсинга. Все задачи роли становятся частью основного списка задач.

```yaml
---
- name: Статический импорт роли
  hosts: dbservers
  become: true
  tasks:
    - name: Импорт роли PostgreSQL
      ansible.builtin.import_role:
        name: postgresql
      vars:
        postgresql_version: 16
        postgresql_max_connections: 200
        postgresql_shared_buffers: "256MB"

    - name: Дополнительная настройка БД
      ansible.builtin.postgresql_db:
        name: myapp
        state: present
```

**Особенности `import_role`:**
- Задачи роли видны при парсинге (`--list-tasks`)
- Условия (`when`) применяются ко **всем** задачам роли
- Нельзя использовать `loop` или динамические `vars` при импорте

#### 3. Динамическое включение (`include_role`)

Подключает роль во время выполнения плейбука. Более гибкий метод.

```yaml
---
- name: Динамическое включение роли
  hosts: app_servers
  become: true
  tasks:
    - name: Установка Java
      ansible.builtin.include_role:
        name: java_runtime
      vars:
        java_version: 21
        java_vendor: adoptium

    - name: Определение окружения
      ansible.builtin.set_fact:
        app_env: "{{ 'production' if 'prod' in inventory_hostname else 'staging' }}"

    - name: Включение роли приложения
      ansible.builtin.include_role:
        name: app
      vars:
        app_env: "{{ app_env }}"
        app_debug: "{{ app_env != 'production' }}"
```

**Особенности `include_role`:**
- Задачи роли **не** видны при парсинге (`--list-tasks`)
- Условия (`when`) применяются к **каждой** задаче роли отдельно
- Поддерживает `loop` и динамические переменные
- Параметр `public: true` (Ansible 2.15+) позволяет передавать переменные между ролями

### Сравнение: `import_role` vs `include_role`

| Характеристика | `import_role` | `include_role` |
| :--- | :--- | :--- |
| **Время выполнения** | Парсинг (статически) | Выполнение (динамически) |
| **Видимость задач** | `--list-tasks` показывает все | `--list-tasks` не показывает |
| **Условия (`when`)** | Применяются ко всем задачам | Применяются к каждой задаче |
| **`loop` / `with_items`** | Не поддерживается | Поддерживается |
| **Передача переменных** | Через `vars` | Через `vars` и `public` |
| **Применение** | Когда нужна предсказуемость | Когда нужна гибкость |

### Приоритет переменных в ролях

Подробнее об иерархии переменных — в [Структура роли](./Roles/structure.md).

```yaml
# roles/nginx/defaults/main.yml — пользователь может переопределить
nginx_worker_processes: "auto"
nginx_worker_connections: 1024
nginx_listen_port: 80
nginx_server_name: "example.com"

# roles/nginx/vars/main.yml — внутренние константы, не для переопределения
nginx_config_dir: "/etc/nginx"
nginx_log_dir: "/var/log/nginx"
nginx_pid_file: "/run/nginx.pid"
```

### Обработчики (Handlers)

Подробнее об обработчиках — в [Структура роли](./Roles/structure.md). Практический пример:

```yaml
# roles/nginx/handlers/main.yml
---
- name: restart nginx
  ansible.builtin.service:
    name: nginx
    state: restarted
  listen: "restart web services"

- name: reload nginx
  ansible.builtin.service:
    name: nginx
    state: reloaded
  listen: "reload web services"

# roles/nginx/tasks/main.yml
---
- name: Установка Nginx
  ansible.builtin.apt:
    name: nginx
    state: present
  notify: restart nginx

- name: Деплой конфигурации
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: /etc/nginx/nginx.conf
    owner: root
    group: root
    mode: "0644"
    validate: "nginx -t -c %s"
  notify: reload nginx
  tags: [configure]
```

---

## Практические сценарии

### Сценарий 1: Создание роли с нуля

```bash
# 1. Инициализация каркаса роли
ansible-galaxy role init roles/nginx

# 2. Структура созданных каталогов
ls -la roles/nginx/
# defaults/ handlers/ files/ meta/ molecule/ tasks/ templates/ vars/ README.md

# 3. Проверка структуры
tree roles/nginx/
```

**Пример заполненного `tasks/main.yml`:**
```yaml
---
# roles/nginx/tasks/main.yml
- name: Включение переменных ОС
  ansible.builtin.include_vars: "{{ item }}"
  with_first_found:
    - "{{ ansible_os_family }}.yml"
    - "default.yml"

- name: Установка Nginx
  ansible.builtin.package:
    name: "{{ nginx_package_name }}"
    state: present
  notify: restart nginx

- name: Создание конфигурационного файла
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: "{{ nginx_config_dir }}/nginx.conf"
    owner: root
    group: root
    mode: "0644"
    backup: true
  notify: reload nginx
  tags: [configure]

- name: Настройка виртуальных хостов
  ansible.builtin.template:
    src: vhost.conf.j2
    dest: "{{ nginx_config_dir }}/sites-available/{{ item.name }}.conf"
    owner: root
    group: root
    mode: "0644"
  loop: "{{ nginx_vhosts }}"
  notify: reload nginx
  tags: [configure]

- name: Активация виртуальных хостов
  ansible.builtin.file:
    src: "{{ nginx_config_dir }}/sites-available/{{ item.name }}.conf"
    dest: "{{ nginx_config_dir }}/sites-enabled/{{ item.name }}.conf"
    state: link
  loop: "{{ nginx_vhosts }}"
  notify: reload nginx

- name: Запуск и автозапуск Nginx
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: true
```

**Пример `defaults/main.yml`:**
```yaml
---
# roles/nginx/defaults/main.yml
nginx_worker_processes: "auto"
nginx_worker_connections: 1024
nginx_listen_port: 80
nginx_server_name: "{{ inventory_hostname }}"
nginx_client_max_body_size: "64m"
nginx_vhosts:
  - name: default
    server_name: "{{ nginx_server_name }}"
    root: "/var/www/html"
    index: "index.html index.htm"
```

**Пример `meta/main.yml`:**
```yaml
---
galaxy_info:
  author: "DevOps Team"
  description: "Nginx web server configuration"
  license: "MIT"
  min_ansible_version: "2.21"
  platforms:
    - name: Ubuntu
      versions:
        - jammy
        - noble
    - name: Debian
      versions:
        - bookworm
  galaxy_tags:
    - nginx
    - webserver
    - reverse_proxy

dependencies:
  - role: common
  - role: firewall
    vars:
      firewall_allowed_ports:
        - 80
        - 443
```

### Сценарий 2: Рефакторинг монолитного проекта

Если ваш плейбук превышает 500 строк или используется для настройки нескольких разнородных сервисов, логику необходимо вынести в роли.

**До рефакторинга:**
```yaml
# playbooks/old_monolith.yml (500+ строк)
---
- hosts: all
  become: true
  tasks:
    # 200 строк: настройка пользователей
    # 150 строк: установка и настройка Nginx
    # 100 строк: настройка PostgreSQL
    # 50 строк: мониторинг
```

**После рефакторинга:**
```yaml
# playbooks/site.yml
---
- name: Настойка веб-серверов
  hosts: webservers
  become: true
  roles:
    - common
    - nginx
    - monitoring_agent

- name: Настройка баз данных
  hosts: dbservers
  become: true
  roles:
    - common
    - postgresql
    - monitoring_agent
```

### Сценарий 3: Использование зависимостей ролей

Зависимости описываются в `meta/main.yml`. Ansible выполняет зависимости автоматически перед основной ролью.

```yaml
# roles/app/meta/main.yml
---
galaxy_info:
  role_name: app
  description: "My Application Server"

dependencies:
  - role: common
  - role: java_runtime
    vars:
      java_version: 21
  - role: nginx
    vars:
      nginx_vhosts:
        - name: myapp
          server_name: "app.example.com"
          proxy_pass: "http://127.0.0.1:8080"
```

**Управление зависимостями в `requirements.yml`:**
```yaml
# requirements.yml
---
roles:
  - name: geerlingguy.docker
    version: ">=8.0.0"
  - name: geerlingguy.nginx
    version: ">=3.3.0"
  - name: geerlingguy.postgresql
    version: ">=4.1.0"

collections:
  - name: community.general
    version: ">=8.0.0"
  - name: community.postgresql
  - name: ansible.posix
```

**Установка зависимостей:**
```bash
# Установка ролей
ansible-galaxy role install -r requirements.yml

# Установка коллекций
ansible-galaxy collection install -r requirements.yml

# Установка в конкретный каталог
ansible-galaxy role install -r requirements.yml -p ./roles/
```

### Сценарий 4: Доступ к приватным ролям через Git

```yaml
# requirements.yml — приватные роли через Git
---
roles:
  # Публичная роль из Galaxy
  - name: geerlingguy.nginx
    version: ">=3.3.0"

  # Приватная роль из Git ( SSH )
  - name: internal_common
    src: git@github.com:myorg/ansible-roles.git
    scm: git
    version: main
    path: roles/

  # Приватная роль из Git ( HTTPS с токеном )
  - name: internal_security
    src: "https://{{ github_token }}@github.com/myorg/ansible-security.git"
    scm: git
    version: "v2.1.0"
    path: roles/
```

### Сценарий 5: Работа с секретами в ролях (Ansible Vault)

```bash
# Шифрование секретных переменных роли
ansible-vault encrypt roles/myapp/defaults/vault.yml

# Запуск плейбука с паролем Vault
ansible-playbook site.yml --ask-vault-pass

# Использование файла с паролем
ansible-playbook site.yml --vault-password-file ~/.vault_pass

# Шифрование отдельной строки
ansible-vault encrypt_string 'SuperSecretPassword' --name 'db_password'
```

**Структура роли с секретами:**
```
roles/myapp/
├── defaults/
│   ├── main.yml          # Общие переменные
│   └── vault.yml         # Зашифрованные секреты (не коммитить!)
├── vars/
│   ├── main.yml          # Внутренние переменные
│   └── vault.yml         # Зашифрованные константы
├── tasks/
│   └── main.yml
└── meta/
    └── main.yml
```

**`.gitignore` для безопасности:**
```
# Не коммитить зашифрованные файлы (опционально)
# roles/*/defaults/vault.yml
# roles/*/vars/vault.yml
```

### Сценарий 6: Сборка коллекции

```bash
# 1. Создание структуры коллекции
ansible-galaxy collection init myorg.my_collection

# 2. Структура коллекции
myorg/my_collection/
├── galaxy.yml           # Метаданные коллекции
├── README.md
├── plugins/
│   ├── modules/         # Собственные модули
│   ├── filter/          # Фильтры Jinja2
│   ├── lookup/          # Lookup-плагины
│   └── module_utils/    # Общий Python-код
├── roles/
│   ├── role1/
│   └── role2/
├── docs/
│   └── readme.rst
└── tests/
    └── integration/

# 3. Сборка tar.gz-архива
ansible-galaxy collection build myorg/my_collection/

# 4. Публикация в Galaxy
ansible-galaxy collection publish myorg-my_collection-1.0.0.tar.gz --api-key $GALAXY_API_KEY
```

### Сценарий 7: Тестирование роли с Molecule

```bash
# 1. Инициализация Molecule в существующей роли
cd roles/nginx
molecule init scenario --driver-name docker

# 2. Структура molecule/
roles/nginx/molecule/
├── default/
│   ├── converge.yml     # Тестовый плейбук
│   ├── molecule.yml     # Конфигурация Molecule
│   ├── prepare.yml      # Предусловия
│   └── verify.yml       # Проверки
└── shared/
    └── Dockerfile.j2

# 3. Запуск тестов
molecule test           # Полный цикл (create → converge → verify → destroy)
molecule create         # Только создание окружения
molecule converge       # Только запуск плейбука
molecule verify         # Только проверка
molecule login          # Вход в контейнер для отладки
molecule destroy        # Удаление окружения
```

**Пример `molecule/default/molecule.yml`:**
```yaml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: ubuntu-2204
    image: ubuntu:22.04
    pre_build_image: true
    privileged: true
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
    cgroupns_mode: host
    command: /lib/systemd/systemd
  - name: debian-bookworm
    image: debian:bookworm
    pre_build_image: true
provisioner:
  name: ansible
  inventory:
    host_vars:
      ubuntu-2204:
        ansible_python_interpreter: /usr/bin/python3
verifier:
  name: ansible
```

**Пример `molecule/default/converge.yml`:**
```yaml
---
- name: Converge
  hosts: all
  become: true
  roles:
    - role: nginx
```

**Пример `molecule/default/verify.yml`:**
```yaml
---
- name: Verify
  hosts: all
  gather_facts: false
  tasks:
    - name: Проверка что Nginx установлен
      ansible.builtin.command: nginx -v
      register: nginx_version
      changed_when: false

    - name: Убедиться что Nginx запущен
      ansible.builtin.service_facts:
    - name: Убедиться что Nginx запущен
      ansible.builtin.assert:
        that:
          - "'nginx.service' in ansible_facts.services"
          - "ansible_facts.services['nginx.service'].state == 'running'"

    - name: Проверка порта 80
      ansible.builtin.wait_for:
        port: 80
        timeout: 5
```

---

## Управление через Ansible Galaxy

### Основные команды

```bash
# === Роли ===
ansible-galaxy role search nginx           # Поиск ролей
ansible-galaxy role info geerlingguy.nginx  # Информация о роли
ansible-galaxy role install geerlingguy.nginx  # Установка роли
ansible-galaxy role install -r requirements.yml  # Установка из файла
ansible-galaxy role list                    # Список установленных ролей
ansible-galaxy role remove geerlingguy.nginx  # Удаление роли

# === Коллекции ===
ansible-galaxy collection search community   # Поиск коллекций
ansible-galaxy collection install community.general  # Установка
ansible-galaxy collection list               # Список коллекций
ansible-galaxy collection verify community.general  # Проверка подписи
ansible-galaxy collection upgrade            # Обновление всех коллекций
```

### Конфигурация путей поиска (`ansible.cfg`)

```ini
[defaults]
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
collections_paths = ./collections:~/.ansible/collections:/usr/share/ansible/collections

[galaxy]
server_url = https://galaxy.ansible.com
```

### Использование коллекций в плейбуках

```yaml
---
- name: Пример использования коллекций
  hosts: all
  become: true
  tasks:
    # FQCN (обязательный стандарт)
    - name: Создание пользователя
      ansible.builtin.user:
        name: deploy
        state: present

    # Модуль из коллекции community.general
    - name: Установка пакета через snap
      community.general.snap:
        name: firefox
        state: present

    # Модуль из коллекции community.docker
    - name: Запуск контейнера
      community.docker.docker_container:
        name: myapp
        image: nginx:alpine
        state: started
        ports:
          - "8080:80"

    # Модуль из коллекции ansible.posix
    - name: Монтирование NFS
      ansible.posix.mount:
        src: "nfs-server:/exports/data"
        path: /mnt/data
        fstype: nfs
        state: mounted
```

---

## Стратегии проектирования

### Основные стратегии

| Стратегия | Описание | Когда использовать |
| :--- | :--- | :--- |
| **По компонентам** | Одна роль = один сервис | Большинство проектов (рекомендуется) |
| **По слоям** | Базовый ОС → Runtime → Приложение | Enterprise-стандарты |
| **Utility Role** | Библиотека утилитарных ролей | Масштабируемые проекты |
| **Composite Role** | Агрегация нескольких ролей | Сложные профили серверов |
| **Micro-roles** | Атомарные функции | Максимальная гибкость |

> Подробное описание каждой стратегии — в [Стратегии проектирования](./Roles/strategies.md).

### Паттерн "Utility Role" (Служебная роль)

Специализированная роль-библиотека, не назначаемая хостам напрямую. Инкапсулирует общие компоненты для других ролей.

```yaml
# Структура utility-роли
roles/lib_common/
├── tasks/main.yml
├── handlers/main.yml
├── defaults/main.yml
├── meta/
│   └── argument_specs.yml
└── README.md

# Использование в основной роли
# roles/app/tasks/main.yml
---
- name: Импорт общих задач
  ansible.builtin.include_role:
    name: lib_common
    tasks_from: validate_env

- name: Основная логика приложения
  ansible.builtin.include_tasks: deploy.yml
```

> Подробнее — в [Utility Role Pattern](./Roles/utility_role_pattern.md).

---

---

## Лучшие практики

### Код и архитектура

1. **FQCN всегда:** Используйте полные имена модулей (`ansible.builtin.apt`, `community.docker.docker_container`).
2. **Идемпотентность:** Каждая задача должна быть безопасна для повторного запуска. Используйте `changed_when` и `failed_when` для точного контроля.
3. **Разделение `defaults` и `vars`:** Храните переопределяемые переменные в `defaults`, константы — в `vars`.
4. **Теги:** Используйте теги для разделения задач (install, configure, deploy, test).
5. **Минимализм:** Одна роль — один ответственный компонент. Не объединяйте логику.

### Тестирование и качество

6. **Тестирование:** Каждая роль должна иметь Molecule-тесты перед попаданием в production. Минимум — `syntax` + `verify`.
7. **Линтинг:** Запускайте `ansible-lint` перед каждым коммитом. В CI/CD используйте профиль `production`.
8. **Семантическое версионирование:** Используйте Git-теги для версионирования ролей (`v1.0.0`, `v1.1.0`, `v2.0.0`).
9. **Pre-commit hooks:** Используйте `.pre-commit-config.yaml` с `ansible-lint`, `yamllint`, `flake8` для автоматической проверки перед коммитом.

### Безопасность и аудит

10. **Секреты:** Не храните секреты в `defaults/main.yml`. Используйте Ansible Vault с внешним бэкендом (HashiCorp Vault, системный keyring).
11. **Документация:** Заполняйте `README.md` и `meta/main.yml` для каждой роли. Используйте `argument_specs.yml` для автогенерации документации.
12. **Гранулярный доступ:** Запускайте роли от непривилегированного пользователя. Используйте `become` только где необходимо.
13. **Аудит изменений:** Используйте `--verify-commit` и GPG-подпись коммитов для отслеживания изменений в коде инфраструктуры.
14. **Сканирование зависимостей:** Регулярно проверяйте зависимости через `ansible-galaxy collection verify` и `ansible-lint`.

### Управление изменениями (Change Management)

15. **GitFlow / trunk-based:** Используйте отдельные ветки для изменений. Запрет прямых коммитов в `main`/`master`.
16. **Code Review:** Все изменения ролей проходят через Merge Request с обязательным аппрувом.
17. **Канареечное развертывание:** Развертывайте роли сначала на 1–2 тестовых узлах, затем на всю инфраструктуру.
18. **Rollback:** Каждая роль должна иметь возможность быстрого отката (Git revert + `ansible-pull` или повторный запуск с предыдущей версией).
19. **Change Management процедура:** Изменения в production-ролях требуют тикета/задачи, окна обслуживания и согласования.
20. **Conventional Commits:** Используйте стандарт `feat(role):`, `fix(role):`, `chore(role):` для семантического коммитинга.

### Наблюдаемость и эксплуатация

21. **Логирование:** Включайте `log_path` в `ansible.cfg`. Используйте callback-плагины для структурированного вывода (`yaml`, `json`).
22. **Мониторинг:** Добавляйте задачи проверки работоспособности сервисов (`uri`, `wait_for`, `service_facts`) после применения роли.
23. **Обработчики:** Используйте `listen` для общих обработчиков. Убедитесь, что обработчики срабатывают только при изменении.
24. **Консистентность окружений:** Используйте `requirements.yml` с зафиксированными версиями. Проверяйте зависимости в CI/CD.
25. **Изоляция окружений:** Для тестирования используйте Molecule с драйверами Docker/Podman. Не тестируйте напрямую на production-хостах.

---

## GitOps и управление изменениями

### Принципы

GitOps для Ansible ролей подразумевает, что весь код инфраструктуры хранится в Git, а изменения развертываются через автоматизированные пайплайны.

*   **СoS (Convergence over Mutation):** Роли должны быть идемпотентными и converge к желаемому состоянию при каждом запуске.
*   **Версионирование:** Каждое изменение роли имеет Git-хеш/тег. В production попадает только проверенная версия.
*   **Аудит:** Все изменения отслеживаются в Git-истории. Используйте `git log --stat` для анализа.

### Бранчинг и защита

```bash
# Пример структуры веток
main/                    # Production-ready код (защищен)
├── develop/             # Интеграционная ветка
├── feature/nginx-v2/    # Feature-ветка для новой версии роли
├── release/v2.1.0/      # Релизная ветка
└── hotfix/critical-fix/  # Срочные исправления
```

**Настройка branch protection (GitHub/GitLab):**
*   `main` защищена: требуются Merge Request, апрувы, прохождение CI.
*   Прямые пушы запрещены.
*   Обязательно: `ansible-lint`, `molecule test`, `yaml-lint` в CI.

### Conventional Commits

```bash
feat(nginx): add support for HTTP/3
fix(nginx): correct worker_processes validation
chore(nginx): update Molecule driver to docker 26.x
docs(nginx): add TLS 1.3 configuration example
refactor(nginx): split vhost logic into separate task file
```

### CI/CD пайплайн (GitLab CI пример)

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - build
  - deploy

variables:
  ANSIBLE_ROLES_PATH: ./roles

lint:
  stage: lint
  image: python:3.14
  script:
    - pip install ansible-lint==26.8.0 yamllint flake8
    - ansible-lint roles/nginx/
    - yamllint roles/nginx/

molecule-test:
  stage: test
  image: python:3.14
  script:
    - pip install molecule[docker]==26.9.0 ansible-core==2.21
    - cd roles/nginx && molecule test

build-collection:
  stage: build
  script:
    - ansible-galaxy collection build
  artifacts:
    paths:
      - *.tar.gz

deploy-canary:
  stage: deploy
  environment:
    name: production
  when: manual
  script:
    - ansible-playbook -i inventory/production/hosts.yml playbooks/deploy.yml --tags canary

deploy-full:
  stage: deploy
  environment:
    name: production
  when: manual
  script:
    - ansible-playbook -i inventory/production/hosts.yml playbooks/deploy.yml
```

### Канареечное развертывание и откат

*   **Canary:** Сначала применяйте роль к 1–2 узлам (тег `canary` или отдельный inventory).
*   **Валидация:** Проверьте метрики, логи, работоспособность сервиса.
*   **Full rollout:** При успехе — применяйте ко всей инфраструктуре.
*   **Rollback:** `git revert <commit>` + повторный запуск плейбука или откат тега роли в `requirements.yml`.

---

## Безопасность и аудит

### Управление доступом

*   **Отдельный пользователь:** Запускайте `ansible-playbook` от непривилегированного пользователя с правами `sudo` только для необходимых команд через `/etc/sudoers.d/`.
*   **SSH-ключи:** Используйте ed25519-ключи с парольной фразой. Никогда не храните приватные ключи в Git.
*   **Deploy Keys:** Для доступа к Git-репозиториям используйте Deploy Keys с правами только на чтение (Read-Only).
*   **Ограничение `become`:** Включайте `become: true` только на уровне задач, требующих привилегий, а не на весь плейбук.
*   **Ротация ключей:** Периодически ротируйте SSH-ключи и пароли Vault. Используйте `password-store` или HashiCorp Vault для хранения.

### Аудит и соответствие

*   **GPG-подпись коммитов:** Все коммиты с изменениями ролей подписываются GPG. `git log --show-signature`.
*   **Верификация коммитов:** Используйте `--verify-commit` при установке ролей из Git.
*   **Аудит Vault:** Включите аудит в HashiCorp Vault для отслеживания доступа к секретам.
*   **Сканирование секретов:** Используйте `git secrets`, `truffleHog` или `gitleaks` для предотвращения попадания секретов в Git.
*   **Проверка подлинности:** `ansible-galaxy collection verify community.general` для проверки подписи коллекций.

### Сетевая изоляция

*   **Outbound-only:** Контрольные узлы должны иметь только исходящий доступ к Git-репозиторию, Ansible Galaxy и системам мониторинга.
*   **Внутренний Git-сервер:** Для production-инфраструктуры используйте внутренний Git-сервер (Gitea, GitLab) вместо публичных GitHub/GitLab.
*   **Segmentation:** Разделите сети управления (management plane) и рабочих нагрузок (data plane).

---

## Pre-commit hooks

Используйте pre-commit framework для автоматической проверки кода ролей перед коммитом.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/ansible/ansible-lint
    rev: v26.8.0
    hooks:
      - id: ansible-lint
        args: ['--profile', 'production']

  - repo: https://github.com/adrienverge/yamllint.git
    rev: v1.35.1
    hooks:
      - id: yamllint
        args: ['-d', '{extends: default, rules: {line-length: {max: 160}}}']

  - repo: https://github.com/pycqa/flake8
    rev: 7.1.1
    hooks:
      - id: flake8
        args: ['--max-line-length=160', '--exclude=.git,__pycache__,.venv']
```

```bash
# Установка pre-commit
pip install pre-commit
pre-commit install

# Ручной запуск для всех файлов
pre-commit run --all-files
```

---

## Поиск и устранение неисправностей

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
| `ERROR! galaxy_tag already registered` | Конфликт тегов Galaxy | Уникальные имена для `galaxy_tags` |
| `ERROR! argument_specs validation failed` | Неверный тип или отсутствует обязательный параметр | Проверьте `meta/argument_specs.yml` |

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

# Проверка подлинности коллекций
ansible-galaxy collection verify community.general

# Проверка целостности роли
ansible-galaxy role verify geerlingguy.nginx
```

---

## Дополнительная информация

### Связанные файлы

*   **[Структура роли](./Roles/structure.md)** — детальный разбор каталогов, включая `argument_specs`.
*   **[Управление выполнением и отладка ролей](./Roles/task-execution-and-debugging.md)** — `run_once`, `delegate_facts`, уровни директив, `debugger`, `check_mode`/`diff`.
*   **[Работа с Ansible Galaxy](./Roles/galaxy.md)** — управление зависимостями через `requirements.yml`.
*   **[Стратегии проектирования](./Roles/strategies.md)** — паттерны «Служебная роль», «Композитная роль» и методы декомпозиции.
*   **[Использование ролей](./Roles/usage.md)** — технические нюансы `import_role` vs `include_role`.
*   **[Utility Role Pattern](./Roles/utility_role_pattern.md)** — паттерн служебных ролей-библиотек.
*   **[Управление версиями через Git](./Roles/git_management.md)** — CI/CD, кеширование, безопасность.
*   **[Тестирование с Molecule](./ansible_testing_with_molecule.md)** — автоматизация проверки качества кода ролей.
*   **[Execution Environments](./ansible-execution-environments.md)** — контейнеризация для воспроизводимости.
*   **[Cross-platform концепции](./CrossPlatform/concepts.md)** — кроссплатформенные роли (Linux/Windows).
*   **[Модели Push vs Pull](../Concepts/configuration_management_push_vs_pull.md)** — архитектурные паттерны.

### См. также

*   **[Ansible Core Concepts](./ansible_core_concepts.md)** — архитектура, идемпотентность, FQCN.
*   **[Ansible Vault и шифрование](./Vault/basics.md)** — управление секретами.
*   **[Ansible Semaphore](./ansible_semaphore.md)** — веб-интерфейс и запуск плейбуков.
*   **[Ansible Lint Guide](./ansible_lint_guide.md)** — статический анализ кода.
*   **[Ansible Collections Deep Dive](./ansible_collections_deep_dive.md)** — углубленное изучение коллекций.

---
