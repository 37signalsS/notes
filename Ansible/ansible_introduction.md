# Введение в Ansible

## Определения

- **Ansible** — это система автоматизации ИТ-инфраструктуры с открытым исходным кодом (Red Hat / IBM), предназначенная для управления конфигурациями, развертывания приложений и оркестрации сложных ИТ-процессов. Это один из ключевых инструментов реализации парадигмы **Infrastructure as Code (IaC)**.
- **Infrastructure as Code (IaC)** — подход, при котором инфраструктура описывается в виде машиночитаемого кода (YAML, JSON, HCL), а не настраивается вручную. Позволяет версионировать конфигурацию, воспроизводить среды и автоматизировать изменения через CI/CD-пайплайны. Ansible реализует IaC через декларативные плейбуки.
- **Декларативность** — основной подход Ansible, при котором пользователь описывает *желаемое состояние* системы (Desired State), а инструмент самостоятельно определяет необходимые действия для его достижения. Это избавляет инженера от написания сложных императивных скриптов с обработкой ошибок каждого шага. Подробнее см. в [Основных концепциях](./ansible_core_concepts.md).
- **Agentless (безагентная архитектура)** — архитектурная особенность, при которой для управления узлами не требуется установка на них специального ПО (агентов). Связь осуществляется через стандартные протоколы: **SSH** для Linux/Unix, **WinRM** или **SSH** для Windows. Это упрощает внедрение и снижает накладные расходы на ресурсы.
- **Идемпотентность** — свойство операции, гарантирующее, что повторное выполнение не изменит систему, если она уже находится в желаемом состоянии. Фундаментальный принцип надежности автоматизации. Подробнее см. **[Идемпотентность](../../Concepts/idempotency.md)**.
- **Push-архитектура** — модель работы, при которой Узел управления (Control Node) инициирует соединение и «проталкивает» конфигурацию на управляемые узлы. Это противоположность Pull-модели (Ansible Pull), где хосты сами запрашивают конфигурацию из репозитория.

## Основные концепции

### Архитектура и компоненты

1.  **Узел управления (Control Node):** Машина, на которой установлен Ansible. С неё запускаются все команды и сценарии. Поддерживаются только Unix-подобные системы (Linux, macOS, WSL2). Для Control Node требуется **Python 3.10+** (для Ansible 9+) или **Python 3.7+** (для более ранних версий).
2.  **Управляемые узлы (Managed Nodes):** Целевые серверы, сетевые устройства или облачные ресурсы, которыми управляет Ansible. Для управления Linux-системами на них должен быть установлен **Python 3.7+**. Управление Windows-системами осуществляется через PowerShell и WinRM.
3.  **Инвентарь (Inventory):** Список хостов и групп хостов. Может быть статическим файлом (INI/YAML) или [динамическим скриптом](./dynamic_inventory.md), получающим данные из облаков или CMDB. Подробнее: [Управление инвентарем](./ansible_setup_and_config.md#управление-инвентарем).
4.  **Модули (Modules):** Исполняемые автономные блоки кода, выполняющие конкретные задачи (установка пакетов, копирование файлов). Современный стандарт требует использования полного имени ресурса — **FQCN (Fully Qualified Collection Name)** (например, `ansible.builtin.apt` вместо `apt`).
5.  **Плейбуки (Playbooks):** Сценарии автоматизации, написанные на языке **YAML**, описывающие шаги развертывания и настройки. Каждый плейбук состоит из «плеев» (Plays), которые связывают группы хостов с набором задач. Подробнее: [Структура плейбуков](./PlaybookStructure/basics.md).
6.  **Event-Driven Ansible (EDA):** Подход к реактивной автоматизации, позволяющий запускать действия на основе внешних событий (алертов, сообщений из очередей) в режиме реального времени. См. **[EDA — Реактивная автоматизация](./event-driven-ansible.md)**.

### Разделение пакетов: ansible-core и ansible

Для решения проблем с масштабированием проекта и скоростью выпуска обновлений, экосистема разделена на два компонента:
- **ansible-core**: Минимальное ядро системы, содержащее движок выполнения, CLI-утилиты (`ansible`, `ansible-playbook`) и набор базовых модулей (`ansible.builtin`). Обновляется строго по циклу релизов ядра.
- **ansible (Community пакет)**: Большой метапакет, включающий в себя `ansible-core` и тысячи модулей и плагинов от сообщества, упакованных в **Коллекции (Collections)**.
- **Execution Environments (EE)**: Современный способ упаковки Ansible, коллекций и зависимостей в контейнеры (**[подробнее](./ansible-execution-environments.md)**) для обеспечения идентичности сред выполнения.

### Преимущества использования

- **Минимальный порог входа:** Использование человекочитаемого формата YAML и системы шаблонизации **Jinja2**.
- **Единообразие инфраструктуры:** Исключение «серверов-снежинок» (уникальных серверов, настроенных вручную и невоспроизводимых автоматически).
- **Масштабируемость:** Возможность управления тысячами узлов одновременно благодаря параллельному выполнению (параметр `forks`, по умолчанию 5).
- **Безопасность:** Отсутствие постоянно запущенных агентов, использование стандартных механизмов аутентификации ОС (SSH-ключи) и интеграция с **Ansible Vault** для защиты чувствительных данных.
- **Идемпотентность:** Безопасный повторный запуск плейбуков — система не будет «сломана» повторным применением.

## Предварительные требования

### Для Control Node (машина, с которой запускается автоматизация)

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| Python | 3.7 | 3.11+ |
| SSH-клиент | OpenSSH 7.0 | OpenSSH 9.0+ |
| ОС | Linux, macOS, WSL2 | Ubuntu 22.04+ / RHEL 9+ |
| Память | 512 MB RAM | 2 GB+ RAM |
| Диск | 100 MB свободного места | 1 GB+ (с коллекциями) |

### Для Managed Nodes (управляемые хосты)

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Python | 3.7 | Обязательно дляinux-модулей |
| SSH-сервер | OpenSSH 7.0 | Для подключения от Control Node |
| sudo | Любая версия | Для повышения привилегий |

> **Примечание:** Для Managed Nodes, на которых отсутствует Python, Ansible может использовать модуль `ansible.builtin.raw` для первоначальной установки (см. [Bootstrapping](#начальная-загрузка-python-на-хосте)).

## Установка Ansible

### Рекомендуемый способ: pip

Установка через pip обеспечивает доступ к последней стабильной версии и изолирует Ansible от системных пакетов Python:

```bash
# Создание виртуального окружения (рекомендуется)
python3 -m venv ~/ansible-venv
source ~/ansible-venv/bin/activate

# Установка ansible (включает ansible-core + все коллекции сообщества)
pip install ansible

# Или установка только ansible-core (минимальная версия)
pip install ansible-core

# Проверка версии
ansible --version
# → ansible [core 2.17.x]
# → config file = None
# → configured module search path = ['/home/user/.ansible/plugins/modules']
# → ansible python module location = /home/user/ansible-venv/lib/python3.11/site-packages/ansible
# → python version = 3.11.x
```

### Системные пакеты

**Ubuntu / Debian:**
```bash
sudo apt update
sudo apt install -y ansible
# → Устанавливается из официального репозитория Ubuntu (может быть не последняя версия)
```

**RHEL / CentOS / Fedora:**
```bash
# RHEL 8/9 или CentOS Stream
sudo dnf install -y epel-release
sudo dnf install -y ansible-core

# Fedora
sudo dnf install -y ansible-core
```

**macOS (Homebrew):**
```bash
brew install ansible
# → Устанавливает ansible-core через homebrew-core
```

### Проверка работоспособности

```bash
# Проверка версии и конфигурации
ansible --version

# Проверка подключения к localhost
ansible all -m ping -i "localhost,"
# → localhost | SUCCESS => {
#     "changed": false,
#     "ping": "pong"
# }

# Просмотр доступных модулей
ansible-doc -l | head -20
# → ansible.builtin.add_host
# → ansible.builtin/apt
# → ansible.builtin.command
# → ...
```

## Практические сценарии

### Шаг 1: Создание первого инвентаря

Создайте файл `inventory.yml` в корне проекта:

```yaml
# inventory.yml — статический инвентарь
all:
  children:
    webservers:
      hosts:
        web1.example.com:
          ansible_user: deploy
          ansible_port: 22
        web2.example.com:
          ansible_user: deploy
      vars:
        http_port: 80
        ansible_become: true

    dbservers:
      hosts:
        db1.example.com:
          ansible_user: admin
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
      vars:
        mysql_port: 3306

    # Группа групп
    production:
      children:
        webservers:
        dbservers:
```

Проверка инвентаря:

```bash
# Дерево групп
ansible-inventory -i inventory.yml --graph
# → @all:
#   ├── @webservers:
#   │   ├── web1.example.com
#   │   └── web2.example.com
#   ├── @dbservers:
#   │   └── db1.example.com
#   └── @ungrouped:

# Вывод в JSON (для отладки)
ansible-inventory -i inventory.yml --list

# Проверка подключения ко всем хостам
ansible all -i inventory.yml -m ping
# → web1.example.com | SUCCESS => { "changed": false, "ping": "pong" }
# → web2.example.com | SUCCESS => { "changed": false, "ping": "pong" }
# → db1.example.com | SUCCESS => { "changed": false, "ping": "pong" }
```

### Шаг 2: Написание первого плейбука

Создайте файл `site.yml`:

```yaml
---
# site.yml — первый плейбук
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

### Шаг 3: Запуск плейбука

```bash
# Первый запуск (изменения будут применены)
ansible-playbook -i inventory.yml site.yml
# → PLAY [Базовая настройка веб-серверов] ****************************************
# → TASK [Gathering Facts] ********************************************************
# → ok: [web1.example.com]
# → ok: [web2.example.com]
# → TASK [Установка пакетов] *******************************************************
# → changed: [web1.example.com]
# → changed: [web2.example.com]
# → TASK [Убедиться, что nginx запущен] *******************************************
# → changed: [web1.example.com]
# → changed: [web2.example.com]
# → TASK [Проверить, что порт 80 открыт] ******************************************
# → ok: [web1.example.com]
# → ok: [web2.example.com]
# → PLAY RECAP ********************************************************************
# → web1.example.com : ok=4  changed=3  unreachable=0  failed=0  skipped=0
# → web2.example.com : ok=4  changed=3  unreachable=0  failed=0  skipped=0

# Повторный запуск (изменений не будет — идемпотентность)
ansible-playbook -i inventory.yml site.yml
# → TASK [Установка пакетов] *******************************************************
# → ok: [web1.example.com]  ← Вместо changed получаем ok (уже установлено)
# → ok: [web2.example.com]
```

### Шаг 4: Анализ изменений (Check & Diff)

Безопасное тестирование плейбука без реального применения изменений:

```bash
# Check Mode — «сухой запуск»
ansible-playbook -i inventory.yml site.yml --check
# → TASK [Установка пакетов] *******************************************************
# → changed: [web1.example.com]  ← Показывает, что изменение БЫЛО бы применено

# Diff Mode — показать разницу в конфигурационных файлах
ansible-playbook -i inventory.yml site.yml --diff
# → Используйте -C для комбинации check + diff
ansible-playbook -i inventory.yml site.yml -C -D
```

### Шаг 5: Сбор фактов и условная логика

Ansible автоматически собирает информацию о системе (**facts**) перед выполнением задач:

```yaml
---
- name: Условная логика на основе facts
  hosts: all
  become: true
  gather_facts: true

  tasks:
    # Вывод всех собранных фактов (для отладки)
    - name: Показать facts о системе
      ansible.builtin.debug:
        var: ansible_facts
      tags: debug

    # Условная установка в зависимости от ОС
    - name: Установка пакетов на Debian/Ubuntu
      ansible.builtin.apt:
        name: nginx
        state: present
      when: ansible_facts['os_family'] == 'Debian'

    - name: Установка пакетов на RHEL/CentOS
      ansible.builtin.dnf:
        name: nginx
        state: present
      when: ansible_facts['os_family'] == 'RedHat'

    # Вывод информации о системе
    - name: Показать ключевые facts
      ansible.builtin.debug:
        msg: >
          OS: {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_version'] }}
          Kernel: {{ ansible_facts['kernel'] }}
          IP: {{ ansible_facts['default_ipv4']['address'] }}
          RAM: {{ ansible_facts['memtotal_mb'] }} MB
          CPUs: {{ ansible_facts['processor_vcpus'] }}
```

### Шаг 6: Обработчики (Handlers)

Обработчики выполняются только при изменении 상태 и в конце плея:

```yaml
---
- name: Настройка веб-сервера
  hosts: webservers
  become: true

  tasks:
    - name: Скопировать конфигурацию nginx
      ansible.builtin.template:
        src: templates/nginx.conf.j2
        dest: /etc/nginx/nginx.conf
        owner: root
        group: root
        mode: '0644'
        validate: 'nginx -t -c %s'  # Валидация перед применением!
      notify: restart nginx

    - name: Скопировать index.html
      ansible.builtin.copy:
        src: files/index.html
        dest: /var/www/html/index.html
        owner: www-data
        mode: '0644'

  handlers:
    - name: restart nginx
      ansible.builtin.service:
        name: nginx
        state: restarted
```

### Начальная загрузка Python на хосте

Если на Managed Node отсутствует Python, стандартные модули не сработают. В этом случае используется модуль `ansible.builtin.raw`:

```yaml
---
- name: Play 1 — Bootstrap Python
  hosts: all
  become: true
  gather_facts: false  # Отключаем сбор фактов, так как он требует Python
  tasks:
    - name: Установить Python3
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      changed_when: false  # Подавляем ложный статус changed

- name: Play 2 — Основная конфигурация
  hosts: all
  become: true
  gather_facts: true  # Теперь Python установлен
  tasks:
    - name: Проверить подключение
      ansible.builtin.ping: {}
      # → "ping": "pong"
```

## Типичные ошибки и их решение (Troubleshooting)

### 1. «Module failures occurred» — отсутствие Python на Managed Node

**Симптом:** Задачи завершаются с ошибкой `Module failures occurred`.

**Диагностика:**
```bash
# Проверка наличия Python
ansible all -m command -a "python3 --version"
# → Если ошибка: «Failed to connect to the host via ssh: python3: command not found»
```

**Решение:** Использовать `ansible.builtin.raw` для первичной установки Python (см. [Начальная загрузка Python](#начальная-загрузка-python-на-хосте)).

### 2. «Unreachable» — проблемы с SSH-подключением

**Симптом:** Хосты недоступны, ошибка `UNREACHABLE!`.

**Диагностика:**
```bash
# Проверка SSH вручную
ssh -v deploy@web1.example.com

# Проверка инвентаря
ansible-inventory -i inventory.yml --host web1.example.com

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

### 3. «FAILED — Permission denied» — проблемы с привилегиями

**Симптом:** Ошибка `Permission denied` при выполнении задач с `become: true`.

**Диагностика:**
```bash
# Проверка sudo без пароля
ansible all -m command -a "sudo whoami" --become
```

**Решение:**
```yaml
# Добавление переменных в инвентарь
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
# Увеличение таймаута для конкретной задачи
- name: Длинная операция
  ansible.builtin.command: /opt/long-task.sh
  async: 3600      # Максимальное время выполнения (секунды)
  poll: 0          # Не ждать завершения (fire and forget)
  register: long_task

# Проверка статуса асинхронной задачи
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

### Сравнение с другими инструментами

#### Таблица сравнения

| Критерий | Ansible | Puppet | Chef | SaltStack | Terraform |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Архитектура** | Agentless | Agent/Agentless | Agent | Agent/Agentless | Agentless |
| **Язык** | YAML | DSL (Puppet DSL) | Ruby (ERB) | YAML + Jinja2 | HCL |
| **Подход** | Push | Pull | Pull | Push/Pull | Push |
| **Кривая обучения** | Низкая | Высокая | Высокая | Средняя | Средняя |
| **Сообщество** | Огромное | Большое | Большое | Среднее | Огромное |
| **Лицензия** | GPLv3 | Apache 2.0 | Apache 2.0 | Apache 2.0 | MPL 2.0 |
| **Фокус** | Configuration Management | Configuration Management | Configuration Management | Configuration Management + Event-driven | Provisioning |
| **Протокол** | SSH/WinRM | Agent (8140) | Agent (443) | ZeroMQ (4505/4506) | API (HTTP/HTTPS) |

#### Когда использовать Terraform vs Ansible

- **Terraform** — для **provisioning**: создание VM, сетей, хранилищ, Kubernetes-кластеров, DNS-записей, IAM-политик. Реализует цикл `create → update → destroy`.
- **Ansible** — для **configuration management**: настройка ПО, управление конфигами, деплой приложений, оркестрация. Гарантирует идемпотентность и Desired State.

**Рекомендуемый подход:** Terraform создаёт инфраструктуру, Ansible настраивает её. Не используйте Ansible для provisioning облаков (нет state management), не используйте Terraform для сложной конфигурации ПО (нет conditionals/loops на уровне YAML).

#### Puppet vs Chef vs Ansible: различия в подходе

| Инструмент | Парадигма | Стиль кода | Управление состоянием |
| :--- | :--- | :--- | --- |
| **Puppet** | DSL (доменно-ориентированный язык) | Declarative, но требует изучения собственного языка | Pull (агент запрашивает манифесты) |
| **Chef** | Ruby-скрипты (recipes/cookbooks) | Императивный, требует знания Ruby | Pull (chef-client запрашивает cookbook-и) |
| **Ansible** | YAML + Jinja2 | Декларативный, человекочитаемый | Push (контрольный узел инициирует изменения) |

**Преимущества Ansible:**
- Отсутствие агентов на managed nodes
- Простой синтаксис YAML
- Не требуется отдельная инфраструктура (master server)

#### Интеграция Ansible с Terraform

```yaml
# Terraform создаёт инфраструктуру
# terraform.tf
resource "aws_instance" "web" {
  count         = 3
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t3.micro"
  tags = {
    Name = "web-${count.index + 1}"
    Group = "webservers"
  }
}

# inventory.ini (динамический инвентарь Terraform)
# Генерируется через terraform-inventory или output
```

```bash
# Пайплайн: Terraform → Ansible
terraform init && terraform apply -auto-approve
terraform-inventory inventory > inventory.ini
ansible-playbook -i inventory.ini site.yml
```

**Пример Terraform provisioner (локальный Ansible):**
```hcl
resource "aws_instance" "web" {
  # ...

  provisioner "local-exec" {
    command = "ansible-playbook -i '${self.private_ip},' --private-key ~/.ssh/id_ed25519 configure.yml"
  }
}
```

## Дополнительная информация

### Рекомендации

- Для повторяющихся задач и управления конфигурацией всегда используйте плейбуки вместо ad-hoc команд, так как они обеспечивают идемпотентность и контроль версий.
- Используйте **FQCN** при вызове модулей для обеспечения стабильности и предотвращения конфликтов (например, `ansible.builtin.copy` вместо `copy`).
- Храните инвентарь и плейбуки в системе контроля версий (Git), следуя принципам **GitOps**.
- Не отключайте проверку SSH-ключей (`host_key_checking = False`) в production без крайней необходимости.
- Всегда используйте `--check` (check mode) перед первым применением плейбука на production-хостах.
- Используйте `ansible-lint` для проверки качества плейбуков перед коммитом.

### Смотрите также

- [Основные концепции Ansible](./ansible_core_concepts.md) — архитектура, идемпотентность, модули и плагины.
- [Установка и настройка](./ansible_setup_and_config.md) — подготовка рабочего окружения узла управления.
- [Ansible Identity Management](./ansible-identity-management.md) — автоматизация Active Directory, FreeIPA и LDAP.
- [Ansible Vault: работа с секретами](./Vault/basics.md) — защита конфиденциальных данных.
- [Автоматизация Kubernetes через Ansible](./ansible-kubernetes-automation.md) — управление ресурсами кластера.
