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
*   **Поддерживаемые ОС:** Ubuntu 24.04 (Noble), RHEL 9, Debian 13 (preliminary), Enterprise Linux 9 (Alma/Rocky).
*   **Установка:**
    ```bash
    ansible-galaxy collection install devsec.hardening
    ```

**Пример расширенной настройки:**
```yaml
- name: Применение базового харденинга
  hosts: all
  become: true
  roles:
    - role: devsec.hardening.os_hardening
      vars:
        # Разрешить SSH-логин только по ключам (отключение паролей)
        ssh_allow_root_with_key: true
        ssh_password_authentication: false
        # Тонкая настройка sysctl без изменения кода роли
        sysctl_overwrite:
          net.ipv4.ip_forward: 0
          net.ipv6.conf.all.forwarding: 0
          kernel.kptr_restrict: 2
        # Исключение критичных пакетов от удаления
        os_unused_package_types: []
```

### 2. Ansible Lockdown (CIS & STIG)

Проект предоставляет роли для глубокого соответствия стандартам. Идеально подходит для регулируемых отраслей (финтех, медицина, госсектор).

*   **Репозитории:** [Ansible Lockdown GitHub](https://github.com/ansible-lockdown)
*   **Ключевые роли (2026):**
    *   `ansible-lockdown.ubuntu24_cis` — поддержка Ubuntu 24.04 LTS.
    *   `ansible-lockdown.rhel9_cis` — поддержка RHEL 9 / Rocky 9.
    *   `ansible-lockdown.rhel9_stig` — реализация DISA STIG для RHEL 9.

**Важно:** Роли Lockdown крайне агрессивны. Всегда начинайте с `setup_audit: true` для предварительной оценки влияния.

## Интеграция с OpenSCAP

OpenSCAP позволяет автоматизировать аудит и генерировать плейбуки исправления на основе актуальных политик **SCAP Security Guide (SSG)**.

### 1. Работа с профилями SSG

Пакет `scap-security-guide` содержит Data Streams (файлы `.xml`), описывающие правила для конкретных ОС.

**Просмотр доступных профилей для RHEL 9:**
```bash
oscap info /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
# → xccdf_org.ssgproject.content_profile_cis (Level 2)
# → xccdf_org.ssgproject.content_profile_cis_server_l1 (Level 1)
# → xccdf_org.ssgproject.content_profile_stig (DISA STIG V2R8)
```

### 2. Генерация Remediation-плейбуков

Вы можете сгенерировать Ansible-код, идеально подходящий под конкретную версию вашей системы и профиль.

```bash
# Генерация плейбука для CIS Level 2 на Ubuntu 24.04
oscap xccdf generate remediation --fix-type ansible \
  --profile xccdf_org.ssgproject.content_profile_cis \
  /usr/share/xml/scap/ssg/content/ssg-ubuntu2404-ds.xml > cis_remediation.yml
```

### 3. Автоматизированный аудит через Ansible

```yaml
- name: Аудит безопасности OpenSCAP
  hosts: servers
  become: true
  tasks:
    - name: Выполнить сканирование на соответствие STIG
      ansible.builtin.command:
        cmd: >
          oscap xccdf eval 
          --profile xccdf_org.ssgproject.content_profile_stig
          --results-arvalis results.xml
          --report report.html
          /usr/share/xml/scap/ssg/content/ssg-rhel9-ds.xml
      register: scan_out
      failed_when: scan_out.rc not in [0, 2]

    - name: Проверка результата
      ansible.builtin.debug:
        msg: "Система соответствует стандарту"
      when: scan_out.rc == 0

    - name: Алярм при несоответствии
      ansible.builtin.debug:
        msg: "Обнаружены уязвимости! См. отчет report.html"
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

## Бестиарий и рекомендации (Чек-лист 2026)

*   **Идемпотентность:** Ваши роли Hardening должны быть на 100% идемпотентными. Повторный запуск не должен менять состояние системы, если она уже защищена.
*   **Исключения (Whitelist):** Всегда составляйте список исключений для специфических нагрузок (например, не отключайте `ptrace`, если используете инструменты профилирования как `strace` или `gdb`).
*   **Разделение /tmp и /var/tmp:** CIS требует монтирования этих директорий с параметрами `noexec, nosuid, nodev`. Убедитесь, что у приложений есть место для временных файлов, не требующих исполнения.
*   **Логирование:** Включайте расширенный аудит через `auditd` для мониторинга попыток изменения системных файлов после применения Hardening.

## Дополнительная информация

### Инструменты и ссылки

*   **[SCAP Security Guide (SSG)](https://github.com/ComplianceAsCode/content)** — первоисточник всех политик OpenSCAP.
*   **[CIS Benchmarks Community](https://www.cisecurity.org/cis-benchmarks/)** — доступ к официальным документам стандартов.
*   **[Ansible-Lockdown](https://ansible-lockdown.io/)** — портал с готовыми ролями соответствия.
*   **[DevSec.io](https://dev-sec.io/)** — фреймворк и тесты (InSpec) для проверки безопасности.

### Смотрите также

*   **[Ansible: Рекомендации по безопасности](./ansible_security_best_practices.md)** — защита Control Node и секретов.
*   **[Обзор аудита и комплаенса](../Security/audit_and_compliance_overview.md)** — общие принципы compliance-менеджмента.
*   **[Харденинг ядра Linux](../../Linux/Security/Mechanisms/Kernel/hardening.md)** — детальное описание параметров `sysctl`.
*   **[Wazuh SCA (Security Configuration Assessment)](../Security/Tools/Wazuh/wazuh-sca.md)** — непрерывный мониторинг комплаенса через агентов.
