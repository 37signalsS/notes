# Compliance для пользователей (CIS, STIG, PCI DSS)

## Определения

- **Compliance (Соответствие стандартам)** — выполнение требований нормативных документов и отраслевых стандартов безопасности (CIS Benchmarks, DISA STIG, PCI DSS, HIPAA, NIST).
- **CIS Benchmark (Center for Internet Security Benchmark)** — набор рекомендаций по настройке безопасности операционных систем и приложений, разработанный экспертным сообществом.
- **DISA STIG (Security Technical Implementation Guide)** — строгий стандарт безопасности, разработанный агентством DISA (США) для систем, используемых в оборонных ведомствах.
- **OpenSCAP** — свободная реализация протокола SCAP (Security Content Automation Protocol) для автоматизированного аудита и исправления конфигураций.
- **SCAP Security Guide (SSG)** — пакет политик для OpenSCAP, содержащий профили для различных стандартов (CIS, STIG, NIST).
- **Remediation (Исправление)** — автоматическое или ручное приведение системы в соответствие с требованиями стандарта.
- **Drift Detection (Обнаружение отклонений)** — мониторинг изменений конфигурации, приводящих к несоответствию стандартам.
- **Hardening (Харденинг)** — процесс укрепления безопасности системы путем отключения ненужных сервисов, настройки правил доступа и установки патчей.

## Базовые концепции

### Ключевые требования к пользователям по стандартам

| Требование | CIS Level 1 | CIS Level 2 | DISA STIG | PCI DSS |
| :--- | :--- | :--- | :--- | :--- |
| **Минимальная длина пароля** | 14+ символов | 14+ символов | 15+ символов | 12+ символов |
| **Сложность пароля** | Буквы, цифры, спецсимволы | Буквы, цифры, спецсимволы | Буквы, цифры, спецсимволы | Буквы, цифры, спецсимволы |
| **Срок действия пароля** | 365 дней | 365 дней | 60 дней | 90 дней |
| **Блокировка после попыток** | 5 неудачных попыток | 5 неудачных попыток | 3 неудачные попытки | 6 неудачных попыток |
| **Время блокировки** | 10 минут | 10 минут | 24 часа | 30 минут |
| **Пустые пароли** | Запрещены | Запрещены | Запрещены | Запрещены |
| **UID 0** | Только root | Только root | Только root | Только root |
| **Ротация SSH-ключей** | Рекомендуется | Требуется | Требуется | Требуется |
| **Аудит входов** | Требуется | Требуется | Требуется | Требуется |
| **Запись сессий** | Рекомендуется | Требуется | Требуется | Требуется |

### Области проверки для пользователей

| Область | Что проверяется | Инструменты |
| :--- | :--- | :--- |
| **Пароли** | Сложность, сроки, хэширование, пустые пароли | `pwck`, `chage`, `auditd` |
| **UID/GID** | Уникальность, конфликты, дубликаты UID 0 | `pwck`, `grpck`, скрипты |
| **Домашние директории** | Права доступа, наличие, ownership | `find`, `ls`, `stat` |
| **Shell** | Запрещенные оболочки (`/bin/bash` для служб) | `grep`, `awk` |
| **sudo** | Делегирование, NOPASSWD, аудит | `visudo`, `sudo -l` |
| **Аудит** | Логирование действий пользователей | `auditd`, `ausearch` |
| **Сессии** | Запись, мониторинг, таймауты | `tlog`, `loginctl` |

## Практические сценарии

### 1. Проверка на соответствие CIS Benchmark

#### Скрипт проверки паролей

```bash
#!/bin/bash
# CIS 5.4.1 - Проверка最小 длины пароля
echo "=== CIS 5.4.1: Минимальная длина пароля ==="
awk -F: '($5 < 14 || $5 == -1) {print "WARN: " $1 " - м длина пароля: " $5}' /etc/shadow

# CIS 5.4.2 - Проверка срока действия пароля
echo "=== CIS 5.4.2: Срок действия пароля ==="
awk -F: '($5 > 365 || $5 == -1) {print "WARN: " $1 " - срок действия: " $5 " дней"}' /etc/shadow

# CIS 5.4.3 - Проверка предупреждения о смене пароля
echo "=== CIS 5.4.3: Предупреждение о смене пароля ==="
awk -F: '($6 < 7 || $6 == -1) {print "WARN: " $1 " - предупреждение за: " $6 " дней"}' /etc/shadow

# CIS 5.4.4 - Проверка неактивности пароля
echo "=== CIS 5.4.4: Неактивность пароля ==="
awk -F: '($7 < 7 || $7 == -1) {print "WARN: " $1 " - неактивность: " $7 " дней"}' /etc/shadow
```

#### Скрипт проверки учетных записей

```bash
#!/bin/bash
# CIS 5.5 - Проверка пустых паролей
echo "=== CIS 5.5: Пустые пароли ==="
awk -F: '($2 == "" || $2 == "!") {print "CRITICAL: " $1 " - пустой пароль"}' /etc/shadow

# CIS 5.4 - Проверка UID 0
echo "=== CIS 5.4: UID 0 accounts ==="
awk -F: '$3 == 0 {print "INFO: " $1 " - UID 0"}' /etc/passwd

# CIS 5.7 - Проверка домашних директорий
echo "=== CIS 5.7: Домашние директории ==="
while IFS=: read -r user _ uid _ _ home shell; do
    if [[ $uid -ge 1000 && $uid -lt 65534 && -n "$home" ]]; then
        if [[ ! -d "$home" ]]; then
            echo "WARN: $user - домашняя директория не существует: $home"
        elif [[ $(stat -c %a "$home") -gt 750 ]]; then
            echo "WARN: $user - избыточные права на домашнюю директорию: $(stat -c %a "$home")"
        fi
    fi
done < /etc/passwd

# CIS 5.8 - Проверка系统的用户accounts
echo "=== CIS 5.8: Системные учетные записи ==="
awk -F: '$3 < 1000 && $7 != "/usr/sbin/nologin" && $7 != "/bin/false" && $7 != "/bin/sync" {print "INFO: " $1 " - shell: " $7}' /etc/passwd
```

#### Скрипт проверки sudo

```bash
#!/bin/bash
# CIS 5.3 - Проверка sudoers
echo "=== CIS 5.3: Правила sudo ==="

# Проверка NOPASSWD
echo "--- NOPASSWD правила ---"
grep -r "NOPASSWD" /etc/sudoers /etc/sudoers.d/ 2>/dev/null

# Проверка ALL=(ALL)
echo "--- ALL=(ALL) правила ---"
grep -r "ALL=(ALL)" /etc/sudoers /etc/sudoers.d/ 2>/dev/null

# Проверка владельца и прав sudoers
echo "--- Права доступа к sudoers ---"
ls -la /etc/sudoers /etc/sudoers.d/ 2>/dev/null

# Проверка syntax
echo "--- Проверка syntax ---"
visudo -c
```

### 2. Автоматический аудит через OpenSCAP

#### Установка и запуск

```bash
# Установка
sudo apt install libopenscap8 ssg-debderived  # Debian/Ubuntu
sudo dnf install openscap-scanner scap-security-guide  # RHEL/CentOS

# Просмотр доступных профилей
oscap info /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# Запуск сканирования (CIS Level 1)
sudo oscap xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_cis_level1_server \
  --results results.xml \
  --report report.html \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml

# Запуск сканирования (DISA STIG)
sudo oscap xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_stig \
  --results results_stig.xml \
  --report report_stig.html \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
```

#### Генерация скрипта исправления

```bash
# Генерация Bash-скрипта для исправления
oscap xccdf generate fix \
  --fix-type bash \
  --output fix.sh \
  results.xml

# Просмотр скрипта
cat fix.sh

# Выполнение (после проверки!)
sudo bash fix.sh
```

#### Автоматизация через Ansible

```yaml
- name: OpenSCAP compliance audit
  hosts: all
  become: yes
  tasks:
    - name: Install OpenSCAP
      ansible.builtin.package:
        name:
          - libopenscap8
          - ssg-debderived
        state: present

    - name: Run CIS scan
      ansible.builtin.command:
        cmd: >
          oscap xccdf eval
          --profile xccdf_org.ssgproject.content_profile_cis_level1_server
          --results /var/log/cis-scan-results.xml
          --report /var/log/cis-scan-report.html
          /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml
      register: scan_result
      ignore_errors: yes

    - name: Fetch report
      ansible.builtin.fetch:
        src: /var/log/cis-scan-report.html
        dest: "./reports/cis-scan-report-{{ inventory_hostname }}.html"
        flat: yes

    - name: Fail if non-compliant
      ansible.builtin.fail:
        msg: "CIS compliance check failed"
      when: scan_result.rc != 0
```

### 3. Мониторинг drift через auditd

```bash
# Правила аудита для мониторинга изменений в пользователях
cat > /etc/audit/rules.d/user-compliance.rules << 'EOF'
# Мониторинг /etc/passwd
-w /etc/passwd -p wa -k user_changes
-w /etc/shadow -p wa -k password_changes
-w /etc/group -p wa -k group_changes
-w /etc/gshadow -p wa -k group_password_changes

# Мониторинг sudoers
-w /etc/sudoers -p wa -k sudoers_changes
-w /etc/sudoers.d/ -p wa -k sudoers_d_changes

# Мониторинг PAM
-w /etc/pam.d/ -p wa -k pam_changes

# Мониторинг login.defs
-w /etc/login.defs -p wa -k login_defs_changes

# Мониторинг nsswitch.conf
-w /etc/nsswitch.conf -p wa -k nsswitch_changes
EOF

# Перезагрузка auditd
sudo systemctl restart auditd

# Просмотр событий
ausearch -k user_changes -ts recent
ausearch -k password_changes -ts recent
```

### 4. Автоматическое исправление через Ansible

#### Исправление паролей

```yaml
- name: CIS Password Compliance
  hosts: all
  become: yes
  tasks:
    - name: Set minimum password length
      ansible.builtin.lineinfile:
        path: /etc/login.defs
        regexp: '^PASS_MIN_LEN'
        line: 'PASS_MIN_LEN    14'

    - name: Set password maximum age
      ansible.builtin.lineinfile:
        path: /etc/login.defs
        regexp: '^PASS_MAX_DAYS'
        line: 'PASS_MAX_DAYS   365'

    - name: Set password warning age
      ansible.builtin.lineinfile:
        path: /etc/login.defs
        regexp: '^PASS_WARN_AGE'
        line: 'PASS_WARN_AGE   7'

    - name: Set password inactivity period
      ansible.builtin.lineinfile:
        path: /etc/login.defs
        regexp: '^PASS_INACTIVE'
        line: 'PASS_INACTIVE   7'

    - name: Configure PAM password quality
      ansible.builtin.lineinfile:
        path: /etc/pam.d/common-password
        regexp: 'pam_pwquality.so'
        line: 'password requisite pam_pwquality.so retry=3 minlen=14 ucredit=-1 lcredit=-1 dcredit=-1 ocredit=-1'
```

#### Исправление аудита

```yaml
- name: CIS Audit Compliance
  hosts: all
  become: yes
  tasks:
    - name: Install auditd
      ansible.builtin.package:
        name:
          - auditd
          - audispd-plugins
        state: present

    - name: Deploy audit rules
      ansible.builtin.copy:
        dest: /etc/audit/rules.d/user-compliance.rules
        content: |
          # Мониторинг пользователей
          -w /etc/passwd -p wa -k user_changes
          -w /etc/shadow -p wa -k password_changes
          -w /etc/group -p wa -k group_changes
          -w /etc/sudoers -p wa -k sudoers_changes
          -w /etc/pam.d/ -p wa -k pam_changes
        mode: '0640'
        owner: root
        group: root
      notify: Restart auditd

  handlers:
    - name: Restart auditd
      ansible.builtin.systemd:
        name: auditd
        state: restarted
```

### 5. Проверка соответствия PCI DSS

```bash
#!/bin/bash
# PCI DSS 8.2 - Идентификация и аутентификация доступа

echo "=== PCI DSS 8.2.1: Уникальные идентификаторы ==="
awk -F: '$3 >= 1000 && $3 < 65534 {print $1}' /etc/passwd | sort | uniq -d

echo "=== PCI DSS 8.2.2: Многофакторная аутентификация ==="
grep -r "pam_u2f\|pam_google_authenticator" /etc/pam.d/

echo "=== PCI DSS 8.2.3: Пароли не менее 7 символов ==="
awk -F: '($5 < 7 || $5 == -1) {print "FAIL: " $1}' /etc/shadow

echo "=== PCI DSS 8.2.4: Смена пароля каждые 90 дней ==="
awk -F: '($5 > 90 || $5 == -1) {print "FAIL: " $1 " - " $5 " дней"}' /etc/shadow

echo "=== PCI DSS 8.2.5: История паролей ==="
grep -r "pam_pwhistory\|pam_unix" /etc/pam.d/ | grep -v "^#"

echo "=== PCI DSS 8.2.6: Блокировка после 6 неудачных попыток ==="
grep -r "pam_faillock\|pam_tally2" /etc/pam.d/
```

## Дополнительная информация

### Ссылки на смежные темы

- **[Управление привилегиями](../../SystemAdministration/privilege_management.md)** — sudo, su, Polkit.
- **[Обзор PAM](../../Security/pam_overview.md)** — модульный фреймворк аутентификации.
- **[Ansible OS Hardening](../../Ansible/ansible-os-hardening.md)** — автоматизация приведения к стандартам CIS/STIG.
- **[Аудит событий](../../SystemAdministration/Logging/auditd.md)** — мониторинг действий пользователей.
- **[Disaster Recovery для пользователей](./users_disaster_recovery.md)** — восстановление после сбоев.

### Полезные ресурсы

- **[CIS Benchmarks](https://www.cisecurity.org/cis-benchmarks/)** — официальные документы стандартов (требуется регистрация).
- **[DISA STIGs](https://public.cyber.mil/stigs/)** — официальный источник STIG-политик.
- **[SCAP Security Guide](https://github.com/ComplianceAsCode/content)** — пакеты OpenSCAP.
- **[OpenSCAP Documentation](https://www.open-scap.org/tools/)** — документация по инструментам.

### Рекомендации по внедрению compliance

1. **Начните с аудита:** Запустите OpenSCAP для определения текущего состояния.
2. **Приоритизируйте:** Исправляйте критические уязвимости в первую очередь.
3. **Автоматизируйте:** Используйте Ansible/Chef/Puppet для consistency.
4. **Мониторьте:** Настройте auditd и Wazuh для обнаружения drift.
5. **Тестируйте:** Проверяйте compliance в staging перед production.
6. **Документируйте:** Фиксируйте исключения и их обоснование.
7. **Обучайте:** Убедитесь, что команда понимает требования стандартов.
