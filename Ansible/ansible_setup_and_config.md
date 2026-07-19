# Ansible — установка и настройка

## Определения

**Узел управления (Control Node)** — машина, на которой установлен Ansible. С неё запускаются команды и плейбуки. Требует наличия Python. На Control Node нельзя использовать Windows (только Linux/macOS или WSL2).

**Управляемый узел (Managed Node)** — целевой сервер, управляемый через Ansible. Не требует установки агента Ansible, достаточно SSH-доступа и Python.

**Инвентарь (Inventory)** — файл или скрипт, содержащий список управляемых узлов, их группировку и переменные подключения.

**Конфигурационный файл (ansible.cfg)** — файл настроек поведения самого Ansible (пути, параметры подключения, оптимизация).

**Плагин подключения (Connection Plugin)** — компонент, реализующий способ связи с узлом (SSH, Local, Docker, WinRM).

## Основные концепции

### Конфигурация Ansible (ansible.cfg)

Ansible ищет файл конфигурации в строгом порядке приоритета. Используется **первый найденный** файл:

1.  **Переменная `ANSIBLE_CONFIG`** — указывает путь к конкретному файлу.
2.  **`ansible.cfg`** в текущем рабочем каталоге (рекомендуется для проектов).
3.  **`~/.ansible.cfg`** в домашнем каталоге пользователя.
4.  **`/etc/ansible/ansible.cfg`** — системный конфиг по умолчанию.

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

Для проверки структуры инвентаря используйте команду:
`ansible-inventory -i inventory.yml --graph`

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
    `ansible-config init --disabled > ansible.cfg`

2.  **Проверка текущих настроек:**
    `ansible-config dump --only-changed` — покажет только те параметры, которые отличаются от значений по умолчанию.

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
```
Всегда обращайтесь к фактам через словарь `ansible_facts`:
`{{ ansible_facts['distribution'] }}` (вместо устаревшего `{{ ansible_distribution }}` ).

### Современные инструменты: Navigator

**Ansible Navigator** — современный TUI (Terminal User Interface) и CLI для запуска плейбуков и работы с **Execution Environments (EE)**.
```bash
ansible-navigator run site.yml -i inventory.yml --mode stdout
```

## Дополнительная информация

### Рекомендации

*   **PEP 668:** В новых дистрибутивах (Ubuntu 24.04+) установка через `pip` вне venv заблокирована. Используйте `pipx` или виртуальные окружения.
*   **Имена хостов:** Старайтесь использовать осмысленные имена в инвентаре, вынося IP-адреса в `ansible_host`.
*   **Локальное выполнение:** Для настройки машины, с которой запущен Ansible, используйте `ansible_connection=local`.

### Смотрите также

*   [Переменные и факты](./PlaybookStructure/variables.md) — глубокое погружение в данные.
*   [Динамический инвентарь](./dynamic_inventory.md) — интеграция с облаками.
*   [Оптимизация производительности](./ansible_performance_tuning.md) — тюнинг `ansible.cfg`.
*   [Рекомендации по безопасности](./ansible_security_best_practices.md) — `become`, `vault` и права доступа.
