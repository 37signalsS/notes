# Ansible: Модули управления пакетами

## Определения

**Модули управления пакетами** — это группа специализированных декларативных инструментов Ansible (преимущественно `ansible.builtin`), предназначенных для автоматизации жизненного цикла программного обеспечения на управляемых хостах. Они абстрагируют команды системных пакетных менеджеров, обеспечивая единообразный способ установки, обновления и удаления ПО.

**Абстракция менеджера (модуль `package`)** — универсальный интерфейс, который автоматически определяет тип ОС и вызывает соответствующий нативный модуль (`apt`, `dnf`, `zypper` и др.). Это удобно для кроссплатформенных плейбуков, но ограничивает доступ к специфичным функциям (например, `purge` в `apt` или модульность в `dnf`).

**FQCN (Fully Qualified Collection Name)** — обязательный стандарт именования модулей (например, `ansible.builtin.apt`), предотвращающий конфликты с модулями из сторонних коллекций и обеспечивающий стабильность выполнения.

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

### Работа через прокси и обработка блокировок

- **Прокси**: Если хост не имеет прямого доступа к интернету, используйте директиву `environment` для передачи `http_proxy` / `https_proxy`.
- **Блокировки (Locks)**: Пакетные менеджеры (особенно `apt`) часто блокируются фоновыми процессами (например, `unattended-upgrades`). Для борьбы с этим используются параметры `retries` и `delay` в задачах Ansible.

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

## Дополнительная информация

- **[Основные концепции Ansible](../ansible_core_concepts.md)** — общие принципы работы и архитектура.
- **[Кроссплатформенные концепции](../CrossPlatform/concepts.md)** — как писать плейбуки для разных ОС.
- **[Обзор модулей Ansible](ansible_modules_overview.md)** — классификация и выбор инструментов.
- **[Безопасность в Ansible](../ansible_security_best_practices.md)** — управление репозиториями и ключами.
