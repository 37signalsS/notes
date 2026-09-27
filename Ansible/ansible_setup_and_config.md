# Ansible — установка и настройка

## Определения

- **Узел управления (Control Node)** — машина, на которой установлен пакет Ansible. Общие сведения: [Введение в Ansible](./ansible_introduction.md). Требует наличия **Python 3.10+** (для современных версий). На Control Node нельзя использовать Windows напрямую; поддерживаются Linux, macOS или **WSL2**.
- **Управляемый узел (Managed Node)** — целевой сервер или устройство, которым управляет Ansible. Не требует установки агента (agentless). Для работы необходим активный SSH-доступ (или WinRM для Windows) и установленный **Python 3.7+**. Общие сведения: [Введение в Ansible](./ansible_introduction.md).
- **Инвентарь (Inventory)** — файл или скрипт, содержащий список управляемых узлов, их группировку и специфические переменные подключения.
- **Конфигурационный файл (ansible.cfg)** — файл, определяющий поведение самого Ansible (пути поиска ролей, параметры SSH, настройки повышения привилегий и тюнинг производительности).
- **Плагин подключения (Connection Plugin)** — низкоуровневый компонент, реализующий способ связи с узлом (`ssh`, `local`, `docker`, `winrm`, `podman`).
- **Повышение привилегий (Privilege Escalation / Become)** — механизм, позволяющий выполнять задачи от имени другого пользователя (обычно `root`) с помощью `sudo`, `su` или `doas`.
- **ansible-core** — минимальное ядро Ansible, содержащее движок выполнения, CLI-утилиты и базовые модули (`ansible.builtin`). Устанавливается отдельно или входит в состав метапакета `ansible`.
- **ansible (Community пакет)** — метапакет, включающий `ansible-core` и коллекции модулей сообщества. Рекомендуется для полного функционала.
- **Execution Environment (EE)** — контейнерный образ с Ansible, коллекциями и зависимостями, обеспечивающий воспроизводимость среды выполнения. См. [подробнее](./ansible-execution-environments.md).

## Предварительные требования

### Для Control Node (управляющий хост)

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| Python | 3.10 | 3.11+ |
| SSH-клиент | OpenSSH 7.0 | OpenSSH 9.0+ |
| ОС | Linux, macOS, WSL2 | Ubuntu 22.04+ / RHEL 9+ |
| Память | 512 MB RAM | 2 GB+ RAM |
| Диск | 100 MB свободного места | 1 GB+ (с коллекциями) |

### Для Managed Nodes (управляемые хосты)

| Компонент | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| Python | 3.7 | Обязательно для Linux-модулей |
| SSH-сервер | OpenSSH 7.0 | Для подключения от Control Node |
| sudo | Любая версия | Для повышения привилегий |

> **Примечание:** Для Managed Nodes, на которых отсутствует Python, Ansible может использовать модуль `ansible.builtin.raw` для первоначальной установки Python (см. раздел «Bootstrap: установка Python на хостах без него»).

## Основные концепции

### Конфигурация Ansible (ansible.cfg)

Ansible ищет файл конфигурации в строгом порядке приоритета и использует **первый найденный** файл:

1.  **Переменная `ANSIBLE_CONFIG`** — указывает абсолютный или относительный путь к конкретному файлу.
2.  **`ansible.cfg` в текущем рабочем каталоге** — рекомендуемый подход для изоляции настроек конкретного проекта (Project-level).
3.  **`~/.ansible.cfg`** — настройки в домашнем каталоге пользователя (User-level).
4.  **`/etc/ansible/ansible.cfg`** — глобальный системный конфиг по умолчанию (System-level).

> **Важно:** Ansible использует только **первый найденный** файл конфигурации. Если в текущем каталоге есть `ansible.cfg`, файлы `~/.ansible.cfg` и `/etc/ansible/ansible.cfg` **игнорируются** полностью.

**Ключевые разделы конфига:**
- `[defaults]`: Базовые настройки (`inventory`, `roles_path`, `remote_user`, `host_key_checking`, `forks`, `timeout`).
- `[privilege_escalation]`: Параметры `become`, `become_method`, `become_user`.
- `[ssh_connection]`: Тюнинг SSH (`pipelining`, `control_path`, `retries`, `ssh_args`).
- `[inventory]`: Настройки кэширования и плагинов инвентаря.

**Полный пример рабочего `ansible.cfg` с пояснениями:**

```ini
[defaults]
# Путь к инвентарю по умолчанию (относительно ansible.cfg)
inventory = ./inventory.ini

# Пути поиска ролей и коллекций (двоеточие — разделитель для нескольких путей)
roles_path = ./roles:/etc/ansible/roles
collections_paths = ./collections:~/.ansible/collections

# Пользователь SSH по умолчанию
remote_user = deploy

# Отключение проверки ключей хостов (только для dev/test!)
host_key_checking = False

# Стратегия выполнения по умолчанию (free — асинхронно, без ожидания всех хостов)
strategy = free

# Количество параллельных потоков (сколько хостов одновременно)
# Для небольших инвентарей 10-20, для крупных 40-100
forks = 10

# Таймаут подключения к хосту (секунды)
timeout = 30

# Режим сбора фактов: smart — кэширует, none — отключает, implicit — всегда
gathering = smart

# Кэширование фактов в JSON-файле (ускоряет повторные запуски)
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400

# Отключение уведомлений о deprecated-функционале
deprecation_warnings = False

# Callback-плагины (подробнее — [Callback-плагины](./ansible_monitoring_callbacks.md))
# callbacks_enabled = timer, profile_roles

# Форматирование вывода в YAML
stdout_callback = yaml

# Логирование (опционально)
# log_path = /var/log/ansible.log

[privilege_escalation]
# Включение повышения привилегий по умолчанию
become = True
become_method = sudo
become_user = root
become_ask_pass = False

[ssh_connection]
# Pipelining — пропускает промежуточные SSH-сеансы, ускоряя выполнение на 30-50%
# Требует: отсутствия requiretty в sudoers на managed nodes
pipelining = True

# Управление SSH-сессиями (кэширование соединений)
control_path = /tmp/ansible-%%h-%%r
ssh_args = -o ControlMaster=auto -o ControlPersist=60s

# Количество повторных попыток при ошибке SSH
retries = 3

[inventory]
# Плагины инвентаря по умолчанию
enable_plugins = host_list, script, yaml, ini, auto
```

### Переменные окружения

Любую настройку из `ansible.cfg` можно переопределить переменной окружения. Это полезно в CI/CD, когда конфиг хранится в репозитории, а чувствительные или специфичные для среды параметры прокидываются извне.

| Переменная | Описание |
| :--- | :--- |
| `ANSIBLE_CONFIG` | Путь к конкретному файлу конфигурации (переопределяет весь поиск). |
| `ANSIBLE_VAULT_PASSWORD_FILE` | Путь к файлу или скрипту с паролем Vault. Подробнее — [Ansible Vault: Лучшие практики](./Vault/best_practices.md). |
| `ANSIBLE_DISPLAY_OK_HOSTS` | Отключить вывод хостов со статусом `ok` (`False`). |
| `ANSIBLE_DISPLAY_SKIPPED_HOSTS` | Отключить вывод хостов со статусом `skipped` (`False`). |
| `ANSIBLE_STDOUT_CALLBACK` | Плагин вывода (`yaml`, `json`, `minimal`, `debug`). |
| `ANSIBLE_FORKS` | Количество параллельных соединений (переопределяет `forks` в `ansible.cfg`). |
| `ANSIBLE_HOST_KEY_CHECKING` | Отключение проверки SSH-ключей (`False`). |
| `ANSIBLE_TIMEOUT` | Таймаут подключения (секунды). |
| `ANSIBLE_PIPELINING` | Включение SSH Pipelining (`True`). |

```bash
# Пример запуска в CI/CD с минимизацией вывода
export ANSIBLE_DISPLAY_OK_HOSTS=False
export ANSIBLE_DISPLAY_SKIPPED_HOSTS=False
export ANSIBLE_VAULT_PASSWORD_FILE=/tmp/vault.pass

ansible-playbook site.yml
```

> **Важно:** При работе в CI/CD (Jenkins, GitLab CI, GitHub Actions) храните `ansible.cfg` в корне репозитория. Секреты (пароли, ключи) передавайте через переменные окружения или внешние секрет-менеджеры (Infisical, HashiCorp Vault), а не коммитьте их в Git.

### Управление инвентарем

Инвентарь может быть статическим (INI/YAML) или [динамическим](./dynamic_inventory.md).

**Формат INI (простой, для небольших проектов):**
```ini
[webservers]
web1.example.com
web2.example.com ansible_port=2222

[dbservers]
db1.example.com
```

**Формат YAML (структурированный, рекомендуемый):**
```yaml
all:
  children:
    webservers:
      hosts:
        web1.example.com:
        web2.example.com:
          ansible_port: 2222
    dbservers:
      hosts:
        db1.example.com:
```

**Вложенная группировка и переменные групп:**
```yaml
all:
  children:
    production:
      children:
        webservers:
          vars:
            http_port: 80
            ansible_user: deploy
          hosts:
            web-prod-01:
            web-prod-02:
        dbservers:
          vars:
            postgres_port: 5432
          hosts:
            db-prod-01:
    staging:
      children:
        webservers:
          hosts:
            web-staging-01:
```

Для проверки структуры и отладки переменных:
```bash
# Дерево групп
ansible-inventory -i inventory.yml --graph
# → @all:
#   ├─@webservers:
#   │ ├─web1.example.com
#   │ └─web2.example.com
#   └─@dbservers:
#     └─db1.example.com

# Полный JSON со всеми переменными (hostvars)
ansible-inventory -i inventory.yml --list

# Просмотр переменных конкретного хоста
ansible-inventory --host web1.example.com

# Визуализация вложенности групп
ansible-inventory -i inventory.yml --graph --vars
```

### Параметры подключения и доступа

Основные переменные для настройки доступа (указываются в инвентаре или `group_vars`):
*   `ansible_host` — реальный IP или FQDN хоста.
*   `ansible_port` — порт SSH (по умолчанию 22).
*   `ansible_user` — имя пользователя для подключения.
*   `ansible_ssh_private_key_file` — путь к приватному ключу SSH.
*   `ansible_connection` — тип подключения (`ssh`, `local`, `docker`, `winrm`).
*   `ansible_python_interpreter` — явное указание пути к Python на целевом хосте (например, `/usr/bin/python3` или `/usr/bin/python3.11`).
*   `ansible_become` — включение повышения привилегий для хоста.
*   `ansible_become_method` — метод повышения привилегий (`sudo`, `su`, `doas`, `pbrun`).
*   `ansible_become_user` — целевой пользователь (по умолчанию `root`).
*   `ansible_become_ask_pass` — запрашивать ли пароль для become (по умолчанию `False`).

**Пример переменных хоста в инвентаре:**
```yaml
all:
  children:
    webservers:
      hosts:
        web1.example.com:
          ansible_host: 10.0.0.10
          ansible_port: 2222
          ansible_user: deploy
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
          ansible_python_interpreter: /usr/bin/python3.11
```

**Безопасность:** Никогда не храните пароли или секреты в открытом виде. Используйте [Ansible Vault](./Vault/basics.md).

## Практические сценарии

### Установка Ansible

**Вариант 1: pipx (рекомендуется для CLI и соблюдения PEP 668)**
Устанавливает Ansible в изолированное окружение, делая бинарные файлы доступными в системе без конфликтов с системным Python.
```bash
# Установка pipx (если не установлен)
sudo apt install pipx
pipx ensurepath

# Установка полного пакета
pipx install ansible
# Или только ядра
pipx install ansible-core
```

**Вариант 2: Virtualenv (рекомендуется для конкретных проектов)**
Обеспечивает воспроизводимость версий Ansible и зависимостей (например, библиотек для облаков) внутри проекта.
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ansible ansible-lint
```

**Вариант 3: Системные пакеты**

*Ubuntu / Debian:*
```bash
sudo apt update && sudo apt install -y ansible
# → Устанавливается из официального репозитория (может быть не последняя версия)
```

*RHEL / CentOS / Fedora:*
```bash
sudo dnf install -y epel-release
sudo dnf install -y ansible-core
```

*macOS (Homebrew):*
```bash
brew install ansible
```

### Настройка SSH-доступа к управляемым хостам

**Генерация SSH-ключи для Ansible:**
```bash
# Создание ключа (Ed25519 — рекомендуется)
ssh-keygen -t ed25519 -C "ansible@$(hostname)" -f ~/.ssh/ansible_ed25519

# Копирование публичного ключа на удаленный хост
ssh-copy-id -i ~/.ssh/ansible_ed25519.pub deploy@10.0.0.10

# Проверка подключения
ssh -i ~/.ssh/ansible_ed25519 deploy@10.0.0.10 "echo ok"
# → ok
```

**Настройка SSH-клиента для Ansible:**

Создайте или дополните файл `~/.ssh/config`:
```
Host web-prod-01
    HostName 10.0.0.10
    User deploy
    IdentityFile ~/.ssh/ansible_ed25519
    StrictHostKeyChecking accept-new

Host db-prod-01
    HostName 10.0.1.10
    User deploy
    IdentityFile ~/.ssh/ansible_ed25519
    StrictHostKeyChecking accept-new
```

> **Примечание:** Ansible автоматически использует SSH-конфиг из `~/.ssh/config` если параметр `ansible_ssh_extra_args` не переопределен.

### Bootstrap: установка Python на хостах без него

Для Managed Nodes без установленного Python (minimal installs, контейнеры) facts недоступны, поэтому используется `ansible.builtin.raw` с проверкой через `failed_when`:
```yaml
# bootstrap.yml
---
- name: Установка Python на хосты без него
  hosts: all
  gather_facts: false
  become: true
  tasks:
    - name: Попытка установки Python (Debian/Ubuntu)
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      register: result_debian
      changed_when: "'Setting up python3' in result.stdout"
      failed_when: false

    - name: Попытка установки Python (RHEL/CentOS/Fedora)
      ansible.builtin.raw: dnf install -y python3 || yum install -y python3
      register: result_redhat
      changed_when: "'Installing' in result.stdout or 'Complete!' in result.stdout"
      failed_when: false
```

Запуск:
```bash
ansible-playbook -i inventory.ini bootstrap.yml
```

### Настройка и проверка окружения

1.  **Генерация примера конфига со всеми опциями:**
    ```bash
    ansible-config init --disabled > ansible.cfg
    # → Создает файл со всеми возможными параметрами (в закомментированном виде)
    ```

2.  **Проверка текущих переопределенных настроек:**
    ```bash
    ansible-config dump --only-changed
    # → Показывает только те параметры, которые отличаются от default, и источник их получения
    ```

3.  **Просмотр списка всех доступных опций:**
    ```bash
    ansible-config list
    ```

4.  **Проверка связи с хостами:**
    ```bash
    # Проверка всех хостов через модуль ping
    ansible all -m ping -i inventory.ini
    # → host1 | SUCCESS => { "changed": false, "ping": "pong" }

    # Проверка с указанием порта и ключа
    ansible web1.example.com -m ping -i inventory.ini \
      -e "ansible_port=2222" -e "ansible_ssh_private_key_file=~/.ssh/ansible_ed25519"
    ```

5.  **Проверка версии и окружения:**
    ```bash
    ansible --version
    # → ansible [core 2.17.x]
    # → config file = /path/to/project/ansible.cfg
    # → configured module search path = ['/path/to/plugins/modules']
    # → ansible python module location = /path/to/site-packages/ansible
    # → python version = 3.11.x
    ```

6.  **Проверка итоговых переменных для хоста:**
    ```bash
    ansible-inventory --host web1.example.com
    # → { "ansible_host": "10.0.0.10", "ansible_port": 2222, "ansible_user": "deploy" }
    ```

### Сбор и работа с системной информацией (Facts)

Модуль `setup` запускается автоматически в начале плейбуков (параметр `gather_facts: true`).
```bash
# Ручной запуск сбора фактов для всех хостов
ansible all -m setup

# Фильтрация фактов по подстроке (только информация об ОС)
ansible all -m setup -a "filter=ansible_distribution*"
# → web1.example.com | SUCCESS => { "ansible_facts": { "ansible_distribution": "Ubuntu", "ansible_distribution_version": "22.04" } }

# Сбор фактов конкретной группы
ansible webservers -m setup

# Сбор фактов конкретного хоста
ansible web1.example.com -m setup -i inventory.ini
```

**Примеры использования фактов в плейбуках:**
```yaml
- name: Настройка в зависимости от ОС
  hosts: all
  gather_facts: true
  tasks:
    - name: Установка пакетов (Debian/Ubuntu)
      ansible.builtin.apt:
        name:
          - nginx
          - python3-pip
        state: present
      when: ansible_facts['os_family'] == 'Debian'

    - name: Установка пакетов (RHEL/CentOS)
      ansible.builtin.dnf:
        name:
          - nginx
          - python3-pip
        state: present
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Вывод информации о системе
      ansible.builtin.debug:
        msg: >
          Хост: {{ inventory_hostname }},
          ОС: {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_version'] }},
          IP: {{ ansible_facts['default_ipv4']['address'] }},
          RAM: {{ ansible_facts['memtotal_mb'] }} MB
```

**Важные рекомендации по фактам:**
- Всегда обращайтесь к фактам через основной словарь: `{{ ansible_facts['distribution'] }}`. Использование прямых переменных типа `{{ ansible_distribution }}` считается устаревшим и может привести к конфликтам имен.
- Для ускорения работы в больших инфраструктурах используйте [Fact Caching](./ansible_performance_tuning.md#кэширование-фактов-fact-caching).
- Отключайте сбор фактов если они не нужны (`gather_facts: false`) — это ускоряет выполнение плейбука.

### Инструменты современной экосистемы

1.  **ansible-lint:** Статический анализатор плейбуков и ролей. Обязателен в CI/CD для выявления антипаттернов (отсутствие FQCN, небезопасные практики, устаревшие модули). Имеет встроенные правила и поддерживает кастомные.
    ```bash
    # Установка
    pip install ansible-lint

    # Анализ плейбука
    ansible-lint site.yml

    # Анализ проекта (ищет все YAML-файлы)
    ansible-lint

    # Формат вывода
    ansible-lint -f json site.yml
    ```
2.  **ansible-navigator:** Современный TUI и CLI для запуска плейбуков в **Execution Environments (EE)**. Решает проблему несовместимости версий библиотек между Control Node и средой выполнения.
    ```bash
    # Установка
    pip install ansible-navigator

    # Запуск плейбука в EE
    ansible-navigator run site.yml

    # Интерактивный режим
    ansible-navigator run site.yml --mode interactive

    # Конфигурация через ansible-navigator.yml
    ```
3.  **ansible-builder:** Инструмент для сборки образов **[Execution Environments (EE)](./ansible-execution-environments.md)** на основе определений в YAML. Позволяет упаковать Ansible, коллекции и системные зависимости в воспроизводимый контейнер.
    ```bash
    pip install ansible-builder
    ansible-builder build
    ```
4.  **molecule:** Фреймворк для тестирования ролей. Обеспечивает изоляцию тестовой среды (Docker, Podman, Vagrant), прогон интеграционных тестов и проверку идемпотентности. См. [Ansible: тестирование с Molecule](./ansible_testing_with_molecule.md).
    ```bash
    pip install "molecule>=24.0" "molecule-plugins[docker,podman]" ansible-lint pytest-testinfra
    ```

## Дополнительная информация

### Рекомендации и нюансы

- **PEP 668:** В современных дистрибутивах (Ubuntu 24.04+, Debian 12+) прямая установка через `pip install ansible` вне виртуального окружения заблокирована. Используйте `pipx` или `venv`.
- **Имена хостов:** Используйте в инвентаре логические имена (`web-prod-01`), а реальные адреса выносите в `ansible_host`. Это упрощает чтение логов и отчетов.
- **Локальное выполнение:** Для управления самой машиной Control Node используйте:
  ```yaml
  hosts: localhost
  connection: local
  ```
- **Host Key Checking:** В новых окружениях проверка SSH-ключей может мешать. Её можно отключить в `ansible.cfg` (`host_key_checking = False`), но помните, что это снижает защиту от MITM-атак.
- **Рекомендуемая структура проекта:**
  ```
  project/
  ├── ansible.cfg           # Конфигурация проекта
  ├── inventory/
  │   ├── production/
  │   │   ├── hosts.yml     # Инвентарь production
  │   │   └── group_vars/
  │   │       ├── all.yml   # Общие переменные
  │   │       ├── webservers.yml
  │   │       └── dbservers.yml
  │   └── staging/
  │       ├── hosts.yml
  │       └── group_vars/
  ├── roles/                # Роли Ansible
  ├── playbooks/            # Основные плейбуки
  ├── collections/          # Локальные коллекции
  └── requirements.yml      # Зависимости (роли/коллекции)
  ```

### Решение типичных проблем (Troubleshooting)

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `UNREACHABLE! Failed to connect to the host via ssh` | Хост недоступен, неверный IP, порт или ключ | 1) Проверьте `ansible_host` и `ansible_port`. 2) Проверьте SSH вручную: `ssh -i key user@host`. 3) Убедитесь, что SSH-сервер запущен. |
| `Permission denied (publickey)` | Неверный ключ или пользователь | 1) Проверьте `ansible_ssh_private_key_file`. 2) Убедитесь, что публичный ключ добавлен на хост (`ssh-copy-id`). 3) Проверьте права на приватный ключ (`chmod 600`). |
| `Host key verification failed` | Хост не в `known_hosts` или сменил ключ | 1) Добавьте ключ: `ssh-keyscan host >> ~/.ssh/known_hosts`. 2) Или включите `host_key_checking = False` в `ansible.cfg`. |
| `Failed to import the required Python library` | На managed node отсутствует Python | Выполните `bootstrap.yml` для установки Python (см. раздел «Bootstrap»). |
| `MODULE_FAILURE: Error connecting: SSH error` | Конфликт SSH-аргументов или pipelining | 1) Проверьте `ssh_args` в `ansible.cfg`. 2) Отключите `pipelining` для диагностики. |
| `The field 'become_user' is not allowed` | Опечатка в имени параметра | Проверьте YAML-синтаксис: `become_user` (через подчеркивание, не дефис). |
| `ERROR! the role 'xxx' was not found` | Роль не установлена | `ansible-galaxy role install -r requirements.yml` |
| `No config file found` | Ansible не находит `ansible.cfg` | Укажите путь явно: `ANSIBLE_CONFIG=./ansible.cfg ansible-playbook site.yml` |

**Диагностические команды:**
```bash
# Подробный вывод с отладкой SSH
ansible all -m ping -vvv

# Проверка подключения с указанием конкретного ключа и порта
ansible web1.example.com -m ping -i inventory.ini \
  -e "ansible_ssh_private_key_file=~/.ssh/ansible_ed25519" \
  -e "ansible_port=2222"

# Просмотр всех переменных хоста
ansible-inventory --host web1.example.com | python3 -m json.tool

# Проверка доступности хоста без Ansible
ssh -o ConnectTimeout=5 deploy@10.0.0.10 "echo ok"

# Проверка Python на managed node
ssh deploy@10.0.0.10 "python3 --version"
```

### Смотрите также

- [Переменные и факты](./PlaybookStructure/variables.md) — детальное описание иерархии и приоритетов.
- [Динамический инвентарь](./dynamic_inventory.md) — интеграция с CMDB (NetBox, Foreman, Consul).
- [Оптимизация производительности](./ansible_performance_tuning.md) — SSH pipelining, Forks и стратегии выполнения.
- [Callback-плагины для мониторинга](./ansible_monitoring_callbacks.md) — настройка `callbacks_enabled` и `stdout_callback`.
- [Ansible Vault: работа с секретами](./Vault/basics.md) — защита конфиденциальных данных.
- [Основные концепции Ansible](./ansible_core_concepts.md) — архитектура, идемпотентность, FQCN.
