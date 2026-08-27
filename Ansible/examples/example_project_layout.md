# Типовая структура проекта в Ansible

## Определения

**Структура проекта Ansible** — логическая организация файлов и каталогов, обеспечивающая масштабируемость, переиспользование кода, изоляцию секретов и удобную командную разработку.

**Иерархия переменных** — порядок, в котором Ansible ищет значения переменных. Правильная структура каталогов (`group_vars`, `host_vars`) позволяет эффективно управлять настройками для разных окружений (Staging, Production) и предотвращать конфликты имен.

**Контрольный узел (Control Node)** — машина, на которой хранится код проекта, установлены зависимости (Ansible, Python-библиотеки) и запускаются команды управления инфраструктурой.

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 10.x | `ansible --version` |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| ansible-lint | 24.x+ | ≥ 24.7 | `ansible-lint --version` |
| yamllint | 1.35+ | ≥ 1.35 | `yamllint --version` |
| Git | 2.30+ | ≥ 2.40 | `git --version` |
| Целевые ОС | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 | `lsb_release -a` |

### Необходимые коллекции

```bash
# Основные коллекции (если используются в ролях/плейбуках)
ansible.builtin
ansible.posix
community.general
community.mysql  # если работаете с MySQL/MariaDB
community.docker  # если работаете с Docker

# Установка всех необходимых коллекций
ansible-galaxy collection install -r requirements.yml
# → Starting galaxy collection install process
# → Process install dependency map
```

### Сетевая доступность

- SSH-доступ к управляемым хостам (порт 22 по умолчанию).
- Параметр `become: true` для выполнения задач с привилегиями root.
- Доступ к интернету для загрузки пакетов и репозиториев.

---

## Базовые концепции

### Ключевые компоненты проекта

| Компонент | Назначение | Ссылка на основной раздел |
|---|---|---|
| `ansible.cfg` | Конфигурация проекта (пути к ролям, настройки SSH, плагины). | [Настройка Ansible](../ansible_setup_and_config.md) |
| `inventory/` или `environments/` | Список хостов и групп (статический или динамический) с разделением по средам. | [Управление инвентарем](../ansible_setup_and_config.md) |
| `group_vars/` | Переменные для групп хостов (например, `all.yml`). | [Переменные](../PlaybookStructure/variables.md) |
| `host_vars/` | Индивидуальные параметры конкретных серверов (использовать с осторожностью). | [Переменные](../PlaybookStructure/variables.md) |
| `roles/` | Каталог для локальных ролей проекта. | [Роли в Ansible](../ansible_roles.md) |
| `collections/` | Директория для внешних коллекций, установленных локально. | [Управление коллекциями](../Roles/galaxy.md) |
| `playbooks/` | Точки входа (сценарии автоматизации). | [Основы плейбуков](../PlaybookStructure/basics.md) |
| `library/` | Пользовательские модули на Python для специфичных задач. | [Собственные модули](../ansible_custom_modules.md) |
| `filter_plugins/` | Собственные Jinja2-фильтры для сложной обработки данных. | — |
| `module_utils/` | Вспомогательные Python-библиотеки для пользовательских модулей. | — |
| `requirements.yml` | Список внешних зависимостей (ролей и коллекций) для загрузки через `ansible-galaxy`. | [Ansible Galaxy](../Roles/galaxy.md) |

**Безопасность:** Секреты (пароли, SSH ключи, токены) должны храниться в зашифрованном виде. Рекомендуется использовать файлы с суффиксом `.vault.yml` или `vault_` префиксом и инструмент **[Ansible Vault](../Vault/basics.md)**.

### Порядок приоритетов поиска ресурсов

```
ansible.cfg [defaults]
    ↓
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
    ↓
collections_path = ./collections:~/.ansible/collections:/usr/share/ansible/collections
    ↓
Плагины: ./library → ./filter_plugins → встроенные модули
```

### Разделение ответственности

| Файл/Директория | Ответственность | Не应当 содержать |
|---|---|---|
| `inventory/` | Адреса хостов, группы, SSH-параметры | Пароли, переменные окружения |
| `group_vars/` | Конфигурация сервисов для групп | Адреса серверов, SSH ключи |
| `host_vars/` | Уникальные настройки конкретного хоста | Общие параметры для группы |
| `roles/` | Бизнес-логика, переиспользуемый код | Секреты, специфичные для среды |
| `playbooks/` | Точки входа, оркестрация | Детали реализации (выносятся в роли) |
| `vars/vault.yml` | Зашифрованные секреты | Открытые пароли |

---

## Практические сценарии

### Сценарий 1: Базовая структура проекта (PoC / Небольшие проекты)

Для небольших проектов или индивидуальной работы достаточно простой структуры, где инвентарь и переменные лежат в корне проекта.

```text
my-ansible-project/
├── ansible.cfg              # Локальная конфигурация
├── inventory.ini            # Плоский список хостов
├── group_vars/
│   └── all.yml              # Общие переменные для всех хостов
├── host_vars/
│   └── web1.yml             # Специфичные переменные для web1
├── roles/
│   └── nginx/               # Локальная роль
├── requirements.yml         # Зависимости из Galaxy
└── site.yml                 # Главный плейбук
```

**Пример `inventory.ini`:**
```ini
[web_servers]
web1 ansible_host=10.0.5.20 ansible_user=deploy
web2 ansible_host=10.0.5.21 ansible_user=deploy

[db_servers]
db1 ansible_host=10.0.5.30 ansible_user=deploy

[all:vars]
ansible_python_interpreter=/usr/bin/python3
ansible_become=true
ansible_become_method=sudo
```

**Пример `site.yml`:**
```yaml
---
- name: Настройка веб-серверов
  hosts: web_servers
  become: true
  roles:
    - nginx

- name: Настройка серверов БД
  hosts: db_servers
  become: true
  roles:
    - mysql
```

**Валидация:**
```bash
# Проверка синтаксиса плейбука
ansible-playbook site.yml --syntax-check
# → playbook: site.yml

# Dry Run без изменений
ansible-playbook site.yml --check --diff

# Запуск с выводом отладки
ansible-playbook site.yml -vvv

# Проверка доступности хостов
ansible all -m ping -i inventory.ini
# → web1 | SUCCESS => { "ping": "pong" }
# → web2 | SUCCESS => { "ping": "pong" }
# → db1 | SUCCESS => { "ping": "pong" }

# Сбор информации о хостах
ansible web_servers -m setup -i inventory.ini -a "filter=ansible_distribution"
# → web1 | SUCCESS => { "ansible_facts": { "ansible_distribution": "Ubuntu" } }
```

### Сценарий 2: Расширенная структура (Enterprise / Мульти-окружение)

В реальных Enterprise-проектах требуется строгое разделение между средами разработки (Stage/Dev) и эксплуатации (Prod). Для этого используется каталог `environments/` или вложенная структура `inventory/`.

```text
enterprise-ansible-project/
├── ansible.cfg              # Глобальные настройки проекта
├── requirements.yml         # Внешние зависимости (Galaxy)
├── .ansible-lint            # Конфигурация линтера Ansible
├── .yamllint                # Конфигурация линтера YAML
├── .gitignore               # Игнорируемые файлы Git
├── environments/            # Разделение по средам
│   ├── prod/                # Среда Production
│   │   ├── hosts.yml        # Инвентарь Production (статический/динамический)
│   │   ├── group_vars/      # Переменные групп Prod
│   │   │   ├── all.yml      # Базовые переменные
│   │   │   └── vault.yml    # Зашифрованные секреты Prod
│   │   └── host_vars/
│   └── stage/               # Среда Staging
│       ├── hosts.yml
│       ├── group_vars/
│       └── host_vars/
├── library/                 # Собственные модули проекта
├── filter_plugins/          # Пользовательские фильтры Jinja2
├── module_utils/            # Вспомогательные Python-библиотеки
├── scripts/                 # Вспомогательные скрипты (например, для Vault)
├── collections/             # Локально загруженные коллекции
├── roles/                   # Локальные роли проекта (бизнес-логика)
│   └── common/              # См. подробности в ../Roles/structure.md
└── playbooks/               # Каталог со сценариями (Entry points)
    ├── site.yml             # Главный оркеструющий плейбук
    ├── deploy_app.yml       # Сценарий деплоя приложения
    └── provision.yml        # Сценарий подготовки ОС
```

**Пример инвентаря `environments/prod/hosts.yml`:**
```yaml
---
all:
  children:
    web_servers:
      hosts:
        web1:
          ansible_host: 10.0.5.20
          nginx_worker_processes: 4
        web2:
          ansible_host: 10.0.5.21
          nginx_worker_processes: 4
    db_servers:
      hosts:
        db1:
          ansible_host: 10.0.5.30
          mariadb_innodb_buffer_pool_size: 2G
    load_balancers:
      hosts:
        lb1:
          ansible_host: 10.0.5.10
  vars:
    ansible_python_interpreter: /usr/bin/python3
    ansible_become: true
    ansible_become_method: sudo
```

**Пример `environments/stage/hosts.yml`:**
```yaml
---
all:
  children:
    web_servers:
      hosts:
        web1:
          ansible_host: 192.168.5.20
          nginx_worker_processes: 2
    db_servers:
      hosts:
        db1:
          ansible_host: 192.168.5.30
          mariadb_innodb_buffer_pool_size: 512M
  vars:
    ansible_python_interpreter: /usr/bin/python3
    ansible_become: true
    ansible_become_method: sudo
```

#### Настройка `ansible.cfg`

Для правильной работы расширенной структуры необходимо адаптировать файл настроек, указав пути поиска ресурсов.

```ini
[defaults]
# Инвентарь по умолчанию (указываем stage для безопасности)
inventory = ./environments/stage/hosts.yml
# Пути поиска ролей (сначала локальные, затем системные)
roles_path = ./roles:~/.ansible/roles:/usr/share/ansible/roles
# Путь поиска коллекций
collections_path = ./collections
# Собственные плагины и модули
library = ./library
filter_plugins = ./filter_plugins
# Отключение проверки SSH-ключей (опционально, для динамических сред)
host_key_checking = False
# Красивый вывод в терминале (YAML формат)
stdout_callback = yaml
# Дополнительные callback-плагины для профилирования
callbacks_enabled = timer, profile_tasks
# Игнорирование удаления Vault-пароля при завершении (для CI/CD)
#vault_password_file = .vault_pass

[privilege_escalation]
become = True
become_method = sudo
become_ask_pass = False

[ssh_connection]
# Ускорение SSH-соединений
pipelining = True
# Контроль SSH-ключей (отключить в dev, включить в prod)
#control_path_dir = /tmp/.ansible-cp
```

#### Главный плейбук (`playbooks/site.yml`)

Главный файл выступает в роли оркестратора. Вместо того, чтобы писать все задачи в одном файле, он вызывает другие плейбуки с помощью директивы `import_playbook`.

```yaml
---
# Вызов плейбука для настройки базовой ОС
- name: Подготовка базовой инфраструктуры
  ansible.builtin.import_playbook: provision.yml

# Вызов плейбука развертывания приложения
- name: Деплой целевого приложения
  ansible.builtin.import_playbook: deploy_app.yml
```

#### Пример плейбука подготовки (`playbooks/provision.yml`)

```yaml
---
- name: Подготовка базовой ОС
  hosts: web_servers
  become: true
  tasks:
    - name: Обновление кэша apt
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 3600

    - name: Установка базовых пакетов
      ansible.builtin.apt:
        name:
          - curl
          - wget
          - git
          - htop
          - ufw
        state: present

    - name: Настройка UFW
      community.general.ufw:
        rule: allow
        name: "{{ item }}"
      loop:
        - OpenSSH
        - 'Nginx Full'
      notify: Reload UFW

    - name: Включение UFW
      community.general.ufw:
        state: enabled

  handlers:
    - name: Reload UFW
      community.general.ufw:
        state: reloaded
```

#### Пример плейбука деплоя (`playbooks/deploy_app.yml`)

```yaml
---
- name: Деплой приложения
  hosts: web_servers
  become: true
  vars_files:
    - "../environments/{{ ansible_env }}/group_vars/vault.yml"
  tasks:
    - name: Клонирование репозитория
      ansible.builtin.git:
        repo: "https://github.com/org/app.git"
        dest: "/var/www/app"
        version: main

    - name: Установка зависимостей
      ansible.builtin.command: pip install -r requirements.txt
      args:
        chdir: /var/www/app
      register: pip_result
      changed_when: "'Successfully installed' in pip_result.stdout"

    - name: Перезапуск приложения
      ansible.builtin.service:
        name: app
        state: restarted
      when: pip_result.changed
```

#### Запуск с указанием окружения

Для запуска задач в конкретной среде необходимо явно передать путь к файлу инвентаря.

```bash
# Проверка синтаксиса перед запуском
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml --syntax-check
# → playbook: playbooks/site.yml

# Dry Run (проверка без изменений)
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml --check --diff

# Запуск на Stage
ansible-playbook playbooks/site.yml -i environments/stage/hosts.yml

# Запуск на Prod с запросом пароля от Vault
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml --ask-vault-pass

# Использование тегов для частичного запуска
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml --tags "nginx,db"

# Запуск на конкретном хосте
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml --limit web1

# Запуск с отладкой (verbose)
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml -vvv

# Просмотр списка хостов в инвентаре
ansible-inventory -i environments/prod/hosts.yml --list

# Визуализация дерева инвентаря
ansible-inventory -i environments/prod/hosts.yml --graph

# Проверка идемпотентности (второй запуск должен показать 0 changed)
ansible-playbook playbooks/site.yml -i environments/prod/hosts.yml 2>&1 | grep "changed"
# → localhost                  : ok=XX   changed=0    unreachable=0    failed=0
```

### Сценарий 3: Минимальный `.gitignore` для проекта

Для исключения секретов и артефактов из Git-репозитория:

```gitignore
# Секреты (никогда не коммитить в открытом виде)
*.vault.yml
.vault_pass
*.pem
*.key

# Python
__pycache__/
*.pyc
.venv/
venv/

# Артефакты Ansible
*.retry
*.log

# Редакторы
.vscode/
.idea/
*.swp
*.swo

# Системные файлы
.DS_Store
Thumbs.db
```

---

## Чек-лист валидации после создания проекта

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Синтаксис плейбука | `ansible-playbook site.yml --syntax-check` | `playbook: site.yml` |
| Dry Run | `ansible-playbook site.yml --check --diff` | Нет ошибок |
| Доступность хостов | `ansible all -m ping` | `SUCCESS => { "ping": "pong" }` |
| Инвентарь | `ansible-inventory --list` | JSON со списком хостов |
| Инвентарь (граф) | `ansible-inventory --graph` | Дерево групп |
| Роли найдены | `ansible-playbook site.yml --list-tasks` | Список задач |
| Синтаксис YAML | `yamllint .` | Нет ошибок |
| Ansible Lint | `ansible-lint` | Нет ошибок |
| Vault работает | `ansible-vault encrypt test.yml && ansible-vault decrypt test.yml` | Файл зашифрован/расшифрован |
| Коллекции установлены | `ansible-galaxy collection list` | Список коллекций |

---

## Устранение типичных неполадок

### Проблема: Роль не найдена при вызове

**Симптом:** `ERROR! the role 'nginx' was not found`.

**Решение:**
```bash
# Проверка путей поиска
ansible-config dump | grep roles_path
# → DEFAULT_ROLES_PATH(default) = ['/home/user/ansible/roles', ...]

# Проверка установленных ролей
ansible-galaxy role list

# Установка роли
ansible-galaxy role install geerlingguy.nginx

# Проверка структуры роли
ls -la roles/nginx/
# → defaults/ handlers/ tasks/ templates/ meta/ files/
```

### Проблема: Конфликт переменных из разных источников

**Симптом:** Переменная берется не из того файла `group_vars`.

**Решение:**
```bash
# Просмотр всех переменных для хоста
ansible web1 -m debug -a "var=hostvars['web1']" -i inventory.ini

# Просмотр конкретной переменной
ansible web1 -m debug -a "var=nginx_port" -i inventory.ini

# Проверка приоритетов
ansible web1 -m debug -a "var=ansible_distribution" -i inventory.ini
```

### Проблема: Vault не расшифровывает переменные

**Симпptom:** `ERROR! A Vault password is required`.

**Решение:**
```bash
# Проверка зашифрованного файла
ansible-vault view vars/vault.yml --ask-vault-pass

# Расшифровка для проверки
ansible-vault decrypt vars/vault.yml --ask-vault-pass

# Шифрование обратно
ansible-vault encrypt vars/vault.yml --ask-vault-pass

# Использование vault password file
ansible-playbook site.yml --vault-password-file .vault_pass
```

### Проблема: SSH не подключается к хостам

**Симптом:** `UNREACHABLE! => {"msg": "Failed to connect to the host via ssh"}`.

**Решение:**
```bash
# Проверка SSH вручную
ssh deploy@10.0.5.20

# Проверка SSH-ключа
ansible all -m ping -i inventory.ini -vvv

# Проверка параметров подключения
ansible all -m setup -i inventory.ini -a "filter=ansible_distribution" -vvv

# Отключение проверки ключей (только для dev)
ansible all -m ping -i inventory.ini -e "ansible_host_key_checking=False"
```

### Проблема: Задачи выполняются дважды

**Симптом:** Один и тот же task выполняется при каждом запуске.

**Решение:**
```bash
# Проверка идемпотентности задачи
ansible-playbook site.yml --check --diff

# Использование регистров для условий
# В плейбуке:
# - name: Установка пакета
#   apt:
#     name: nginx
#     state: present
#   register: nginx_install
#   changed_when: "'installed' in nginx_install.stdout"

# Проверка через отладку
ansible-playbook site.yml -vvv | grep "changed="
```

### Проблема: Обработчик не выполняется

**Симптом:** `notify: Reload Nginx` не срабатывает при изменении конфигурации.

**Решение:**
```bash
# Проверка, что notify привязан к задаче
# В плейбуке:
# - name: Копирование конфигурации
#   template:
#     src: nginx.conf.j2
#     dest: /etc/nginx/nginx.conf
#   notify: Reload Nginx   # ← Должно быть на одном уровне с задачей

# Проверка обработчиков
ansible-playbook site.yml --list-handlers

# Принудительный запуск обработчиков
ansible-playbook site.yml --handlers-first
```

---

## Дополнительная информация

### Иерархия переменных: Playbook-relative vs Inventory-relative

Ansible ищет каталоги `group_vars` и `host_vars` в двух основных местах:
1.  **Playbook-relative**: Рядом с файлом плейбука. Эти переменные применяются ко всем запускам этого плейбука.
2.  **Inventory-relative**: Рядом с файлом инвентаря (как показано в Сценарии 2). Это позволяет изолировать настройки `prod` от `stage`.

**Рекомендация:** Используйте инвентарно-зависимые переменные (`environments/prod/group_vars/`) для параметров, специфичных для среды (IP-адреса, ключи доступа).

### Динамическое масштабирование и плагины

При работе с облачными провайдерами (AWS, Yandex Cloud, GCP) статические файлы `hosts.yml` заменяются или дополняются конфигурациями плагинов динамического инвентаря (например, `yandex_cloud_compute.yml`). Рекомендуется хранить такие конфигурации также внутри директории соответствующего окружения. Подробнее: **[Динамический инвентарь](../dynamic_inventory.md)**.

### Интеграция с CI/CD и стандарты качества

В Enterprise-проектах рекомендуется:
- Хранить секреты не только в Vault, но и использовать внешние менеджеры (HashiCorp Vault, AWS Secrets Manager).
- Использовать **ansible-lint** для соблюдения стандартов кодирования.
- Автоматизировать запуск через пайплайны (GitLab CI, GitHub Actions), передавая пароли Vault через переменные окружения. Подробнее см. **[Безопасный CI/CD пайплайн](example_real_world_ci_cd.md)**.

### Именование и нумерация

- **Плейбуки:** Использование префиксов `01_`, `02_` в `playbooks/` помогает визуализировать порядок развертывания.
- **Переменные:** Всегда используйте префиксы ролей (например, `nginx_port`), чтобы избежать конфликтов при слиянии переменных из разных источников.

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Несколько `ansible.cfg` | Конфликт настроек | Ansible использует ближайший `ansible.cfg` к плейбуку; не создавайте дубли |
| Симлинки в `roles/` | Поиск ресурсов ломается | Используйте `roles_path` в `ansible.cfg` вместо симлинков |
| Windows-контрольный узел | Некоторые модули не работают | Используйте WSL2 или Linux-контрольный узел |
| Параллельный запуск | Файловые конфликты | Используйте `serial` в плейбуке или `forks` в `ansible.cfg` |
| Большие инвентари | Медленная загрузка | Используйте динамический инвентарь или `yaml` вместо `ini` формата |
| Vault и CI/CD | Пароль Vault недоступен | Передавайте через `ANSIBLE_VAULT_PASSWORD_FILE` env var |

---

## Смотрите также

- [Структура роли (tasks, templates, handlers)](../Roles/structure.md)
- [Установка и базовая настройка Ansible](../ansible_setup_and_config.md)
- [Работа с Ansible Galaxy (роли и коллекции)](../Roles/galaxy.md)
- [Антипаттерны Ansible](../ansible_bad_practices.md)
