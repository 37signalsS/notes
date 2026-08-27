# Ansible: Модули управления пакетами

## Определения

**Модули управления пакетами** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для автоматизации жизненного цикла программного обеспечения на управляемых хостах. Они абстрагируют команды системных пакетных менеджеров, обеспечивая единообразный способ установки, обновления и удаления ПО.

**Абстракция менеджера (модуль `package`)** — универсальный интерфейс, который автоматически определяет тип ОС и вызывает соответствующий нативный модуль (`apt`, `dnf`, `zypper` и др.). Это удобно для кроссплатформенных плейбуков, но ограничивает доступ к специфичным функциям (например, `purge` в `apt` или модульность в `dnf`).

**FQCN (Fully Qualified Collection Name)** — обязательный стандарт именования модулей (например, `ansible.builtin.apt`), предотвращающий конфликты с модулями из сторонних коллекций и обеспечивающий стабильность выполнения.

### Возвращаемые данные (Return Values)

Все модули пакетов возвращают стандартный набор данных:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `stdout` | string | Стандартный вывод команды пакетного менеджера |
| `stderr` | string | Стандартный поток ошибок |
| `rc` | integer | Код возврата команды (0 = успех) |
| `changed` | boolean | Были ли произведены изменения |
| `cache_updated` | boolean | Был ли обновлен кэш (для apt/dnf) |
| `diff` | dict | Различия до и после выполнения (если включен `--diff`) |

## Основные концепции

### Типы модулей по назначению

1.  **Системные (Нативные)**:
    *   `ansible.builtin.apt`: Для Debian, Ubuntu и производных.
    *   `ansible.builtin.dnf`: Для RHEL 8+, Fedora, AlmaLinux. Полная поддержка **DNF5** в последних версиях Ansible (2.17+).
    *   `ansible.builtin.yum`: Для RHEL 7 и старых систем на базе RPM.
    *   `ansible.builtin.zypper`: Для SUSE/openSUSE.
    *   `community.general.pacman`: Для Arch Linux.
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
5.  **Управление источниками и репозиториями**:
    *   `ansible.builtin.deb822_repository`: Современный формат репозиториев для Debian/Ubuntu.
    *   `ansible.builtin.apt_repository` / `ansible.builtin.yum_repository`: Традиционные способы добавления репозиториев.
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

### Работа через прокси и обработка блокировок

- **Прокси**: Если хост не имеет прямого доступа к интернету, используйте директиву `environment` для передачи `http_proxy` / `https_proxy`.
- **Блокировки (Locks)**: Пакетные менеджеры (особенно `apt`) часто блокируются фоновыми процессами (например, `unattended-upgrades`). Для борьбы с этим используются параметры `retries` и `delay` в задачах Ansible.

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
- name: "Добавление репозитория Docker для RHEL"
  ansible.builtin.yum_repository:
    name: docker-ce
    description: Docker CE Repository
    baseurl: "https://download.docker.com/linux/centos/$releasever/$basearch/stable"
    gpgcheck: yes
    gpgkey: "https://download.docker.com/linux/centos/gpg"
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

### Управление GPG-ключами

**Импорт ключа для RPM:**
```yaml
- name: "Импорт GPG-ключа Docker"
  ansible.builtin.rpm_key:
    key: "https://download.docker.com/linux/centos/gpg"
    state: present
```

**Импорт ключа для APT:**
```yaml
- name: "Скачивание GPG-ключа"
  ansible.builtin.get_url:
    url: "https://packages.cloud.google.com/apt/doc/apt-key.gpg"
    dest: /usr/share/keyrings/kubernetes-archive-keyring.gpg
    mode: '0644'

- name: "Добавление репозитория с ключом"
  ansible.builtin.apt_repository:
    repo: "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://apt.kubernetes.io/ kubernetes-xenial main"
    state: present
```

### Привилегированный доступ (become)

Для установки пакетов требуется root-доступ:

```yaml
- name: "Установка пакетов от root"
  ansible.builtin.apt:
    name: nginx
    state: present
  become: yes
  become_method: sudo
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

### Установка в современных RPM-системах (DNF/DNF5)
Управление модулями и группами пакетов.

```yaml
- name: "Установка потока модуля Node.js через DNF"
  ansible.builtin.dnf:
    name: "@nodejs:20"
    state: present

- name: "Очистка кэша и установка группы"
  ansible.builtin.dnf:
    name: "@Development Tools"
    state: present
    update_cache: yes
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

### Установка Docker на Ubuntu

```yaml
- name: "Установка зависимостей Docker"
  ansible.builtin.apt:
    name:
      - apt-transport-https
      - ca-certificates
      - curl
      - gnupg
      - lsb-release
    state: present
    update_cache: yes

- name: "Добавление GPG-ключа Docker"
  ansible.builtin.get_url:
    url: "https://download.docker.com/linux/ubuntu/gpg"
    dest: /etc/apt/keyrings/docker.asc
    mode: '0644'

- name: "Добавление репозитория Docker"
  ansible.builtin.apt_repository:
    repo: "deb [arch={{ ansible_architecture }} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu {{ ansible_distribution_release }} stable"
    state: present

- name: "Установка Docker"
  ansible.builtin.apt:
    name:
      - docker-ce
      - docker-ce-cli
      - containerd.io
    state: present
    update_cache: yes
```

### Управление Python-пакетами с виртуальными окружениями

```yaml
- name: "Создание виртуального окружения"
  ansible.builtin.command: python3 -m venv /opt/myapp/venv
  args:
    creates: /opt/myapp/venv/bin/activate

- name: "Установка Python-пакетов"
  ansible.builtin.pip:
    name:
      - flask==3.0.0
      - gunicorn==21.2.0
      - psycopg2-binary==2.9.9
    state: present
    virtualenv: /opt/myapp/venv
    virtualenv_command: python3 -m venv

- name: "Обновление pip в окружении"
  ansible.builtin.pip:
    name: pip
    state: latest
    virtualenv: /opt/myapp/venv
```

### Установка Node.js и npm-пакетов

```yaml
- name: "Установка Node.js через nvm"
  ansible.builtin.shell: |
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
    export NVM_DIR="$HOME/.nvm"
    [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
    nvm install 20
  args:
    creates: "{{ ansible_user_dir }}/.nvm/versions/node/v20.11.0"
  become: yes
  become_user: "{{ deploy_user }}"

- name: "Установка npm-пакетов"
  community.general.npm:
    name: "{{ item }}"
    state: present
    global: yes
  loop:
    - pm2
    - typescript
    - eslint
  become: yes
  become_user: "{{ deploy_user }}"
```

### Управление Gem-пакетами (Ruby)

```yaml
- name: "Установка Bundler"
  community.general.gem:
    name: bundler
    state: present
    user_install: no
  become: yes

- name: "Установка Rails"
  community.general.gem:
    name: rails
    version: "7.1.2"
    state: present
    user_install: no
  become: yes
```

### Установка Snap-пакетов

```yaml
- name: "Установка VS Code через Snap"
  community.general.snap:
    name: code
    classic: yes
    state: present

- name: "Установка Firefox через Snap"
  community.general.snap:
    name: firefox
    state: present
```

### Установка Flatpak-пакетов

```yaml
- name: "Добавление Flathub репозитория"
  community.general.flatpak_remote:
    name: flathub
    flatpakrepo_url: "https://dl.flathub.org/repo/flathub.flatpakrepo"
    state: present

- name: "Установка приложений через Flatpak"
  community.general.flatpak:
    name: "{{ item }}"
    state: present
  loop:
    - org.mozilla.firefox
    - com.visualstudio.code
    - org.libreoffice.LibreOffice
```

### Установка пакетов в Windows

**Через WinGet:**
```yaml
- name: "Установка приложений через WinGet"
  community.windows.win_winget:
    name: "{{ item }}"
    state: present
  loop:
    - Microsoft.VisualStudioCode
    - Git.Git
    - Microsoft.WindowsTerminal
```

**Через Win Package (MSI/EXE):**
```yaml
- name: "Установка Zoom"
  ansible.windows.win_package:
    path: "https://zoom.us/client/latest/ZoomInstallerFull.exe"
    arguments: /silent
    state: present
    creates: "C:\\Users\\{{ ansible_user_id }}\\AppData\\Roaming\\Zoom\\bin\\Zoom.exe"
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

- name: "Добавление репозитория OBS"
  ansible.builtin.zypper_repository:
    name: obs-python
    description: "Open Build Service Python"
    url: "https://download.opensuse.org/repositories/devel:/languages:/python/openSUSE_Tumbleweed/"
    state: present
    auto_import_keys: yes
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
          - php-fpm
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

- name: "Установка пакетов из л록ального репозитория"
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

## Оптимизация производительности

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

## Обработка ошибок

### Типичные ошибки и их решение

| Ошибка | Причина | Решение |
|--------|---------|---------|
| `Unable to locate package` | Пакет не найден в репозитории | Обновите кэш или добавьте репозиторий |
| `Could not get lock` | Блокировка пакетного менеджера | Используйте `retries` и `delay` |
| `GPG error` | Ошибка ключа подписи | Импортируйте正确的 GPG-ключ |
| `Dependency conflict` | Конфликт зависимостей | Проверьте версии или используйте `--force` |
| `Permission denied` | Недостаточно прав | Добавьте `become: yes` |
| `No such file or directory` | Отсутствует виртуальное окружение | Создайте окружение перед установкой |

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

## Дополнительная информация

- **[Основные концепции Ansible](../ansible_core_concepts.md)** — общие принципы работы и архитектура.
- **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)** — как писать плейбуки для разных ОС.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — классификация и выбор инструментов.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление репозиториями и ключами.
- **[Патч-менеджмент](../ansible_patch_management.md)** — стратегии обновления ОС.
- **[Тестирование с Molecule](../ansible_testing_with_molecule.md)** — проверка кода автоматизации.
- **[Официальная документация (builtin)](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/index.html)** — полный список параметров.
