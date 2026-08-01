# Ansible — установка и настройка

## Определения

**Узел управления (Control Node)** — машина, на которой установлен Ansible. С неё запускаются команды и плейбуки. Требует наличия **Python 3.10+** (для современных версий Ansible). На Control Node нельзя использовать Windows напрямую (допускается только Linux, macOS или WSL2).

**Управляемый узел (Managed Node)** — целевой сервер, управляемый через Ansible. Не требует установки агента Ansible, достаточно активного SSH-доступа (или WinRM для Windows) и установленного **Python 3.7+**.

**Инвентарь (Inventory)** — файл или скрипт, содержащий список управляемых узлов, их группировку и переменные подключения.

**Конфигурационный файл (ansible.cfg)** — файл настроек поведения самого Ansible (пути поиска ролей, параметры подключения, тюнинг производительности).

**Плагин подключения (Connection Plugin)** — компонент, реализующий способ связи с целевым узлом (SSH, Local, Docker, WinRM).

## Основные концепции

### Конфигурация Ansible (ansible.cfg)

Ansible ищет файл конфигурации в строгом порядке приоритета. Используется **первый найденный** файл:

1.  **Переменная `ANSIBLE_CONFIG`** — указывает абсолютный или относительный путь к конкретному файлу.
2.  **`ansible.cfg`** в текущем рабочем каталоге (рекомендуемый подход для изоляции проектов).
3.  **`~/.ansible.cfg`** в домашнем каталоге текущего пользователя.
4.  **`/etc/ansible/ansible.cfg`** — глобальный системный конфиг по умолчанию.

### Управление инвентарем

Инвентарь может быть статическим (файлы INI/YAML) или динамическим.

**Формат INI (простой):**
```ini
[webservers]
web1.example.com
web2.example.com ansible_port=2222

[dbservers]
db1.example.com
```

**Формат YAML (структурированный):**
```yaml
all:
  children:
    webservers:
      hosts:
        web1.example.com:
        web2.example.com:
          ansible_port: 2222
```

Для проверки структуры и парсинга инвентаря используйте команду:
```bash
ansible-inventory -i inventory.yml --graph
# → @all:
# →   |--@webservers:
# →   |  |--web1.example.com
# →   |  |--web2.example.com
```

### Параметры подключения

Основные переменные для настройки доступа:
*   `ansible_host` — адрес хоста.
*   `ansible_user` — имя пользователя для подключения.
*   `ansible_ssh_private_key_file` — путь к SSH-ключу.
*   `ansible_connection` — тип подключения (`ssh`, `local`, `docker`).

> **Безопасность:** Никогда не храните пароли в открытом виде. Используйте [Ansible Vault](./Vault/basics.md).

## Практические сценарии

### Установка Ansible

**Вариант 1: pipx (рекомендуется для CLI)**
Устанавливает Ansible в изолированное окружение, делая команды доступными глобально.
```bash
pipx install ansible
# Или установка только ядра
pipx install ansible-core
```

**Вариант 2: Virtualenv (для проектов)**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install ansible
```

### Настройка и проверка окружения

1.  **Генерация примера конфига:**
    ```bash
    ansible-config init --disabled > ansible.cfg
    # → Создан файл ansible.cfg с настройками по умолчанию (закомментированными)
    ```

2.  **Проверка текущих настроек:**
    Команда покажет только те параметры, которые отличаются от значений по умолчанию, и укажет источник их переопределения.
    ```bash
    ansible-config dump --only-changed
    # → DEFAULT_ROLES_PATH(ansible.cfg) = ['/path/to/roles']
    ```

3.  **Проверка связи с хостами:**
    ```bash
    # Проверка всех хостов из инвентаря
    ansible all -m ping -i inventory.ini
    # → host1 | SUCCESS => { "ping": "pong" }
    ```

### Сбор системной информации (Facts)

Модуль `setup` запускается автоматически в начале плейбуков (gather_facts).
```bash
# Ручной запуск сбора фактов
ansible all -m setup
# → host1 | SUCCESS => { "ansible_facts": { "distribution": "Ubuntu", ... } }
```
Всегда обращайтесь к фактам через словарь `ansible_facts`:
`{{ ansible_facts['distribution'] }}` (вместо устаревшего `{{ ansible_distribution }}` ).

### Современные инструменты экосистемы

1. **ansible-lint:** Обязательный инструмент для статического анализа плейбуков. Выявляет антипаттерны и нарушения стилистики до запуска.
   ```bash
   pipx install ansible-lint
   ansible-lint site.yml
   # → WARNING  [fqcn] Use FQCN for builtin module actions
   ```

2. **Ansible Navigator:** Современный TUI (Terminal User Interface) и CLI для запуска плейбуков и работы с контейнеризированными **Execution Environments (EE)**.
   ```bash
   ansible-navigator run site.yml -i inventory.yml --mode stdout
   # → Выполняет плейбук в контейнере, выводя результаты в stdout
   ```

## Дополнительная информация

### Рекомендации

*   **PEP 668:** В новых дистрибутивах (Ubuntu 24.04+) установка через `pip` вне venv заблокирована. Обязательно используйте `pipx` или виртуальные окружения.
*   **Имена хостов:** Старайтесь использовать осмысленные, читаемые имена в инвентаре (например, `web-prod-01`), вынося реальные IP-адреса в переменную `ansible_host`.
*   **Локальное выполнение:** Для настройки машины, с которой запущен Ansible, используйте `ansible_connection=local` и `hosts: localhost`.

### Смотрите также

*   [Переменные и факты](./PlaybookStructure/variables.md) — глубокое погружение в работу с данными инвентаря.
*   [Динамический инвентарь](./dynamic_inventory.md) — интеграция с облачными провайдерами и CMDB.
*   [Оптимизация производительности](./ansible_performance_tuning.md) — тюнинг SSH и кэширования в `ansible.cfg`.
