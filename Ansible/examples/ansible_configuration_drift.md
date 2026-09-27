# Обнаружение дрейфа конфигурации через Ansible

## Определения

**Configuration drift** — неконтролируемое отклонение фактического состояния управляемого хоста от состояния, определенного инфраструктурным кодом или желаемым состоянием (desired state). В production-среде дрейф возникает из-за ручных изменений, обновлений пакетов, неправильно примененных патчей, ошибок в плейбуках или действий сторонних инструментов.

**Desired State Configuration (DSC)** — модель управления инфраструктурой, где вся конфигурация описана в коде (Ansible playbooks/roles), и система постоянно проверяет соответствие фактического состояния желаемому.

**Idempotency** — свойство операции, которое гарантирует, что повторное применение операции не изменит результат. В контексте Ansible означает, что повторный запуск плейбука не должен вносить изменения, если конфигурация уже соответствует желаемому состоянию.

**Remediation** — автоматическое или ручное исправление дрейфа, когда Ansible применяет конфигурацию для возврата хоста в desired state.

**Compliance check** — проверка соответствия конфигурации политикам и стандартам (PCI-DSS, HIPAA, CIS Benchmarks, DISA STIG) без внесения изменений.

**Golden image** — эталонный образ системы или контейнера, который используется как базовая конфигурация для сравнения с фактическими хостами.

**Configuration snapshot** — точка восстановления конфигурации, созданная перед изменением для возможности отката (rollback).

**Change Management** — формализованный процесс управления изменениями в production-среде, включающий approval workflow, maintenance windows и документацию.

**Audit trail** — не изменяемый журнал всех изменений конфигурации, позволяющий отслеживать, когда и кто допустил дрейф.

**MTTR (Mean Time To Remediate)** — среднее время обнаружения и устранения дрейфа. Ключевая метрика для SRE.

**Supply Chain Security (конфигураций)** — практики защиты цепочки поставок конфигурации: проверка подписей baseline, контроль версий зависимостей, immutable infrastructure где возможно.

## Базовые концепции

### Причины дрейфа конфигурации

| Причина | Пример | Последствия |
|---|---|---|
| **Ручные изменения** | Админ изменил `/etc/nginx/nginx.conf` вручную | Дрейф от desired state, непредвиденное поведение |
| **Обновления пакетов** | Автоматическое обновление изменило конфиг | Совместимость, неожиданные параметры |
| **Неправильные патчи** | Патч изменил конфигурационный файл | Некорректная работа сервисов |
| **Ошибки в playbooks** | Playbook применил не ту версию | Дрейф, проблемы с безопасностью |
| **Сторонние инструменты** | Ansible + Chef/Puppet одновременно | Конфликты конфигураций |
| **Изменения в окружении** | Обновление зависимостей | Влияние на работу приложений |
| **Отказы после remediation** | Remediation вызвал сбой | Инцидент, требуется rollback |

### Жизненный цикл управления дрейфом

1. **Определение desired state** — написание Ansible playbooks/roles, описывающих желаемую конфигурацию.
2. **Применение конфигурации** — запуск playbooks для приведения хостов в desired state с созданием configuration snapshot.
3. **Регулярное сканирование** — запуск `--check` mode для обнаружения дрейфа без внесения изменений.
4. **Анализ отчета** — изучение расхождений, определение критических изменений, классификация по severity.
5. **Change Management** — создание инцидента, approval workflow, планирование remediation в maintenance window.
6. **Remediation** — автоматическое или ручное исправление дрейфа с `serial`/`throttle` для rolling update.
7. **Верификация** — проверка после remediation через `--check` mode или health-check эндпоинты.
8. **Уведомление** — отправка алертов при обнаружении критического дрейфа и отчетов после remediation.

### Предварительные требования

| Компонент | Минимальная версия | Проверка |
|---|---|---|
| ansible-core | 2.21+ | `ansible --version` |
| Python (control node) | 3.12+ | `python3 --version` |
| Python (managed node) | 3.9+ | `python3 --version` |
| OpenSSH | 8.0+ | `ssh -V` |
| ansible-lint | 26.8+ | `ansible-lint --version` |
| PyYAML | 6.0+ | `python3 -c "import yaml; print(yaml.__version__)"` |

### Жизненный цикл configuration snapshot

Для SRE критически важно иметь возможность отката перед remediation:

1. **Создание snapshot** — перед любым изменением создается архив конфигурации.
2. **Хранение** — snapshots хранятся на control node или в централизованном хранилище с retention policy.
3. **Верификация** — проверка целостности snapshot через checksum.
4. **Использование** — при неудачном remediation выполняется rollback из snapshot.
5. **Очистка** — старые snapshots удаляются по политике retention (например, 30 дней).

### Ключевые принципы

1. **Immutability where possible** — предпочитайте развертывание новых инстансов вместо изменения существующих.
2. **Regular scanning** — сканируйте дрейф не реже раза в день, особенно на production хостах.
3. **Change management** — все remediation в production проходят через approval workflow и maintenance windows.
4. **Pre-remediation backup** — создавайте configuration snapshot перед любым изменением.
5. **Audit trail** — ведите журнал всех изменений, чтобы отслеживать источник дрейфа.
6. **Least privilege** — ограничьте права ручного изменения конфигураций на production хостах.
7. **Serial/throttle** — используйте rolling update для минимизации влияния на production.
8. **Verification** — после remediation всегда проверяйте desired state через `--check` или health-check.

## Практические сценарии

### Сценарий 1: Регулярное сканирование дрейфа

Настройка регулярного запуска Ansible в `--check` mode для обнаружения дрейфа без внесения изменений с формированием отчета.

```yaml
---
- name: Обнаружение дрейфа конфигурации
  hosts: all
  gather_facts: yes
  serial: "25%"
  tasks:
    - name: Сбор информации о состоянии системы
      ansible.builtin.setup:
        gather_subset:
          - '!all'
          - '!min'
        filter: ansible_*

    - name: Проверка конфигурации SSH
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PasswordAuthentication'
        line: 'PasswordAuthentication no'
        state: present
      check_mode: yes
      register: ssh_drift

    - name: Проверка наличия фаервола
      ansible.builtin.service:
        name: ufw
        state: started
        enabled: yes
      check_mode: yes
      register: ufw_drift

    - name: Проверка обновлений пакетов
      ansible.builtin.package:
        name:
          - nginx
          - curl
          - htop
        state: present
      check_mode: yes
      register: pkg_drift

    - name: Проверка конфигурации sysctl
      ansible.builtin.sysctl:
        name: "{{ item }}"
        value: "{{ expected_sysctl[item] }}"
        state: present
      check_mode: yes
      register: sysctl_drift
      loop:
        - net.ipv4.ip_forward
        - net.ipv4.conf.all.rp_filter
      vars:
        expected_sysctl:
          net.ipv4.ip_forward: '0'
          net.ipv4.conf.all.rp_filter: '1'

    - name: Формирование отчета о дрейфе
      ansible.builtin.copy:
        content: |
          Drift Report for {{ inventory_hostname }}:
          Timestamp: {{ ansible_date_time.iso8601 }}
          SSH Configuration: {{ 'DRIFT DETECTED' if ssh_drift.changed else 'OK' }}
          UFW Firewall: {{ 'DRIFT DETECTED' if ufw_drift.changed else 'OK' }}
          Packages: {{ 'DRIFT DETECTED' if pkg_drift.changed else 'OK' }}
          Sysctl: {{ 'DRIFT DETECTED' if sysctl_drift.changed | default(false) else 'OK' }}
        dest: "/var/log/drift_report_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0644"
      delegate_to: localhost
```

**Валидация:**

```bash
# Запуск сканирования дрейфа
ansible-playbook detect_drift.yml --check
# → показывает, какие изменения будут применены, без внесения изменений

# Пример вывода:
# TASK [Формирование отчета о дрейфе]
# ok: [web1] => {
#     "msg": "Drift Report for web1:\nSSH Configuration: DRIFT DETECTED\nUFW Firewall: OK\nPackages: DRIFT DETECTED\nSysctl: OK"
# }

# Проверка конкретного параметра
ansible web1 -m lineinfile -a "path=/etc/ssh/sshd_config regexp='^PasswordAuthentication' line='PasswordAuthentication no'" --check
# → показывает, будет ли изменен файл

# Проверка с diff для визуализации изменений
ansible-playbook detect_drift.yml --check --diff
# → показывает diff конфигурационных файлов
```

### Сценарий 2: Автоматическое исправление дрейфа (Remediation)

Настройка автоматического исправления дрейфа через регулярный запуск плейбука без `--check` с созданием backup и верификацией.

```yaml
---
- name: Автоматическое исправление дрейфа
  hosts: all
  become: true
  serial: "10%"
  vars:
    auto_remediate: true
    backup_dir: "/var/backups/pre_remediation"

  pre_tasks:
    - name: Создание директории для backup
      ansible.builtin.file:
        path: "{{ backup_dir }}"
        state: directory
        mode: "0750"

    - name: Создание configuration snapshot перед remediation
      ansible.builtin.archive:
        path:
          - /etc/ssh/sshd_config
          - /etc/nginx/nginx.conf
          - /etc/sysctl.conf
        dest: "{{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.iso8601 | regex_replace(':','') }}.tar.gz"
        format: gz
      register: snapshot_result

    - name: Сохранение метаданных snapshot
      ansible.builtin.copy:
        content: |
          Snapshot created: {{ ansible_date_time.iso8601 }}
          Host: {{ inventory_hostname }}
          Backup file: {{ snapshot_result.dest }}
          Playbook: remediate_drift.yml
          Operator: automated
        dest: "{{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.meta"
        mode: "0640"

  tasks:
    - name: Приведение конфигурации SSH в desired state
      ansible.builtin.lineinfile:
        path: /etc/ssh/sshd_config
        regexp: '^PasswordAuthentication'
        line: 'PasswordAuthentication no'
        state: present
      notify: Restart SSH

    - name: Убедиться, что UFW запущен
      ansible.builtin.service:
        name: ufw
        state: started
        enabled: yes

    - name: Установка только необходимых пакетов
      ansible.builtin.package:
        name:
          - nginx
          - curl
          - htop
        state: present

    - name: Приведение sysctl в desired state
      ansible.builtin.sysctl:
        name: "{{ item }}"
        value: "{{ expected_sysctl[item] }}"
        state: present
        reload: yes
      loop:
        - net.ipv4.ip_forward
        - net.ipv4.conf.all.rp_filter
      vars:
        expected_sysctl:
          net.ipv4.ip_forward: '0'
          net.ipv4.conf.all.rp_filter: '1'

  post_tasks:
    - name: Верификация remediation
      ansible.builtin.command:
        cmd: "ansible-playbook detect_drift.yml --check --limit {{ inventory_hostname }}"
      register: verify_result
      delegate_to: localhost
      changed_when: false

    - name: Проверка результата верификации
      ansible.builtin.assert:
        that:
          - verify_result.rc == 0
        fail_msg: "Remediation FAILED on {{ inventory_hostname }}: drift still detected"
        success_msg: "Remediation SUCCESS on {{ inventory_hostname }}: no drift"

    - name: Формирование отчета о remediation
      ansible.builtin.copy:
        content: |
          REMEDIATION REPORT
          Host: {{ inventory_hostname }}
          Timestamp: {{ ansible_date_time.iso8601 }}
          Status: SUCCESS
          Snapshot: {{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.tar.gz
        dest: "/var/log/drift_remediation_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0644"

  handlers:
    - name: Restart SSH
      ansible.builtin.systemd:
        name: sshd
        state: restarted
```

**Валидация:**

```bash
# Запуск remediation
ansible-playbook remediate_drift.yml
# → применяет изменения, исправляющие дрейф, с serial: "10%" для rolling update

# Проверка, что дрейф устранен
ansible-playbook detect_drift.yml --check
# → показывает DRIFT DETECTED: No / OK: Yes

# Просмотр snapshot
ls -la /var/backups/pre_remediation/
# → web1_20240115T143022.tar.gz

# Проверка отчета
cat /var/log/drift_remediation_web1_20240115.log
# → REMEDIATION REPORT ... Status: SUCCESS
```

### Сценарий 3: Сравнение с golden image и checksum verification

Использование checksum-сравнения для обнаружения дрейфа в критичных конфигурационных файлах.

```yaml
---
- name: Сравнение с golden image
  hosts: all
  gather_facts: yes
  vars:
    golden_config_path: "/tmp/golden-config/"
    critical_files:
      - /etc/nginx/nginx.conf
      - /etc/ssh/sshd_config
      - /etc/sysctl.conf

  tasks:
    - name: Получение golden image с master хоста
      ansible.builtin.fetch:
        src: "{{ item }}"
        dest: "{{ golden_config_path }}/{{ inventory_hostname }}/{{ item | basename }}"
        flat: yes
      loop: "{{ critical_files }}"
      run_once: true
      delegate_to: "{{ groups['master'][0] }}"

    - name: Сравнение конфигурации с golden image
      ansible.builtin.command: diff "{{ item }}" "{{ golden_config_path }}/{{ inventory_hostname }}/{{ item | basename }}"
      register: config_diff
      changed_when: config_diff.rc != 0
      failed_when: false
      loop: "{{ critical_files }}"
      register: diff_results

    - name: Проверка наличия drift
      ansible.builtin.assert:
        that:
          - diff_results.results | selectattr('changed', 'equalto', true) | list | length == 0
        fail_msg: "Drift detected in configuration files:\n{% for r in diff_results.results %}{% if r.changed %}{{ r.item }}: {{ r.stdout }}{% endif %}{% endfor %}"
        success_msg: "All configurations match golden image"
```

**Валидация:**

```bash
# Запуск сравнения
ansible-playbook compare_golden.yml
# → показывает drift или подтверждает соответствие

# Пример вывода при дрейфе:
# fatal: [web1]: FAILED! => {
#     "assertion": false,
#     "fail_msg": "Drift detected in configuration files:\n/etc/nginx/nginx.conf: 3c3\n<     worker_processes auto;\n---\n>     worker_processes 4;"
# }

# При отсутствии дрейфа:
# ok: [web1] => {
#     "msg": "All configurations match golden image"
# }
```

### Сценарий 4: Drift detection как инцидент (Incident Response)

Обработка drift как операционного инцидента с MTTR-подходом: backup, remediation, верификация.

```yaml
---
- name: Incident response: configuration drift
  hosts: all
  become: true
  serial: "50"
  gather_facts: false
  vars:
    incident_dir: "/var/log/incidents"
    backup_dir: "/var/backups/pre_remediation"

  pre_tasks:
    - name: Создание директорий
      ansible.builtin.file:
        path: "{{ item }}"
        state: directory
        mode: "0750"
      loop:
        - "{{ incident_dir }}"
        - "{{ backup_dir }}"

    - name: Создание incident ticket (локальный журнал)
      ansible.builtin.copy:
        content: |
          INCIDENT: Configuration drift detected on {{ inventory_hostname }}
          Severity: P1
          Owner: ops-team
          Timestamp: {{ ansible_date_time.iso8601 }}
          Action: Automated remediation initiated
        dest: "{{ incident_dir }}/drift_{{ inventory_hostname }}_{{ ansible_date_time.date }}.log"
        mode: "0640"
      delegate_to: localhost

    - name: Backup текущего состояния перед remediation
      ansible.builtin.archive:
        path:
          - /etc/nginx/nginx.conf
          - /etc/ssh/sshd_config
        dest: "{{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.iso8601 | regex_replace(':','') }}.tar.gz"
        format: gz

  tasks:
    - name: Применение baseline (remediation)
      ansible.builtin.include_role:
        name: baseline_config

    - name: Верификация remediation
      ansible.builtin.command:
        cmd: "ansible-playbook site.yml --check --limit {{ inventory_hostname }}"
      register: verify
      delegate_to: localhost
      changed_when: false

    - name: Проверка верификации
      ansible.builtin.assert:
        that:
          - verify.rc == 0
        fail_msg: "Remediation failed on {{ inventory_hostname }}: rollback required"
        success_msg: "Remediation verified on {{ inventory_hostname }}"

  post_tasks:
    - name: Формирование отчета об инциденте
      ansible.builtin.copy:
        content: |
          INCIDENT RESOLVED
          Host: {{ inventory_hostname }}
          Timestamp: {{ ansible_date_time.iso8601 }}
          Status: RESOLVED
          Snapshot: {{ backup_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.tar.gz
        dest: "{{ incident_dir }}/drift_{{ inventory_hostname }}_{{ ansible_date_time.date }}_resolved.log"
        mode: "0640"
      delegate_to: localhost
```

**Валидация:**

```bash
# Запуск incident response
ansible-playbook incident_response.yml --limit web1
# → создает incident ticket, backup, применяет remediation, верифицирует результат

# Проверка incident ticket
cat /var/log/incidents/drift_web1_20240115.log
# → INCIDENT: Configuration drift detected on web1 ...

# Проверка backup
ls -la /var/backups/pre_remediation/
# → web1_20240115T143022.tar.gz
```

### Сценарий 5: Мониторинг дрейфа и интеграция с оповещениями

Настройка job templates для регулярного сканирования дрейфа и отправки отчетов через нагрудные системы оповещений.

```yaml
---
- name: Drift monitoring report
  hosts: localhost
  gather_facts: no
  vars:
    drift_results: []
    scan_timestamp: "{{ ansible_date_time.iso8601 }}"

  tasks:
    - name: Запуск сканирования дрейфа на всех хостах
      ansible.builtin.include_role:
        name: drift_scanner
      loop: "{{ groups['all'] }}"
      loop_control:
        loop_var: target_host
      register: drift_scan_results

    - name: Агрегация результатов дрейфа
      ansible.builtin.set_fact:
        drifted_hosts: >-
          {% set drifted = [] %}
          {% for host in groups['all'] %}
          {% if hostvars[host].drift_status is defined and 'DRIFT' in hostvars[host].drift_status %}
          {% set drifted = drifted + [host] %}
          {% endif %}
          {% endfor %}
          {{ drifted }}

    - name: Формирование отчета
      ansible.builtin.copy:
        content: |
          Drift Report - {{ scan_timestamp }}
          Total hosts: {{ groups['all'] | length }}
          Drifted hosts: {{ drifted_hosts | length }}
          {% if drifted_hosts | length > 0 %}
          Drifted hosts list:
          {% for host in drifted_hosts %}
          - {{ host }}: {{ hostvars[host].drift_details | default('No details') }}
          {% endfor %}
          {% else %}
          No drift detected.
          {% endif %}
        dest: "/var/log/drift_report_{{ ansible_date_time.date }}.log"
        mode: "0644"
      delegate_to: localhost

    - name: Отправка отчета через email
      ansible.builtin.mail:
        host: localhost
        port: 25
        to: ops-team@example.com
        subject: "Drift Report - {{ scan_timestamp }}"
        body: "{{ lookup('file', '/var/log/drift_report_' + ansible_date_time.date + '.log') }}"
      when: drifted_hosts | length > 0
      delegate_to: localhost

    - name: Отправка отчета в Telegram (опционально)
      ansible.builtin.uri:
        url: "https://api.telegram.org/bot{{ telegram_bot_token }}/sendMessage"
        method: POST
        body:
          chat_id: "{{ telegram_chat_id }}"
          text: |
            Drift Report - {{ scan_timestamp }}
            Drifted hosts: {{ drifted_hosts | length }}
            {% for host in drifted_hosts %}
            - {{ host }}
            {% endfor %}
        body_format: json
      when: drifted_hosts | length > 0
      delegate_to: localhost
```

**Валидация:**

```bash
# Запуск через AWX/Tower или напрямую
ansible-playbook drift_monitoring.yml
# → запускает сканирование дрейфа

# Просмотр отчета
cat /var/log/drift_report_20240115.log
# → Drift Report - 2024-01-15T14:30:00 ...

# Проверка оповещения
# → email отправлен ops-team@example.com при наличии drifted_hosts
```

### Сценарий 6: Configuration snapshot и disaster recovery

Интеграция drift detection с disaster recovery: создание snapshots, retention policy, восстановление.

```yaml
---
- name: Configuration snapshot management
  hosts: all
  gather_facts: yes
  vars:
    snapshot_dir: "/var/backups/config_snapshots"
    retention_days: 30

  tasks:
    - name: Создание директории для snapshots
      ansible.builtin.file:
        path: "{{ snapshot_dir }}"
        state: directory
        mode: "0750"

    - name: Создание configuration snapshot
      ansible.builtin.archive:
        path:
          - /etc/ssh/sshd_config
          - /etc/nginx/nginx.conf
          - /etc/sysctl.conf
          - /etc/fstab
        dest: "{{ snapshot_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.iso8601 | regex_replace(':','') }}.tar.gz"
        format: gz
      register: snapshot

    - name: Сохранение checksums критичных файлов
      ansible.builtin.slurp:
        src: "{{ item }}"
      register: file_checksums
      loop: "{{ ['/etc/ssh/sshd_config', '/etc/nginx/nginx.conf', '/etc/sysctl.conf'] }}"

    - name: Запись checksums в файл
      ansible.builtin.copy:
        content: |
          Snapshot: {{ snapshot.dest }}
          Timestamp: {{ ansible_date_time.iso8601 }}
          {% for item in file_checksums.results %}
          {{ item.source }}: {{ item.content | b64encode | hash('sha256') }}
          {% endfor %}
        dest: "{{ snapshot_dir }}/{{ inventory_hostname }}_{{ ansible_date_time.date }}.checksums"
        mode: "0640"

    - name: Очистка старых snapshots (retention policy)
      ansible.builtin.find:
        paths: "{{ snapshot_dir }}"
        patterns: "{{ inventory_hostname }}_*.tar.gz"
        age: "{{ retention_days }}d"
        age_stamp: mtime
      register: old_snapshots

    - name: Удаление старых snapshots
      ansible.builtin.file:
        path: "{{ item.path }}"
        state: absent
      loop: "{{ old_snapshots.files }}"
```

**Валидация:**

```bash
# Создание snapshot
ansible-playbook config_snapshot.yml
# → создает snapshot и checksums

# Проверка snapshots
ls -la /var/backups/config_snapshots/
# → web1_20240115T143022.tar.gz
# → web1_20240115.checksums

# Восстановление из snapshot
ansible all -m unarchive -a "src=/var/backups/config_snapshots/web1_20240115T143022.tar.gz dest=/etc/ remote_src=yes" -b
# → восстанавливает конфигурацию из snapshot
```

### Сценарий 7: Compliance проверки (CIS Benchmarks)

Для проверки compliance с CIS Benchmarks и другими стандартами используйте специализированные роли. Подробнее о hardening и compliance см. **[Ansible: OS Hardening и комплаенс](../ansible-os-hardening.md)**.

**Пример базовой compliance проверки:**

```yaml
---
- name: CIS Benchmark Compliance Check (базовый пример)
  hosts: all
  gather_facts: yes
  vars:
    cis_level: "1"

  tasks:
    - name: Проверка 1.1.1.1 - Убедиться, что монтирование /tmp имеет отдельный раздел
      ansible.builtin.command: findmnt /tmp
      register: tmp_mount
      changed_when: false
      failed_when: false

    - name: Проверка 1.1.1.1 - результат
      ansible.builtin.assert:
        that:
          - tmp_mount.rc == 0
        fail_msg: "CIS 1.1.1.1 FAILED: /tmp not on separate partition"
        success_msg: "CIS 1.1.1.1 PASSED"

    - name: Проверка 1.2.1 - Убедиться, что пакет manager.conf содержит корректные настройки
      ansible.builtin.lineinfile:
        path: /etc/apt/apt.conf.d/99custom
        regexp: '^APT::Get::AllowUnauthenticated'
        line: 'APT::Get::AllowUnauthenticated "false";'
        state: present
      check_mode: yes
      register: apt_config_check

    - name: Проверка 1.2.1 - результат
      ansible.builtin.assert:
        that:
          - apt_config_check is not changed
        fail_msg: "CIS 1.2.1 FAILED: APT configuration incorrect"
        success_msg: "CIS 1.2.1 PASSED"

    - name: Проверка 2.2.1 - Убедиться, что xinetd отключен
      ansible.builtin.service:
        name: xinetd
        state: stopped
        enabled: no
      check_mode: yes
      register: xinetd_check

    - name: Проверка 2.2.1 - результат
      ansible.builtin.assert:
        that:
          - xinetd_check is not changed
        fail_msg: "CIS 2.2.1 FAILED: xinetd is not disabled"
        success_msg: "CIS 2.2.1 PASSED"
```

**Валидация:**

```bash
# Запуск compliance check
ansible-playbook cis_compliance.yml --check
# → показывает прохождение/непрохождение проверок

# Пример вывода:
# TASK [Проверка 1.1.1.1 - результат]
# ok: [web1] => {
#     "assertion": true,
#     "success_msg": "CIS 1.1.1.1 PASSED"
# }

# TASK [Проверка 1.2.1 - результат]
# fatal: [web1]: FAILED! => {
#     "assertion": false,
#     "fail_msg": "CIS 1.2.1 FAILED: APT configuration incorrect"
# }
```

## Операции и команды

### Основные команды для обнаружения дрейфа

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml --check` | Проверка без внесения изменений | `ansible-playbook site.yml --check` |
| `ansible-playbook playbook.yml --check --diff` | Проверка с diff | `ansible-playbook site.yml --check --diff` |
| `ansible host -m lineinfile -a "..." --check` | Проверка конкретного параметра | `ansible web1 -m lineinfile -a "path=/etc/ssh/sshd_config regexp='^PasswordAuthentication' line='PasswordAuthentication no'" --check` |
| `ansible host -m service -a "..." --check` | Проверка состояния сервиса | `ansible web1 -m service -a "name=ufw state=started enabled=yes" --check` |
| `ansible host -m package -a "..." --check` | Проверка установки пакетов | `ansible web1 -m package -a "name=nginx state=present" --check` |
| `ansible host -m command -a "diff file1 file2"` | Сравнение файлов | `ansible web1 -m command -a "diff /etc/nginx/nginx.conf /tmp/golden.conf"` |
| `ansible host -m stat -a "path=/etc/file"` | Проверка атрибутов файла | `ansible web1 -m stat -a "path=/etc/nginx/nginx.conf"` |
| `ansible host -m setup` | Сбор фактов о хосте | `ansible web1 -m setup` |

### Команды для управления дрейфом

| Команда | Назначение | Пример |
|---|---|---|
| `ansible-playbook playbook.yml` | Применение desired state | `ansible-playbook remediate_drift.yml` |
| `ansible-playbook playbook.yml --diff` | Применение с diff | `ansible-playbook remediate_drift.yml --diff` |
| `ansible-playbook playbook.yml --limit host` | Применение к конкретному хосту | `ansible-playbook remediate_drift.yml --limit web1` |
| `diff file1 file2` | Сравнение файлов | `diff /etc/nginx/nginx.conf /tmp/golden.conf` |
| `findmnt` | Проверка монтирования | `findmnt /tmp` |
| `sha256sum file` | Проверка checksum | `sha256sum /etc/nginx/nginx.conf` |

## Устранение типичных неполадок

| Ошибка | Причина | Решение |
|---|---|---|
| `check mode не обнаруживает дрейф` | Модуль не поддерживает check mode | Используйте модули с поддержкой `check_mode`, или `ansible.builtin.command` для проверки |
| `Drift detected после применения playbook` | Playbook неполный или содержит ошибки | Проверьте playbook, убедитесь, что все параметры covered, используйте `--diff` для анализа |
| `Автоматическая remediation вызывает сбои` | Изменения несовместимы с running service | Используйте maintenance windows, `serial`/`throttle`, pre-remediation backup |
| `Слишком много drift alerts` | Чувствительность сканирования слишком высокая | Настройте фильтры, сканируйте только критичные параметры, severity-based alerting |
| `Golden image устарел` | Golden image не обновляется | Автоматически обновляйте golden image при изменении desired state |
| `Drift detection нестабильный` | Переменные факторы (время, случайные данные) | Используйте идемпотентные проверки, фиксируйте временные метки, игнорируйте динамические параметры |
| `Remediation не прошел верификацию` | Desired state устарел или содержит ошибки | Проверьте desired state, обновите playbook, выполните rollback из snapshot |
| `Configuration snapshot поврежден` | Ошибка при создании archive | Проверьте права доступа, место на диске, целостность файлов перед архивацией |

## Рекомендации

### Best Practices

1. **Regular scanning** — сканируйте дрейф не реже раза в день, особенно на production хостах.
2. **Change management** — все remediation в production проходят через approval workflow и maintenance windows.
3. **Pre-remediation backup** — создавайте configuration snapshot перед любым изменением.
4. **Automated remediation with caution** — автоматическое исправление только для некритичных параметров, с approval gate для критичных.
5. **Audit trail** — ведите журнал всех изменений, чтобы отслеживать источник дрейфа.
6. **Golden image maintenance** — поддерживайте golden image в актуальном состоянии.
7. **Compliance as code** — используйте Ansible для проверки compliance (CIS, PCI-DSS, DISA STIG). Подробнее см. **[Ansible: OS Hardening и комплаенс](../ansible-os-hardening.md)**.
8. **Monitoring and alerting** — интегрируйте drift detection с мониторингом и отправляйте алерты.
9. **Serial/throttle** — используйте rolling update для минимизации влияния на production.
10. **Immutable infrastructure** — где возможно, используйте immutable infrastructure вместо remediation.
11. **Verification** — после remediation всегда проверяйте desired state через `--check` или health-check.
12. **Retention policy** — настройте retention для snapshots и отчетов (например, 30 дней).

### Чек-лист валидации после настройки

| Проверка | Команда | Ожидаемый результат |
|---|---|---|
| Сканирование дрейфа | `ansible-playbook detect_drift.yml --check` | Отчет о дрейфе без изменений |
| Remediation | `ansible-playbook remediate_drift.yml` | Изменения применены, дрейф устранен |
| Верификация remediation | `ansible-playbook detect_drift.yml --check` | DRIFT DETECTED: No |
| Configuration snapshot | `ls -la /var/backups/pre_remediation/` | Snapshot создан |
| Compliance check | `ansible-playbook cis_compliance.yml --check` | PASSED/FAILED для каждого контрольного пункта |
| Golden image comparison | `ansible-playbook compare_golden.yml` | Соответствие или отчет о расхождениях |
| Monitoring integration | `cat /var/log/drift_report_*.log` | Отчеты сформированы |

## Дополнительная информация

### Смотрите также

- **[Ansible: Основные концепции](../ansible_core_concepts.md)** — drift detection как операционный инцидент, incident response, rollback стратегии, check & diff mode.
- **[Ansible: OS Hardening и комплаенс](../ansible-os-hardening.md)** — CIS Benchmarks, DISA STIG, OpenSCAP, DevSec Hardening Framework, compliance as code.
- **[Ansible: Кроссплатформенный откат, тестирование и drift detection](../CrossPlatform/ansible_cross_platform_rollback_testing_drift.md)** — кроссплатформенные стратегии отката, canary deployments, Molecule для тестирования drift detection.

### Интеграция с другими системами

| Система | Назначение | Интеграция |
|---|---|---|
| **Ansible AWX/Tower** | Планирование и запуск сканирований | Scheduled Job Templates, Workflow Templates |
| **Prometheus Pushgateway** | Сбор метрик дрейфа | Экспорт drift-отчета в Prometheus |
| **Grafana** | Дашборды дрейфа | Визуализация метрик drift |
| **Alertmanager** | Алерты о дрейфе | Правила алертинга на основе метрик |
| **Elasticsearch/OpenSearch** | Хранение отчетов о дрейфе | Логи drift reports |
| **Kibana/Grafana** | Поиск и визуализация | Дашборды drift trends |
| **AIDE/Tripwire** | Мониторинг целостности файлов | Интеграция с Ansible для верификации |
| **auditd** | Аудит изменений файлов | Корреляция с drift detection |

### Граничные случаи

| Сценарий | Проблема | Решение |
|---|---|---|
| Дрейф после автоматического обновления | Обновление изменило конфигурацию | Используйте pin версии пакетов, pre-update scan, hold |
| Конфликтующие изменения | Несколько инструментов меняют конфигурацию | Централизуйте управление через Ansible, отключите другие инструменты |
| Дрейф в production | Риск сбоев при автоматическом исправлении | Используйте maintenance windows, `serial`/`throttle`, rolling update, approval gate |
| Устаревший golden image | Неверное сравнение | Автоматически обновляйте golden image при изменении desired state |
| Большое количество хостов | Сканирование занимает много времени | Используйте `serial`, `--forks`, parallel execution, фрагментацию по группам |
| Drift detection нестабильный | Переменные факторы (время, случайные данные) | Используйте идемпотентные проверки, игнорируйте динамические параметры |
| Concurrent remediation | Два оператора исправляют дрейф одновременно | Используйте approval queue, maintenance windows, lock mechanism |
| Rollback после неудачного remediation | Система в непредсказуемом состоянии | Используйте configuration snapshot, disaster recovery playbook |
| Supply chain атака на baseline | Вредоносный код в desired state | Проверяйте подписи playbooks, immutable infrastructure, audit trail |
