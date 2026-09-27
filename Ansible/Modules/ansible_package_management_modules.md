# Ansible: Модули управления пакетами

## Определения

**Модули управления пакетами** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для автоматизации жизненного цикла программного обеспечения на управляемых хостах. Они абстрагируют команды системных пакетных менеджеров, обеспечивая единообразный способ установки, обновления и удаления ПО.

**Абстракция менеджера (модуль `package`)** — универсальный интерфейс, который автоматически определяет тип ОС и вызывает соответствующий нативный модуль (`apt`, `dnf`, `zypper`, `apk` и др.). Это удобно для кроссплатформенных плейбуков, но ограничивает доступ к специфичным функциям (например, `purge` в `apt` или модульность в `dnf`).

**FQCN (Fully Qualified Collection Name)** — обязательный стандарт именования модулей (например, `ansible.builtin.apt`), предотвращающий конфликты с модулями из сторонних коллекций и обеспечивающий стабильность выполнения.

**Идемпотентность** — свойство модулей гарантировать, что повторное выполнение задачи с одинаковыми параметрами не приводит к дополнительным изменениям в системе. Достигается через параметр `state` и внутреннюю логику сравнения желаемого и фактического состояния пакета.

### Версионирование и требования

| Компонент | Минимальная версия | Рекомендуемая версия |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ |
| **Python** (control node) | 3.12+ | 3.14 |
| **Python** (managed node) | 3.9+ | 3.12+ |
| **openssh-server** (целевые хосты) | 7.0+ | Актуальная LTS |
| **sudo** (целевые хосты) | 1.8+ | Актуальная LTS |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

ansible all -m ping
```

### Возвращаемые данные (Return Values)

Все модули пакетов возвращают стандартный набор данных:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `stdout` | string | Стандартный вывод команды пакетного менеджера |
| `stderr` | string | Стандартный поток ошибок |
| `rc` | integer | Код возврата команды (0 = успех) |
| `changed` | boolean | Были ли произведены изменения |
| `cache_updated` | boolean | Был ли обновлен кэш (для `apt`/`dnf`) |
| `diff` | dict | Различия до и после выполнения (если включен `--diff`) |

## Основные концепции и архитектура

### Принцип работы модулей управления пакетами

Модули управления пакетами в Ansible реализуют двухуровневую архитектуру:

1. **Уровень абстракции (Universal Layer)**: Модуль `ansible.builtin.package` определяет факты о целевом хосте (`ansible_facts`) — дистрибутив, версию ОС, архитектуру — и на их основе делегирует вызов нативному модулю. Это обеспечивает кроссплатформенность, но со стандартизированным набором параметров.

2. **Уровень нативных модулей (Native Layer)**: Каждый дистрибутив имеет свой специализированный модуль (`ansible.builtin.apt`, `ansible.builtin.dnf`, `ansible.builtin.yum`, `ansible.builtin.zypper`, `ansible.builtin.apk` и др.), который предоставляет доступ ко всем специфичным возможностям пакетного менеджера (модули DNF5, purge в APT, индексы Zypper, Alpine `apk`).

Жизненный цикл выполнения задачи управления пакетом:

```
Задача (Task) → Модуль (Module) → Проверка фактов → Вызов пакетного менеджера →
Обработка возвращаемых данных → Применение идемпотентности → Результат (changed/failed)
```

### DNF4 и DNF5: два модуля, один менеджер пакетов

DNF5 — не «модульная поддержка внутри `dnf`», а **отдельный модуль** `ansible.builtin.dnf5` со своим бэкендом на библиотеке `python3-libdnf5`. Это ключевой момент, который часто понимают неверно.

| Аспект | `ansible.builtin.dnf` | `ansible.builtin.dnf5` |
| :--- | :--- | :--- |
| Библиотека на хосте | `python3-dnf` | **`python3-libdnf5`** |
| Добавлен в ansible-core | давно | **2.15** |
| Где применяется | RHEL 8, Fedora до 40 | RHEL 9/10, Fedora 41+ |
| `enablerepo` / `disablerepo` | Да | **Нет** (параметр отсутствует) |
| `download_dir` | Да | **Нет** |
| `installroot` | Нет | **Да** (относительно него ставятся все пакеты, по умолчанию `/`) |
| `disable_gpg_check` | Нет | **Да** (список значений) |
| `disable_excludes` | Только `all` | `all`, `main` или конкретный `repoid` |
| `security=yes` | Да | Да (в актуальных версиях) |
| `auto_install_module_deps` | Нет | Да (с ansible-core 2.19) |
| `lock_timeout` | Пробрасывает таймаут в dnf | **No-op**: у dnf5 нет такой CLI-опции |
| `install_repoquery` | Устарел, **удалён в 2.20** | Устарел, **удалён в 2.20** |
| `use_backend` | Да (см. ниже) | Нет (модуль и есть бэкенд) |
| Статус | Стабильный | Официальная документация предупреждает: DNF5 ещё развивается, и «не все возможности `dnf` реализованы в `dnf5`» |

**Требования на управляемом хосте** для `dnf5`: `python3` и `python3-libdnf5`. На RHEL 9/10 ставится пакетом `python3-libdnf5`.

```bash
# Проверить наличие бэкенда DNF5 на хосте
ansible rhel9 -m ansible.builtin.command -a "rpm -q python3-libdnf5"
ansible rhel9 -m ansible.builtin.command -a "dnf5 --version"
```

### Как выбирается бэкенд: `use_backend`

Модуль `ansible.builtin.dnf` (и `ansible.builtin.package`, делегирующий в него на RPM-системах) принимает `use_backend` со значениями:

| `use_backend` | Что вызывается |
| :--- | :--- |
| `auto` | Выбирается по факту `ansible_facts.pkg_mgr` |
| `yum` | Псевдоним `auto` |
| `dnf` / `dnf4` / `yum4` | `ansible.builtin.dnf` (DNF4) |
| **`dnf5`** | `ansible.builtin.dnf5` |

По умолчанию `auto` подставляет нужный бэкенд по фактам ОС, поэтому в кроссплатформенном плейбуке явный `use_backend` обычно не нужен. Он нужен в двух случаях: принудительный DNF4 на RHEL 9 (например, из-за несовместимости стороннего пакета) или явный DNF5 там, где факты его ещё не определяют.

```yaml
# Принудительно DNF4 на хосте, где по умолчанию определяется DNF5
- name: "Установка через DNF4 принудительно"
  ansible.builtin.dnf:
    name: nginx
    state: present
    use_backend: dnf

# Принудительно DNF5
- name: "Установка через DNF5"
  ansible.builtin.dnf:
    name: nginx
    state: present
    use_backend: dnf5
```

**Альтернатива — вызов `ansible.builtin.dnf5` напрямую.** Это делает намерение явным и не зависит от фактов:

```yaml
- name: "Явный вызов модуля dnf5"
  ansible.builtin.dnf5:
    name: "{{ item }}"
    state: present
  loop:
    - nginx
    - postgresql-server
```

**Практический совет:** для одного плейбука на смешанной парке RHEL 8 / RHEL 9 используйте `ansible.builtin.dnf` с `use_backend: auto` (то есть просто `dnf`) — он сам выберет DNF4 или DNF5. Смешивать в одном плейбуке прямой `dnf5` и `dnf` с ручным `use_backend` стоит только при осознанной необходимости.

### Ограничения DNF5, которые ломают переход с DNF4

1. **Нет `enablerepo` / `disablerepo`.** Репозитории включаются через конфигурацию: файлы `*.repo` в `/etc/yum.repos.d/` или `ansible.builtin.ini_file` / `ansible.builtin.template` по секции `[repo]`. Перенос плейбука с `enablerepo: epel` на DNF5 требует переписывания.
2. **Нет `download_dir`.** Для выкачивания RPM без установки используйте `dnf5 download` через `command` либо `get_url` по прямым ссылкам.
3. **`lock_timeout` — no-op.** DNF5 не имеет опции ожидания lock-файла, поэтому модуль не может увеличить таймаут ожидания блокировки. Параллельные запуски плейбуков на одном хосте защищайте внешними средствами: `serial: 1` во фрагменте, `throttle` на группе или блокировкой в CI.
4. **`disable_gpg_check` осознанно упрощён.** Параметр принимает список значений, но отключение проверки GPG на продакшене — плохая практика; используйте его только для диагностических установок.
5. **Устаревшие параметры исчезают.** `install_repoquery` удалён в ansible-core 2.20 — если он остался в ваших плейбуках, они сломаются на этой версии.

### Типы модулей по назначению

1.  **Системные (Нативные)**:
    *   `ansible.builtin.apt`: Для Debian, Ubuntu и производных. Поддерживает `purge`, `only_upgrade`, `cache_valid_time`. В Ubuntu 20.04+ `apt-transport-https` встроен в `apt` и не требует отдельной установки.
    *   `ansible.builtin.dnf`: Для RHEL 8+, Fedora, AlmaLinux. Управляет **DNF4**. Поддерживает модули (`@module:stream`), группы пакетов, репозитории, `enablerepo`/`disablerepo`.
    *   `ansible.builtin.dnf5`: Для RHEL 9/10, Fedora 41+, где DNF5 вытеснил DNF4. **Добавлен в ansible-core 2.15.** Требует `python3-libdnf5` на управляемом хосте. Не все возможности `dnf` реализованы — см. раздел про DNF5 ниже.
    *   `ansible.builtin.yum`: Больше не самостоятельный бэкенд. **YUM-бэкенд удалён в ansible-core 2.17** (требуемые библиотеки недоступны для поддерживаемых версий Python). Имя сохранено как псевдоним для `auto`/`dnf` ради совместимости синтаксиса.
    *   `ansible.builtin.zypper`: Для SUSE/openSUSE. Поддерживает патчи (`patch:name`), репозитории, импорт ключей.
    *   `ansible.builtin.apk`: Для Alpine Linux. Поддерживает `repository` для добавления репозиториев.
    *   `community.general.pacman`: Для Arch Linux. Требует установки коллекции `community.general`.
2.  **Windows-менеджеры**:
    *   `chocolatey.chocolatey.win_chocolatey`: Управление пакетами через Chocolatey.
    *   `community.windows.win_winget`: Интеграция с Windows Package Manager (Winget).
    *   `ansible.windows.win_package`: Установка `.msi` и `.exe` файлов.
3.  **Контейнеризированные и универсальные**:
    *   `community.general.snap`: Управление пакетами Snap (Ubuntu, CentOS).
    *   `community.general.flatpak`: Управление пакетами Flatpak.
4.  **Языковые и прикладные**:
    *   `ansible.builtin.pip`: Пакеты Python. В современных ОС (Ubuntu 24.04+) требует виртуальных окружений из-за **PEP 668**.
    *   `community.general.npm`: Пакеты Node.js.
    *   `community.general.gem`: Пакеты Ruby.
    *   `community.general.cargo`: Пакеты Rust.
    *   `community.general.go`: Пакеты Go (модули).
    *   `community.general.dotnet`: Пакеты .NET (NuGet). Требует установленного SDK .NET на целевом хосте.
5.  **Управление источниками и репозиториями**:
    *   `ansible.builtin.deb822_repository`: Современный формат репозиториев для Debian/Ubuntu (Deb822/SRCREC).
    *   `ansible.builtin.apt_repository` / `ansible.builtin.yum_repository`: Традиционные способы добавления репозиториев.
    *   `ansible.builtin.zypper_repository`: Добавление репозиториев в SUSE/openSUSE.
    *   `ansible.builtin.rpm_key`: Управление GPG-ключами для RPM-систем.

### Идемпотентность и параметры состояния (state)

Все модули пакетов следуют принципу идемпотентности через параметр `state`:

- `present` (по умолчанию): Пакет должен быть установлен. Если он уже есть, действия не предпринимаются.
- `installed`: Синоним `present`, считается устаревшим, но поддерживается.
- `latest`: Установка или обновление до самой свежей версии в репозитории. **Внимание**: Может нарушить стабильность, если версия обновится неожиданно. Стратегии массового применения обновлений безопасности и управления жизненным циклом патчинга подробно описаны в **[Patch Management: Стратегии обновления ОС](../ansible_patch_management.md)**.
- `absent`: Пакет должен быть удален.
- `fixed`: В некоторых модулях позволяет зафиксировать версию (pinning).

**Критически важные флаги:**
- `update_cache`: Обновление индексов репозиториев перед выполнением.
- `allow_downgrade`: Разрешает установку более старой версии (только для нативных модулей).
- `autoremove`: Удаление неиспользуемых зависимостей.
- `purge`: (Только для `apt`) Удаление конфигурационных файлов вместе с пакетом.
- `only_upgrade`: (Только для `apt`) Устанавливает пакет только если он уже установлен.
- `force`: (Только для `apt`) Принудительная установка (использовать с осторожностью).
- `enablerepo` / `disablerepo`: (Для `dnf`/`yum`) Включение/отключение конкретных репозиториев.
- `lock_timeout`: (Для `apt`) Таймаут ожидания блокировки (по умолчанию 60 сек).
- `cache_valid_time`: (Для `apt`) Время жизни кэша в секундах; предотвращает лишние обращения к сети.
- `dpkg_options`: (Для `apt`) Опции для `dpkg`, например `skip-broken` для пропуска битых пакетов.
- `security`: (Для `dnf`) Установка только обновлений безопасности.

### Механика идемпотентности

Модули пакетов определяют необходимость изменений через сравнение состояния:

1. **Сбор фактов**: Модуль получает текущий список установленных пакетов через `dpkg-query` (APT), `rpm` (RPM) или `apk` (Alpine).
2. **Сравнение версий**: Сравнивается запрошенная версия с установленной. Если указано `state: latest`, выполняется запрос к репозиторию.
3. **Принятие решения**: Если пакет отсутствует или версия не совпадает — выполняется транзакция. В противном случае модуль возвращает `changed: false`.

### Работа через прокси и обработка блокировок

- **Прокси**: Если хост не имеет прямого доступа к интернету, используйте директиву `environment` для передачи `http_proxy` / `https_proxy`.
- **Блокировки (Locks)**: Пакетные менеджеры (особенно `apt`) часто блокируются фоновыми процессами (например, `unattended-upgrades`). Для борьбы с этим используются параметры `retries` и `delay` в задачах Ansible.

### Привилегированный доступ (become)

Для установки пакетов требуется root-доступ. Все примеры установки пакетов предполагают использование `become: yes` и `become_method: sudo`.

```yaml
- name: "Установка пакетов от root"
  ansible.builtin.apt:
    name: nginx
    state: present
  become: yes
  become_method: sudo
```

## Установка и настройка

### Управление репозиториями

**Добавление PPA в Debian/Ubuntu:**
```yaml
- name: "Добавление PPA для Node.js"
  ansible.builtin.apt_repository:
    repo: "ppa:chris-lea/node.js"
    state: present
    update_cache: yes
```

**Добавление RPM-репозитория:**
```yaml
- name: "Добавление репозитория для RHEL"
  ansible.builtin.yum_repository:
    name: custom-repo
    description: Custom Repository
    baseurl: "https://repo.example.com/rhel/$releasever/$basearch"
    gpgcheck: yes
    gpgkey: "https://repo.example.com/rhel/gpg"
    enabled: yes
```

**Современный формат Debian (deb822):**
```yaml
- name: "Добавление репозитория в формате deb822"
  ansible.builtin.deb822_repository:
    name: docker-ce
    types: deb
    uris: "https://download.docker.com/linux/ubuntu"
    suites: "{{ ansible_distribution_release }}"
    components: stable
    architectures: amd64
    signed_by: /etc/apt/keyrings/docker.gpg
    state: present
```

**Добавление репозитория OBS в SUSE/openSUSE:**
```yaml
- name: "Добавление репозитория OBS"
  ansible.builtin.zypper_repository:
    name: obs-python
    description: "Open Build Service Python"
    url: "https://download.opensuse.org/repositories/devel:/languages:/python/openSUSE_Tumbleweed/"
    state: present
    auto_import_keys: yes
```

**Добавление репозитория в Alpine Linux:**
```yaml
- name: "Добавление репозитория Edge в Alpine"
  ansible.builtin.apk:
    repository: "http://dl-cdn.alpinelinux.org/alpine/edge/main"
    state: present
```

### Управление GPG-ключами

**Импорт ключа для RPM:**
```yaml
- name: "Импорт GPG-ключа"
  ansible.builtin.rpm_key:
    key: "https://repo.example.com/rhel/gpg"
    state: present
```

**Импорт ключа для APT:**
```yaml
- name: "Скачивание GPG-ключа"
  ansible.builtin.get_url:
    url: "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
    dest: /usr/share/keyrings/postgresql-keyring.gpg
    mode: '0644'

- name: "Добавление репозитория с ключом"
  ansible.builtin.apt_repository:
    repo: "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt {{ ansible_distribution_release }}-pgdg main"
    state: present
    filename: pgdg
```

### Обработка ошибок

**Паттерны с повторными попытками:**
```yaml
- name: "Установка с обработкой ошибок"
  ansible.builtin.apt:
    name: nginx
    state: present
    update_cache: yes
  register: apt_result
  until: apt_result is success
  retries: 3
  delay: 10
  become: yes
```

**Игнорирование некритических ошибок:**
```yaml
- name: "Установка пакета (если доступен)"
  ansible.builtin.dnf:
    name: optional-package
    state: present
  ignore_errors: yes
  register: optional_result

- name: "Логирование статуса"
  ansible.builtin.debug:
    msg: "Пакет optional-package не установлен: {{ optional_result.stderr }}"
  when: optional_result is failed
```

### Кросс-платформенные особенности

**Универсальный подход:**
```yaml
- name: "Установка curl на любой ОС"
  ansible.builtin.package:
    name: curl
    state: present
  become: yes
```

**Условная установка по ОС:**
```yaml
- name: "Установка Python (Linux)"
  ansible.builtin.package:
    name: python3
    state: present
  become: yes
  when: ansible_system == "Linux"

- name: "Установка Python (Windows)"
  ansible.windows.win_package:
    path: "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"
    arguments: "/quiet InstallAllUsers=1 PrependPath=1"
  when: ansible_system == "Win32NT"
```

### Отладка и логирование

**Проверка установленных пакетов:**
```yaml
- name: "Сбор информации о пакетах"
  ansible.builtin.package_facts:
    manager: auto

- name: "Вывод списка установленных пакетов"
  ansible.builtin.debug:
    msg: "{{ ansible_facts.packages.keys() | list }}"
```

**Проверка версии пакета:**
```yaml
- name: "Проверка версии OpenSSL"
  ansible.builtin.package_facts:
    manager: auto

- name: "Вывод версии OpenSSL"
  ansible.builtin.debug:
    msg: "Установлена версия: {{ ansible_facts.packages['openssl'][0].version }}"
  when: "'openssl' in ansible_facts.packages"
```

## Операции и команды

### Универсальные операции

| Операция | Модуль | Ключевые параметры |
|----------|--------|-------------------|
| Установка пакета | `ansible.builtin.package` | `name`, `state: present` |
| Удаление пакета | `ansible.builtin.package` | `name`, `state: absent` |
| Обновление до последней версии | `ansible.builtin.package` | `name`, `state: latest` |
| Сбор фактов о пакетах | `ansible.builtin.package_facts` | `manager: auto` |

### Операции для APT (Debian/Ubuntu)

| Операция | Пример |
|----------|--------|
| Установка с обновлением кэша | `ansible.builtin.apt: name=nginx state=present update_cache=yes` |
| Полное удаление с purge | `ansible.builtin.apt: name=apache2 state=absent purge=yes autoremove=yes` |
| Установка только обновлений | `ansible.builtin.apt: name=nginx state=latest only_upgrade=yes` |
| Добавление PPA | `ansible.builtin.apt_repository: repo=ppa:chris-lea/node.js state=present` |
| Очистка кэша | `ansible.builtin.apt: name=nginx state=present clean=yes autoremove=yes` |

### Операции для DNF/YUM (RHEL/Fedora)

| Операция | Пример |
|----------|--------|
| Установка модуля | `ansible.builtin.dnf: name=@nodejs:20 state=present` |
| Установка группы | `ansible.builtin.dnf: name="@Development Tools" state=present` |
| Включение репозитория (только DNF4) | `ansible.builtin.dnf: name=pkg state=present enablerepo=epel` |
| Очистка кэша | `ansible.builtin.dnf: name=* state=latest update_cache=yes` |
| Только security-патчи | `ansible.builtin.dnf: name=* security=yes state=latest` |
| Принудительный бэкенд DNF4 | `ansible.builtin.dnf: name=pkg state=present use_backend=dnf` |
| Принудительный бэкенд DNF5 | `ansible.builtin.dnf: name=pkg state=present use_backend=dnf5` |
| Прямой вызов модуля DNF5 | `ansible.builtin.dnf5: name=pkg state=present` |
| Установка в отдельный installroot (DNF5) | `ansible.builtin.dnf5: name=pkg state=present installroot=/mnt/sysroot` |

### Операции для Zypper (SUSE/openSUSE)

| Операция | Пример |
|----------|--------|
| Установка пакетов | `ansible.builtin.zypper: name=[apache2, php8] state=present update_cache=yes` |
| Установка патча | `ansible.builtin.zypper: name=patch:name state=present` |
| Добавление репозитория | `ansible.builtin.zypper_repository: name=obs-python state=present auto_import_keys=yes` |

### Операции для APK (Alpine Linux)

| Операция | Пример |
|----------|--------|
| Установка пакета | `ansible.builtin.apk: name=nginx state=present` |
| Обновление индексов | `ansible.builtin.apk: name=nginx state=present update=yes` |
| Добавление репозитория | `ansible.builtin.apk: repository=https://dl-cdn.alpinelinux.org/alpine/edge/main state=present` |

### Операции для Windows

| Операция | Модуль | Пример |
|----------|--------|--------|
| Установка через Chocolatey | `chocolatey.chocolatey.win_chocolatey` | `name=googlechrome state=present` |
| Установка через Winget | `community.windows.win_winget` | `name=Microsoft.VisualStudioCode state=present` |
| Установка MSI/EXE | `ansible.windows.win_package` | `path=https://... arguments=/silent` |

### Работа с языковыми пакетными менеджерами

| Менеджер | Модуль | Особенности |
|----------|--------|-------------|
| pip | `ansible.builtin.pip` | Требует `virtualenv` в новых ОС из-за PEP 668 |
| npm | `community.general.npm` | Поддержка глобальной и локальной установки |
| gem | `community.general.gem` | Поддержка `user_install` и `version` |
| snap | `community.general.snap` | Поддержка `classic` confinement |
| flatpak | `community.general.flatpak` | Требует предварительного добавления remote |

## Практические сценарии

### Оптимизированная установка в Debian/Ubuntu

Использование `cache_valid_time` предотвращает лишние обращения к сети.

```yaml
- name: "Установка базового ПО с оптимизацией кэша"
  ansible.builtin.apt:
    name: [curl, git, htop]
    state: present
    update_cache: yes
    cache_valid_time: 86400 # Не чаще раза в сутки
    autoremove: yes
    purge: yes
  register: apt_res
  until: apt_res is success
  retries: 5
  delay: 10
```

### Установка в современных RPM-системах (DNF4/DNF5)

Управление модулями и группами пакетов. `use_backend: auto` (по умолчанию) сам выбирает DNF4 или DNF5 по фактам хоста, поэтому один плейбук работает и на RHEL 8, и на RHEL 9/10.

```yaml
- name: "Установка потока модуля Node.js (DNF)"
  ansible.builtin.dnf:
    name: "@nodejs:20"
    state: present

- name: "Очистка кэша и установка группы"
  ansible.builtin.dnf:
    name: "@Development Tools"
    state: present
    update_cache: yes
```

**Явный DNF5 с включением репозитория через конфигурацию.** На DNF5 параметра `enablerepo` нет, поэтому репозиторий включается файлом в `/etc/yum.repos.d/`:

```yaml
- name: "Включить репозиторий EPEL на DNF5 (enablerepo недоступен)"
  ansible.builtin.copy:
    dest: /etc/yum.repos.d/epel.repo
    content: |
      [epel]
      name=Extra Packages for Enterprise Linux
      baseurl=https://download.example/pub/epel/$releasever/Everything/$basearch
      enabled=1
      gpgcheck=1
      gpgkey=https://download.example/pub/epel/RPM-GPG-KEY-EPEL
    owner: root
    group: root
    mode: "0644"
  register: epel_repo

- name: "Обновить кэш метаданных после добавления репозитория"
  ansible.builtin.dnf:
    update_cache: true
  when: epel_repo is changed

- name: "Установить пакет из EPEL"
  ansible.builtin.dnf5:
    name: epel-release
    state: present
    disable_gpg_check: false

# Проверка фактического бэкенда на хосте
- name: "Определить версию DNF"
  ansible.builtin.command:
    cmd: dnf --version
  register: dnf_ver
  changed_when: false

- name: "Показать используемый бэкенд"
  ansible.builtin.debug:
    msg: "Хост {{ inventory_hostname }}: DNF {{ dnf_ver.stdout_lines[0] }}"
```

**Установка в альтернативный корень через `installroot`** (доступно только в DNF5). Полезно для сборки образов и подготовки chroot:

```yaml
- name: "Установить пакеты в /mnt/sysroot без влияния на основную систему"
  ansible.builtin.dnf5:
    name:
      - bash
      - systemd
      - openssh-server
    state: present
    installroot: /mnt/sysroot
    releasever: "9"

- name: "Проверить, что пакет появился только в sysroot"
  ansible.builtin.command:
    cmd: rpm -qa bash --root /mnt/sysroot
  changed_when: false
```

### Управление Python-пакетами (PEP 668)

В новых дистрибутивах прямая установка в системный Python заблокирована.

```yaml
- name: "Установка приложения в изолированное окружение"
  ansible.builtin.pip:
    name: "flask>=3.0.0"
    state: present
    virtualenv: /opt/web_app/venv
    virtualenv_command: python3 -m venv
```

### Установка ПО в Windows через Chocolatey

Пример для гетерогенных сред.

```yaml
- name: "Установка браузеров в Windows"
  chocolatey.chocolatey.win_chocolatey:
    name:
      - googlechrome
      - firefox
    state: present
```

### Использование package_facts для аудита безопасности

Сбор данных о ПО для последующих проверок.

```yaml
- name: "Анализ установленного ПО"
  ansible.builtin.package_facts:
    manager: auto

- name: "Прерывание, если установлена уязвимая версия"
  ansible.builtin.assert:
    that:
      - "ansible_facts.packages['openssl'][0].version is version('3.0.0', '>=')"
    fail_msg: "Обнаружена критическая уязвимость в OpenSSL!"
  when: "'openssl' in ansible_facts.packages"
```

### Очистка системы от старых ядер (RHEL/CentOS)

Управление количеством установленных версий.

```yaml
- name: "Удаление старых версий ядер"
  ansible.builtin.dnf:
    name: kernel
    state: absent
    autoremove: yes
  # В современных системах лучше управлять через /etc/dnf/dnf.conf (installonly_limit)
```

### Управление репозиториями и GPG-ключами

**Добавление репозитория PostgreSQL:**
```yaml
- name: "Установка GPG-ключа PostgreSQL"
  ansible.builtin.get_url:
    url: "https://www.postgresql.org/media/keys/ACCC4CF8.asc"
    dest: /usr/share/keyrings/postgresql-keyring.gpg
    mode: '0644'

- name: "Добавление репозитория PostgreSQL"
  ansible.builtin.apt_repository:
    repo: "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt {{ ansible_distribution_release }}-pgdg main"
    state: present
    filename: pgdg

- name: "Установка PostgreSQL"
  ansible.builtin.apt:
    name:
      - postgresql-16
      - postgresql-client-16
    state: present
    update_cache: yes
```

### Установка базовых пакетов (образы контейнеров и минимальные системы)

Для минимальных образов (Alpine, Docker) и систем без менеджера пакетов:

```yaml
- name: "Установка Python на Alpine Linux"
  ansible.builtin.apk:
    name: python3
    state: present

- name: "Установка базовых утилит"
  ansible.builtin.package:
    name:
      - curl
      - git
      - vim
    state: present
```

### Управление пакетами в SUSE/openSUSE

```yaml
- name: "Установка пакетов через zypper"
  ansible.builtin.zypper:
    name:
      - apache2
      - php8
      - postgresql16
    state: present
    update_cache: yes
```

### Управление пакетами в Arch Linux

```yaml
- name: "Установка пакетов через pacman"
  community.general.pacman:
    name:
      - base-devel
      - git
      - vim
    state: present
    update_cache: yes

- name: "Установка AUR-пакетов"
  kewlfft.aur.aur:
    name: "{{ item }}"
    state: present
  loop:
    - visual-studio-code-bin
    - google-chrome
  become: yes
  become_user: "{{ aur_user }}"
```

### Условная установка на основе версии ОС

```yaml
- name: "Установка пакетов для Ubuntu 22.04"
  ansible.builtin.apt:
    name:
      - python3.10
      - python3.10-venv
    state: present
  when:
    - ansible_distribution == "Ubuntu"
    - ansible_distribution_version == "22.04"

- name: "Установка пакетов для Ubuntu 24.04"
  ansible.builtin.apt:
    name:
      - python3.12
      - python3.12-venv
    state: present
  when:
    - ansible_distribution == "Ubuntu"
    - ansible_distribution_version == "24.04"
```

### Пакетная установка с проверкой зависимостей

```yaml
- name: "Полная установка веб-сервера"
  block:
    - name: "Установка веб-сервера"
      ansible.builtin.apt:
        name:
          - nginx
          - php-fpm
          - php-mysql
          - php-curl
          - php-gd
          - php-mbstring
          - php-xml
          - php-zip
        state: present
        update_cache: yes
      register: web_install

    - name: "Запуск веб-сервера"
      ansible.builtin.service:
        name: nginx
        state: started
        enabled: yes
      when: web_install is changed

  rescue:
    - name: "Откат при ошибке"
      ansible.builtin.apt:
        name:
          - nginx
          - php-mysql
        state: absent
      ignore_errors: yes
```

### Установка пакетов из локального репозитория

```yaml
- name: "Настройка локального репозитория"
  ansible.builtin.apt_repository:
    repo: "deb file:/opt/local-repo ./"
    state: present
    filename: local-repo

- name: "Установка пакетов из локального репозитория"
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
    update_cache: yes
  loop:
    - custom-app-1.0
    - custom-lib-2.0
```

### Безопасная работа с секретами

```yaml
- name: "Установка пакетов с приватного репозитория"
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  environment:
    apt_proxy: "http://{{ vault_apt_proxy_user }}:{{ vault_apt_proxy_pass }}@proxy.company.com:3128"
  loop:
    - private-package-1
    - private-package-2
  no_log: true
```

### Параллельная установка на нескольких хостах

```yaml
- name: "Параллельная установка на всех хостах"
  ansible.builtin.package:
    name: "{{ item }}"
    state: present
  become: yes
  async: 300
  poll: 0
  register: install_jobs
  loop:
    - curl
    - git
    - htop

- name: "Ожидание завершения на всех хостах"
  ansible.builtin.async_status:
    jid: "{{ item.ansible_job_id }}"
  loop: "{{ install_jobs.results }}"
  register: async_final
  until: async_final.finished
  retries: 60
  delay: 10
```

### Удаление пакетов с очисткой

```yaml
- name: "Полное удаление Apache"
  ansible.builtin.apt:
    name:
      - apache2
      - apache2-utils
      - apache2-bin
    state: absent
    purge: yes
    autoremove: yes

- name: "Удаление конфигурационных файлов"
  ansible.builtin.file:
    path: "{{ item }}"
    state: absent
  loop:
    - /etc/apache2
    - /var/log/apache2
    - /var/www/html
  ignore_errors: yes
```

### Проверка и откат обновлений

```yaml
- name: "Создание снапшота перед обновлением"
  community.general.snap:
    name: myapp
    state: present
  register: snap_before

- name: "Обновление пакетов"
  ansible.builtin.apt:
    name: "*"
    state: latest
    update_cache: yes
  register: update_result

- name: "Откат при ошибке"
  community.general.snap:
    name: myapp
    revision: "{{ snap_before.current_snap.current_revision }}"
  when: update_result is failed
```

### Массовое развертывание пакетов в кластере

```yaml
- name: "Установка пакетов на кластер с batch-стратегией"
  ansible.builtin.dnf:
    name: "{{ packages }}"
    state: present
  vars:
    packages:
      - htop
      - iotop
      - sysstat
  serial: "25%"
  throttle: 10
```

### Управление версиями пакетов (pinning)

```yaml
- name: "Фиксация версии PostgreSQL"
  ansible.builtin.dnf:
    name: postgresql-16
    state: present
  register: pg_install

- name: "Блокировка версии через versionlock"
  ansible.builtin.command: dnf versionlock add postgresql-16
  when: pg_install is changed
  become: yes

- name: "Фиксация версии в APT"
  ansible.builtin.command: apt-mark hold postgresql-16
  when: pg_install is changed
  become: yes
```

### Работа в air-gapped средах (без доступа к интернету)

```yaml
- name: "Настройка локального репозитория (offline)"
  ansible.builtin.apt_repository:
    repo: "deb [signed-by=/usr/share/keyrings/local.gpg] file:/opt/local-repo ./"
    state: present
    filename: local-repo

- name: "Установка из локального репозитория"
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
    update_cache: yes
  loop:
    - custom-app-1.0
    - custom-lib-2.0
```

### Создание зеркала репозитория для офлайн-сред

```bash
# На хосте-зеркале (выполняется один раз)
reposync --repoid=baseos --download-path=/opt/mirror --newest-only --delete
createrepo --update /opt/mirror/baseos
```

## Диагностика и устранение неисправностей

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Unable to locate package` | Пакет не найден в репозитории | Обновите кэш или добавьте репозиторий |
| `Could not get lock` | Блокировка пакетного менеджера | Используйте `retries` и `delay` |
| `GPG error` | Ошибка ключа подписи | Импортируйте корректный GPG-ключ |
| `Dependency conflict` | Конфликт зависимостей | Проверьте версии или используйте `--force` |
| `Permission denied` | Недостаточно прав | Добавьте `become: yes` |
| `No such file or directory` | Отсутствует виртуальное окружение | Создайте окружение перед установкой |
| `E: Unable to fetch some archives` | Проблемы с сетью/репозиторием | Проверьте DNS, proxy, доступность репозитория |
| `Transaction check error` | Конфликт файлов в пакетах | Удалите конфликтующие пакеты вручную |
| `No module named 'libdnf5'` на `dnf5` | Не установлена библиотека `python3-libdnf5` на управляемом хосте | Установите пакет `python3-libdnf5`; модуль требует её на хосте, а не на контрольном узле |
| `Unsupported parameters for module: enablerepo` на DNF5 | `ansible.builtin.dnf5` не реализует `enablerepo`/`disablerepo` | Включите репозиторий файлом в `/etc/yum.repos.d/` или используйте `dnf` с `use_backend: dnf` |
| `Unsupported parameters for module: download_dir` на DNF5 | Параметр отсутствует в `dnf5` | Скачивайте RPM через `command: dnf5 download` или `ansible.builtin.get_url` |
| `lock_timeout` не помогает на DNF5 | У dnf5 нет CLI-опции ожидания lock-файла, параметр — no-op | Ограничьте параллелизм: `serial: 1`, `throttle`, блокировка в CI |
| `install_repoquery` не принимается | Параметр устарел и **удалён в ansible-core 2.20** | Удалите параметр из плейбуков |
| `yum` не работает как раньше | YUM-бэкенд **удалён в ansible-core 2.17** | Используйте `ansible.builtin.dnf` (имя `yum` осталось псевдонимом для совместимости) |
| Пакет ставится не тем бэкендом, что ожидалось | `use_backend: auto` выбирает по фактам хоста | Проверьте `ansible_facts.pkg_mgr`; задайте `use_backend` явно |

### Паттерны обработки ошибок

```yaml
- name: "Установка с обработкой ошибок"
  ansible.builtin.apt:
    name: "{{ item }}"
    state: present
  register: result
  until: result is success
  retries: 3
  delay: 10
  loop:
    - package1
    - package2
    - package3
  become: yes
```

## Рекомендации и оптимизация

### Кэширование и параллелизм

```yaml
- name: "Оптимизированная установка"
  ansible.builtin.apt:
    name: "{{ packages }}"
    state: present
    update_cache: yes
    cache_valid_time: 86400
  vars:
    packages:
      - nginx
      - postgresql
      - redis-server
      - python3
      - python3-pip
  become: yes
  tags:
    - packages
```

### Раздельная установка по ролям

```yaml
# В файле roles/webserver/tasks/main.yml
- name: "Установка веб-сервера"
  ansible.builtin.package:
    name: "{{ web_packages }}"
    state: present
  become: yes

# В файле roles/database/tasks/main.yml
- name: "Установка базы данных"
  ansible.builtin.package:
    name: "{{ db_packages }}"
    state: present
  become: yes
```

### Общие рекомендации

- **Используйте FQCN** для всех модулей (`ansible.builtin.apt` вместо `apt`), чтобы избежать конфликтов с модулями из сторонних коллекций.
- **Предпочитайте нативные модули** универсальному `package`, когда требуется специфичная функциональность (`purge`, `only_upgrade`, модули DNF5).
- **Обновляйте кэш только когда необходимо** — используйте `cache_valid_time` для минимизации сетевых вызовов.
- **Используйте `retries` и `delay`** для задач установки в средах с возможными блокировками пакетных менеджеров.
- **Изолируйте Python-пакеты** в виртуальные окружения в соответствии с PEP 668.
- **Никогда не храните секреты в открытом виде** — используйте `no_log: true` и Ansible Vault.
- **Используйте нативные модули вместо `command`/`shell`** для управления пакетами, чтобы сохранить идемпотентность.

## Дополнительная информация

- **[Основные концепции Ansible](../ansible_core_concepts.md)** — общие принципы работы и архитектура.
- **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)** — как писать плейбуки для разных ОС.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — классификация и выбор инструментов.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление репозиториями и ключами.
- **[Патч-менеджмент](../ansible_patch_management.md)** — стратегии обновления ОС.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Официальная документация (builtin)](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)** — полный список параметров.
