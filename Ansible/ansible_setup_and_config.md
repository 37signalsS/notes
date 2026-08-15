# Ansible — установка и настройка

## Определения

- **Узел управления (Control Node)** — машина, на которой установлен пакет Ansible. С неё запускаются команды `ansible`, `ansible-playbook` и другие утилиты CLI. Требует наличия **Python 3.10+** (для современных версий). На Control Node нельзя использовать Windows напрямую; поддерживаются Linux, macOS или **WSL2**.
- **Управляемый узел (Managed Node)** — целевой сервер или устройство, которым управляет Ansible. Не требует установки агента (agentless). Для работы необходим активный SSH-доступ (или WinRM для Windows) и установленный **Python 3.7+**.
- **Инвентарь (Inventory)** — файл или скрипт, содержащий список управляемых узлов, их группировку и специфические переменные подключения.
- **Конфигурационный файл (ansible.cfg)** — файл, определяющий поведение самого Ansible (пути поиска ролей, параметры SSH, настройки повышения привилегий и тюнинг производительности).
- **Плагин подключения (Connection Plugin)** — низкоуровневый компонент, реализующий способ связи с узлом (`ssh`, `local`, `docker`, `winrm`, `podman`).
- **Повышение привилегий (Privilege Escalation / Become)** — механизм, позволяющий выполнять задачи от имени другого пользователя (обычно `root`) с помощью `sudo`, `su` или `doas`.

## Основные концепции

### Конфигурация Ansible (ansible.cfg)

Ansible ищет файл конфигурации в строгом порядке приоритета и использует **первый найденный** файл:

1.  **Переменная `ANSIBLE_CONFIG`** — указывает абсолютный или относительный путь к конкретному файлу.
2.  **`ansible.cfg` в текущем рабочем каталоге** — рекомендуемый подход для изоляции настроек конкретного проекта (Project-level).
3.  **`~/.ansible.cfg`** — настройки в домашнем каталоге пользователя (User-level).
4.  **`/etc/ansible/ansible.cfg`** — глобальный системный конфиг по умолчанию (System-level).

**Ключевые разделы конфига:**
- `[defaults]`: Базовые настройки (`inventory`, `roles_path`, `remote_user`, `host_key_checking`).
- `[privilege_escalation]`: Параметры `become`, `become_method`, `become_user`.
- `[ssh_connection]`: Тюнинг SSH (`pipelining`, `control_path`, `retries`).
- `[inventory]`: Настройки кэширования и плагинов инвентаря.

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

Для проверки структуры и отладки переменных:
```bash
# Дерево групп
ansible-inventory -i inventory.yml --graph
# Полный JSON со всеми переменными (hostvars)
ansible-inventory -i inventory.yml --list
```

### Параметры подключения и доступа

Основные переменные для настройки доступа (указываются в инвентаре или `group_vars`):
*   `ansible_host` — реальный IP или FQDN хоста.
*   `ansible_user` — имя пользователя для подключения.
*   `ansible_ssh_private_key_file` — путь к приватному ключу SSH.
*   `ansible_connection` — тип подключения (`ssh`, `local`, `docker`).
*   `ansible_python_interpreter` — явное указание пути к Python на целевом хосте.

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
    ```

### Сбор и работа с системной информацией (Facts)

Модуль `setup` запускается автоматически в начале плейбуков (параметр `gather_facts: true`).
```bash
# Ручной запуск сбора фактов для всех хостов
ansible all -m setup
```
**Важные рекомендации по фактам:**
- Всегда обращайтесь к фактам через основной словарь: `{{ ansible_facts['distribution'] }}`. Использование прямых переменных типа `{{ ansible_distribution }}` считается устаревшим и может привести к конфликтам имен.
- Для ускорения работы в больших инфраструктурах используйте [Fact Caching](./ansible_performance_tuning.md#кэширование-фактов-fact-caching).

### Инструменты современной экосистемы

1.  **ansible-lint:** Статический анализатор. Обязателен в CI/CD для выявления антипаттернов (например, отсутствие FQCN — `ansible.builtin.copy`).
    ```bash
    ansible-lint site.yml
    ```
2.  **ansible-navigator:** Современный TUI и CLI для запуска плейбуков в **Execution Environments (EE)**. Решает проблему несовместимости версий библиотек между Control Node и средой выполнения.
3.  **ansible-builder:** Инструмент для сборки образов **[Execution Environments (EE)](./ansible-execution-environments.md)** на основе определений в YAML.
4.  **molecule:** Фреймворк для тестирования ролей. См. [Ansible: тестирование с Molecule](./ansible_testing_with_molecule.md).

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

### Смотрите также

- [Переменные и факты](./PlaybookStructure/variables.md) — детальное описание иерархии и приоритетов.
- [Динамический инвентарь](./dynamic_inventory.md) — интеграция с AWS, Yandex Cloud и NetBox.
- [Оптимизация производительности](./ansible_performance_tuning.md) — SSH pipelining, Forks и стратегии выполнения.
- [Ansible Vault: работа с секретами](./Vault/basics.md) — защита конфиденциальных данных.
