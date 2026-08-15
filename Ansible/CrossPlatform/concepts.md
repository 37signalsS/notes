# Кроссплатформенные плейбуки Ansible: Концепции

## Определения

- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий, спроектированный для корректного выполнения на различных операционных системах (ОС) путем адаптации логики и параметров к специфике целевой среды.
- **Факты Ansible (`ansible_facts`)** — системные переменные, автоматически собираемые модулем `ansible.builtin.setup` с управляемых узлов. В современных версиях Ansible (2.10+) доступ к фактам осуществляется через глобальный словарь `ansible_facts`.
- **FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `ansible.builtin.apt` вместо `apt`). Использование FQCN — современный стандарт, предотвращающий конфликты модулей.
- **Иерархия идентификации системы**:
    - **`ansible_facts['os_family']`** — верхнеуровневое семейство ОС (например, `Debian`, `RedHat`, `Suse`, `Windows`, `Darwin`). Основной ключ для разделения логики.
    - **`ansible_facts['distribution']`** — конкретный дистрибутив (например, `Ubuntu`, `CentOS`, `Fedora`, `Rocky`, `Alpine`).
    - **`ansible_facts['distribution_major_version']`** — мажорная версия ОС (например, `22`, `24` для Ubuntu; `8`, `9` для RHEL/Rocky).
    - **`ansible_facts['distribution_release']`** — кодовое имя релиза (например, `focal`, `jammy`, `bullseye`). Важно для настройки специфичных репозиториев (APT/PPA).
    - **`ansible_facts['architecture']`** — архитектура процессора (например, `x86_64`, `aarch64`, `armv7l`). Необходима при скачивании бинарных файлов.
    - **`ansible_facts['system']`** — тип операционной системы (`Linux`, `Darwin`, `Win32NT`). Позволяет различать Unix-подобные системы и Windows на самом высоком уровне.

## Основные концепции

### Ключевые принципы разработки

1.  **Разделение логики и данных (Logic vs Data)**: Никогда не используйте жестко заданные пути или имена пакетов в задачах. Выносите их в переменные (`vars/`), специфичные для ОС, сохраняя задачи универсальными.
2.  **Использование словаря фактов**: Рекомендуется использовать синтаксис `ansible_facts['os_family']` вместо устаревшего `ansible_os_family`. Это снижает риск конфликтов с пользовательскими переменными.
3.  **Принцип "Fail Fast"**: Если роль не поддерживает конкретную ОС, добавьте `ansible.builtin.assert` в начало `tasks/main.yml`.
4.  **Предпочтение универсальным модулям**: Используйте `ansible.builtin.package` для базовой установки пакетов (автоматически выбирает `apt`, `dnf`, `apk`, `zypper`). Однако для специфичных параметров (обновление кэша, выбор репозитория) лучше использовать нативные модули (`ansible.builtin.apt`, `ansible.builtin.dnf`) внутри OS-специфичных задач.
5.  **Разделение Unix и Windows**: Windows требует использования специализированных модулей (коллекция `ansible.windows`). Кроссплатформенность Linux/Windows реализуется через `ansible.builtin.include_tasks` на основе `ansible_facts['os_family']`.
6.  **Оптимизация сбора фактов**: Для ускорения работы в кроссплатформенных средах можно ограничить сбор фактов: `gather_subset: ['!all', '!min', 'distribution']`.

### Стратегии разделения логики

#### 1. Динамическое включение задач (`include_tasks`)
Подходит, когда действия для разных ОС кардинально различаются (например, разная структура конфигурационных файлов или методы управления сервисами).

```yaml
# tasks/main.yml
- name: Включение задач для конкретного семейства ОС
  ansible.builtin.include_tasks: "{{ ansible_facts['os_family'] | lower }}.yml"
```

#### 2. Загрузка переменных по фактам (`include_vars`)
Самый эффективный способ. Позволяет использовать один и тот же набор задач, подставляя в них системно-зависимые переменные через паттерн `with_first_found`.

```yaml
# tasks/main.yml
- name: Загрузка переменных для конкретной ОС
  ansible.builtin.include_vars: "{{ item }}"
  with_first_found:
    - files:
        - "{{ ansible_facts['distribution'] }}-{{ ansible_facts['distribution_major_version'] }}.yml"
        - "{{ ansible_facts['distribution'] }}.yml"
        - "{{ ansible_facts['os_family'] }}.yml"
        - "default.yml"
      paths: ["../vars"]
```

#### 3. Группировка хостов через `group_by`
Динамическое создание групп хостов на основе фактов, удобно для применения специфичных плеев (plays) в рамках одного плейбука.

```yaml
- name: Группировка по семейству ОС
  ansible.builtin.group_by:
    key: "os_{{ ansible_facts['os_family'] }}"

# В этом же плейбуке ниже:
- hosts: os_Debian
  tasks:
    - name: Задача только для Debian
      ansible.builtin.apt:
        name: ufw
        state: present
```

### Использование значений по умолчанию (`defaults`)

Директория `defaults/` предназначена для переменных с самым низким приоритетом. Здесь следует определять параметры, которые являются общими для всех ОС или служат безопасными значениями "по умолчанию".

**Пример `defaults/main.yml`:**
```yaml
app_port: 8080
app_user: "appuser" # Может быть переопределено в vars/RedHat.yml как "nginx" или в vars/Win32NT.yml как "SYSTEM"
```

## Практические сценарии

### Сценарий 1: Адаптация параметров "на лету" (Linux-фокус)
Использование тернарного оператора для простых различий в именах пакетов или групп.

```yaml
- name: Установка веб-сервера
  ansible.builtin.package:
    name: "{{ 'apache2' if ansible_facts['os_family'] == 'Debian' else 'httpd' }}"
    state: present

- name: Определение группы сервиса
  ansible.builtin.set_fact:
    web_group: "{{ (ansible_facts['os_family'] == 'RedHat') | ternary('nginx', 'www-data') }}"
```

### Сценарий 2: Кроссплатформенная проверка путей
Использование модуля `ansible.builtin.stat` для проверки существования директорий, которые могут отличаться в разных дистрибутивах (например, `/etc/apache2` vs `/etc/httpd`).

```yaml
- name: Проверка директории конфигурации
  ansible.builtin.stat:
    path: "{{ config_dir }}"
  register: dir_check

- name: Создание конфига, если путь валиден
  ansible.builtin.template:
    src: config.j2
    dest: "{{ config_dir }}/app.conf"
    mode: '0644'
  when: dir_check.stat.exists and dir_check.stat.isdir
```

### Сценарий 3: Блокировка неподдерживаемых систем
Гарантирует, что плейбук не нанесет вред системе, для которой он не тестировался (например, Alpine Linux или Arch Linux).

```yaml
- name: Проверка поддержки ОС
  ansible.builtin.assert:
    that:
      - ansible_facts['os_family'] in ['Debian', 'RedHat', 'Windows']
    fail_msg: "Данная роль не поддерживает {{ ansible_facts['os_family'] }}"
```

### Сценарий 4: Специфика Windows и macOS
Пример разделения задач для систем, отличных от Linux.

```yaml
# tasks/main.yml
- name: Установка софта на macOS через Homebrew
  community.general.homebrew:
    name: wget
    state: present
  when: ansible_facts['os_family'] == 'Darwin'

- name: Установка пакета на Windows
  ansible.windows.win_package:
    path: http://example.com/installer.msi
    state: present
  when: ansible_facts['os_family'] == 'Windows'
```

## Тестирование кроссплатформенности (Molecule)

Для обеспечения надежности кроссплатформенных ролей используется инструмент **Molecule**.

1.  **Матрица платформ**: В `molecule.yml` описываются все целевые системы (Docker-контейнеры для Linux, Vagrant-боксы для Windows).
2.  **Идемпотентность**: Проверка того, что повторный запуск роли на разных дистрибутивах не вносит изменений (`changed=0`).
3.  **Сценарии верификации**: Использование `ansible.builtin.assert` в сценариях `verify.yml` для подтверждения того, что сервис запущен и корректно настроен на каждой из платформ.

## Дополнительная информация

- **[Патч-менеджмент (Обновление ОС)](../ansible_patch_management.md)** — стратегии кроссплатформенного обновления в гетерогенных средах.
- [Тестирование ролей с Molecule](../ansible_testing_with_molecule.md) — подробнее о матрицах тестирования.
- [Управление потоком](../PlaybookStructure/flow_control.md) — подробнее об условиях `when` и `assert`.
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — сравнение `package`, `apt`, `dnf` и `win_package`.
- [Переменные в Ansible](../PlaybookStructure/variables.md) — приоритеты и типы переменных.
- [Роли: Стратегии проектирования](../Roles/strategies.md) — организация структуры кроссплатформенных ролей.
