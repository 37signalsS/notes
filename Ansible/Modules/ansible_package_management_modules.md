# Ansible: Модули управления пакетами

## Определения

**Модули управления пакетами** — это инструменты Ansible для установки, обновления и удаления программного обеспечения на управляемых хостах. Они абстрагируют работу системных пакетных менеджеров (APT, YUM, DNF, APK и др.), обеспечивая декларативный способ управления составом ПО.

## Основные концепции

### Типы модулей

1.  **Универсальные (`package`)**: Пытаются автоматически определить системный менеджер пакетов. Удобны для кроссплатформенных задач, но поддерживают только базовые параметры (`name`, `state`).
2.  **Нативные (`apt`, `yum`, `dnf`)**: Специфичны для конкретных ОС. Предоставляют полный контроль над возможностями менеджера (управление кэшем, репозиториями, исключениями).
3.  **Языковые (`pip`, `npm`, `gem`)**: Управляют библиотеками и пакетами внутри конкретных экосистем программирования.
4.  **Управление репозиториями (`apt_repository`, `yum_repository`)**: Позволяют добавлять сторонние источники ПО и GPG-ключи.

### Идемпотентность
Все модули управления пакетами являются идемпотентными: если пакет уже установлен в требуемом состоянии (`present`, `latest`, `absent`), повторный запуск задачи не внесет изменений.

### Сравнение универсального и нативных модулей

| Характеристика | `package` (универсальный) | `apt` / `yum` / `dnf` (нативные) |
| :--- | :--- | :--- |
| **Простота** | Высокая (один модуль для всех ОС) | Средняя (нужна условная логика) |
| **Функциональность** | Базовая | Полная (кэш, репозитории, версии) |
| **Надежность** | Средняя | Высокая (предсказуемое поведение) |
| **Рекомендация** | Простые задачи, быстрые прототипы | Production-окружения, сложные роли |

## Практические сценарии

### Системные пакеты (Debian/Ubuntu)

Использование `apt` с обновлением кэша.

```yaml
- name: Установка Nginx с обновлением кэша
  ansible.builtin.apt:
    name: nginx
    state: latest
    update_cache: yes
    cache_valid_time: 3600 # Обновлять кэш, только если он старше 1 часа
```

### Системные пакеты (RHEL/CentOS/Fedora)

Для современных систем (RHEL 8+, Fedora) рекомендуется использовать `dnf`, для старых — `yum`.

```yaml
- name: Установка Apache через DNF
  ansible.builtin.dnf:
    name: httpd
    state: present
```

### Управление репозиториями

Добавление стороннего источника (на примере Docker для Ubuntu).

```yaml
- name: Добавление GPG-ключа Docker
  ansible.builtin.apt_key:
    url: https://download.docker.com/linux/ubuntu/gpg
    state: present

- name: Добавление репозитория Docker
  ansible.builtin.apt_repository:
    repo: deb [arch=amd64] https://download.docker.com/linux/ubuntu {{ ansible_distribution_release }} stable
    state: present
```

### Языковые пакеты (Python/Node.js)

```yaml
- name: Установка Python-библиотеки в virtualenv
  ansible.builtin.pip:
    name: requests
    virtualenv: /opt/venv

- name: Глобальная установка пакета npm
  community.general.npm:
    name: pm2
    global: yes
```

### Получение информации об установленных пакетах

```yaml
- name: Сбор фактов об установленных пакетах
  ansible.builtin.package_facts:
    manager: auto

- name: Проверка наличия пакета в фактах
  ansible.builtin.debug:
    msg: "Пакет curl установлен"
  when: "'curl' in ansible_facts.packages"
```

## Дополнительная информация

*   [Официальная документация: модули управления пакетами](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html#plugins-in-ansible-builtin)
*   [Кроссплатформенные плейбуки](../CrossPlatform/concepts.md)
*   [Переменные и факты](../PlaybookStructure/variables.md)
*   [Обзор часто используемых модулей](ansible_modules_overview.md)
