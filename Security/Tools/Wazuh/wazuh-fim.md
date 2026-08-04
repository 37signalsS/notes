# Мониторинг целостности файлов (FIM) в Wazuh

## Определения

**Wazuh File Integrity Monitoring (FIM)** — это компонент платформы Wazuh, предназначенный для отслеживания изменений в файловой системе в режиме реального времени. В отличие от инструментов статического анализа (например, AIDE), FIM обеспечивает непрерывный мониторинг и позволяет идентифицировать не только факт изменения, но и пользователя или процесс, инициировавший событие.

**Syscheck** — внутренний модуль агента Wazuh, отвечающий за сканирование файлов, вычисление контрольных сумм (MD5, SHA-1, SHA-256) и мониторинг атрибутов (права доступа, владелец).

## Базовые концепции

### Режимы мониторинга

1.  **Периодическое сканирование (Scheduled):** Агент сканирует выбранные директории через определенные интервалы времени.
2.  **Реальное время (Real-time):** Использование механизмов ядра (inotify в Linux) для мгновенного обнаружения изменений.
3.  **Аудит данных (Whodata):** Самый продвинутый режим, использующий подсистему `auditd` для получения информации о том, **кто** (пользователь) и **каким процессом** изменил файл.

### Архитектура FIM

| Компонент | Роль |
| :--- | :--- |
| **Wazuh Agent** | Наблюдает за файлами, вычисляет хеши и отправляет события на сервер. |
| **auditd** | (Опционально) Поставляет данные о пользователях для режима `whodata`. |
| **Wazuh Manager** | Сравнивает полученные данные с эталонной базой (baseline) и генерирует алерты. |
| **Wazuh Indexer** | Хранит историю изменений и результаты diff. |

## Практические сценарии

### 1. Подготовка инфраструктуры

Для работы режима `whodata` на Linux-агентах должна быть установлена и запущена подсистема аудита.

**Установка auditd:**

```bash
# Для Debian/Ubuntu
sudo apt install auditd audispd-plugins -y
sudo systemctl enable --now auditd

# Для RHEL/CentOS/Rocky
sudo dnf install audit audispd-plugins -y
sudo systemctl enable --now auditd
```

**Проверка работы:**
```bash
sudo auditctl -l
# → result: (список правил или сообщение о том, что правил нет)
```

### 2. Централизованная конфигурация группы

Рекомендуется настраивать мониторинг через группы агентов на стороне менеджера (`/var/ossec/etc/shared/linux/agent.conf`).

```xml
<agent_config>
  <syscheck>
    <!-- Интервал полного сканирования (300 секунд) -->
    <frequency>300</frequency>
    
    <!-- Включение режима whodata и отображение diff -->
    <whodata>yes</whodata>
    <diff>yes</diff>
    
    <!-- Мониторинг критических файлов -->
    <directories check_all="yes" whodata="yes" report_changes="yes">/etc/passwd</directories>
    <directories check_all="yes" whodata="yes" report_changes="yes">/etc/shadow</directories>
    <directories check_all="yes" whodata="yes" report_changes="yes">/etc/sudoers</directories>
    <directories check_all="yes" whodata="yes" report_changes="yes">/etc/ssh/sshd_config</directories>
    
    <!-- Игнорирование временных файлов -->
    <ignore>/etc/passwd-</ignore>
    <ignore>/etc/shadow-</ignore>
    <ignore>/etc/sudoers.tmp</ignore>
    <ignore>/etc/.pwd.lock</ignore>
    
    <!-- Дополнительные параметры -->
    <alert_new_files>yes</alert_new_files>
    <scan_on_start>yes</scan_on_start>
    <auto_ignore>no</auto_ignore>
  </syscheck>
</agent_config>
```

### 3. Настройка правил алертинга

Для критических файлов рекомендуется повысить уровень важности событий до **12**. Отредактируйте `/var/ossec/etc/rules/local_rules.xml` на менеджере:

```xml
<group name="syscheck,">
  <!-- Изменение /etc/passwd -->
  <rule id="100100" level="12">
    <if_sid>550</if_sid>
    <field name="file">/etc/passwd</field>
    <description>КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: Изменен файл /etc/passwd</description>
    <mitre>
      <id>T1078</id>
      <id>T1136</id>
    </mitre>
  </rule>

  <!-- Изменение /etc/shadow -->
  <rule id="100101" level="12">
    <if_sid>550</if_sid>
    <field name="file">/etc/shadow</field>
    <description>КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: Изменен файл /etc/shadow (пароли)</description>
    <mitre>
      <id>T1003</id>
      <id>T1078</id>
    </mitre>
  </rule>

  <!-- Изменение /etc/sudoers -->
  <rule id="100102" level="12">
    <if_sid>550</if_sid>
    <field name="file">/etc/sudoers</field>
    <description>КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ: Изменен файл /etc/sudoers</description>
    <mitre>
      <id>T1078</id>
      <id>T1548</id>
    </mitre>
  </rule>

  <!-- Дополнительное правило для whodata: КТО изменил -->
  <rule id="100103" level="10">
    <if_sid>554</if_sid>
    <field name="file">/etc/passwd</field>
    <field name="file">/etc/shadow</field>
    <field name="file">/etc/sudoers</field>
    <description>Обнаружен пользователь, изменивший критический файл: $(file) - $(audit.user.name)</description>
    <mitre>
      <id>T1078</id>
    </mitre>
  </rule>
</group>
```

## Дополнительная информация

### Сравнение с другими инструментами
| Особенность | Wazuh FIM | AIDE / Tripwire |
| :--- | :--- | :--- |
| **Режим** | В реальном времени | По расписанию (cron) |
| **Централизация** | Да (Wazuh Manager) | Нет (локальные БД) |
| **Аудит (Кто?)** | Да (через auditd) | Нет |
| **Реагирование** | Active Response | Нет |

### См. также
- [auditd: аудит системных вызовов](../../../Linux/SystemAdministration/Logging/auditd.md)
- [Мониторинг ядра через Wazuh](./kernel_monitoring.md)
- [Wazuh: обзор SIEM](../wazuh.md)
- [Проверка целостности файлов в Linux](../../../Linux/Security/Concepts/file-integrity-checking.md)
- [Автоматизация Wazuh через Ansible](./ansible-automation-per-agent.md) — управление конфигурациями и правилами в больших средах.
