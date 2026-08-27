# Ansible: OS Hardening и комплаенс

## Определения

**Ansible OS Hardening** — процесс автоматизированного укрепления защиты операционной системы с использованием Ansible для приведения конфигурации в соответствие отраслевым стандартам безопасности.

**Compliance as Code (Комплаенс как код)** — парадигма управления ИТ-инфраструктурой, при которой требования безопасности и комплаенса описываются в виде декларативного кода, позволяющего проводить автоматизированный аудит, валидацию и исправление (remediation) состояния систем.

**OpenSCAP** — свободная реализация протокола **SCAP (Security Content Automation Protocol)**, предоставляющая набор инструментов для автоматизированной проверки систем на соответствие политикам безопасности, обнаружения уязвимостей и формирования отчетов.

**CIS Benchmarks (Center for Internet Security)** — признанные во всем мире «золотые стандарты» для безопасной настройки систем, ПО и сетей. Разделяются на два уровня:
*   **Level 1 (Basic):** Базовые настройки безопасности, которые не оказывают существенного влияния на производительность и функциональность сервисов.
*   **Level 2 (High Security):** Более строгие настройки для сред с повышенными требованиями к безопасности (Defense-in-Depth). Могут ограничивать функциональность.

**STIG (Security Technical Implementation Guide)** — набор правил безопасности, разработанный агентством DISA (США) для систем, используемых в оборонных ведомствах. Считается одним из самых строгих стандартов харденинга.

## Основные концепции

### Стратегия укрепления систем

Процесс Hardening в экосистеме Ansible строится по циклической модели:
1.  **Определение политики:** Выбор стандарта (CIS, STIG, NIST) и уровня строгости.
2.  **Аудит (Scanning):** Проверка текущего состояния систем с помощью OpenSCAP или специализированных Ansible-ролей в `check_mode`.
3.  **Исправление (Remediation):** Применение Ansible-сценариев для приведения параметров к целевому состоянию.
4.  **Непрерывный мониторинг:** Обнаружение «дрейфа конфигурации» (drift detection) и автоматический возврат к эталону.

### Иерархия Hardening в Ansible

Рекомендуется разделять процесс на три уровня:
*   **Base Hardening:** Настройка ядра (`sysctl`), базовых прав доступа и SSH. Реализуется через общие роли (например, `devsec.hardening`).
*   **Compliance Hardening:** Приведение к конкретному стандарту (CIS L1/L2). Реализуется через специализированные роли (Ansible Lockdown).
*   **Application Hardening:** Специфичные настройки для Web, DB или Docker (см. [Харденинг контейнеров](../../Docker/Docker_security/container_hardening.md)).

## Готовые инструменты и коллекции

### 1. Коллекция DevSec (Hardening Framework)

Проект DevSec является стандартом де-факто для базового укрепления Linux. Начиная с 2024–2025 гг., рекомендуется переходить от отдельных ролей к использованию коллекции.

*   **Коллекция:** `devsec.hardening`
*   **Актуальная версия:** 10.6.0 (май 2026)
*   **Поддерживаемые ОС (2026):**
    *   Ubuntu 22.04 / 24.04 / 26.04
    *   RHEL 8 / 9 / 10
    *   AlmaLinux 8 / 9 / 10
    *   Rocky Linux 8 / 9 / 10
    *   CentOS Stream 9
    *   Debian 11 / 12 / 13
    *   Fedora 42 / 43 / 44
*   **Включенные роли:** `os_hardening`, `ssh_hardening`, `nginx_hardening`, `mysql_hardening` (в разработке: `apache_hardening`, `windows_hardening`)
*   **Установка:**
    ```bash
    ansible-galaxy collection install devsec.hardening
    # → Installing 'devsec.hardening' to '.../collections/ansible_collections/devsec/hardening'
    ```
*   **Ключевые изменения в 10.x:**
    *   Ограничение `ptrace` для привилегированных пользователей (по умолчанию `ptrace_scope=2`)
    *   Автоматическое обновление APT-кэша перед установкой пакетов на свежих системах
    *   Корректная работа с systemd socket activation для SSH на Ubuntu 24.04+
    *   Значение `kernel.unprivileged_userns_clone` зависит от версии ядра

**Пример расширенной настройки (полный набор переменных):**
```yaml
- name: Применение базового харденинга
  hosts: all
  become: true
  roles:
    - role: devsec.hardening.os_hardening
      vars:
        # --- SSH Hardening ---
        ssh_allow_root_with_key: true
        ssh_password_authentication: false
        ssh_max_auth_tries: 3
        ssh_permit_empty_passwords: false
        ssh_x11_forwarding: false
        ssh_client_alive_interval: 300
        ssh_client_alive_count_max: 2

        # --- sysctl (безопасность ядра) ---
        sysctl_overwrite:
          # Защита от LPE
          kernel.kptr_restrict: 2
          kernel.dmesg_restrict: 1
          kernel.perf_event_paranoid: 3
          kernel.yama.ptrace_scope: 2
          # ASLR
          kernel.randomize_va_space: 2
          # Сеть
          net.ipv4.ip_forward: 0
          net.ipv6.conf.all.forwarding: 0
          net.ipv4.conf.all.rp_filter: 1
          # Файловая система
          fs.protected_fifos: 2
          fs.protected_regular: 2
          fs.protected_symlinks: 1
          fs.protected_hardlinks: 1

        # --- Исключения ---
        os_unused_package_types: []  # Не удалять пакеты
        os_ignore_users: []          # Не удалять системных пользователей

        # --- Файловые права ---
        os_file_mode_uid:
          /etc/passwd: { mode: "0644", owner: "root", group: "root" }
          /etc/shadow: { mode: "0640", owner: "root", group: "shadow" }
```

**Важные побочные эффекты параметров sysctl (см. [Харденинг ядра Linux](../../Linux/Security/Mechanisms/Kernel/hardening.md)):**

| Параметр | Что может сломаться | Рекомендация |
| :--- | :--- | :--- |
| `kernel.kptr_restrict=2` | Falco, Sysdig, perf | Отключить для хостов с профилировщиками |
| `kernel.unprivileged_bpf_disabled=1` | Cilium, Falco, bpftrace | Добавить в исключения если используется eBPF |
| `net.ipv4.ip_forward=0` | Kubernetes, Docker, CNI | Установить `1` для контейнерных хостов |
| `user.max_user_namespaces=0` | Rootless контейнеры | Не использовать на Docker-хостах |

### 2. Ansible Lockdown (CIS & STIG)

Проект предоставляетroles для глубокого соответствия стандартам. Идеально подходит для регулируемых отраслей (финтех, медицина, госсектор). Поддерживает как **Remediation** (применение), так и **Audit** (проверку через Goss).

*   **Репозитории:** [Ansible Lockdown GitHub](https://github.com/ansible-lockdown)
*   **Документация:** [ansible-lockdown.readthedocs.io](https://ansible-lockdown.readthedocs.io/)
*   **Актуальные роли (2026):**

**CIS Benchmarks (Linux):**

| Роль | ОС | Поддержка |
| :--- | :--- | :--- |
| `ansible-lockdown.UBUNTU24-CIS` | Ubuntu 24.04 LTS | Активна |
| `ansible-lockdown.UBUNTU26-CIS` | Ubuntu 26.04 LTS | В разработке |
| `ansible-lockdown.RHEL8-CIS` | RHEL 8 / Alma 8 / Rocky 8 | Активна |
| `ansible-lockdown.RHEL9-CIS` | RHEL 9 / Alma 9 / Rocky 9 | Активна |
| `ansible-lockdown.RHEL10-CIS` | RHEL 10 / Alma 10 / Rocky 10 | Активна |
| `ansible-lockdown.DEBIAN12-CIS` | Debian 12 | Активна |
| `ansible-lockdown.DEBIAN13-CIS` | Debian 13 | Активна |
| `ansible-lockdown.AMAZON2023-CIS` | Amazon Linux 2023 | Активна |

**CIS Benchmarks (Cloud / Applications):**

| Роль | Платформа | Примечание |
| :--- | :--- | :--- |
| `ansible-lockdown.AWS-FOUNDATIONS-CIS` | AWS | Только Remediation |
| `ansible-lockdown.AZURE-CIS` | Azure | Только Remediation |
| `ansible-lockdown.APACHE-2.4-CIS` | Apache HTTP Server | |
| `ansible-lockdown.POSTGRES-12-CIS` | PostgreSQL | |

**DISA STIG Roles:**

| Роль | ОС |
| :--- | :--- |
| `ansible-lockdown.UBUNTU24-STIG` | Ubuntu 24.04 LTS |
| `ansible-lockdown.RHEL8-STIG` | RHEL 8 |
| `ansible-lockdown.RHEL9-STIG` | RHEL 9 |

**Важно:** Роли Lockdown крайне агрессивны. Всегда начинайте с предварительной оценки:

```yaml
# Префикс переменных для безопасного тестирования
vars:
  # Аудит-режим: показывает что будет изменено без применения
  audit_only: true
  # Включение только критических правил (CAT I / CAT II)
  # Для STIG: rhel_08_010000, rhel_08_010020 и т.д.
```

**Пример: применение CIS Level 2 на Ubuntu 24.04:**
```yaml
- name: CIS Level 2 Hardening
  hosts: ubuntu_servers
  become: true
  vars:
    # Отключение правил, конфликтующих с Docker
    cis_rule_1_1_1_1: false  # tmp noexec (ломает Docker builds)
    cis_rule_5_3: false      # PAM (если используется LDAP)
  roles:
    - ansible-lockdown.UBUNTU24-CIS
```

## Интеграция с OpenSCAP

OpenSCAP позволяет автоматизировать аудит и генерировать плейбуки исправления на основе актуальных политик **SCAP Security Guide (SSG)**.

### 1. Работа с профилями SSG

Пакет `scap-security-guide` содержит Data Streams (файлы `.xml`), описывающие правила для конкретных ОС.

**Актуальные версии профилей (SSG 0.1.80+, июнь 2026):**

| ОС | CIS Benchmark | DISA STIG | Файл Data Stream |
| :--- | :--- | :--- | :--- |
| RHEL 8 | v4.0.0 | V2R6 | `ssg-rhel8-ds.xml` |
| RHEL 9 | v2.0.0+ | V2R7 | `ssg-rhel9-ds.xml` |
| RHEL 10 | В разработке | В разработке | `ssg-rhel10-ds.xml` |
| Ubuntu 24.04 | CIS Level 1/2 | V1R1 | `ssg-ubuntu2404-ds.xml` |
| Debian 12 | CIS Level 1/2 | — | `ssg-debian12-ds.xml` |

**Просмотр доступных профилей для RHEL 9:**
```bash
oscap info /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
# → xccdf_org.ssgproject.content_profile_cis (Level 2)
# → xccdf_org.ssgproject.content_profile_cis_server_l1 (Level 1)
# → xccdf_org.ssgproject.content_profile_stig (DISA STIG V2R7)
# → xccdf_org.ssgproject.content_profile_cis_workstation_l1
# → xccdf_org.ssgproject.content_profile_bsi_itGrundschutz (NEW)
```

**Просмотр доступных профилей для Ubuntu 24.04:**
```bash
oscap info /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
# → xccdf_org.ssgproject.content_profile_cis_level1_server
# → xccdf_org.ssgproject.content_profile_cis_level2_server
# → xccdf_org.ssgproject.content_profile_cis_level1_workstation
# → xccdf_org.ssgproject.content_profile_cis_level2_workstation
```

### 2. Генерация Remediation-плейбуков

Вы можете сгенерировать Ansible-код, идеально подходящий под конкретную версию вашей системы и профиль.

```bash
# Генерация плейбука для CIS Level 2 на Ubuntu 24.04
oscap xccdf generate remediation --fix-type ansible \
  --profile xccdf_org.ssgproject.content_profile_cis \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml > cis_remediation.yml
# → Готовый плейбуки с задачами для каждого правила CIS

# Генерация для RHEL 9 STIG
oscap xccdf generate remediation --fix-type ansible \
  --profile xccdf_org.ssgproject.content_profile_stig \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml > stig_remediation.yml
```

### 3. Настройка профиля через Tailoring-файл

Tailoring позволяет исключить или изменить конкретные правила без модификации исходного профиля. Это критически важно для production-сред, где отдельные проверки могут нарушить работу сервисов.

**Создание tailoring-файла:**
```bash
# Экспорт базового профиля
oscap xccdf generate fix --fix-type ansible \
  --profile xccdf_org.ssgproject.content_profile_cis \
  --output tailoring_base.yml \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml

# Генерация tailoring-файла (XML) для исключения правил
oscap xccdf generate fix --fix-type ansible \
  --profile xccdf_org.ssgproject.content_profile_cis \
  --output cis_tailored.yml \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
```

**Пример tailoring-файла (XML):**
```xml
<tailoring xmlns="http://checklists.nist.gov/xccdf/1.2" id="custom_cis">
  <benchmark href="/usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml"/>
  <version time="2026-08-26T12:00:00">1</version>

  <select idref="xccdf_org.ssgproject.content_rule_disable_usb_storage" selected="false"/>
  <select idref="xccdf_org.ssgproject.content_rule_sysctl_net_ipv4_ip_forward" selected="false"/>
  <select idref="xccdf_org.ssgproject.content_rule_mount_option_dev_shm_noexec" selected="false"/>

  <refine-value idref="xccdf_org.ssgproject.content_value_sshd_maxauthtries" selector="4"/>
</tailoring>
```

**Применение tailoring-файла:**
```bash
oscap xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_cis \
  --tailoring /path/to/cis_tailored.xml \
  --results results.xml \
  --report report.html \
  /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
```

### 3. Автоматизированный аудит через Ansible

```yaml
- name: Аудит безопасности OpenSCAP
  hosts: servers
  become: true
  vars:
    oscap_profile: xccdf_org.ssgproject.content_profile_stig
    oscap_content: /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
    report_dir: /var/log/compliance

  tasks:
    - name: Создать директорию для отчетов
      ansible.builtin.file:
        path: "{{ report_dir }}"
        state: directory
        mode: '0750'

    - name: Выполнить сканирование на соответствие STIG
      ansible.builtin.command:
        cmd: >
          oscap xccdf eval
          --profile {{ oscap_profile }}
          --results {{ report_dir }}/results.xml
          --report {{ report_dir }}/report.html
          {{ oscap_content }}
      register: scan_out
      # rc=0 — все правила пройдены, rc=2 — есть провалы
      failed_when: scan_out.rc not in [0, 2]
      changed_when: false

    - name: Собрать статистику
      ansible.builtin.shell: |
        TOTAL=$(grep -c '<rule-result' {{ report_dir }}/results.xml || echo 0)
        FAIL=$(grep -c 'result="fail"' {{ report_dir }}/results.xml || echo 0)
        PASS=$((TOTAL - FAIL))
        echo "total=$TOTAL pass=$PASS fail=$FAIL"
      register: stats
      changed_when: false

    - name: Вывести статистику
      ansible.builtin.debug:
        msg: "Аудит завершен: {{ stats.stdout }}"

    - name: Алярм при несоответствии
      ansible.builtin.debug:
        msg: >
          Обнаружены нарушения! См. отчет: {{ report_dir }}/report.html
          Статистика: {{ stats.stdout }}
      when: scan_out.rc == 2

    - name: Загрузить отчет на Control Node
      ansible.builtin.fetch:
        src: "{{ report_dir }}/report.html"
        dest: "reports/{{ inventory_hostname }}_oscap_report.html"
        flat: true
      when: scan_out.rc == 2
```

## Практические сценарии

### Сценарий 1: Предотвращение SSH-блокировки (Safety First)

Применение Hardening часто приводит к потере доступа по SSH из-за изменения `sshd_config`.

**Рекомендации:**
1.  **Проверка ключей:** Убедитесь, что ваш публичный ключ добавлен в `authorized_keys` ДО отключения паролей.
2.  **Тестовое соединение:** Используйте `meta: flush_handlers` и второй SSH-сеанс для проверки доступа до завершения работы плейбука.
3.  **Использование `authselect`:** На RHEL 8/9 всегда проверяйте совместимость ролей с `authselect`, чтобы не сломать PAM-стек.

### Сценарий 2: Интеграция с Ansible Automation Platform (AAP) / AWX

Для корпоративных сред Hardening выносится в отдельные **Workflow Job Templates**:
1.  **Шаг 1:** Запуск `Audit Job` (OpenSCAP).
2.  **Шаг 2:** Если аудит провален — Approval Node (одобрение администратора).
3.  **Шаг 3:** Запуск `Remediation Job` (применение роли Lockdown).
4.  **Шаг 4:** Повторный аудит для подтверждения исправления.

**Пример Workflow в AAP/AWX:**
```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌─────────────┐
│ Audit Job   │────▶│ Approval     │────▶│ Remediation   │────▶│ Re-Audit    │
│ (OpenSCAP)  │     │ (if failed)  │     │ (Lockdown)    │     │ (Verify)    │
└─────────────┘     └──────────────┘     └───────────────┘     └─────────────┘
       │                    │
       │ rc=0 ─────────────┘ ( compliant, skip remediation )
       ▼
  ┌─────────┐
  │ Success  │
  └─────────┘
```

### Сценарий 3: CI/CD Pipeline для Hardening (GitLab CI)

Полный цикл аудита и ремедиации в пайплайне:

```yaml
stages:
  - lint
  - audit
  - remediate
  - verify

variables:
  ANSIBLE_FORCE_COLOR: "true"

ansible_lint:
  stage: lint
  image: cytopia/ansible-lint
  script:
    - ansible-lint --profile security playbooks/hardening.yml

oscap_audit:
  stage: audit
  image: rhel9/openscap:latest
  script:
    - |
      oscap xccdf eval \
        --profile xccdf_org.ssgproject.content_profile_cis \
        --results results.xml \
        --report report.html \
        /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml || true
    - FAIL=$(grep -c 'result="fail"' results.xml || echo 0)
    - echo "Failed rules: $FAIL"
    - |
      if [ "$FAIL" -gt 0 ]; then
        echo "Compliance check failed — triggering remediation"
        exit 1
      fi
  artifacts:
    paths:
      - report.html
    when: always
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"

remediate:
  stage: remediate
  image: cytopia/ansible
  script:
    - ansible-playbook playbooks/hardening.yml --check  # Preview first
    - ansible-playbook playbooks/hardening.yml           # Apply
  when: on_failure  # Только если аудит провален
  allow_failure: false

verify:
  stage: verify
  image: rhel9/openscap:latest
  script:
    - |
      oscap xccdf eval \
        --profile xccdf_org.ssgproject.content_profile_cis \
        --results final_results.xml \
        --report final_report.html \
        /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml || true
    - FAIL=$(grep -c 'result="fail"' final_results.xml || echo 0)
    - |
      if [ "$FAIL" -gt 0 ]; then
        echo "ERROR: Still $FAIL non-compliant rules after remediation"
        exit 1
      fi
  artifacts:
    paths:
      - final_report.html
    when: always
```

### Сценарий 4: Rollback при Hardening

Откат изменений — критически важный аспект. Всегда планируйте стратегию отката до применения Hardening.

**Подготовка к откату:**
```yaml
- name: Hardening с возможностью отката
  hosts: servers
  become: true
  vars:
    backup_dir: /var/backups/hardening

  tasks:
    # --- Фаза 1: Резервное копирование ---
    - name: Создать директорию для бэкапов
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: '0700'

    - name: Бэкап критичных конфигов
      ansible.builtin.copy:
        src: "{{ item }}"
        dest: "{{ backup_dir }}/{{ item | basename }}.bak"
        remote_src: true
        mode: '0600'
      loop:
        - /etc/ssh/sshd_config
        - /etc/sysctl.conf
        - /etc/security/limits.conf
        - /etc/pam.d/sshd

    - name: Бэкап текущих sysctl
      ansible.builtin.shell: |
        sysctl -a > {{ backup_dir }}/sysctl_current.txt
      changed_when: false

    # --- Фаза 2: Применение Hardening ---
    - name: Применить roles
      ansible.builtin.include_role:
        name: devsec.hardening.os_hardening

    # --- Фаза 3: Проверка доступности SSH ---
    - name: Проверка SSH после изменений
      ansible.builtin.wait_for_connection:
        delay: 10
        timeout: 60

    # --- Фаза 4: Откат при проблемах ---
    - name: Восстановить sshd_config при ошибке
      ansible.builtin.copy:
        src: "{{ backup_dir }}/sshd_config.bak"
        dest: /etc/ssh/sshd_config
        remote_src: true
        owner: root
        group: root
        mode: '0600'
      notify: restart sshd
      when: hardening_failed is defined and hardening_failed

    - name: Восстановить sysctl при ошибке
      ansible.builtin.shell: |
        sysctl -p {{ backup_dir }}/sysctl_current.txt
      when: hardening_failed is defined and hardening_failed

  handlers:
    - name: restart sshd
      ansible.builtin.systemd:
        name: sshd
        state: restarted
```

**Автоматический rollback через Handler:**
```yaml
# В roles/hardening/tasks/main.yml
- name: Применить SSH Hardening
  ansible.builtin.template:
    src: sshd_config.j2
    dest: /etc/ssh/sshd_config
    validate: '/usr/sbin/sshd -t -f %s'  # Проверка синтаксиса!
  notify: rollback sshd on failure

- name: Проверить доступность SSH
  ansible.builtin.wait_for_connection:
    delay: 5
    timeout: 30
  register: ssh_check
  ignore_errors: true

- name: Откатить при недоступности SSH
  ansible.builtin.debug:
    msg: "SSH недоступен! Выполняется откат..."
  when: ssh_check is failed

handlers:
  - name: rollback sshd on failure
    ansible.builtin.copy:
      src: /etc/ssh/sshd_config.bak
      dest: /etc/ssh/sshd_config
      remote_src: true
    listen: "restart sshd"
```

## Бестиарий и рекомендации (Чек-лист 2026)

*   **Идемпотентность:** Ваши роли Hardening должны быть на 100% идемпотентными. Повторный запуск не должен менять состояние системы, если она уже защищена.
*   **Исключения (Whitelist):** Всегда составляйте список исключений для специфических нагрузок (например, не отключайте `ptrace`, если используете инструменты профилирования как `strace` или `gdb`).
*   **Разделение /tmp и /var/tmp:** CIS требует монтирования этих директорий с параметрами `noexec, nosuid, nodev`. Убедитесь, что у приложений есть место для временных файлов, не требующих исполнения.
*   **Логирование:** Включайте расширенный аудит через `auditd` для мониторинга попыток изменения системных файлов после применения Hardening.
*   **FIPS Compliance:** В government/financial средах используйте roles с поддержкой FIPS 140-2/3 (ansible-lockdown roles поддерживают `fips_mode: true`).
*   **Testing перед продом:** Всегда запускайте roles в `check_mode` или на тестовых серверах перед mass-ремедиацией.
*   **Версионирование политик:** Храните tailoring-файлы и переменные roles в Git для отслеживания изменений compliance-политик.
*   **Непрерывный мониторинг:** После однократного Hardening настройте Wazuh SCA или定时 cron-задачи с OpenSCAP для обнаружения drift-конфигурации.

## Troubleshooting (Типичные ошибки)

### 1. SSH-блокировка после Hardening

**Симптом:** Потеря доступа по SSH после применения `ssh_hardening`.

**Диагностика:**
```bash
# На удалённой машине (через консоль/iDRAC/IPMI):
sudo systemctl status sshd
sudo journalctl -u sshd --since "10 minutes ago"
sudo sshd -T  # Проверка конфигурации

# Проверка ключей аутентификации
ls -la ~/.ssh/authorized_keys
```

**Решение:**
```bash
# Через out-of-band доступ:
sudo cp /etc/ssh/sshd_config.bak /etc/ssh/sshd_config
sudo systemctl restart sshd
```

**Профилактика:** Всегда используйте `validate: '/usr/sbin/sshd -t -f %s'` в задачах конфигурации SSH.

### 2. Конфликт sysctl с контейнерами

**Симптом:** Kubernetes/Docker поды не могут маршрутизировать трафик.

**Причина:** `net.ipv4.ip_forward=0` нарушает маршрутизацию для CNI.

**Решение:**
```yaml
# Исключить правило для контейнерных хостов
sysctl_overwrite:
  net.ipv4.ip_forward: "{{ 1 if is_container_host else 0 }}"

# Или через group_vars
# group_vars/container_hosts.yml
sysctl_overwrite:
  net.ipv4.ip_forward: 1
  net.bridge.bridge-nf-call-iptables: 1
```

### 3. SELinux-конфликты (RHEL/CentOS)

**Симптом:** Сервисы не запускаются после Hardening из-за неправильных контекстов.

**Диагностика:**
```bash
# Проверка SELinux-отказов
ausearch -m avc --start recent
sudo sealert -a /var/log/audit/audit.log
```

**Решение:**
```yaml
# Генерация и применение SELinux-политики
- name: Генерация модуля SELinux
  ansible.builtin.shell: |
    ausearch -m avc --start recent | audit2allow -M hardening_fix
    semodule -i hardening_fix.pp
  when: selinux_fix_needed
```

### 4. OpenSCAP: «No rules matched»

**Симптом:** Сканирование возвращает 0 правил или все «notapplicable».

**Причина:** Неправильный профиль для данной ОС или устаревший пакет `scap-security-guide`.

**Решение:**
```bash
# Обновить SSG до последней верси
sudo dnf update scap-security-guide  # RHEL
sudo apt install ssg-debderived      # Debian/Ubuntu

# Проверить доступные профили
oscap info /usr/share/xml/scap/ssg/content/ssg-$(lsb_release -sr | tr -d.)-ds.xml
```

### 5. DevSec os_hardening: «Module not found»

**Симптом:** Ошибка при запуске роли из коллекции `devsec.hardening`.

**Причина:** Отсутствует коллекция или несовместимая версия Ansible.

**Решение:**
```bash
# Проверка версии Ansible (требуется >= 2.15)
ansible --version

# Переустановка коллекции
ansible-galaxy collection install devsec.hardening --force

# Проверка зависимостей
ansible-galaxy collection list | grep devsec
```

### 6. Broken symlinks после удаления пакетов

**Симптом:** Сломанные симлинки в `/etc/pam.d/` или `/etc/systemd/`.

**Причина:** Удаление пакетов через `os_unused_packages` без проверки зависимостей.

**Решение:**
```yaml
# Поиск сломанных симлинков
- name: Найти broken symlinks
  ansible.builtin.find:
    paths: /etc
    patterns: "*.broken*"
    file_type: link
    recurse: false
  register: broken_links

- name: Вывести сломанные ссылки
  ansible.builtin.debug:
    msg: "{{ broken_links.files | map(attribute='path') | list }}"
```

## Дополнительная информация

### Инструменты и ссылки

*   **[SCAP Security Guide (SSG)](https://github.com/ComplianceAsCode/content)** — первоисточник всех политик OpenSCAP (пакеты: `scap-security-guide`, `ssg-debderived`).
*   **[CIS Benchmarks Community](https://www.cisecurity.org/cis-benchmarks/)** — доступ к официальным документам стандартов (требуется регистрация).
*   **[Ansible Lockdown](https://ansible-lockdown.io/)** — портал с готовыми ролями соответствия (MIT-лицензия).
*   **[DevSec.io](https://dev-sec.io/)** — фреймворк и тесты (InSpec) для проверки безопасности.
*   **[Lockdown Enterprise](https://lockdownenterprise.com/)** — коммерческая поддержка roles (enterprise SLA).
*   **[DISA STIGs](https://public.cyber.mil/stigs/)** — официальный источник STIG-политик.

### Смотрите также

*   **[Ansible: Рекомендации по безопасности](./ansible_security_best_practices.md)** — защита Control Node и секретов.
*   **[Обзор аудита и комплаенса](../Security/audit_and_compliance_overview.md)** — общие принципы compliance-менеджмента (ISO 27001, SOC 2, PCI-DSS).
*   **[Харденинг ядра Linux](../../Linux/Security/Mechanisms/Kernel/hardening.md)** — детальное описание параметров `sysctl` и Kernel Lockdown.
*   **[Wazuh SCA (Security Configuration Assessment)](../Security/Tools/Wazuh/wazuh-sca.md)** — непрерывный мониторинг комплаенса через агентов.
