# Кроссплатформенные плейбуки Ansible: Концепции

## Определения

- **Кроссплатформенный плейбук (Cross-Platform Playbook)** — сценарий, спроектированный для корректного выполнения на различных операционных системах (ОС) путем адаптации логики и параметров к специфике целевой среды. В контексте Ansible кроссплатформенность означает, что один сценарий способен управлять гетерогенным парком (Linux, macOS, BSD, Windows) без отдельных копий плейбуков.
- **Контрол-нода (Control Node)** — узел, на котором установлен ansible-core и запускаются `ansible-playbook`/`ansible`. Управляемые узлы (Managed Nodes) не требуют установки Ansible.
- **Факты Ansible (`ansible_facts`)** — системные переменные, автоматически собираемые модулем `ansible.builtin.setup` с управляемых узлов. В современных версиях Ansible (2.10+) доступ к фактам осуществляется через глобальный словарь `ansible_facts`, а не через плоскостные переменные `ansible_*`.
- **FQCN (Fully Qualified Collection Name)** — полное имя модуля, включающее пространство имен и коллекцию (например, `ansible.builtin.apt` вместо `apt`). Использование FQCN — современный стандарт, предотвращающий конфликты модулей между коллекциями.
- **Интерпретатор на управляемом узле (Python Interpreter)** — Python, используемый для выполнения программной части модулей на удаленном хосте. По умолчанию ansible-core автоматически обнаруживает подходящий интерпретатор; при необходимости задается переменной инвентаря `ansible_python_interpreter`. Для Windows по протоколу WinRM Python не требуется — используется PowerShell.
- **Become (повышение привилегий)** — механизм выполнения задач от другого пользователя (обычно root/Administrator): `sudo`/`su` на POSIX-системах и `runas` на Windows.
- **Иерархия идентификации системы**:
    - **`ansible_facts['os_family']`** — верхнеуровневое семейство ОС (например, `Debian`, `RedHat`, `Suse`, `Alpine`, `Archlinux`, `Windows`, `Darwin`, `FreeBSD`, `Solaris`, `AIX`, `HP-UX`). Основной ключ для разделения логики.
    - **`ansible_facts['distribution']`** — конкретный дистрибутив (например, `Ubuntu`, `CentOS`, `Fedora`, `Rocky`, `AlmaLinux`, `Debian`, `Alpine`, `MacOSX`).
    - **`ansible_facts['distribution_major_version']`** — мажорная версия ОС (например, `22`, `24` для Ubuntu; `8`, `9` для RHEL/Rocky/Alma; `12`, `13` для Debian).
    - **`ansible_facts['distribution_version']`** — полная версия ОС (например, `22.04`, `9.4`). Полезна, когда нужна точечная градация внутри мажорной версии.
    - **`ansible_facts['distribution_release']`** — кодовое имя релиза (например, `jammy`, `noble`, `bookworm`, `trixie`). Важно для настройки специфичных репозиториев (APT/PPA).
    - **`ansible_facts['architecture']`** — архитектура процессора (например, `x86_64`, `aarch64`, `armv7l`). Необходима при скачивании бинарных файлов.
    - **`ansible_facts['system']`** — тип операционной системы (`Linux`, `Darwin`, `Win32NT`, `FreeBSD`, `SunOS`). Позволяет различать Unix-подобные системы и Windows на самом высоком уровне.
    - **`ansible_facts['pkg_mgr']`** — обнаруженный пакетный менеджер (например, `apt`, `dnf`, `apk`, `zypper`, `pacman`, `homebrew`). Удобен для универсальных задач без проверки семейства.
    - **`ansible_facts['service_mgr']`** — процесс инициализации и механизм управления сервисами (например, `systemd`, `sysvinit`, `openrc`, `runit`, `launchd` на macOS, `bsdinit` на FreeBSD, `smf` на Solaris).
    - **`ansible_facts['selinux']`** — словарь со статусом SELinux (`status`: `enabled`, `disabled`, `permissive`), доступен на RHEL-семействе.

## Предварительные требования

Для эффективной разработки кроссплатформенных плейбуков Ansible необходимо выполнение следующих условий:

### Версии и компоненты

- **ansible-core**: поддерживаемые ветки на текущий момент — **2.19, 2.20, 2.21** (текущая стабильная — 2.21, релиз май 2026). Более старые версии (2.14 и ниже) — EOL, их использование не рекомендуется.
- **Python на контрол-ноде**: для ansible-core 2.20/2.21 — **Python 3.12–3.14** (минимум 3.12); для 2.19 — 3.11–3.13. Контрол-нода на Windows поддерживается только через WSL2.
- **Python на управляемых хостах (POSIX)**: для ansible-core 2.20/2.21 — **Python 3.9–3.14** (минимум 3.9); для 2.19 — минимум 3.8. Python 2.7 и 3.6 не поддерживаются начиная с 2.17.
- **Windows-хосты**: PowerShell 5.1 (ansible-core 2.21 дополнительно поддерживает PowerShell 7.x LTS). При подключении через WinRM Python не требуется; при `ansible_connection=ssh` для Windows Python обязателен.
- **OpenSSH**: на целевых хостах должен быть доступен SSH-сервер (7.0+); для Windows Server 2019+ — роль OpenSSH Server.

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.3]

ansible localhost -m ansible.builtin.setup -a "filter=ansible_os_family*"
# → "ansible_facts": { "os_family": "Darwin" }   (пример для macOS-контрол-ноды)
```

### Необходимые коллекции

`ansible.builtin` входит в состав ansible-core и не устанавливается отдельно. Для кроссплатформенных сценариев обычно требуются дополнительные коллекции:

```yaml
# requirements.yml
collections:
  - name: ansible.posix          # firewalld, seboolean, sysctl, mount, etc.
  - name: ansible.windows        # win_service, win_package, win_user, win_reboot, ...
  - name: community.general      # ufw, homebrew, apparmor, pacman, snap, ...
  - name: community.windows      # win_winget и расширенные win_* модули
```

Установка коллекций:
```bash
ansible-galaxy collection install -r requirements.yml
ansible-galaxy collection install ansible.windows:==2.6.0   # фиксация версии (пример)
```

### Сетевая доступность и аутентификация

- SSH-доступ к Linux/macOS/BSD управляемым хостам (порт 22 по умолчанию).
- WinRM (порты 5985 HTTP / 5986 HTTPS) или SSH для Windows (рекомендуется SSH для Windows Server 2019+).
- Параметр `become` для выполнения задач с привилегиями root/administrator (см. сценарий 10).
- Для Windows при WinRM — настроенные listener и транспорт аутентификации (Basic, Kerberos, NTLM, CredSSP), детали в [ansible_windows_automation.md](../ansible_windows_automation.md).

### Сбор фактов

Для кроссплатформенных плейбуков критически важно наличие актуальных фактов. По умолчанию факты собираются в начале каждого плея (`gather_facts: true`) через модуль `ansible.builtin.setup`. На больших гетерогенных парках рекомендуется ограничивать объем сбора:

```yaml
- name: Сбор фактов
  ansible.builtin.setup:
    gather_subset:
      - '!all'
      - '!min'
      - distribution
      - os_family
      - pkg_mgr
      - service_mgr
```

Если факты отключены (`gather_facts: false`), условные выражения вида `ansible_facts['os_family']` не работают. Для многоэтапных плейбуков этот порядок управляется поведением сбора фактов по плеям и fact-кэшированием (см. [variables.md](../PlaybookStructure/variables.md)).

## Основные концепции

### Как работает идентификация ОС (How it works)

Ansible использует агентскую (agentless) модель: `ansible.builtin.setup` подключается к узлу по SSH/WinRM, выполняет на нем Python (или PowerShell для Windows) и возвращает словарь фактов. Интерпретатор может быть задан явно или обнаружен автоматически:

- Переменная инвентаря `ansible_python_interpreter` — путь к Python на целевом хосте (полностью отключает автообнаружение).
- Ключ `interpreter_python` в `[defaults]` `ansible.cfg` — глобальная настройка (`auto`, `auto_silent`, путь).
- Режим `auto` (по умолчанию с 2.12) ищет интерпретатор по списку распространенных путей и предупреждает, если выбор может измениться после установки другого Python.

Для Windows по WinRM факты собираются через PowerShell без Python; набор фактов Windows отличается от POSIX (например, `ansible_facts['system'] == 'Win32NT'`, отсутствуют сетевые факты Ethernet-типа). Модуль `ansible.builtin.setup` заявлен как поддерживающий Windows-хост.

**Важно про устаревший формат фактов:** `INJECT_FACTS_AS_VARS` (внедрение фактов как плоских переменных `ansible_os_family`, `ansible_distribution` и т.п.) объявлен устаревшим: с ansible-core 2.20 появляются предупреждения, а с версии 2.24 значение по умолчанию станет `false`. Все новые плейбуки обязаны использовать форму `ansible_facts['os_family']`.

### Матрица платформ

Сводная таблица ключевых платформ и соответствующих инструментов управления:

| `os_family` | Примеры дистрибутивов | Пакетный менеджер / модуль | Менеджер сервисов / модуль | Файрвол / модуль | Админ-группа (sudo) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `Debian` | Debian, Ubuntu, Raspberry Pi OS | `apt` — `ansible.builtin.apt` | systemd — `ansible.builtin.systemd` / `service` | `ufw` — `community.general.ufw` | `sudo` |
| `RedHat` | RHEL, Rocky, AlmaLinux, Fedora, Oracle Linux, Amazon Linux | `dnf` (RHEL/Fedora 8+) — `ansible.builtin.dnf`; `yum` (RHEL 7) — `ansible.builtin.yum` | systemd — `ansible.builtin.systemd` | `firewalld` — `ansible.posix.firewalld` | `wheel` |
| `Suse` | SLES, openSUSE, SLED | `zypper` — `ansible.builtin.zypper` | systemd | `firewalld`/`SuSEfirewall2` | `wheel` |
| `Alpine` | Alpine Linux | `apk` — `ansible.builtin.apk` | OpenRC — `ansible.builtin.service` | `iptables` из `community.general.iptables` | `wheel` |
| `Archlinux` | Arch, Manjaro | `pacman` — `community.general.pacman` | systemd | `iptables`/`ufw` | `wheel` |
| `Darwin` | macOS | `homebrew` — `community.general.homebrew`; `pkgutil` | launchd (не systemd!) | PF — нет модуля в базовых коллекциях | `admin` |
| `FreeBSD` | FreeBSD | `pkg` — `community.general.pkgng` | `service` (не systemd) — `ansible.builtin.service` | PF — `community.general.pf` | `wheel` |
| `Windows` | Windows Server, Windows 10/11 | Chocolatey — `community.windows.win_chocolatey`; `win_package` | `ansible.windows.win_service` | `win_firewall_rule` — `ansible.windows.win_firewall_rule` | `Administrators` (become_method `runas`) |

> Таблица отражает типичное состояние; фактическое значение менеджера лучше проверять через факты `ansible_facts['pkg_mgr']` и `ansible_facts['service_mgr']`, а не хардкодить.

### Ключевые принципы разработки

1.  **Разделение логики и данных (Logic vs Data)**: Никогда не используйте жестко заданные пути или имена пакетов в задачах. Выносите их в переменные (`vars/`), специфичные для ОС, сохраняя задачи универсальными.
2.  **Использование словаря фактов**: Обязательно используйте синтаксис `ansible_facts['os_family']` вместо устаревшего плоского формата `ansible_os_family`. Это снижает риск конфликтов с пользовательскими переменными и готовит базу к отключению `INJECT_FACTS_AS_VARS` (по умолчанию `false` в ansible-core 2.24).
3.  **Принцип "Fail Fast"**: Если роль не поддерживает конкретную ОС, добавьте `ansible.builtin.assert` в начало `tasks/main.yml` — так ошибка конфигурации проявится сразу, а не в середине выполнения.
4.  **Предпочтение универсальным модулям**: Используйте `ansible.builtin.package` для базовой установки пакетов (автоматически выбирает `apt`, `dnf`, `apk`, `zypper` и т.д.). Однако для специфичных параметров (обновление кэша, выбор репозитория, DNF-модули) лучше использовать нативные модули (`ansible.builtin.apt`, `ansible.builtin.dnf`) внутри OS-специфичных задач. `package` не поддерживает Windows — для него применяется `ansible.windows.win_package`.
5.  **Разделение Unix и Windows**: Windows требует использования специализированных модулей (коллекции `ansible.windows` и `community.windows`). Кроссплатформенность Linux/Windows реализуется через `ansible.builtin.include_tasks` на основе `ansible_facts['os_family']` или `ansible_facts['system']`.
6.  **Оптимизация сбора фактов**: Для ускорения работы в кроссплатформенных средах ограничьте сбор фактов: `gather_subset: ['!all', '!min', 'distribution', 'os_family']` или отключите его там, где он не нужен.
7.  **Явный интерпретатор Python**: Для узлов с нестандартным Python (RHEL 8 — 3.6, контейнеры, pyenv) задавайте `ansible_python_interpreter` в inventory или `group_vars`, а не полагайтесь на автообнаружение.
8.  **become — тоже платформозависимый**: `sudo` на POSIX и `runas` на Windows имеют разную семантику и настройку (см. сценарий 10).

### Типичные проблемы кроссплатформенности

При разработке плейбуков для разных ОС возникают специфические трудности:

1. **Различия в именах пакетов**: `apache2` (Debian) vs `httpd` (RedHat), `python3-pip` (Debian) vs `python3-pip` (RedHat) vs `py3-pip` (Alpine) vs `python3-pip` (Arch).
2. **Пути конфигурационных файлов**: `/etc/apache2/` (Debian) vs `/etc/httpd/` (RedHat), `/etc/nginx/sites-available/` (Debian) vs `/etc/nginx/conf.d/` (RedHat), `/etc/pki/tls/certs` (RedHat) vs `/etc/ssl/certs` (Debian), пути Homebrew на macOS (`/opt/homebrew` на ARM vs `/usr/local` на Intel).
3. **Управление сервисами**: systemd (большинство современных ОС), SysVinit (старые системы), Upstart (CentOS 6), OpenRC (Alpine), launchd (macOS). Модуль `ansible.builtin.service` абстрагирует большинство из них, но `systemd`-специфичные параметры (`daemon_reload`) доступны только в `ansible.builtin.systemd`.
4. **Безопасность**: SELinux (RedHat) vs AppArmor (Debian/Ubuntu/SUSE), разные группы администраторов (`wheel` vs `sudo` vs `admin`), SELinux boolean'ы и профили AppArmor управляются разными модулями.
5. **Сетевые инструменты**: `firewalld` (RedHat/SUSE) vs `ufw` (Debian/Ubuntu) vs `iptables`/`nftables` (универсальный) vs Windows Firewall.
6. **Менеджеры зависимостей**: `apt` (Debian) vs `dnf`/`yum` (RedHat) vs `apk` (Alpine) vs `zypper` (SUSE) vs `pacman` (Arch) vs Chocolatey/Winget (Windows).
7. **Архитектуры**: Различия в доступных архитектурах (x86_64, aarch64, armv7l) и доступности пакетов/бинарных артефактов для них; macOS ARM vs Intel.
8. **Перевод строк и разделители путей**: POSIX-конфиги используют `\n` и `/`, Windows — `\r\n` и `\`; шаблоны должны адаптироваться (см. сценарий 8).
9. **Наличие Python на узле**: минимальные системы и контейнеры могут не содержать Python вовсе — требуется bootstrap (см. сценарий 9).

### Стратегии разделения логики

#### 1. Динамическое включение задач (`include_tasks`)
Подходит, когда действия для разных ОС кардинально различаются (например, разная структура конфигурационных файлов или методы управления сервисами).

```yaml
# tasks/main.yml
- name: Включение задач для конкретного семейства ОС
  ansible.builtin.include_tasks: "{{ ansible_facts['os_family'] | lower }}.yml"
```

> `include_tasks` вычисляет имя файла во время выполнения и допускает переменные; статический `import_tasks` — нет. Именно поэтому кроссплатформенное включение выполняется через `include_tasks`.

#### 2. Загрузка переменных по фактам (`include_vars`)
Самый эффективный способ. Позволяет использовать один и тот же набор задач, подставляя в них системно-зависимые переменные через поиск `first_found`:

```yaml
# tasks/main.yml
- name: Загрузка переменных для конкретной ОС
  ansible.builtin.include_vars:
    file: "{{ lookup('first_found', params) }}"
    name: os_specific
  vars:
    params:
      files:
        - "{{ ansible_facts['distribution'] }}-{{ ansible_facts['distribution_major_version'] }}.yml"
        - "{{ ansible_facts['distribution'] }}.yml"
        - "{{ ansible_facts['os_family'] }}.yml"
        - "default.yml"
      paths:
        - "../vars"
      skip: true  # не падать, если ни один файл не найден
```

Детальнее о `include_vars`, приоритетах и `first_found` — в [variables.md](../PlaybookStructure/variables.md).

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

Директория `defaults/` предназначена для переменных с самым низким приоритетом. Здесь следует определять параметры, которые являются общими для всех ОС или служат безопасными значениями "по умолчанию". Эти значения могут быть легко переопределены в `vars/`, inventory или через extra-переменные.

**Пример `defaults/main.yml`:**
```yaml
# Общие настройки приложения
app_port: 8080
app_user: "appuser" # Может быть переопределено в vars/RedHat.yml как "nginx" или в vars/Windows.yml как "SYSTEM"
app_log_level: "info"

# Параметры, специфичные для ОС, с значениями по умолчанию
web_server_package: "nginx"
web_server_service: "nginx"
ssl_cert_path: "/etc/ssl/certs"
```

**Приоритет переменных** (от низкого к высокому, упрощенно для ролей; полная иерархия в [variables.md](../PlaybookStructure/variables.md)):
1. `defaults/main.yml` (роли)
2. Inventory-переменные (`group_vars`, `host_vars`)
3. Play-переменные (`vars:` в play)
4. `vars/main.yml` (роли)
5. `include_vars`, `set_fact`, `register`
6. Параметры роли и include-параметры (`role:` / `include_role` / `include_tasks` с `vars:`)
7. Extra-переменные (`-e`) — абсолютный приоритет

> Важно: `vars/main.yml` роли имеет **более высокий** приоритет, чем play-переменные и inventory-переменные, поэтому переопределяемые настройки следует размещать в `defaults/`, а не в `vars/`.

### Паттерны проектирования кроссплатформенных ролей

Для создания поддерживаемых кроссплатформенных ролей рекомендуется использовать следующие паттерны:

1. **Структура каталогов roles/**:
   ```text
   roles/my_role/
   ├── defaults/
   │   └── main.yml          # Значения по умолчанию
   ├── vars/
   │   ├── Debian.yml        # Переменные для Debian/Ubuntu
   │   ├── RedHat.yml        # Переменные для RHEL/Rocky/Alma
   │   ├── Windows.yml       # Переменные для Windows
   │   └── default.yml       # Резервные значения
   ├── tasks/
   │   ├── main.yml          # Точка входа: include_vars + include_tasks
   │   ├── setup-debian.yml  # Задачи для Debian
   │   ├── setup-redhat.yml  # Задачи для RHEL
   │   ├── setup-windows.yml # Задачи для Windows
   │   └── configure.yml     # Универсальные (ОС-независимые) задачи
   ├── templates/
   ├── handlers/
   ├── meta/
   │   └── argument_specs.yml # Валидация входных параметров
   └── molecule/
       └── default/          # Сценарии тестирования Molecule
   ```

2. **Единая точка входа**: `tasks/main.yml` загружает переменные (через `include_vars` + `first_found`) и включает OS-специфичные задачи (через `include_tasks`).
3. **Декларативный подход**: Описывайте желаемое состояние, а не команды для его достижения.
4. **Идемпотентность**: Каждая задача должна быть безопасна для повторного выполнения; повторный запуск роли не должен давать `changed` по перечню задач.
5. **Тестируемость**: Используйте Molecule для проверки на разных платформах и документацию интерфейса через `meta/argument_specs.yml`.

Системные паттерны композиции ролей (Wrapper Role, явные/неявные зависимости) описаны в [strategies.md](../Roles/strategies.md).

## Практические сценарии

### Сценарий 1: Адаптация параметров "на лету" (Linux-фокус)
Использование тернарного оператора для простых различий в именах пакетов или групп. Подходит для точечных различий; для множества различий предпочитайте `include_vars`.

```yaml
- name: Установка веб-сервера
  ansible.builtin.package:
    name: "{{ 'apache2' if ansible_facts['os_family'] == 'Debian' else 'httpd' }}"
    state: present

- name: Определение группы сервиса
  ansible.builtin.set_fact:
    web_group: "{{ (ansible_facts['os_family'] == 'RedHat') | ternary('apache', 'www-data') }}"
```

> Пользователь процесса: RHEL-семейство (Apache — `apache`, nginx — `nginx`), Debian-семейство — `www-data`.

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
Гарантирует, что плейбук не нанесет вред системе, для которой он не тестировался (например, Alpine Linux или Arch Linux). Принцип "Fail Fast".

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

> macOS-замечания: пути Homebrew зависят от архитектуры (`/opt/homebrew` на Apple Silicon, `/usr/local` на Intel), многие операции требуют `become` и могут конфликтовать с SIP. Для Windows при подключении по SSH (в отличие от WinRM) на хосте должен быть установлен Python, а путь к нему задан через `ansible_python_interpreter`.

### Сценарий 5: Управление сервисами на разных ОС

Модуль `ansible.builtin.service` автоматически определяет систему инициализации (systemd, SysVinit, OpenRC) и обеспечивает единый интерфейс управления. Для Windows применяется `ansible.windows.win_service`.

```yaml
- name: Обеспечение запуска сервиса Nginx
  ansible.builtin.service:
    name: nginx
    state: started
    enabled: true
  become: true
  when: ansible_facts['system'] != 'Win32NT'

# Для systemd-систем с дополнительными параметрами
- name: Перезагрузка systemd и запуск сервиса
  ansible.builtin.systemd:
    name: my_custom_service
    state: restarted
    daemon_reload: true
    enabled: true
  when: ansible_facts['service_mgr'] == 'systemd'

# Для Windows
- name: Управление сервисом на Windows
  ansible.windows.win_service:
    name: 'W3SVC'           # IIS World Wide Web
    state: started
    start_mode: auto
  when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 6: Настройка файрвола (firewalld vs ufw)

Разные ОС используют различные инструменты управления файрволом. Рекомендуется использовать модуль `ansible.posix.firewalld` для firewalld и `community.general.ufw` для ufw.

```yaml
# Для RedHat (firewalld)
- name: Открытие порта HTTP в firewalld
  ansible.posix.firewalld:
    port: 80/tcp
    permanent: true
    state: enabled
    immediate: true
  when: ansible_facts['os_family'] == 'RedHat'

# Для Debian (ufw)
- name: Разрешение HTTP через ufw
  community.general.ufw:
    rule: allow
    port: '80'
    proto: tcp
  when: ansible_facts['os_family'] == 'Debian'

# Для Windows
- name: Разрешение HTTP в Windows Firewall
  ansible.windows.win_firewall_rule:
    name: Allow HTTP
    localport: 80
    action: allow
    direction: in
    protocol: tcp
    state: present
    enabled: true
  when: ansible_facts['os_family'] == 'Windows'
```

### Сценарий 7: Управление SELinux/AppArmor

Системы принудительного контроля доступа (MAC) требуют специфических действий. SELinux управляется модулем `ansible.posix.seboolean` (и `community.general.selinux` для fcontext), AppArmor — модулем `community.general.apparmor` (профили и их режимы).

```yaml
# Для RedHat (SELinux)
- name: Разрешение веб-серверу сетевые соединения в SELinux
  ansible.posix.seboolean:
    name: httpd_can_network_connect
    state: true
    persistent: true
  when: ansible_facts['os_family'] == 'RedHat' and ansible_facts['selinux'] is defined and ansible_facts['selinux']['status'] == 'enabled'

# Для Debian (AppArmor) — перевод профиля в режим enforce
- name: Перевод профиля AppArmor в режим enforce
  community.general.apparmor:
    name: usr.sbin.nginx
    state: enforce
  when: ansible_facts['os_family'] == 'Debian'

# Развертывание собственного профиля AppArmor через шаблон
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

### Сценарий 8: Кроссплатформенное копирование файлов, пути и перевод строк

Модули `ansible.builtin.copy`/`ansible.builtin.template` предназначены для POSIX; для Windows используются `ansible.windows.win_copy`/`ansible.windows.win_template`. Пути и владельцы выносятся в OS-специфичные переменные.

```yaml
# vars/Debian.yml
app_conf_path: "/etc/myapp/app.conf"
app_user: "www-data"
app_group: "www-data"

# vars/RedHat.yml
app_conf_path: "/etc/myapp/app.conf"
app_user: "apache"
app_group: "apache"

# vars/Windows.yml
app_conf_path: "C:\\ProgramData\\MyApp\\app.conf"
```

```yaml
- name: Копирование конфигурационного файла (Linux/macOS)
  ansible.builtin.template:
    src: app.conf.j2
    dest: "{{ app_conf_path }}"
    owner: "{{ app_user }}"
    group: "{{ app_group }}"
    mode: '0644'
    newline_sequence: '\n'   # POSIX-конфиги ожидают LF
  when: ansible_facts['system'] != 'Win32NT'
  notify: Restart Service

- name: Копирование конфигурационного файла (Windows)
  ansible.windows.win_template:
    src: app.conf.j2
    dest: "{{ app_conf_path }}"
  when: ansible_facts['system'] == 'Win32NT'
  notify: Restart Service Windows

# Построение пути через фильтр path_join (кросс-платформенный)
- name: Определение пути к файлу лога
  ansible.builtin.set_fact:
    log_path: "{{ [base_dir, 'logs', 'app.log'] | path_join }}"
```

> `win_template` пишет файлы в UTF-8 (по умолчанию без BOM). Если PowerShell-скрипт содержит не-ASCII символы, Windows PowerShell 5.1 может неверно разобрать его без BOM — используйте `output_encoding: utf-8-sig`. В Linux-конфигах параметр `newline_sequence: '\n'` страхует от случайного CRLF, который ломает разбор `systemd`-юнитов, shell-скриптов и т.п.

### Сценарий 9: Python-интерпретатор и bootstrap узлов без Python

Python на целевом узле не всегда предустановлен (минимальные контейнеры, старые дистрибутивы). Без Python не работает ни факт-сбор, ни модули — только `ansible.builtin.raw` и `ansible.builtin.script`, которые выполняют команды через shell. Поэтому bootstrap выполняется в отдельном плеe с `gather_facts: false`, опираясь на группы инвентаря (фактов еще нет):

```yaml
# bootstrap_play.yml
- name: Установка Python перед основным запуском
  hosts: all
  gather_facts: false          # фактов нет — Python еще не установлен
  become: true
  tasks:
    - name: Debian/Ubuntu
      ansible.builtin.raw: apt-get update && apt-get install -y python3
      when: "'debian' in group_names"
    - name: RHEL-семейство
      ansible.builtin.raw: dnf install -y python3
      when: "'rhel' in group_names"
    - name: Alpine
      ansible.builtin.raw: apk add python3
      when: "'alpine' in group_names"

- name: Основной плейбук
  hosts: all
  tasks:
    - name: Теперь доступен полный набор фактов и модулей
      ansible.builtin.package:
        name: htop
        state: present
```

После bootstrap сбор фактов идет штатно. Для узлов с нестандартным интерпретатором явно задайте путь:

```ini
# inventory.ini — группа group_vars/rhel8.yml
[rhel8:vars]
ansible_python_interpreter=/usr/bin/python3
```

```ini
# ansible.cfg — тихое автообнаружение вместо предупреждающего auto
[defaults]
interpreter_python=auto_silent
```

### Сценарий 10: become на разных платформах

Повышение привилегий различается: `sudo`/`su` на POSIX (группы `wheel`/`sudo`/`admin`), `runas` на Windows. На Windows базовые `win_*` модули (сервисы, файрвол, реестр) требуют административных прав через `become`.

```yaml
- name: Установка пакета с привилегиями (POSIX)
  ansible.builtin.package:
    name: htop
    state: present
  become: true
  when: ansible_facts['system'] != 'Win32NT'

- name: Операция с правами администратора (Windows)
  ansible.windows.win_shell: |
    New-Item -ItemType Directory -Path C:\App -Force
  become: true
  become_method: runas
  become_user: Administrator
  vars:
    ansible_become_pass: "{{ vault_admin_password }}"
  when: ansible_facts['os_family'] == 'Windows'
```

> При использовании входов по ключам/без пароля для sudo убедитесь, что у пользователя настроена группа `wheel` (RedHat/SUSE) или `sudo` (Debian/Ubuntu) и правило sudoers. Данные для `ansible_become_pass` храните в Ansible Vault.

### Сценарий 11: Кроссплатформенное управление пользователями и группами

`ansible.builtin.user` не работает на Windows — там применяется `ansible.windows.win_user`. Группа администраторов различается по семейству.

```yaml
- name: Создание пользователя deploy (POSIX)
  ansible.builtin.user:
    name: deploy
    groups: "{{ admin_group }}"
    append: true
    create_home: true
    shell: /bin/bash
  when: ansible_facts['system'] != 'Win32NT'
```

> Группа администратора различается по семейству, поэтому переменную `admin_group` выносят в OS-специфичные `vars/`:
> ```yaml
> # vars/RedHat.yml
> admin_group: "wheel"
> # vars/Debian.yml
> admin_group: "sudo"
> # vars/Darwin.yml
> admin_group: "admin"
> # vars/Windows.yml
> admin_group: "Administrators"
> ```

```yaml
# Windows: создание пользователя и добавление в группу
- name: Добавление пользователя в группу администраторов (Windows)
  ansible.windows.win_user:
    name: deploy
    password: "{{ vault_user_password }}"
    groups:
      - Administrators
    groups_action: add
    state: present
```

#### Дополнение: SSH-ключи, skeletal files и platform-specific окружение

```yaml
# authorized_keys (POSIX)
- name: Размещение SSH-ключа
  ansible.builtin.authorized_key:
    user: "{{ item }}"
    key: "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"
    state: present
  loop: "{{ ssh_users }}"
  when: ansible_facts['system'] != 'Win32NT'

# authorized_keys (Windows через win_shell)
- name: Размещение SSH-ключа (Windows)
  ansible.windows.win_shell: |
    $key = Get-Content -Path "C:\Users\deploy\.ssh\authorized_keys"
    if ($key -notmatch "{{ lookup('file', '~/.ssh/id_rsa.pub') }}") {
      Add-Content -Path "C:\Users\deploy\.ssh\authorized_keys" -Value "{{ lookup('file', '~/.ssh/id_rsa.pub') }}"
    }
  when: ansible_facts['os_family'] == 'Windows'

# Skeletal files (Linux/macOS)
- name: Копирование skeletal-файлов
  ansible.builtin.copy:
    src: "skel/{{ item }}"
    dest: "/etc/skel/{{ item }}"
    owner: root
    group: root
    mode: '0644'
  loop:
    - .bashrc
    - .profile
  when: ansible_facts['system'] != 'Win32NT'

# Профиль по умолчанию (Windows)
- name: Настройка профиля по умолчанию (Windows)
  ansible.windows.win_copy:
    src: "templates\\Default-Profile.ps1"
    dest: "C:\\Users\\Default\\Documents\\WindowsPowerShell\\profile.ps1"
  when: ansible_facts['os_family'] == 'Windows'
```

> **Production note:** на Windows SSH-ключи размещаются в `C:\Users\<user>\.ssh\authorized_keys` (OpenSSH Server) или через реестр (Win32-OpenSSH). `create_home` на POSIX автоматически копирует файлы из `/etc/skel`; на Windows используйте `win_copy` для шаблонов профиля. Для macOS skeletal files находятся в `/System/Library/User Template/` (защищены SIP) или `/Library/User Template/`.

### Сценарий 12: Планировщик задач — cron vs scheduled task

На POSIX планировщик — cron, на Windows — Task Scheduler. Модули не пересекаются.

```yaml
- name: Задача cron (POSIX)
  ansible.builtin.cron:
    name: "Очистка логов"
    minute: "0"
    hour: "3"
    job: "/usr/local/bin/cleanup.sh"
  when: ansible_facts['system'] != 'Win32NT'

- name: Scheduled task (Windows)
  ansible.windows.win_scheduled_task:
    name: cleanup_logs
    description: "Очистка логов"
    actions:
      - path: C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe
        arguments: "-ExecutionPolicy Bypass -File C:\\scripts\\cleanup.ps1"
    triggers:
      - type: daily
        start_boundary: '2026-09-23T03:00:00'
    state: present
    enabled: true
```

### Сценарий 13: Контроль скорости изменений на гетерогенном парке (SRE-подход)

Для снижения радиуса поражения (blast radius) в гетерогенных средах широко используются `serial`, `max_fail_percentage`, `any_errors_fatal`, `--limit` для канареечных групп, а также `--check --diff` перед применением.

```yaml
- name: Поэтапное обновление с ограничением скорости
  hosts: mixed_servers
  serial: 1              # сначала один хост (канареечный)
  max_fail_percentage: 20
  any_errors_fatal: false
  tasks:
    - name: Обновление пакета
      ansible.builtin.package:
        name: "{{ target_pkg }}"
        state: latest
```

```bash
# Проверка изменений на канареечной группе без применения
ansible-playbook site.yml --check --diff --limit canary

# Применение только к канареечной группе
ansible-playbook site.yml --limit canary

# Полный прогон
ansible-playbook site.yml
```

Стратегии массовых обновлений и условных перезагрузок подробно разобраны в [ansible_patch_management.md](../ansible_patch_management.md).

### Сценарий 14: Ветвление по версии дистрибутива и кроссплатформенные операторы

В продакшне часто требуется ветвление внутри одного `os_family` по версии дистрибутива. Ansible предоставляет фильтр `version()` и операторы приведения типов.

```yaml
# Сравнение версий: Ubuntu 22.04+ vs старые
- name: Установка репозитория только для новых Ubuntu
  ansible.builtin.apt_repository:
    repo: "ppa:ondrej/php"
    state: present
  when: 
    - ansible_facts['os_family'] == 'Debian'
    - ansible_facts['distribution_major_version'] | int >= 22

# Сравнение через version() — для точных версий
- name: Настройка только для RHEL 9+
  ansible.builtin.set_fact:
    use_dnf_module: true
  when: ansible_facts['distribution_version'] | version('9.0', '>=')

# Логическое И/ИЛИ в allow/deny-списках
- name: Разрешенные дистрибутивы
  ansible.builtin.assert:
    that:
      - ansible_facts['os_family'] in ['Debian', 'RedHat']
      - ansible_facts['distribution_major_version'] | int >= 12 or ansible_facts['distribution_major_version'] | int >= 8
    fail_msg: "Неподдерживаемая ОС: {{ ansible_facts['distribution'] }} {{ ansible_facts['distribution_version'] }}"

# Тернарный оператор для версионных параметров
- name: Выбор версии Python по ОС
  ansible.builtin.set_fact:
    python_pkg: "{{ (ansible_facts['os_family'] == 'RedHat' and ansible_facts['distribution_major_version'] | int >= 9) | ternary('python3.12', 'python3') }}"

# Приведение типов при сравнении
- name: Проверка архитектуры
  ansible.builtin.assert:
    that:
      - ansible_facts['architecture'] in ['x86_64', 'aarch64']
    fail_msg: "Архитектура {{ ansible_facts['architecture'] }} не поддерживается"
```

> **Production note:** всегда приводите `distribution_major_version` к `int` перед сравнением, иначе происходит строковое сравнение (`'9' > '12'` → `true`). Для точных версий используйте `version()` фильтр.

### Сценарий 15: block/rescue/always и кроссплатформенный откат

`block/rescue/always` позволяет реализовать атомарные изменения с откатом (rollback). В кроссплатформенных плейбуках rescue-действия отличаются по ОС.

```yaml
- name: Атомарное обновление с кроссплатформенным откатом
  block:
    - name: Установка пакета
      ansible.builtin.package:
        name: "{{ pkg_name }}"
        state: present
      notify: Restart Service

    - name: Применение конфигурации
      ansible.builtin.template:
        src: app.conf.j2
        dest: "{{ config_path }}"
      notify: Restart Service

  rescue:
    - name: Откат: удаление пакета (Debian)
      ansible.builtin.apt:
        name: "{{ pkg_name }}"
        state: absent
      when: ansible_facts['os_family'] == 'Debian'

    - name: Откат: откат пакета (RedHat)
      ansible.builtin.dnf:
        name: "{{ pkg_name }}"
        state: downgrade
      when: ansible_facts['os_family'] == 'RedHat'

    - name: Откат: удаление пакета (Windows)
      ansible.windows.win_package:
        path: "{{ pkg_installer_path }}"
        state: absent
      when: ansible_facts['os_family'] == 'Windows'

  always:
    - name: Очистка временных файлов
      ansible.builtin.file:
        path: /tmp/install_temp
        state: absent
      when: ansible_facts['system'] != 'Win32NT'

    - name: Очистка временных файлов (Windows)
      ansible.windows.win_file:
        path: C:\Windows\Temp\install_temp
        state: absent
      when: ansible_facts['system'] == 'Win32NT'

    - name: Уведомление об ошибке
      ansible.builtin.debug:
        msg: "Операция завершилась с ошибкой, выполнен откат на {{ ansible_facts['os_family'] }}"
```

> **Production note:** используйте `meta: clear_host_errors` в `rescue`, если планируете повторную попытку на том же хосте. `block` можно вкладывать внутрь других `block` для каскадного отката.

### Сценарий 16: Кроссплатформенный перезагруз и handlers

Перезагрузка требуется после обновления ядра, изменения сетевых параметров или某些 критичных настроек. Механизмы перезагрузки различаются по платформам.

```yaml
# tasks/main.yml
- name: Проверка необходимости перезагрузки (Linux)
  ansible.builtin.shell: needs-restarting -r
  register: reboot_required
  changed_when: false
  failed_when: false
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Проверка необходимости перезагрузки (Windows)
  ansible.windows.win_shell: |
    if (Get-WURebootStatus -SilentlyContinue) { exit 0 } else { exit 1 }
  register: reboot_required
  changed_when: false
  failed_when: false
  when: ansible_facts['os_family'] == 'Windows'

- name: Проверка необходимости перезагрузки (macOS)
  ansible.builtin.shell: softwareupdate --list 2>/dev/null | grep -q "restart"
  register: reboot_required
  changed_when: false
  failed_when: false
  when: ansible_facts['os_family'] == 'Darwin'

- name: Перезагрузка (Linux)
  ansible.builtin.reboot:
    reboot_timeout: 600
    connect_timeout: 30
    pre_reboot_delay: 10
    post_reboot_delay: 30
  when: 
    - ansible_facts['service_mgr'] == 'systemd'
    - reboot_required.rc == 0
  notify: Verify Reboot

- name: Перезагрузка (Windows)
  ansible.windows.win_reboot:
    reboot_timeout: 600
    pre_reboot_delay: 10
  when: 
    - ansible_facts['os_family'] == 'Windows'
    - reboot_required.rc == 0
  notify: Verify Reboot Windows

- name: Перезагрузка (macOS)
  ansible.builtin.reboot:
    reboot_timeout: 600
    pre_reboot_delay: 10
  when: 
    - ansible_facts['os_family'] == 'Darwin'
    - reboot_required.rc == 0
  notify: Verify Reboot
```

> **Production note:** на Windows `win_reboot` работает только через WinRM (не через SSH). Для macOS `ansible.builtin.reboot` работает через `shutdown -r`, но требует `become`. На Linux `reboot` модуль интегрируется с `systemd` и ждет готовности SSH.

### Сценарий 17: tags в кроссплатформенных плейбуках

`tags` позволяют выборочно запускать задачи в гетерогенном парке. В mixed-средах (Linux + Windows) это особенно полезно для разделения platform-specific логики.

```yaml
# tasks/main.yml
- name: Установка пакетов (POSIX)
  ansible.builtin.package:
    name: "{{ pkg_name }}"
    state: present
  tags: [linux, packages, always]

- name: Установка пакетов (Windows)
  ansible.windows.win_package:
    path: "{{ pkg_installer_path }}"
    state: present
  tags: [windows, packages, always]

- name: Настройка firewall
  ansible.posix.firewalld:
    service: http
    permanent: yes
    state: enabled
  tags: [linux, firewall]
  when: ansible_facts['os_family'] == 'RedHat'
```

```bash
# Запуск только Linux-задач
ansible-playbook site.yml --tags linux

# Запуск только Windows-задач
ansible-playbook site.yml --tags windows

# Пропуск firewall-задач
ansible-playbook site.yml --skip-tags firewall

# Запуск всех задач с тегом always
ansible-playbook site.yml --tags always
```

> **Production note:** теги `always` выполняются даже при `--skip-tags`. Используйте их для критичных задач (создание пользователей, директорий), которые должны runs на всех платформах. Избегайте `tags: always` на platform-specific задачах — это сломает селективный запуск.

### Сценарий 18: changed_when/failed_when в кроссплатформенном контексте

Модули `command` и `shell` всегда возвращают `changed`, что ломает идемпотентность и `--check`. В кроссплатформенных плейбуках условия `changed_when`/`failed_when` должны учитывать различия в выводе команд между ОС.

```yaml
- name: Проверка статуса службы (Linux systemd)
  ansible.builtin.shell: systemctl is-active nginx
  register: service_status
  changed_when: false
  failed_when: 
    - service_status.rc != 0
    - service_status.stdout != "active"
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Проверка статуса службы (Windows)
  ansible.windows.win_shell: |
    $svc = Get-Service -Name W3SVC -ErrorAction SilentlyContinue
    if ($svc.Status -eq 'Running') { exit 0 } else { exit 1 }
  register: service_status
  changed_when: false
  failed_when: service_status.rc != 0
  when: ansible_facts['os_family'] == 'Windows'

- name: Установка пакета с platform-specific changed_when
  ansible.builtin.command: "{{ pkg_manager_cmd }} install -y {{ pkg_name }}"
  register: pkg_result
  changed_when: 
    - "'Installing' in pkg_result.stdout"
    - "'Upgrading' in pkg_result.stdout"
    - "pkg_result.rc == 0"
  failed_when: 
    - pkg_result.rc != 0
    - "'Unable to locate package' in pkg_result.stdout"
  when: ansible_facts['system'] != 'Win32NT'
```

> **Production note:** для `command`/`shell` всегда добавляйте `changed_when: false` на read-only проверки. Для мутационных операций используйте `register` + проверку ключевых слов в `stdout`/`stderr`. На Windows `rc` интерпретируется так же, как на POSIX (0 = success).

### Сценарий 19: delegate_to/run_once в кроссплатформенных плейбуках

`delegate_to` и `run_once` используются для операций, которые должны выполняться один раз или на специфичном хосте, независимо от целевой платформы.

```yaml
- name: Сбор фактов ОС один раз на контрол-ноде
  ansible.builtin.set_fact:
    target_os: "{{ ansible_facts['os_family'] }}"
  run_once: true
  delegate_to: localhost

- name: Скачивание правильного артефакта под целевую ОС
  ansible.builtin.get_url:
    url: "https://releases.example.com/{{ target_os }}/artifact.tar.gz"
    dest: "/tmp/artifact.tar.gz"
  run_once: true
  delegate_to: localhost

- name: Проверка синтаксиса всех плейбуков (один раз)
  ansible.builtin.command: ansible-playbook --syntax-check site.yml
  register: syntax_check
  changed_when: false
  run_once: true
  delegate_to: localhost
  failed_when: syntax_check.rc != 0
```

> **Production note:** `run_once: true` выполняет задачу только на первом хосте в батче. `delegate_to: localhost` перенаправляет выполнение на контрол-ноду. Комбинация идеальна для артефактов, специфичных для целевой ОС, или единых проверок. При использовании `delegate_to` убедитесь, что контрол-нода имеет доступ к нужным ресурсам (интернет, registry).

### Сценарий 20: Кроссплатформенный package: версионирование, lock, hold

Управление версиями и блокировка пакетов существенно различается между ОС. В mixed-парках это один из самых частых источников несовместимости.

```yaml
# Версионирование: platform-specific строки версий
- name: Установка конкретной версии пакета
  ansible.builtin.package:
    name: "{{ pkg_name }}"
    version: "{{ pkg_version[ansible_facts['os_family']] }}"
    state: present
  vars:
    pkg_version:
      Debian: "=1.2.3-1"
      RedHat: "1.2.3-1.el9"

# Lock/hold: предотвращение автоматических обновлений
- name: Блокировка пакета (Debian/Ubuntu)
  ansible.builtin.command: apt-mark hold {{ pkg_name }}
  register: hold_result
  changed_when: "'hold' in hold_result.stdout"
  when: ansible_facts['os_family'] == 'Debian'

- name: Блокировка пакета (RedHat/Fedora)
  ansible.builtin.command: dnf versionlock add {{ pkg_name }}
  register: hold_result
  changed_when: "'Lock' in hold_result.stdout or 'already' in hold_result.stdout"
  when: ansible_facts['os_family'] == 'RedHat'

- name: Блокировка пакета (Windows)
  community.windows.win_chocolatey:
    name: "{{ pkg_name }}"
    state: present
    version: "{{ pkg_version }}"
    pin: yes
  when: ansible_facts['os_family'] == 'Windows'
```

> **Production note:** `apt-mark hold` и `dnf versionlock` — инструменты разных систем. В Debian-семействе `hold` блокирует upgrade; в RedHat-семействе `versionlock` добавляет пакет в `/etc/dnf/plugins/versionlock.list`. На Windows `choco pin` эквивалентен hold. Для снятия блокировки используйте `apt-mark unhold`, `dnf versionlock delete`, `choco unpin`.

### Сценарий 21: Кроссплатформенные handlers с listen/notify

Handlers с `listen` позволяют нескольким задачам triggered один обработчик. В кроссплатформенных плейбуках это обеспечивает unified restart pattern.

```yaml
# handlers/main.yml
- name: Restart Web Service
  ansible.builtin.systemd:
    name: "{{ web_service }}"
    state: restarted
    daemon_reload: yes
  listen: "Restart {{ web_service }}"
  when: ansible_facts['service_mgr'] == 'systemd'

- name: Restart Web Service (Windows)
  ansible.windows.win_service:
    name: "{{ web_service }}"
    state: restarted
  listen: "Restart {{ web_service }}"
  when: ansible_facts['os_family'] == 'Windows'

- name: Reload Firewall
  ansible.posix.firewalld:
    permanent: yes
    state: enabled
  listen: "Reload Firewall"
  when: ansible_facts['os_family'] == 'RedHat'

- name: Reload Firewall (Debian)
  community.general.ufw:
    state: enabled
  listen: "Reload Firewall"
  when: ansible_facts['os_family'] == 'Debian'
```

```yaml
# tasks/main.yml
- name: Развертывание конфигурации
  ansible.builtin.template:
    src: "{{ config_template }}"
    dest: "{{ config_path }}"
  notify: "Restart {{ web_service }}"

- name: Изменение firewall-правил
  ansible.posix.firewalld:
    port: "{{ item }}"
    permanent: yes
    state: enabled
  loop: "{{ firewall_ports }}"
  notify: "Reload Firewall"
  when: ansible_facts['os_family'] == 'RedHat'
```

> **Production note:** `listen` позволяет использовать один и тот же обработчик для разных источников triggered. В примере выше `Restart nginx` может быть triggered изменением конфига Nginx или обновлением пакета. На Windows используйте отдельные handlers с `win_service`; `listen` работает только внутри одной `handlers/main.yml` и не пересекается между platform-specific файлами.

### Сценарий 22: Кроссплатформенный доступ к данным и артефактам

Модули `uri`, `get_url`, `slurp`, `fetch` имеют разные реализации на POSIX и Windows. Подробнее — в [Кроссплатформенный доступ к данным](./ansible_cross_platform_data_retrieval.md).

Краткие паттерны:
- `uri` работает на всех платформах через Python/PowerShell
- `get_url` — на POSIX через urllib, на Windows через `win_get_url` или делегирование
- `slurp`/`fetch` — только на POSIX; для Windows используйте делегирование на контрол-ноду
- Для больших файлов используйте `synchronize` (rsync) вместо `slurp`

```yaml
- name: Health-check (все платформы)
  ansible.builtin.uri:
    url: "http://localhost:{{ app_port }}/health"
    status_code: 200
    timeout: 10
  register: health
  retries: 5
  delay: 10
  until: health.status == 200
```

## Тестирование кроссплатформенности (Molecule)

Для обеспечения надежности кроссплатформенных ролей используется инструмент **Molecule**. Подробные инструкции — в [ansible_testing_with_molecule.md](../ansible_testing_with_molecule.md).

1.  **Матрица платформ**: В `molecule.yml` описываются все целевые системы (Docker-контейнеры для Linux, Vagrant-боксы для Windows).
2.  **Идемпотентность**: Проверка того, что повторный запуск роли на разных дистрибутивах не вносит изменений (`changed=0`).
3.  **Сценарии верификации**: Использование `ansible.builtin.assert` в сценариях `verify.yml` для подтверждения того, что сервис запущен и корректно настроен на каждой из платформ.
4.  **Интеграция в CI**: Прогон `molecule test` и `ansible-lint` в pipeline (например, GitLab CI/GitHub Actions) для каждой матрицы ОС на каждый merge request.

## Операции и команды

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ansible localhost -m ansible.builtin.setup -a "filter=ansible_os_family*"` | Просмотр фактов семейства ОС | `"ansible_facts": { "os_family": "Darwin" }` |
| `ansible all -m ansible.builtin.setup -a "gather_subset=!all,min,distribution"` | Быстрый сбор только фактов дистрибутива на всех хостах | Перечень хостов с фактами |
| `ansible-playbook --syntax-check site.yml` | Проверка синтаксиса | `playbook: site.yml` |
| `ansible-playbook site.yml --check --diff --limit web_servers` | Сухой прогон с диффами | `ok`/`changed` без применения изменений |
| `ansible-playbook site.yml --list-tasks` | Список задач до выполнения | Список задач без выполнения |
| `ansible-inventory --graph --vars` | Граф групп и переменных инвентаря | Дерево групп и переменных хостов |
| `ansible-doc ansible.posix.firewalld` | Справка по модулю | Документация по параметрам модуля |
| `ansible-lint .` | Статический анализ плейбуков/ролей | Отчет о нарушениях правил |
| `ansible-galaxy collection install -r requirements.yml` | Установка коллекций по манифесту | Список установленных коллекций |
| `molecule test` | Прогон тестов роли на матрице платформ | Итог по сценариям (pass/fail) |
| `ansible-playbook site.yml --tags linux --skip-tags windows` | Селективный запуск по платформе | Выполняются только задачи с тегом `linux` |
| `ansible all -m ansible.builtin.shell -a "systemctl is-active nginx"` | Проверка статуса сервиса (systemd) | `active` / `inactive` |
| `ansible windows_servers -m ansible.windows.win_shell -a "Get-Service W3SVC"` | Проверка статуса сервиса (Windows) | `Status: Running` |
| `ansible all -m ansible.builtin.reboot` | Перезагрузка Linux/macOS | Хост перезагружен и доступен |
| `ansible windows_servers -m ansible.windows.win_reboot` | Перезагрузка Windows | Хост перезагружен и доступен |
| `ansible all -m ansible.builtin.uri -a "url=http://localhost/health"` | Кроссплатформенный health-check | HTTP 200 |
| `ansible all -m ansible.builtin.get_url -a "url=https://... dest=/tmp/file"` | Скачивание файла (POSIX) | Файл сохранен |
| `ansible all -m ansible.builtin.slurp -a "src=/etc/hostname"` | Чтение файла в base64 (POSIX) | Base64-контент |
| `ansible all -m ansible.builtin.fetch -a "src=/var/log/app.log dest=/tmp/logs"` | Выгрузка логов на контрол-ноду (POSIX) | Файлы в `/tmp/logs/<host>/` |
| `ansible windows_servers -m ansible.windows.win_get_url -a "url=https://... dest=C:\\Temp\\file"` | Скачивание файла (Windows) | Файл сохранен на хосте |
| `ansible all -m ansible.builtin.command -a "apt-mark hold pkg"` | Блокировка пакета (Debian) | `pkg hold` |
| `ansible all -m ansible.builtin.command -a "dnf versionlock add pkg"` | Блокировка пакета (RedHat) | Пакет в versionlock |
| `ansible windows_servers -m community.windows.win_chocolatey -a "name=pkg pin=yes"` | Блокировка пакета (Windows) | Пакет закреплен |

## Валидация и проверка кроссплатформенности

### Методы проверки

1. **Синтаксический анализ**: Всегда запускайте `ansible-playbook --syntax-check playbook.yml` перед выполнением.
2. **Проверка на сухом ходу**: Используйте `--check --diff` для визуализации изменений без их применения.
3. **Тестирование на конкретных хостах**: Запускайте плейбуки на целевых платформах с использованием `--limit` (по одной платформе из матрицы).
4. **Идемпотентность**: Двойной запуск плейбука должен показать `changed=0` на втором проходе.
5. **Drift-аудит**: Периодический запуск `--check` как «ревизия» конфигурации: любое отличие от желаемого состояния сигнализирует о дрейфе.

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

## Граничные случаи и ограничения

- **Узлы без Python**: минимальные образы, container'ы и старые дистрибутивы могут не содержать Python. До установки доступны только `raw`/`script`; требуют bootstrap (сценарий 9).
- **Старые дистрибутивы вне поддержки**: CentOS 7, RHEL 7, Debian 9/EOL-версии не покрываются современными ansible-core (отсутствует совместимый Python). Для унаследованных систем либо используйте старые ветки ansible-core, либо `raw`-адаптеры и `ansible_python_interpreter` на системный Python.
- **RHEL 8 и модуль `dnf`**: начиная с ansible-core 2.17 модуль `ansible.builtin.dnf` не работает на RHEL 8 без Python 3.9+ (проблема python-привязок DNF). Рабочий вариант — установить на RHEL 8 python39 (`dnf module install python39`) или держать узел на ansible-core 2.21, где поддержка восстановлена при наличии Python 3.9+.
- **Windows-факты ограничены**: набор фактов для Windows меньше, чем для POSIX (нет сетевых/аппаратных фактов в том же объеме), `os_family == 'Windows'`, `system == 'Win32NT'`. Условные переходы лучше строить на `os_family`/`system`.
- **SSH vs WinRM для Windows**: при `ansible_connection=ssh` на Windows требуется Python (путь задают через `ansible_python_interpreter`, например `C:\Python311\python.exe`); при WinRM Python не нужен.
- **`become` на Windows**: только `become_method: runas` (не `sudo`); пароль администратора передается через `ansible_become_pass`. Многие `win_*` модули административные — без `become` вернут `Access denied`.
- **`--check` поддерживается не всеми модулями**: `command`/`shell` не прогнозируют изменения; для предсказуемости используйте `register` + `changed_when`, а самопроверяемые задачи выносите в `verify`-сценарии. У модулей, не поддерживающих check mode, задание будет пропущено с предупреждением — учтите в валидации.
- **Alpine и BusyBox**: `os_family == 'Alpine'`, используется OpenRC, а не systemd; некоторые модули и сценарии, завязанные на systemd/Python-библиотеки, требуют адаптации.
- **macOS**: `os_family == 'Darwin'`, менеджер сервисов — launchd (не systemd); пути Homebrew отличаются между Intel и Apple Silicon; SIP ограничивает изменения защищенных разделов (в т.ч. `/usr/local/bin`).
- **`package` и специфика**: универсальный `package` не покрывает специфичные параметры (`apt purge`, `dnf` module streams, `zypper patch`) и не работает на Windows — для них используйте нативные модули.
- **Кроссплатформенное включение — только через `include_*`**: `import_tasks` не принимает динамические имена файлов из переменных — ошибка `'import_tasks' does not accept a dynamic filename`.
- **Идемпотентность shell-задач**: без `changed_when` модули `command`/`shell` всегда возвращают `changed`, что ломает идемпотентность-проверки и сухие прогоны.
- **Окончания строк**: CRLF в POSIX-конфигах (скрипты, systemd-юниты, crontab) приводит к ошибкам разбора; LF в PowerShell-скриптах. Используйте `newline_sequence` и `win_template`.
- **Факты на больших парках**: полный сбор фактов на гетерогенной флоте медленный. Используйте `gather_subset`, `gather_facts: false` и fact-кэширование.

## Рекомендации и лучшие практики

- **Всегда словарь `ansible_facts[...]`**: сплошной переход на автономные переменные `ansible_*` не требуется, но новые обращения к фактам — только через dict-форму (готовит базу к `INJECT_FACTS_AS_VARS=false` в ansible-core 2.24).
- **FQCN везде**: `ansible.builtin.*`, `ansible.posix.*`, `ansible.windows.*` — исключает конфликты модулей из разных коллекций.
- **OS-специфичные переменные**: `vars/<family>.yml` + `include_vars` с цепочкой `first_found` (`distribution-major` → `distribution` → `os_family` → `default`). В `defaults/` — безопасные значения по умолчанию.
- **Fail-fast**: `assert` в начале `tasks/main.yml` о поддержке ОС; `argument_specs.yml` — валидация входных параметров роли.
- **Нативные модули для нюансов**: `package` — для простых установок; `apt`/`dnf`/`zypper`/`apk` — там, где нужны специфические флаги и репозитории.
- **Инвентарь как код**: inventory, `group_vars`/`host_vars` и `requirements.yml` под версионированием (version control); фиксируйте версии коллекций.
- **Изоляция изменений**: `--check --diff` в CI, `--limit` для канареечных групп, `serial`/`max_fail_percentage` для массовых операций.
- **Идемпотентность**: контроль `changed=0` при повторном запуске; для `command`/`shell` — `register` + `changed_when`/`failed_when`.
- **Хендлеры**: перезапуск сервисов только при изменении конфигурации; на Windows — отдельные хендлеры с `win_service`.
- **Тестирование**: Molecule с матрицей платформ + `ansible-lint` в pipeline на каждый merge request.
- **Секреты**: пароли become и WinRM/SSH — только через Ansible Vault, не в плейбуках.
- **Факт-кэш**: включайте `fact_caching` (например, `jsonfile`) для сокращения времени прогона на больших парках.
- **Безопасный интерпретатор**: для флота с разными Python задавайте `ansible_python_interpreter` в группах инвентаря или `interpreter_python=auto_silent`.
- **Стратегия выполнения**: `linear` по умолчанию; переключайтесь на `free` только для независимых хостов. Используйте `serial` + `max_fail_percentage` для контролируемого rollout.
- **Throttle для внешних API**: ограничивайте конкурентность задач, обращающихся к внешним сервисам, через `throttle`.
- **SSH-тюнинг**: включите `pipelining = True` и `ControlPersist = 3600s` для ускорения на 30–50%.
- **Check Mode в CI**: добавляйте `check_mode: false` к read-only валидациям (`nginx -t`, `curl /health`), чтобы они работали в `--check`.
- **Async для длительных операций**: используйте `async` + `poll: >0` для критичных задач; `poll: 0` теряется при перезапуске Control Node.
- **Теги для селективного деплоя**: `--tags linux --skip-tags windows` для mixed-парков. Избегайте `tags: always` на platform-specific задачах.
- **Host patterns**: создавайте OS-группы через `group_by` и используйте `--limit os_Debian` для точечного деплоя.
- **Fact caching**: включайте для парков >100 хостов. Используйте раздельные каталоги для prod/staging/dev.

## Дополнительная информация

- [Кроссплатформенный LAMP/LEMP-пример](./lamp-example.md) — полный практический разбор кроссплатформенной роли.
- [Кроссплатформенное выполнение](./ansible_cross_platform_execution_flow.md) — `strategy`, `serial`, `throttle`, `check_mode`, `async`, `tags`, `--limit` в mixed-парках.
- [Кроссплатформенный инвентарь и факты](./ansible_cross_platform_inventory_and_facts.md) — динамический инвентарь, constructed plugin, host patterns, fact caching.
- [Кроссплатформенные соединения](./ansible_cross_platform_connection.md) — SSH-тюнинг, WinRM, bastion, connection plugins.
- [Кроссплатформенная конфигурация системы](./ansible_cross_platform_system_config.md) — `sysctl`, NTP/timezone, systemd timers, логи, файловые системы.
- [Кроссплатформенный откат и drift detection](./ansible_cross_platform_rollback_testing_drift.md) — rollback стратегии, canary, drift detection в CI/CD, Molecule.
- [Переменные и факты в Ansible](../PlaybookStructure/variables.md) — полная иерархия приоритетов переменных и работа с `ansible_facts`.
- [Автоматизация Windows через Ansible](../ansible_windows_automation.md) — настройка WinRM, модули `win_*`, безопасность.
- [Кроссплатформенный доступ к данным](./ansible_cross_platform_data_retrieval.md) — `uri`, `get_url`, `slurp`, `fetch` в гетерогенных средах.