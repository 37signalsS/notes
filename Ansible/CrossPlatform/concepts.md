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

## Предварительные требования

Для эффективной разработки кроссплатформенных плейбуков Ansible необходимо выполнение следующих условий:

### Версии и компоненты

- **Ansible Core**: версия 2.10 или выше (рекомендуется 2.14+). С версии 2.10 доступ к фактам осуществляется через глобальный словарь `ansible_facts`.
- **Python на узлах управления**: Python 3.8 или выше (для Ansible 2.14+). Windows: PowerShell 5.1+ и Python 3 (обычно через WSL2 или удаленный SSH).
- **Python на управляемых хостах**: Минимум Python 2.7 или Python 3.6+. Для современных модулей (например, `ansible.builtin.template`) рекомендуется Python 3.6+.

### Необходимые коллекции

Для кроссплатформенных сценариев могут потребоваться дополнительные коллекции:

```bash
# Основные коллекции (обычно предустановлены)
ansible.builtin
ansible.posix

# Для Windows
ansible.windows

# Для дополнительных модулей
community.general
community.windows
```

Установка коллекций:
```bash
ansible-galaxy collection install ansible.windows
ansible-galaxy collection install community.general
```

### Сетевая доступность и аутентификация

- SSH-доступ к Linux/macOS управляемым хостам (порт 22 по умолчанию).
- WinRM или SSH для Windows (рекомендуется SSH для Windows Server 2019+).
- Параметр `become` для выполнения задач с привилегиями root/administrator.

### Сбор фактов

Для кроссплатформенных плейбуков критически важно наличие актуальных фактов. Рекомендуется явный вызов сбора фактов:

```yaml
- name: Сбор фактов
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - '!min'
      - distribution
      - os_family
```

## Основные концепции

### Ключевые принципы разработки

1.  **Разделение логики и данных (Logic vs Data)**: Никогда не используйте жестко заданные пути или имена пакетов в задачах. Выносите их в переменные (`vars/`), специфичные для ОС, сохраняя задачи универсальными.
2.  **Использование словаря фактов**: Рекомендуется использовать синтаксис `ansible_facts['os_family']` вместо устаревшего `ansible_os_family`. Это снижает риск конфликтов с пользовательскими переменными.
3.  **Принцип "Fail Fast"**: Если роль не поддерживает конкретную ОС, добавьте `ansible.builtin.assert` в начало `tasks/main.yml`.
4.  **Предпочтение универсальным модулям**: Используйте `ansible.builtin.package` для базовой установки пакетов (автоматически выбирает `apt`, `dnf`, `apk`, `zypper`). Однако для специфичных параметров (обновление кэша, выбор репозитория) лучше использовать нативные модули (`ansible.builtin.apt`, `ansible.builtin.dnf`) внутри OS-специфичных задач.
5.  **Разделение Unix и Windows**: Windows требует использования специализированных модулей (коллекция `ansible.windows`). Кроссплатформенность Linux/Windows реализуется через `ansible.builtin.include_tasks` на основе `ansible_facts['os_family']`.
6.  **Оптимизация сбора фактов**: Для ускорения работы в кроссплатформенных средах можно ограничить сбор фактов: `gather_subset: ['!all', '!min', 'distribution']`.

### Типичные проблемы кроссплатформенности

При разработке плейбуков для разных ОС возникают специфические трудности:

1. **Различия в именах пакетов**: `apache2` (Debian) vs `httpd` (RedHat), `python3-pip` (Debian) vs `python3-pip` (RedHat) или `python3-pip` (Alpine).
2. **Пути конфигурационных файлов**: `/etc/apache2/` (Debian) vs `/etc/httpd/` (RedHat), `/etc/nginx/sites-available/` (Debian) vs `/etc/nginx/conf.d/` (RedHat).
3. **Управление сервисами**: systemd (большинство современных ОС), SysVinit (старые системы), Upstart (CentOS 6).
4. **Безопасность**: SELinux (RedHat) vs AppArmor (Debian/Ubuntu), разные группы пользователей (`wheel` vs `sudo`).
5. **Сетевые инструменты**: `firewalld` (RedHat) vs `ufw` (Debian) vs `iptables` (универсальный).
6. **Менеджеры зависимостей**: `apt` (Debian) vs `dnf`/`yum` (RedHat) vs `apk` (Alpine) vs `zypper` (SUSE).
7. **Архитектуры**: Различия в доступных архитектурах (x86_64, aarch64, armv7l) и доступности пакетов для них.

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

Директория `defaults/` предназначена для переменных с самым низким приоритетом. Здесь следует определять параметры, которые являются общими для всех ОС или служат безопасными значениями "по умолчанию". Эти значения могут быть легко переопределены в `vars/`, inventory или.extra_vars.

**Пример `defaults/main.yml`:**
```yaml
# Общие настройки приложения
app_port: 8080
app_user: "appuser" # Может быть переопределено в vars/RedHat.yml как "nginx" или в vars/Win32NT.yml как "SYSTEM"
app_log_level: "info"

# Параметры, специфичные для ОС, с значениями по умолчанию
web_server_package: "nginx"
web_server_service: "nginx"
ssl_cert_path: "/etc/ssl/certs"
```

**Приоритет переменных** (от низкого к высокому):
1. `defaults/main.yml` (роли)
2. `vars/main.yml` (роли)
3. Inventory переменные
4. Playbook переменные
5. Extra variables (`-e`)

Это позволяет пользователям переопределять параметры без изменения самой роли.

### Паттерны проектирования кроссплатформенных ролей

Для создания поддерживаемых кроссплатформенных ролей рекомендуется использовать следующие паттерны:

1. **Структура каталогов roles/**:
   ```text
   roles/my_role/
   ├── defaults/
   │   └── main.yml          # Значения по умолчанию
   ├── vars/
   │   ├── Debian.yml        # Переменные для Debian/Ubuntu
   │   ├── RedHat.yml        # Переменные для RHEL/Rocky
   │   ├── Windows.yml       # Переменные для Windows
   │   └── default.yml       # Резервные значения
   ├── tasks/
   │   ├── main.yml          # Точка входа
   │   ├── setup-debian.yml  # Задачи для Debian
   │   ├── setup-redhat.yml  # Задачи для RHEL
   │   └── setup-windows.yml # Задачи для Windows
   ├── templates/
   ├── handlers/
   └── meta/
   ```

2. **Единая точка входа**: `tasks/main.yml` загружает переменные и включает OS-специфичные задачи.
3. **Декларативный подход**: Описывайте желаемое состояние, а не команды для его достижения.
4. **Идемпотентность**: Каждая задача должна быть безопасна для повторного выполнения.
5. **Тестируемость**: Используйте Molecule для проверки на разных платформах.

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

### Сценарий 5: Управление сервисами на разных ОС

Модуль `ansible.builtin.service` автоматически определяет систему инициализации (systemd, SysVinit, OpenRC) и обеспечивает единый интерфейс управления.

```yaml
- name: Обеспечение запуска сервиса Nginx
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: yes
  become: yes

# Для systemd-систем с дополнительными параметрами
- name: Перезагрузка systemd и запуск сервиса
  ansible.builtin.systemd:
    name: my_custom_service
    state: restarted
    daemon_reload: yes
    enabled: yes
  when: ansible_facts['service_mgr'] == 'systemd'
```

### Сценарий 6: Настройка файрвола (firewalld vs ufw)

Разные ОС используют различные инструменты управления файрволом. Рекомендуется использовать модуль `ansible.posix.firewalld` для firewalld и `community.general.ufw` для ufw.

```yaml
# Для RedHat (firewalld)
- name: Открытие порта HTTP в firewalld
  ansible.posix.firewalld:
    port: 80/tcp
    permanent: yes
    state: enabled
    immediate: yes
  when: ansible_facts['os_family'] == 'RedHat'

# Для Debian (ufw)
- name: Разрешение HTTP через ufw
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp
  when: ansible_facts['os_family'] == 'Debian'
```

### Сценарий 7: Управление SELinux/AppArmor

Системы принудительного контроля доступа требуют специфических действий:

```yaml
# Для RedHat (SELinux)
- name: Разрешение веб-серверу сетевые соединения в SELinux
  ansible.posix.seboolean:
    name: httpd_can_network_connect
    state: yes
    persistent: yes
  when: ansible_facts['os_family'] == 'RedHat'

# Для Debian (AppArmor) - через шаблоны профилей
- name: Копирование профиля AppArmor
  ansible.builtin.template:
    src: apparmor_profile.j2
    dest: /etc/apparmor.d/usr.sbin.nginx
    owner: root
    group: root
    mode: '0644'
  when: ansible_facts['os_family'] == 'Debian'
  notify: Reload AppArmor
```

### Сценарий 8: Кроссплатформенное копирование файлов

Использование модуля `ansible.builtin.copy` или `ansible.builtin.template` с учетом различий в правах и.owner:

```yaml
- name: Копирование конфигурационного файла
  ansible.builtin.template:
    src: app.conf.j2
    dest: "{{ config_path }}"
    owner: root
    group: "{{ 'root' if ansible_facts['os_family'] == 'Debian' else 'root' }}"
    mode: '0644'
  notify: Restart Service

# Динамическое определение пути назначения
- name: Установка конфигурации в правильную директорию
  ansible.builtin.template:
    src: nginx.conf.j2
    dest: "{{ '/etc/nginx/sites-available' if ansible_facts['os_family'] == 'Debian' else '/etc/nginx/conf.d' }}/app.conf"
    mode: '0644'
```

## Тестирование кроссплатформенности (Molecule)

Для обеспечения надежности кроссплатформенных ролей используется инструмент **Molecule**.

1.  **Матрица платформ**: В `molecule.yml` описываются все целевые системы (Docker-контейнеры для Linux, Vagrant-боксы для Windows).
2.  **Идемпотентность**: Проверка того, что повторный запуск роли на разных дистрибутивах не вносит изменений (`changed=0`).
3.  **Сценарии верификации**: Использование `ansible.builtin.assert` в сценариях `verify.yml` для подтверждения того, что сервис запущен и корректно настроен на каждой из платформ.

## Валидация и проверка кроссплатформенности

### Методы проверки

1. **Синтаксический анализ**: Всегда запускайте `ansible-playbook --syntax-check playbook.yml` перед выполнением.
2. **Проверка на сухом ходу**: Используйте `--check --diff` для визуализации изменений без их применения.
3. **Тестирование на конкретных хостах**: Запускайте плейбуки на целевых платформах с использованием `--limit`.
4. **Идемпотентность**: Двойной запуск плейбука должен показать `changed=0` на втором проходе.

### Автоматическая верификация

```yaml
- name: Проверка работоспособности сервиса
  ansible.builtin.uri:
    url: "http://localhost:{{ app_port }}/health"
    status_code: 200
  register: health_check
  retries: 5
  delay: 10
  until: health_check.status == 200

- name: Утверждение корректной конфигурации
  ansible.builtin.assert:
    that:
      - health_check.status == 200
      - "'running' in ansible_facts.services['nginx.service'].state"
    fail_msg: "Сервис не прошел проверку работоспособности"
    success_msg: "Сервис работает корректно на {{ ansible_facts['os_family'] }}"
```

## Устранение типичных неполадок

### Проблемы с фактами

- **Симптом**: Задачи выполняются с ошибками из-за отсутствия нужных фактов.
- **Решение**: Убедитесь, что сбор фактов включен (`gather_facts: yes`) и проверьте `ansible_facts` через `debug`.

### Конфликты имен пакетов

- **Симптом**: Задача установки пакета завершается ошибкой на некоторых ОС.
- **Решение**: Используйте условные выражения `when` или выносите имена пакетов в переменные.

### Проблемы с правами доступа

- **Симптом**: Ошибки записи в конфигурационные файлы или запуска сервисов.
- **Решение**: Проверьте параметр `become: yes` и убедитесь, что пользователь имеет необходимые привилегии.

### Различия в путях

- **Симптом**: Задачи не находят конфигурационные файлы на разных дистрибутивах.
- **Решение**: Используйте переменные для путей и проверяйте их существование через `stat`.

### Проблемы с сетевыми настройками

- **Симптом**: Сервисы не могут установить сетевые соединения.
- **Решение**: Проверьте настройки файрвола и SELinux/AppArmor для конкретной ОС.

## Дополнительная информация

- **[Патч-менеджмент (Обновление ОС)](../ansible_patch_management.md)** — стратегии кроссплатформенного обновления в гетерогенных средах.
- [Тестирование ролей с Molecule](../ansible_testing_with_molecule.md) — подробнее о матрицах тестирования.
- [Управление потоком](../PlaybookStructure/flow_control.md) — подробнее об условиях `when` и `assert`.
- [Модули управления пакетами](../Modules/ansible_package_management_modules.md) — сравнение `package`, `apt`, `dnf` и `win_package`.
- [Переменные в Ansible](../PlaybookStructure/variables.md) — приоритеты и типы переменных.
- [Роли: Стратегии проектирования](../Roles/strategies.md) — организация структуры кроссплатформенных ролей.
