# Типовая структура проекта в Ansible

## Определения

**Структура проекта Ansible** — логическая организация файлов и каталогов, обеспечивающая масштабируемость, переиспользование кода, изоляцию секретов и удобную командную разработку для команд DevOps/SRE.

**Иерархия переменных** — порядок, в котором Ansible ищет значения переменных. Правильная структура каталогов (`group_vars`, `host_vars`) позволяет эффективно управлять настройками для разных окружений (Staging, Production) и предотвращать конфликты имен.

**Control Node** — машина, на которой хранится код проекта, установлены зависимости (Ansible, Python-библиотеки) и запускаются команды управления инфраструктурой. Требует Unix-подобную ОС: Linux, macOS или WSL2.

**Managed Node** — целевой хост, на который Ansible подключается по SSH и применяет конфигурацию. Может быть физическим сервером, виртуальной машиной или контейнером.

**Ansible Vault** — механизм шифрования чувствительных данных (пароли, ключи, токены) в репозитории. Файлы `vault.yml` расшифровываются в памяти во время выполнения плейбука.

## Предварительные требования

| Компонент | Минимальная версия | Рекомендуемая | Проверка |
|---|---|---|---|
| Ansible Core | 2.15+ | ≥ 2.20 | `ansible --version` |
| Python (управление) | 3.10+ | ≥ 3.12 | `python3 --version` |
| Python (целевые хосты) | 3.10+ | ≥ 3.12 | `ansible all -m setup -a "filter=ansible_python_version"` |
| ansible-lint | 26.x+ | ≥ 26.8.0 | `ansible-lint --version` |
| yamllint | 1.35+ | ≥ 1.35 | `yamllint --version` |
| Git | 2.30+ | ≥ 2.40 | `git --version` |
| Целевые ОС | Ubuntu 22.04+ / Debian 12+ / RHEL 9+ | Ubuntu 24.04 / RHEL 9 | `lsb_release -a` или `cat /etc/os-release` |

### Необходимые коллекции

```bash
# Основные коллекции
ansible.builtin
ansible.posix
community.general

# Специализированные коллекции (опционально)
ansible.mysql    # для работы с MySQL/MariaDB
community.crypto # для управления сертификатами

# Установка всех зависимостей
ansible-galaxy collection install -r requirements.yml
# → Starting galaxy collection install process
# → Process install dependency map
```

### Сетевая доступность

- SSH-доступ к управляемым хостам (порт 22 по умолчанию).
- Параметр `become: true` для выполнения задач с привилегиями root.
- Доступ к интернету для загрузки пакетов и репозиториев.
- Разрешение исходящих подключений на порт 443 для Galaxy/HTTPS-репозиториев.

---

## Базовые концепции

### Принципы организации проекта

Правильная структура проекта решает три ключевые задачи для DevOps/SRE:
1. **Масштабируемость** — возможность добавления новых сервисов без переписывания всего кода.
2. **Безопасность** — изоляция секретов от кода, минимальные привилегии, аудит изменений.
3. **Воспроизводимость** — идентичные результаты на разных окружениях (Dev/Stage/Prod).

### Жизненный цикл проекта Ansible

```
Создание → Разработка → Тестирование → Code Review → Merge → Deploy → Валидация
   ↑         ↑            ↑            ↑           ↑        ↑         ↑
 Git       Molecule     ansible-lint   PR/MR      CI/CD   Runbook   Мониторинг
```

### Компоненты проекта и их назначение

| Компонент | Назначение | Примечание для SRE |
|---|---|---|
| `ansible.cfg` | Глобальная конфигурация: пути, SSH, плагины | Должен быть в репозитории; секреты — через env vars |
| `inventory/` | Список хостов и групп | Разделение по средам minimizes blast radius |
| `group_vars/` | Переменные для групп хостов | Избегайте хранения секретов здесь |
| `host_vars/` | Индивидуальные параметры хостов | Используйте только для уникальных настроек |
| `roles/` | Локальные роли проекта | См. [Структура роли](../Roles/structure.md) |
| `playbooks/` | Entry points, оркестрация | Должны быть тонкими; логика — в ролях |
| `library/` | Пользовательские модули Python | Для специфичных задач без готовых модулей |
| `filter_plugins/` | Jinja2-фильтры | Для сложной трансформации данных |
| `requirements.yml` | Зависимости из Galaxy | Фиксируйте версии для воспроизводимости |

### Безопасность: изоляция секретов

Секреты (пароли, SSH ключи, токены) должны храниться в зашифрованном виде. Рекомендуется использовать файлы с суффиксом `.vault.yml` или префиксом `vault_` и инструмент **[Ansible Vault](../Vault/basics.md)**.

**Принципы:**
- Никогда не коммитьте секреты в открытом виде.
- Используйте `no_log: true` для задач с чувствительными данными.
- Права на vault-файлы: `chmod 600 vars/vault.yml`.
- Пароль Vault храните вне репозитория (файл `.vault_pass` с правами `600` или менеджер секретов).

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

| Файл/Директория | Ответственность | Не должна содержать |
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
│   └── common/              # См. подробности в [Структура роли](../Roles/structure.md)
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

### Сценарий 4: Управление обновлениями (Patch Management) в структуре проекта

В production-проектах важно разделить задачи обновления ОС и приложений. Рекомендуется вынести их в отдельные плейбуки и запускать через CI/CD с `serial` для zero-downtime обновления.

```yaml
---
# playbooks/patch_management.yml
- name: Обновление ОС (rolling)
  hosts: all
  serial: "25%"
  max_fail_percentage: 10
  any_errors_fatal: true
  become: true
  tasks:
    - name: Обновление кэша пакетов
      ansible.builtin.apt:
        update_cache: yes
        cache_valid_time: 3600
      when: ansible_os_family == "Debian"

    - name: Обновление пакетов
      ansible.builtin.apt:
        upgrade: dist
        autoremove: yes
        autoclean: yes
      register: apt_upgrade
      notify: Reboot if needed
      when: ansible_os_family == "Debian"

    - name: Проверка необходимости перезагрузки
      ansible.builtin.stat:
        path: /var/run/reboot-required
      register: reboot_required

    - name: Отчет об обновлении
      ansible.builtin.debug:
        msg: "Packages upgraded: {{ apt_upgrade.stdout | default('none') }}"

  handlers:
    - name: Reboot if needed
      ansible.builtin.reboot:
        reboot_timeout: 600
      when: reboot_required.stat.exists

---
# playbooks/rolling_deploy.yml
- name: Rolling deploy приложения
  hosts: web_servers
  serial: 1
  max_fail_percentage: 0
  become: true
  tasks:
    - name: Вывод из балансировщика
      ansible.builtin.lineinfile:
        path: /etc/nginx/upstream.conf
        regexp: "server.*{{ inventory_hostname }}"
        line: "# server {{ inventory_hostname }}:8000; # disabled"
      delegate_to: "{{ groups['load_balancer'][0] }}"
      notify: Reload Nginx

    - name: Ожидание завершения соединений
      ansible.builtin.wait_for:
        timeout: 10

    - name: Деплой нового кода
      ansible.builtin.unarchive:
        src: "https://releases.example.com/app-{{ app_version }}.tar.gz"
        dest: /opt/app
        remote_src: yes

    - name: Перезапуск приложения
      ansible.builtin.service:
        name: app
        state: restarted

    - name: Проверка health check
      ansible.builtin.uri:
        url: http://{{ inventory_hostname }}/health
        status_code: 200
        timeout: 10
      register: health_check
      until: health_check.status == 200
      retries: 30
      delay: 2

    - name: Возврат в балансировщик
      ansible.builtin.lineinfile:
        path: /etc/nginx/upstream.conf
        regexp: "# server {{ inventory_hostname }}:8000; # disabled"
        line: "server {{ inventory_hostname }}:8000;"
      delegate_to: "{{ groups['load_balancer'][0] }}"
      notify: Reload Nginx

  handlers:
    - name: Reload Nginx
      ansible.builtin.service:
        name: nginx
        state: reloaded
```

**Запуск через CI/CD:**

```bash
# Обновление ОС на всех хостах (rolling)
ansible-playbook playbooks/patch_management.yml -i environments/prod/hosts.yml --ask-vault-pass

# Rolling deploy приложения
ansible-playbook playbooks/rolling_deploy.yml -i environments/prod/hosts.yml --ask-vault-pass
```

**Валидация:**

```bash
# Проверка статуса обновления
ansible all -m shell -a "apt list --upgradable" --become
# → показывает доступные обновления

# Проверка необходимости перезагрузки
ansible all -m shell -a "ls -la /var/run/reboot-required" --become
# → файл существует, если требуется перезагрузка

# Проверка rolling deploy
ansible-playbook playbooks/rolling_deploy.yml --list-tasks
# → показывает последовательность задач

# Dry-run
ansible-playbook playbooks/rolling_deploy.yml --check --diff
# → показывает изменения без применения
```


---

## Операции и команды

### Основные команды для управления проектом

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook site.yml --syntax-check` | Проверка синтаксиса YAML | `ansible-playbook playbooks/site.yml --syntax-check` |
| `ansible-playbook site.yml --check --diff` | Dry-run с показом изменений | `ansible-playbook playbooks/site.yml --check --diff` |
| `ansible-playbook site.yml --list-tasks` | Просмотр задач без выполнения | `ansible-playbook playbooks/site.yml --list-tasks` |
| `ansible-playbook site.yml --list-tags` | Просмотр тегов | `ansible-playbook playbooks/site.yml --list-tags` |
| `ansible-playbook site.yml --list-hosts` | Просмотр хостов | `ansible-playbook playbooks/site.yml --list-hosts` |
| `ansible-playbook site.yml --step` | Пошаговое выполнение | `ansible-playbook playbooks/site.yml --step` |
| `ansible-playbook site.yml --start-at-task` | Запуск с конкретной задачи | `ansible-playbook playbooks/site.yml --start-at-task="Deploy"` |
| `ansible-inventory --graph` | Визуализация инвентаря | `ansible-inventory -i environments/prod/hosts.yml --graph` |
| `ansible-inventory --host` | Переменные хоста | `ansible-inventory -i environments/prod/hosts.yml --host web1` |
| `ansible <host> -m setup` | Сбор фактов | `ansible web1 -m setup -a "filter=ansible_os_family*"` |
| `ansible <host> -m debug` | Просмотр переменной | `ansible web1 -m debug -a "var=my_var"` |
| `ansible <host> -m ping` | Проверка доступности | `ansible all -m ping` |
| `ansible-vault create` | Создание зашифрованного файла | `ansible-vault create vars/vault.yml` |
| `ansible-vault edit` | Редактирование зашифрованного файла | `ansible-vault edit vars/vault.yml` |
| `ansible-galaxy collection install` | Установка коллекций | `ansible-galaxy collection install -r requirements.yml` |
| `ansible-galaxy role install` | Установка роли | `ansible-galaxy role install geerlingguy.nginx` |
| `ansible-lint` | Проверка качества кода | `ansible-lint playbooks/` |
| `yamllint` | Проверка синтаксиса YAML | `yamllint .` |

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

**Симптом:** `ERROR! A Vault password is required`.

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
#   ansible.builtin.apt:
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
#   ansible.builtin.template:
#     src: nginx.conf.j2
#     dest: /etc/nginx/nginx.conf
#   notify: Reload Nginx   # ← Должно быть на одном уровне с задачей

# Проверка обработчиков
ansible-playbook site.yml --list-handlers

# Принудительный запуск обработчиков
ansible-playbook site.yml --handlers-first
```

---

## Рекомендации

### Best Practices

1. **Храните секреты в Vault**: Никогда не коммитьте пароли в открытом виде. Используйте `ansible-vault` с защищенным хранилищем паролей (например, `~/.vault_pass` с правами `600`).
2. **Используйте FQCN**: Всегда указывайте полные имена модулей (`ansible.builtin.apt` вместо `apt`) для совместимости между версиями Ansible и коллекций.
3. **Настраивайте `no_log: true`** для задач с секретами. Это предотвращает утечку данных в логи CI/CD.
4. **Проверяйте идемпотентность**: Второй запуск плейбука не должен вносить изменения (`changed=0`). Это подтверждает корректность декларативного подхода.
5. **Используйте `block/rescue/always`** вместо `ignore_errors: true` для осмысленной обработки ошибок.
6. **Документируйте переменные** в `README.md` проекта или в `defaults/main.yml` роли с комментариями.
7. **Выносите логику в роли**: Для повторного использования настройка сервисов должна быть оформлена как роль. Подробнее: **[Структура роли Ansible](../Roles/structure.md)**.
8. **Настраивайте `ansible.cfg`** с разумными таймаутами и `ControlPersist` для ускорения повторных подключений.
9. **Используйте `--check --diff`** перед первым запуском в production. Это позволяет увидеть точные изменения без риска.
10. **Валидируйте конфигурацию**: Всегда проверяйте синтаксис YAML и плейбуков через `ansible-playbook --syntax-check` и `ansible-lint`.

### Чек-лист безопасности

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Vault зашифрован | `ansible-vault view vars/vault.yml` | Содержимое отображается только после ввода пароля |
| No_log включен | `grep no_log playbooks/*.yml` | Задачи с секретами имеют `no_log: true` |
| Права на vault-файл | `ls -la vars/vault.yml` | `-rw-------` |
| SSH-ключи | `ssh -o BatchMode=yes deploy@web1` | Подключение без пароля |
| Sudo без пароля | `ansible web_servers -m command -a "whoami" --become` | `root` |
| Линтер | `ansible-lint playbooks/` | Нет ошибок |
| Синтаксис YAML | `yamllint .` | Нет ошибок |

---

## Дополнительная информация

### Смотрите также

- [Структура роли (tasks, templates, handlers)](../Roles/structure.md)
- [Установка и базовая настройка Ansible](../ansible_setup_and_config.md)
- [Работа с Ansible Galaxy (роли и коллекции)](../Roles/galaxy.md)
- [Антипаттерны Ansible](../ansible_bad_practices.md)
- [Создание и использование ролей](../Roles/usage.md)

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

### Интеграция с CI/CD

В Enterprise-проектах для автоматизации пайплайнов рекомендуется:
- Использовать **ansible-lint** для соблюдения стандартов кодирования.
- Автоматизировать запуск через пайплайны (GitLab CI, GitHub Actions, Jenkins), передавая пароли Vault через переменные окружения. Подробнее см. **[Безопасный CI/CD пайплайн](example_real_world_ci_cd.md)**.
- Хранить секреты во внешнем менеджере секретов (HashiCorp Vault) вместо файлов на диск.
