# Введение в Ansible

## Определения

- **Ansible** — открытая система автоматизации ИТ-инфраструктуры (Red Hat / IBM) для управления конфигурациями, развертывания приложений и оркестрации процессов. Реализует парадигму **Infrastructure as Code (IaC)** через декларативные плейбуки на YAML.
- **IaC (Infrastructure as Code)** — подход, при котором инфраструктура описывается в виде машиночитаемого кода (YAML, JSON, HCL), а не настраивается вручную. Позволяет версионировать конфигурацию, воспроизводить среды и автоматизировать изменения через CI/CD-пайплайны.
- **Декларативность (Declarative Approach)** — основной принцип Ansible: пользователь описывает желаемое состояние системы (Desired State), а движок сам определяет действия для его достижения. Это избавляет от написания сложных императивных скриптов.
- **Идемпотентность (Idempotency)** — свойство операции, гарантирующее, что повторное выполнение не изменит систему, если она уже находится в желаемом состоянии. Фундаментальный принцип надежности автоматизации.
- **Agentless (безагентная архитектура)** — архитектурная особенность, при которой для управления узлами не требуется установка специального ПО. Связь осуществляется через стандартные протоколы: **SSH** для Linux/Unix, **WinRM/PSRP** для Windows.
- **Push-модель** — модель работы, при которой Узел управления (Control Node) инициирует соединение и «проталкивает» конфигурацию на управляемые узлы. Противоположность Pull-модели (Ansible Pull), где хосты сами запрашивают конфигурацию.
- **FQCN (Fully Qualified Collection Name)** — полное имя ресурса в формате `namespace.collection.resource` (например, `ansible.builtin.apt`). Использование FQCN обязательно в современных версиях для предотвращения конфликтов имен.
- **Inventory (Инвентарь)** — список хостов и групп хостов. Может быть статическим файлом (INI/YAML) или динамическим скриптом, получающим данные из CMDB, Git или API. Подробнее: [Динамический инвентарь](./dynamic_inventory.md).

## Архитектура и принципы работы

### Компоненты системы

1. **Узел управления (Control Node):** Машина, на которой установлен Ansible. С неё запускаются все команды и сценарии. Поддерживаются только Unix-подобные системы (Linux, macOS, WSL2). Требуется **Python 3.10+** (для современных версий). Подробные требования и способы установки: [Установка и настройка](./ansible_setup_and_config.md).
2. **Управляемые узлы (Managed Nodes):** Целевые серверы, сетевые устройства или контейнеры, которыми управляет Ansible. Для Linux требуется **Python 3.7+**, для Windows — PowerShell. Агенты не требуются.
3. **Модули (Modules):** Исполняемые автономные блоки кода, выполняющие конкретные задачи (установка пакетов, копирование файлов, управление сервисами).
4. **Плейбуки (Playbooks):** Сценарии автоматизации на YAML, описывающие шаги развертывания и настройки. Каждый плейбук состоит из «плеев» (Plays), связывающих группы хостов с задачами.
5. **Плагины:** Расширяют функциональность Ansible: Connection (ssh, winrm, local), Inventory (статический, динамический), Lookup, Filter, Callback, Vars.
6. **Коллекции (Collections):** Формат распространения модулей, плагинов и ролей. Примеры: `ansible.builtin`, `community.general`, `community.proxmox`, `theforeman.foreman`.

### Разделение пакетов: ansible-core и ansible

- **ansible-core:** Минимальное ядро, содержащее движок выполнения, CLI-утилиты (`ansible`, `ansible-playbook`) и базовые модулы (`ansible.builtin`). Обновляется по циклу релизов ядра.
- **ansible (Community пакет):** Метапакет, включающий `ansible-core` и тысячи модулей/плагинов от сообщества в виде коллекций.
- **Execution Environment (EE):** Современный способ упаковки Ansible, коллекций и зависимостей в контейнеры для обеспечения идентичности сред выполнения.

### Жизненный цикл выполнения плейбука

1. **Парсинг:** Чтение плейбука, проверка синтаксиса YAML и схемы Ansible.
2. **Загрузка инвентаря:** Построение графа хостов и групп, подстановка переменных.
3. **Сбор фактов (gather_facts):** Опрос управляемых узлов через `ansible.builtin.setup` для получения данных об ОС, сети, дисках.
4. **Расширение переменных:** Объединение фактов, инвентаря, плейбуков, ролей и Vault-секретов в единое пространство имен.
5. **Планирование задач:** Определение порядка выполнения, обработка `when`, `tags`, `handlers`.
6. **Выполнение:** Параллельная отправка задач на управляемые узлы через SSH/WinRM.
7. **Обработка результатов:** Вызов callback-плагинов, запись в лог, обновление фактов.

### Идемпотентность и состояние

Ansible не хранит состояние на управляемых узлах. При каждом запуске он:
- Сравнивает текущее состояние с желаемым (через модули)
- Применяет изменения только если они необходимы
- Помечает задачу как `changed` только при реальном изменении

Это делает автоматизацию безопасной для повторного запуска в production.

## Практические сценарии

### Сценарий 1: Первый инвентарь и плейбук

Создайте структуру проекта:

```bash
mkdir -p ~/projects/ansible-first/{inventory,playbooks}
cd ~/projects/ansible-first
```

**Шаг 1:** Создайте `inventory/hosts.yml`:

```yaml
all:
  children:
    webservers:
      hosts:
        web01.example.com:
          ansible_user: deploy
          ansible_port: 22
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
      vars:
        http_port: 80
        ansible_become: true

    dbservers:
      hosts:
        db01.example.com:
          ansible_user: admin
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
      vars:
        mysql_port: 3306

    production:
      children:
        webservers:
        dbservers:
```

**Шаг 2:** Проверьте инвентарь:

```bash
ansible-inventory -i inventory/hosts.yml --graph
# → @all:
#   ├── @webservers:
#   │   └── web01.example.com
#   ├── @dbservers:
#   │   └── db01.example.com
#   └── @production:
#       ├── @webservers
#       └── @dbservers

ansible all -i inventory/hosts.yml -m ping
# → web01.example.com | SUCCESS => { "changed": false, "ping": "pong" }
```

**Шаг 3:** Создайте `playbooks/site.yml`:

```yaml
---
- name: Базовая настройка веб-серверов
  hosts: webservers
  become: true
  gather_facts: true

  vars:
    packages:
      - nginx
      - htop
      - curl

  tasks:
    - name: Установка пакетов
      ansible.builtin.apt:
        name: "{{ packages }}"
        state: present
        update_cache: true
        cache_valid_time: 3600
      register: install_result

    - name: Вывод информации об установке
      ansible.builtin.debug:
        msg: "Установлены пакеты: {{ packages }}"

    - name: Убедиться, что nginx запущен
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: true

    - name: Проверить, что порт 80 открыт
      ansible.builtin.wait_for:
        port: 80
        delay: 5
        timeout: 30
```

**Шаг 4:** Запустите плейбук:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml
# → PLAY [Базовая настройка веб-серверов] ****************************************
# → TASK [Gathering Facts] ********************************************************
# → ok: [web01.example.com]
# → TASK [Установка пакетов] *******************************************************
# → changed: [web01.example.com]
# → TASK [Убедиться, что nginx запущен] *******************************************
# → changed: [web01.example.com]
# → TASK [Проверить, что порт 80 открыт] ******************************************
# → ok: [web01.example.com]
# → PLAY RECAP ********************************************************************
# → web01.example.com : ok=4  changed=3  unreachable=0  failed=0  skipped=0

# Повторный запуск (идемпотентность)
ansible-playbook -i inventory/hosts.yml playbooks/site.yml
# → TASK [Установка пакетов] *******************************************************
# → ok: [web01.example.com]  ← Вместо changed получаем ok
```

**Шаг 5:** Проверка без применения изменений:

```bash
# Check Mode — «сухой запуск»
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --check

# Diff Mode — показать разницу в конфигурационных файлах
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --diff

# Комбинация check + diff
ansible-playbook -i inventory/hosts.yml playbooks/site.yml -C -D
```

### Сценарий 2: Условная логика и обработчики

```yaml
---
- name: Настройка веб-сервера с обработчиком
  hosts: webservers
  become: true
  gather_facts: true

  vars:
    nginx_config_template: templates/nginx.conf.j2

  tasks:
    - name: Создать директорию для сайта
      ansible.builtin.file:
        path: /var/www/html
        state: directory
        owner: www-data
        group: www-data
        mode: '0755'

    - name: Скопировать index.html
      ansible.builtin.copy:
        src: files/index.html
        dest: /var/www/html/index.html
        owner: www-data
        group: www-data
        mode: '0644'
      notify: restart nginx

    - name: Установить nginx с валидацией конфига
      ansible.builtin.template:
        src: "{{ nginx_config_template }}"
        dest: /etc/nginx/nginx.conf
        owner: root
        group: root
        mode: '0644'
        validate: 'nginx -t -c %s'
      notify: restart nginx

  handlers:
    - name: restart nginx
      ansible.builtin.service:
        name: nginx
        state: restarted
```

### Сценарий 3: Bootstrap Python на хосте без интерпретатора

Для Managed Nodes без Python (minimal installs, контейнеры) используйте `ansible.builtin.raw`:

```yaml
---
- name: Play 1 — Bootstrap Python
  hosts: all
  gather_facts: false
  become: true
  tasks:
    - name: Установить Python3 (Debian/Ubuntu)
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      changed_when: false

- name: Play 2 — Основная конфигурация
  hosts: all
  become: true
  gather_facts: true
  tasks:
    - name: Проверить подключение
      ansible.builtin.ping: {}
```

### Сценарий 4: Интеграция с GitOps и CI/CD

```yaml
# playbooks/deploy_app.yml
---
- name: Развертывание приложения
  hosts: webservers
  become: true
  vars_files:
    - ../../group_vars/prod/vault.yml  # Зашифрованные секреты

  pre_tasks:
    - name: Проверить drift от последнего коммита
      ansible.builtin.command: git diff HEAD~1 -- playbooks/
      register: git_diff
      delegate_to: localhost
      changed_when: git_diff.stdout != ""

  tasks:
    - name: Развернуть версию {{ app_version }}
      ansible.builtin.shell: |
        cd /opt/app && git pull && systemctl restart app
```

В CI/CD-пайплайне (GitLab CI, GitHub Actions, Jenkins):

```yaml
# .gitlab-ci.yml
stages:
  - lint
  - test
  - deploy

ansible-lint:
  stage: lint
  image: quay.io/ansible/ansible-lint:latest
  script:
    - ansible-lint playbooks/

ansible-check:
  stage: test
  script:
    - ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml --check

deploy-prod:
  stage: deploy
  when: manual
  script:
    - ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml
```

## Операции и команды

### Справочник CLI

| Команда | Назначение | Пример |
| :--- | :--- | :--- |
| `ansible` | Ad-hoc выполнение задачи на хостах | `ansible webservers -m ping -i inventory.yml` |
| `ansible-playbook` | Запуск плейбука | `ansible-playbook -i inventory.yml site.yml --check` |
| `ansible-inventory` | Просмотр и валидация инвентаря | `ansible-inventory -i inventory.yml --graph --list` |
| `ansible-vault` | Шифрование/дешифрование секретов | `ansible-vault encrypt group_vars/prod/vault.yml` |
| `ansible-galaxy` | Установка ролей и коллекций | `ansible-galaxy collection install community.general` |
| `ansible-config` | Просмотр и проверка конфигурации | `ansible-config dump --only-changed` |
| `ansible-doc` | Справка по модулям и плагинам | `ansible-doc ansible.builtin.apt` |
| `ansible-lint` | Статический анализ плейбуков и ролей | `ansible-lint playbooks/` |

### Распространенные комбинации флагов

```bash
# Проверка доступности всех хостов
ansible all -i inventory.yml -m ping

# Сбор фактов без выполнения задач
ansible all -i inventory.yml -m setup -a "filter=ansible_distribution*"

# Выполнение команды на группе хостов
ansible webservers -i inventory.yml -m shell -a "systemctl status nginx"

# Запуск с тэгом
ansible-playbook -i inventory.yml site.yml --tags "packages"

# Пропуск тэга
ansible-playbook -i inventory.yml site.yml --skip-tags "restart"

# Указание vault-пароля через файл
ansible-playbook -i inventory.yml site.yml --vault-id prod@.vault_pass

# Ограничение на конкретный хост
ansible-playbook -i inventory.yml site.yml --limit web01.example.com

# Проверка синтаксиса без выполнения
ansible-playbook -i inventory.yml site.yml --syntax-check
```

### Проверка работоспособности окружения

```bash
# Проверка версии Ansible
ansible --version
# → ansible [core 2.18.x]

# Проверка подключения ко всем хостам
ansible all -i inventory.yml -m ping

# Валидация инвентаря
ansible-inventory -i inventory.yml --list | jq .

# Проверка доступных модулей
ansible-doc -l | grep ansible.builtin | head -20
```

## Типичные ошибки и их решение (Troubleshooting)

### 1. «Module failures occurred» — отсутствие Python на Managed Node

**Симптом:** Задачи завершаются с ошибкой `Module failures occurred`.

**Диагностика:**
```bash
ansible all -m command -a "python3 --version"
# → Если ошибка: «Failed to connect to the host via ssh: python3: command not found»
```

**Решение:** Использовать `ansible.builtin.raw` для первичной установки Python (см. [Сценарий 3](#сценарий-3-bootstrap-python-на-хосте-без-интерпретатора)).

### 2. «UNREACHABLE!» — проблемы с SSH-подключением

**Симптом:** Хосты недоступны, ошибка `UNREACHABLE!`.

**Диагностика:**
```bash
# Проверка SSH вручную
ssh -v deploy@web01.example.com

# Проверка инвентаря
ansible-inventory -i inventory.yml --host web01.example.com

# Запуск с увеличенным уровнем логирования
ansible all -m ping -vvv
```

**Решение:**
```ini
# ansible.cfg — увеличение таймаутов
[defaults]
timeout = 60
remote_user = deploy

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s -o ServerAliveInterval=30
pipelining = true
retries = 3
```

### 3. «Permission denied» — проблемы с привилегиями

**Симптом:** Ошибка `Permission denied` при выполнении задач с `become: true`.

**Диагностика:**
```bash
ansible all -m command -a "sudo whoami" --become
```

**Решение:**
```yaml
all:
  children:
    webservers:
      vars:
        ansible_become: true
        ansible_become_method: sudo
        ansible_become_user: root
        # Если sudo требует пароль:
        # ansible_become_pass: "{{ vault_sudo_pass }}"
```

### 4. «ERROR! Timeout expired» — превышение времени ожидания

**Симптом:** Задача зависает и завершается по таймауту.

**Решение:**
```yaml
- name: Длинная операция
  ansible.builtin.command: /opt/long-task.sh
  async: 3600      # Максимальное время выполнения (секунды)
  poll: 0          # Не ждать завершения (fire and forget)
  register: long_task

- name: Дождаться завершения
  ansible.builtin.async_status:
    jid: "{{ long_task.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 60
  delay: 60
```

### 5. «Vault password» — запрос пароля при каждом запуске

**Симптом:** При использовании `ansible-vault` пароль запрашивается интерактивно при каждом запуске.

**Решение:**
```bash
# Способ 1: Файл пароля (для CI/CD)
echo "my_vault_password" > .vault_pass
chmod 600 .vault_pass

# ansible.cfg
[defaults]
vault_password_file = .vault_pass

# Способ 2: Переменная окружения
export ANSIBLE_VAULT_PASSWORD_FILE=.vault_pass

# Способ 3: Vault ID для multiple vaults
ansible-playbook site.yml --vault-id prod@prompt --vault-id dev@.vault_pass_dev
```

Подробнее о работе с секретами: [Ansible Vault: Основы](./Vault/basics.md).

### 6. «ERROR! the role 'xxx' was not found» — отсутствие роли

**Симптом:** Роль не найдена при запуске плейбука.

**Решение:**
```bash
# Проверка установленных ролей
ansible-galaxy role list

# Установка роли
ansible-galaxy role install geerlingguy.docker

# Установка коллекции
ansible-galaxy collection install community.general

# Проверка путей поиска
ansible-config dump | grep roles_path
```

## Лучшие практики

- **Идемпотентность:** Всегда пишите задачи так, чтобы повторный запуск был безопасен. Используйте `state=present` вместо `state=installed`, проверяйте условия через `when`.
- **FQCN:** Используйте полные имена модулей (`ansible.builtin.apt` вместо `apt`) для стабильности и предотвращения конфликтов.
- **GitOps:** Храните инвентарь, плейбуки, роли и коллекции в Git. Используйте ветки для сред (`main` — production, `develop` — staging).
- **Секреты:** Никогда не храните пароли в открытом виде. Используйте `ansible-vault` с `vault_password_file` в CI/CD. Для production используйте внешние хранилища (HashiCorp Vault, CyberArk).
- **Check Mode:** Всегда запускайте `--check` перед первым применением на production. Используйте `--diff` для просмотра изменений.
- **Логирование:** Настройте `log_path` в `ansible.cfg` для аудита. В CI/CD интегрируйте с ELK/Graylog для централизованного хранения.
- **Статический анализ:** Внедрите `ansible-lint` в pre-commit hooks и CI/CD-пайплайны для контроля качества плейбуков.
- **Ограничение параллелизма:** Для production используйте `forks = 10` и `serial` в плейбуках, чтобы избежать перегрузки управляемых узлов.
- **Документация:** Комментируйте сложные задачи в плейбуках. Используйте `--start-at-task` для отладки.

## Сравнение с другими инструментами

| Критерий | Ansible | Puppet | Chef | SaltStack |
| :--- | :--- | :--- | :--- | :--- |
| **Архитектура** | Agentless | Agent/Agentless | Agent | Agent/Agentless |
| **Язык** | YAML + Jinja2 | DSL (Puppet DSL) | Ruby (ERB) | YAML + Jinja2 |
| **Подход** | Push | Pull | Pull | Push/Pull |
| **Кривая обучения** | Низкая | Высокая | Высокая | Средняя |
| **Сообщество** | Огромное | Большое | Большое | Среднее |
| **Лицензия** | GPLv3 | Apache 2.0 | Apache 2.0 | Apache 2.0 |
| **Фокус** | Configuration Management + Orchestration | Configuration Management | Configuration Management | CM + Event-driven |
| **Протокол** | SSH/WinRM | Agent (8140) | Agent (443) | ZeroMQ (4505/4506) |

Сравнение Ansible с Terraform/OpenTofu — в [Обзоре CM-инструментов](../Concepts/configuration_management_tools.md#terraform--opentofu--ansible).

### Когда использовать Terraform vs Ansible

См. раздел [Terraform / OpenTofu + Ansible](../Concepts/configuration_management_tools.md#terraform--opentofu--ansible).

### Puppet vs Chef vs Ansible: различия в подходе

| Инструмент | Парадигма | Стиль кода | Управление состоянием |
| :--- | :--- | :--- | :--- |
| **Puppet** | DSL (доменно-ориентированный язык) | Declarative, но требует изучения собственного языка | Pull (агент запрашивает манифесты) |
| **Chef** | Ruby-скрипты (recipes/cookbooks) | Императивный, требует знания Ruby | Pull (chef-client запрашивает cookbook-и) |
| **Ansible** | YAML + Jinja2 | Декларативный, человекочитаемый | Push (контрольный узел инициирует изменения) |

**Преимущества Ansible:**
- Отсутствие агентов на managed nodes
- Простой синтаксис YAML
- Не требуется отдельная инфраструктура (master server)

#### Интеграция Ansible с Terraform

Подробное описание рабочих процессов, разделения ответственности и практических сценариев совместного использования Terraform/OpenTofu и Ansible — в [Обзоре CM-инструментов: комбинирование Terraform и Ansible](../Concepts/configuration_management_tools.md#terraform--opentofu--ansible).

## Дополнительная информация

### Рекомендации

- Для повторяющихся задач используйте плейбуки вместо ad-hoc команд — они обеспечивают идемпотентность и контроль версий.
- Настраивайте `ansible.cfg` на уровне проекта для изоляции параметров. Глобальный конфиг `/etc/ansible/ansible.cfg` используется только если нет локального.
- Используйте `ansible-pull` для хостов с нестабильным подключением или динамическим масштабированием.
- Интегрируйте `ansible-lint` в pre-commit hooks для предотвращения плохих практик в коде.
- Настройте факт-кэширование (`fact_caching = jsonfile`) для ускорения повторных запусков на больших инвентарях.

### Смотрите также

- [Установка и настройка](./ansible_setup_and_config.md) — подробная установка, конфигурация `ansible.cfg`, настройка SSH и bootstrap.
- [Основные концепции](./ansible_core_concepts.md) — идемпотентность, факты, плагины, стратегии выполнения.
- [Динамический инвентарь](./dynamic_inventory.md) — CMDB, NetBox, Consul, Git-based инвентарь.
