# Ansible Patch Management: Стратегии и жизненный цикл обновления ОС

## Определения

- **Управление обновлениями (Patch Management)** — процесс систематического обновления программного обеспечения (чаще всего ядер ОС и системных пакетов) для исправления уязвимостей (CVE), повышения производительности и обеспечения стабильности инфраструктуры.
- **CVE (Common Vulnerabilities and Exposures)** — база данных общеизвестных уязвимостей информационной безопасности. Управление патчами напрямую связано с устранением CVE.
- **Окно обслуживания (Maintenance Window)** — запланированный период времени, в течение которого допускается временная недоступность сервисов для проведения регламентных работ.
- **Rolling Update (Последовательное обновление)** — стратегия, при которой узлы кластера обновляются по очереди или небольшими группами, что позволяет минимизировать простой приложения.
- **Canary Update (Канареечное обновление)** — метод, при котором обновление сначала применяется к одному или нескольким «тестовым» узлам для проверки стабильности перед массовой раскаткой.
- **Pre-Patching / Post-Patching** — этапы подготовки (проверка здоровья, создание снимков) и верификации (проверка работы служб) до и после непосредственной установки пакетов.
- **Lock Packages (Блокировка пакетов)** — механизм предотвращения автоматического обновления или удаления критически важных пакетов через `apt-mark hold` (Debian/Ubuntu) или `dnf versionlock` (RHEL/Rocky).
- **dnf-automatic** — таймерный сервис в RHEL/Rocky/Alpine, автоматически загружающий и устанавливающий обновления по расписанию. Аналог `unattended-upgrades` для Debian/Ubuntu.
- **unattended-upgrades** — демон в Debian/Ubuntu, автоматически применяющий обновления безопасности (и опционально — все обновления) без участия администратора.
- **needs-restarting** — утилита RHEL/Rocky, проверяющая, какие процессы используют обновлённые библиотеки и требуют перезапуска для применения изменений.
- **Kernel Livepatching** — механизм применения исправлений ядра без перезагрузки (kpatch для RHEL, canonical-livepatch для Ubuntu). Позволяет устранять критические CVE без простоя.

## Предварительные требования

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | Ядро Ansible (рекомендуется 2.17+) |
| **Python** | 3.8+ | Совместимость с ansible-core |
| **openssh-server** (целевые хосты) | 7.0+ | Доступ по SSH для Ansible |
| **sudo** (целевые хосты) | 1.8+ | Права root для установки пакетов |
| **dnf / yum** (RHEL/Rocky) | dnf 5.0+ / yum 3.4+ | Пакетный менеджер |
| **apt** (Debian/Ubuntu) | apt 2.0+ | Пакетный менеджер |
| **winrm** (Windows) | 5.0+ | Удалённое управление Windows-хостами |

**Проверка окружения:**
```bash
# Версия Ansible
ansible --version | head -1
# → ansible [core 2.17.x]

# Доступность целевых хостов
ansible all -m ping

# Проверка пакетного менеджера
ansible all -m ansible.builtin.command -a "which dnf || which apt || which yum"
```

## Жизненный цикл управления патчами

Современный подход к патчингу в Ansible строится на трехфазной модели, обеспечивающей максимальную безопасность и аудит.

### Фаза 1: Подготовка (Pre-Patching)
1.  **Сбор фактов и свидетельств:** Запись текущих версий ядра и критических пакетов.
2.  **Проверка готовности:** Контроль свободного места на диске (минимум 2 ГБ для `/var`) и отсутствия битых пакетов.
3.  **Создание точек отката:** Использование модулей облачных платформ или виртуализации (например, `community.vmware.vmware_guest_snapshot`) для создания мгновенных снимков системного диска.
4.  **Уведомление:** Оповещение команд мониторинга о начале работ для предотвращения ложных срабатываний (Silence).
5.  **Блокировка критических пакетов:** Предотвращение случайного обновления БД, ядра или других критических компонентов.
6.  **Создание бэкапа конфигураций:** Копирование критических конфигов перед обновлением.

#### Блокировка критических пакетов

```yaml
# Debian/Ubuntu: блокировка пакетов через apt-mark
- name: Блокировка критических пакетов
  ansible.builtin.command: "apt-mark hold {{ item }}"
  loop:
    - postgresql-15
    - nginx
    - linux-image-*-generic
  become: true

# RHEL/Rocky: блокировка через dnf versionlock
- name: Установка плагина versionlock
  ansible.builtin.dnf:
    name: dnf-plugin-versionlock
    state: present

- name: Блокировка критических пакетов
  ansible.builtin.command: "dnf versionlock add {{ item }}"
  loop:
    - postgresql-server
    - nginx
  become: true
```

#### Сохранение текущего состояния

```yaml
- name: Запись текущих версий пакетов
  ansible.builtin.shell: "rpm -qa --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort"
  register: installed_packages_rpm
  when: ansible_facts['os_family'] == "RedHat"

- name: Запись текущих версий пакетов (Debian)
  ansible.builtin.shell: "dpkg -l | grep '^ii' | awk '{print $2, $3}'"
  register: installed_packages_dpkg
  when: ansible_facts['os_family'] == "Debian"

- name: Сохранение списка пакетов в файл
  ansible.builtin.copy:
    content: |
      {{ installed_packages_rpm.stdout | default(installed_packages_dpkg.stdout) }}
    dest: "/var/log/patching/packages_before_{{ ansible_date_time.date }}.txt"
    mode: '0644'
```

### Фаза 2: Исполнение (Patching)
Применение обновлений с использованием стратегий конкурентности (`serial`, `throttle`) и фильтрации по категориям безопасности.

### Фаза 3: Верификация (Post-Patching)
1.  **Контрольная перезагрузка:** Выполнение только при необходимости.
2.  **Проверка здоровья (Health Checks):** Верификация доступности портов, ответов API и состояния системных юнитов.
3.  **Отчетность:** Генерация списка обновленных пакетов для целей комплаенса.
4.  **Разблокировка пакетов:** Возврат возможности обновления заблокированных пакетов.
5.  **Очистка кэша:** Удаление скачанных пакетов для освобождения места.

#### Аудит результатов

```yaml
# RHEL/Rocky: просмотр истории обновлений
- name: Просмотр последней транзакции dnf
  ansible.builtin.command: dnf history info last
  register: dnf_history
  changed_when: false

# Debian/Ubuntu: просмотр лога обновлений
- name: Просмотр последних обновлений apt
  ansible.builtin.shell: "grep Upgrade /var/log/apt/history.log | tail -20"
  register: apt_log
  changed_when: false
  when: ansible_facts['os_family'] == "Debian"

# Сравнение до/после
- name: Запись текущих версий пакетов (после обновления)
  ansible.builtin.shell: "rpm -qa --queryformat '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort"
  register: installed_packages_after
  when: ansible_facts['os_family'] == "RedHat"

- name: Сравнение версий
  ansible.builtin.shell: |
    diff /var/log/patching/packages_before_{{ ansible_date_time.date }}.txt \
         /tmp/packages_after.txt
  register: diff_result
  changed_when: diff_result.rc != 0
```

#### Очистка после обновления

```yaml
- name: Очистка кэша пакетов (RHEL)
  ansible.builtin.command: dnf clean all
  when: ansible_facts['os_family'] == "RedHat"

- name: Очистка кэша пакетов (Debian)
  ansible.builtin.apt:
    autoremove: yes
    clean: yes
  when: ansible_facts['os_family'] == "Debian"

- name: Разблокировка пакетов (если нужно вернуть возможность обновления)
  ansible.builtin.command: "apt-mark unhold {{ item }}"
  loop:
    - postgresql-15
    - nginx
  when: ansible_facts['os_family'] == "Debian"
  ignore_errors: true
```

## Стратегии массового обновления

### 1. Последовательное обновление (`serial`)
Директива `serial` ограничивает количество хостов, обрабатываемых Ansible одновременно. Это основной инструмент для реализации Rolling Updates.

```yaml
- name: Обновление веб-серверов
  hosts: web_servers
  serial: "25%"  # Обновление по четверти серверов за раз
  tasks:
    - name: Обновление всех пакетов
      ansible.builtin.package:
        name: "*"
        state: latest
```
# → Ansible обновляет первую группу, и только при успехе переходит к следующей.

**Варианты настройки `serial`:**
*   `serial: 1` — строгая последовательность (Canary-стиль для первого хоста).
*   `serial: [1, 5, 20%]` — прогрессивная стратегия: сначала 1 хост, затем 5, затем 20% от остатка.
*   `any_errors_fatal: true` — при ошибке на любом хосте выполнение всего плейбука немедленно прекращается (критично для Canary).

### 2. Ограничение конкурентности задач (`throttle`)
В отличие от `serial`, который работает на уровне всего плея, `throttle` ограничивает количество одновременных выполнений конкретной задачи.

```yaml
- name: Регистрация в балансировщике
  ansible.builtin.uri:
    url: https://api.lb.example.com/register
  throttle: 1  # Только одно обращение к API за раз, чтобы не перегрузить его
```

### 3. Асинхронные обновления (`async`)
Используются для длительных операций (например, полное обновление ОС или пересборка ядра), которые могут превысить таймаут SSH-сессии.

```yaml
- name: Запуск долгого обновления ОС
  ansible.builtin.command: yum update -y
  async: 3600  # Максимальное время выполнения — 1 час
  poll: 0      # Режим "запустил и забыл"
  register: update_job

- name: Проверка статуса выполнения
  ansible.builtin.async_status:
    jid: "{{ update_job.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 30
  delay: 60
```

### 4. Синхронное обновление с остановкой при ошибке

```yaml
---
- name: Безопасное обновление с block/rescue
  hosts: web_servers
  serial: "25%"
  tasks:
    - block:
        - name: Обновление пакетов
          ansible.builtin.dnf:
            name: "*"
            security: yes
            state: latest
          register: update_result

        - name: Проверка здоровья сервиса
          ansible.builtin.uri:
            url: "http://localhost:8080/health"
            status_code: 200
          register: health_check
          until: health_check.status == 200
          retries: 5
          delay: 10

      rescue:
        - name: Откат через dnf (RHEL)
          ansible.builtin.command: dnf history undo last -y
          when: ansible_facts['os_family'] == "RedHat"

        - name: Уведомление об ошибке
          ansible.builtin.uri:
            url: "https://hooks.slack.com/services/T00/B00/XXX"
            method: POST
            body_format: json
            body:
              text: "Патчинг провалился на {{ inventory_hostname }}. Откат выполнен."
```

## Целевое обновление безопасности

В 2025-2026 годах рекомендуется отдавать приоритет обновлениям безопасности, а не обновлять все пакеты до `latest` без разбора.

### RHEL / Rocky / AlmaLinux
Используйте модуль `dnf` с параметром `security`.
```yaml
- name: Установка только security-патчей
  ansible.builtin.dnf:
    name: "*"
    security: yes
    state: latest
```

**Просмотр доступных CVE:**
```yaml
- name: Список доступных исправлений безопасности
  ansible.builtin.command: dnf updateinfo list --security
  register: cve_list
  changed_when: false

- name: Подсчёт количества CVE
  ansible.builtin.debug:
    msg: "Доступно {{ cve_list.stdout_lines | length }} исправлений безопасности"

- name: Детальный список CVE (только критические)
  ansible.builtin.command: dnf updateinfo list --security --severity Critical
  register: critical_cves
  changed_when: false
```

### Ubuntu / Debian
Для управления безопасностью рекомендуется использовать `unattended-upgrades` или точечное обновление через `apt`.
```yaml
- name: Обновление кеша и установка только обновлений безопасности
  ansible.builtin.apt:
    upgrade: dist
    update_cache: yes
    only_upgrade: yes
```

**Просмотр доступных обновлений:**
```yaml
- name: Список доступных обновлений
  ansible.builtin.shell: apt list --upgradable 2>/dev/null
  register: available_updates
  changed_when: false

- name: Подсчёт обновлений
  ansible.builtin.debug:
    msg: "Доступно {{ available_updates.stdout_lines | length }} обновлений"
```

### Windows
Для Windows-инфраструктуры используется специализированный модуль.
```yaml
- name: Установка критических обновлений Windows
  ansible.windows.win_updates:
    category_names:
      - SecurityUpdates
      - CriticalUpdates
    reboot: yes  # Автоматическая перезагрузка только при необходимости
```

### SUSE / openSUSE
```yaml
- name: Обновление пакетов (zypper)
  ansible.builtin.zypper:
    name: "*"
    state: latest
    type: patch
```

## Умная перезагрузка (Conditional Reboot)

Безусловная перезагрузка — плохая практика. Ansible позволяет проверять необходимость рестарта.

### Реализация для Debian/Ubuntu
Проверяется наличие файла-маркера.
```yaml
- name: Проверка необходимости перезагрузки (Debian)
  ansible.builtin.stat:
    path: /var/run/reboot-required
  register: reboot_required_file

- name: Перезагрузка Linux
  ansible.builtin.reboot:
    msg: "Reboot initiated by Ansible after patching"
  when: reboot_required_file.stat.exists
```

### Реализация для RHEL/Rocky
Используется утилита `needs-restarting`.
```yaml
- name: Проверка необходимости перезагрузки (RHEL)
  ansible.builtin.command: needs-restarting -r
  register: result
  failed_when: false
  changed_when: result.rc != 0

- name: Перезагрузка RHEL
  ansible.builtin.reboot:
  when: result.rc != 0
```

### Определение процессов, требующих перезапуска

```yaml
- name: Список процессов с обновлёнными библиотеками
  ansible.builtin.command: needs-restarting -s
  register: restarted_services
  changed_when: false

- name: Перезапуск только затронутых сервисов
  ansible.builtin.systemd:
    name: "{{ item }}"
    state: restarted
  loop: "{{ restarted_services.stdout_lines }}"
  when: restarted_services.stdout_lines | length > 0
```

### Координация перезагрузки с балансировщиком

```yaml
- name: Снять с балансировщика перед перезагрузкой
  ansible.builtin.uri:
    url: "https://api.lb.example.com/deregister/{{ inventory_hostname }}"
    method: POST
    status_code: 200
  delegate_to: localhost

- name: Перезагрузка
  ansible.builtin.reboot:
    msg: "Rolling reboot after patching"

- name: Проверка готовности сервиса
  ansible.builtin.uri:
    url: "http://localhost:8080/health"
    status_code: 200
  register: health
  until: health.status == 200
  retries: 12
  delay: 5

- name: Вернуть на балансировщик
  ansible.builtin.uri:
    url: "https://api.lb.example.com/register/{{ inventory_hostname }}"
    method: POST
    status_code: 200
  delegate_to: localhost
```

## Практические сценарии

### Сценарий 1: Комплексный кроссплатформенный Workflow
Безопасное обновление с предварительными проверками и Canary-тестированием.

```yaml
---
- name: Корпоративный стандарт патчинга 2026
  hosts: servers
  become: true
  serial: [1, "100%"]
  any_errors_fatal: true

  tasks:
    # --- Фаза 1: Pre-patching ---
    - name: Проверка свободного места в /var
      ansible.builtin.assert:
        that: ansible_facts['mounts'] | selectattr('mount', 'equalto', '/var') | map(attribute='size_available') | first > 2000000000
        msg: "Недостаточно места для обновлений"

    # --- Фаза 2: Patching ---
    - name: Обновление Linux (Debian)
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes
      when: ansible_facts['os_family'] == "Debian"
      register: apt_res

    - name: Обновление Linux (RedHat)
      ansible.builtin.dnf:
        name: "*"
        security: yes
        state: latest
      when: ansible_facts['os_family'] == "RedHat"
      register: dnf_res

    # --- Фаза 3: Post-patching & Reboot ---
    - name: Перезагрузка при необходимости
      ansible.builtin.reboot:
      when: 
        - (ansible_facts['os_family'] == "RedHat" and dnf_res.changed) or
          (ansible_facts['os_family'] == "Debian" and apt_res.changed)

    - name: Верификация работы приложения
      ansible.builtin.uri:
        url: "http://localhost:8080/health"
        status_code: 200
      register: health_check
      until: health_check.status == 200
      retries: 5
      delay: 10
```

### Сценарий 2: Обновление с откатом при ошибке

```yaml
---
- name: Безопасное обновление с block/rescue/always
  hosts: critical_servers
  serial: 1
  become: true

  tasks:
    - block:
        # --- Pre-patching ---
        - name: Сохранение текущих версий
          ansible.builtin.shell: "rpm -qa > /tmp/packages_before.txt"
          when: ansible_facts['os_family'] == "RedHat"

        - name: Создание снимка (VMware)
          community.vmware.vmware_guest_snapshot:
            datacenter: "{{ vcenter_dc }}"
            folder: "/{{ vcenter_dc }}/vm/{{ vcenter_folder }}"
            name: "{{ inventory_hostname }}"
            snapshot_name: "pre-patch-{{ ansible_date_time.date }}"
            state: present
          delegate_to: localhost
          when: use_snapshot | default(false)

        # --- Patching ---
        - name: Обновление пакетов
          ansible.builtin.dnf:
            name: "*"
            security: yes
            state: latest
          register: update_result

        # --- Post-patching ---
        - name: Перезагрузка (если обновлено ядро)
          ansible.builtin.reboot:
            msg: "Reboot after security patching"
          when: update_result.changed

        - name: Верификация сервиса
          ansible.builtin.uri:
            url: "http://localhost:8080/health"
            status_code: 200
          register: health
          until: health.status == 200
          retries: 10
          delay: 15

      rescue:
        - name: Откат через dnf
          ansible.builtin.command: dnf history undo last -y
          when: ansible_facts['os_family'] == "RedHat"
          register: undo_result

        - name: Откат через apt (Debian)
          ansible.builtin.shell: |
            # Получение списка обновлённых пакетов и откат
            apt-mark hold $(apt list --upgradable 2>/dev/null | cut -d/ -f1)
          when: ansible_facts['os_family'] == "Debian"

        - name: Откат снимка (VMware)
          community.vmware.vmware_guest_snapshot:
            datacenter: "{{ vcenter_dc }}"
            folder: "/{{ vcenter_dc }}/vm/{{ vcenter_folder }}"
            name: "{{ inventory_hostname }}"
            snapshot_name: "pre-patch-{{ ansible_date_time.date }}"
            state: revert
          delegate_to: localhost
          when: use_snapshot | default(false)

        - name: Уведомление об откате
          ansible.builtin.uri:
            url: "{{ slack_webhook }}"
            method: POST
            body_format: json
            body:
              text: "Откат выполнен на {{ inventory_hostname }}. Причина: {{ ansible_failed_result.msg | default('ошибка верификации') }}"

      always:
        - name: Логирование результата
          ansible.builtin.lineinfile:
            path: /var/log/patching_history.log
            line: "{{ ansible_date_time.iso8601 }} | {{ inventory_hostname }} | {{ 'SUCCESS' if update_result.changed else 'NO_CHANGES' }} | {{ 'ROLLED_BACK' if undo_result is defined else 'OK' }}"
            create: yes
```

### Сценарий 3: Обновление по группам с определёнными репозиториями

```yaml
---
- name: Обновление только определённых компонентов
  hosts: all
  become: true
  serial: "30%"

  tasks:
    # Обновление только Security
    - name: Security-патчи (RHEL)
      ansible.builtin.dnf:
        name: "*"
        security: yes
        state: latest
      when: ansible_facts['os_family'] == "RedHat"

    # Обновление только ядра
    - name: Обновление ядра (RHEL)
      ansible.builtin.dnf:
        name: "kernel*"
        state: latest
      when:
        - ansible_facts['os_family'] == "RedHat"
        - update_kernel | default(false)

    # Исключение определённых пакетов
    - name: Обновление с исключениями (Debian)
      ansible.builtin.apt:
        upgrade: dist
        update_cache: yes
        dpkg_options: "skip-broken"
      when: ansible_facts['os_family'] == "Debian"
      environment:
        DEBIAN_FRONTEND: noninteractive
```

## Устранение типичных ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `E: Could not get lock /var/lib/dpkg/lock` | Фоновый процесс (unattended-upgrades) блокирует dpkg | Остановите `unattended-upgrades` перед запуском или используйте `retries` + `delay` |
| `DNF transaction failed` | Конфликт зависимостей пакетов | Используйте `--skip-broken` или `--best` |
| `No package matching` | Пакет не найден в репозитории | Проверьте `dnf repolist` / `apt-cache policy <pkg>` |
| `needs-restarting: command not found` | Утилита не установлена | `yum install -y needs-restarting` или `dnf install -y needs-restarting` |
| `Reboot required but skipped` | `reboot` в `when` не срабатывает | Проверьте регистрацию переменной (register + changed_when) |
| `Permission denied` | Нет прав sudo | Убедитесь, что `become: true` и sudo настроен |
| `Connection closed by remote host` | Таймаут SSH при долгом обновлении | Используйте `async` или увеличьте `timeout` |
| `Ansible module not found` | Коллекция не установлена | `ansible-galaxy collection install <name>` |
| `Hash Sum mismatch` | Повреждён кэш пакетов | `apt clean && apt update` или `dnf clean all` |
| `dpkg was interrupted` | Прерывание во время обновления | `dpkg --configure -a` |

**Диагностика:**
```bash
# Проверка текущих обновлений
ansible all -m shell -a "apt list --upgradable" --one-line  # Debian/Ubuntu
ansible all -m shell -a "dnf check-update" --one-line       # RHEL/Rocky

# Проверка блокированных пакетов
ansible all -m shell -a "apt-mark showhold"  # Debian/Ubuntu
ansible all -m shell -a "dnf versionlock list"  # RHEL/Rocky

# Проверка истории обновлений
ansible all -m shell -a "dnf history list" --one-line
ansible all -m shell -a "grep Upgrade /var/log/apt/history.log" --one-line

# Проверка необходимости перезагрузки
ansible all -m shell -a "test -f /var/run/reboot-required && echo REBOOT || echo OK"
ansible all -m shell -a "needs-restarting -r; echo RC=$?"
```

## Контрольный список: лучшие практики

- [ ] **Canary перед массовым обновлением:** Запускайте `serial: 1` на тестовом хосте перед раскаткой
- [ ] **Блокировка критических пакетов:** Используйте `apt-mark hold` / `dnf versionlock` для БД, ядра, NSS
- [ ] **Проверка свободного места:** Минимум 2 ГБ свободного в `/var` перед обновлением
- [ ] **Снимки/бэкапы:** Создавайте точки отката перед обновлением критических серверов
- [ ] **Security-only обновления:** Приоритизируйте `security: yes` над полным обновлением
- [ ] **Conditional reboot:** Перезагружайте только при необходимости (проверка `/var/run/reboot-required` или `needs-restarting`)
- [ ] **Координация с LB:** Снимайте хост с балансировщика перед перезагрузкой
- [ ] **Post-patching health check:** Верифицируйте доступность сервиса после обновления
- [ ] **Аудит:** Логируйте результаты обновлений для комплаенса
- [ ] **Очистка кэша:** Выполняйте `dnf clean all` / `apt clean` после обновления
- [ ] **Error handling:** Используйте `block/rescue/always` для отката при ошибках
- [ ] **Логирование:** Сохраняйте списки пакетов до/после обновления

## Дополнительная información

- [Модули управления системой](./Modules/ansible_service_and_system_config_modules.md) — детали параметров `ansible.builtin.reboot`.
- [Кроссплатформенные концепции](./CrossPlatform/concepts.md) — глубокое погружение в разделение логики по ОС.
- [Оптимизация производительности](./ansible_performance_tuning.md) — настройка `forks` и `ssh_pipelining` для ускорения массового патчинга.
- [Выполнение плейбука: база](./PlaybookStructure/basics.md) — основы работы с `serial` и `tags`.
- [Управление ходом выполнения](./PlaybookStructure/flow_control.md) — использование `block` и `rescue` для обработки ошибок обновления.
