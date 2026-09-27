# Мониторинг целостности файлов (FIM) в Wazuh

## Определения

**Wazuh File Integrity Monitoring (FIM)** — компонент платформы Wazuh, предназначенный для непрерывного отслеживания изменений в файловой системе конечных точек. В отличие от инструментов статического анализа (например, AIDE или Tripwire), FIM обеспечивает мониторинг в реальном времени и позволяет идентифицировать не только факт изменения, но и контекст события: какой пользователь и какой процесс инициировали правку. Актуален для Wazuh 4.x и 5.x.

**Syscheck** — внутренний модуль агента Wazuh, выполняющий сканирование файлов, вычисление контрольных сумм (MD5, SHA-1, SHA-256) и мониторинг метаданных (права доступа, владелец, группа, размер, inode, mtime, ctime, extended attributes).

**Whodata** — расширенный режим мониторинга, предоставляющий информацию о пользователе (UID, User) и процессе (PID, имя, командная строка), внесшем изменения. Основан на механизмах аудита ядра.

**Baseline (Эталонная база)** — локальная SQLite-база агенента, содержащая контрольные суммы и метаданные файлов после последнего сканирования. При каждом изменении модуль сравнивает текущее состояние с baseline и генерирует событие при расхождении.

**Active Response** — механизм Wazuh, позволяющий автоматически применять корректирующие действия (блокировка пользователя, отключение агента, блокировка IP) по результатам анализа алертов.

## Основные концепции

### Режимы мониторинга

1. **Периодическое сканирование (Scheduled):** Агент сканирует выбранные директории через заданные интервалы времени (`<frequency>` в секундах). Используется для синхронизации baseline и обнаружения изменений, совершеннных во время недоступности механизмов реального времени (например, при отключенном `inotify` или `auditd`).
2. **Реальное время (Real-time):** Использование механизмов ядра (`inotify` в Linux, `ReadDirectoryChangesW` в Windows) для мгновенного обнаружения изменений. При изменении файла модуль вычисляет хеш и отправляет событие на менеджер.
3. **Аудит данных (Whodata):** Наиболее детализированный режим, предоставляющий атрибуцию. Использует провайдер аудита ядра для перехвата системных вызовов (`open`, `write`, `unlink`, `chmod`, `rename` и др.) и связывания их с UID и PID.

### Механизмы Whodata по платформам

| Платформа | Механизм (Provider) | Особенности |
| :--- | :--- | :--- |
| **Linux (Kernel 4.14+)** | **eBPF** | Оптимизированная производительность, низкая нагрузка на CPU, не требует auditd. Рекомендуется по умолчанию для современных ядер. |
| **Linux (Legacy)** | **Auditd** | Использует подсистему аудита ядра через `auditd`. Может вызывать задержки на высоконагруженных системах из-за синхронной записи в лог. Требует отдельной ротации логов. |
| **Windows** | **Windows Audit** | Использует SACL (System Access Control Lists). Требует включения политики "Audit File System" через `auditpol` или групповые политики. |

### Атрибуты файлов, мониторируемые Syscheck

При `check_all="yes"` модуль отслеживает:
- Контрольные суммы: MD5, SHA-1, SHA-256 (регулируется через `<checksum>`)
- Метаданные: владелец, группа, права доступа (mode), inode, размер
- Временные метки: mtime (изменение содержимого), ctime (изменение метаданных), atime (доступ)
- Extended attributes (xattrs) и ACL, если поддерживаются платформой
- Содержимое файла (`report_changes="yes"`) — отправка diff на менеджер

### Жизненный цикл события FIM

1. **Перехват:** Механизм ядра (eBPF / inotify / Audit) детектирует вызов к файлу.
2. **Фильтрация:** Агент проверяет путь по спискам `<ignore>` и `<ignore type="sregex">`.
3. **Вычисление хеша:** Модуль syscheck считывает файл и вычисляет контрольную сумму.
4. **Сбор контекста (Whodata):** Извлекается UID, PID, имя процесса, командная строка.
5. **Сравнение с baseline:** Если хеш/метаданные отличаются от SQLite-базы — формируется событие.
6. **Отправка:** Событие упаковывается в JSON и передается на Wazuh Manager через `wazuh-analysisd` (или Wazuh-Engine в 5.x).
7. **Корреляция:** Manager применяет правила (XML/Sigma) и присваивает уровень важности.
8. **Хранение:** Событие индексируется в OpenSearch/Wazuh Indexer и отображается в Dashboard.
9. **Реагирование:** При соответствии правилу срабатывает Active Response.

### Архитектура FIM

| Компонент | Роль в FIM |
| :--- | :--- |
| **Wazuh Agent** | Наблюдает за файлами, вычисляет хеши, собирает данные о процессах и отправляет события. Выполняет фильтрацию до отправки. |
| **Модули ядра** | (eBPF, inotify, Audit) перехватывают системные вызовы обращения к файлам. |
| **Wazuh Manager** | Сравнивает данные с эталонной базой (baseline), хранящейся в SQLite на агенте, применяет правила корреляции и генерирует алерты. |
| **Wazuh Indexer** | Индексирует события для визуализации в Dashboard и полнотекстового поиска по истории изменений. |

## Практические сценарии

### 1. Предварительные требования

#### Аппаратные и программные требования

- **Wazuh Manager:** 4 CPU, 8 GB RAM, 100 GB SSD (минимально для парка до 50 агентов). Для 1000+ агентов рекомендуется от 16 CPU и 32 GB RAM с отдельным томом для индекса.
- **Wazuh Agent (Linux):** 1 CPU, 512 MB RAM, 10 GB диска. Ядро Linux 4.14+ для eBPF-провайдера. Модуль `bpf` должен быть загружен (`lsmod | grep bpf`).
- **Wazuh Agent (Windows):** Windows Server 2016+ или Windows 10+. Подсистема аудита включена по умолчанию на Server 2019+.

#### Зависимости

**Linux (Audit-провайдер):**
```bash
# Debian/Ubuntu
sudo apt install auditd audispd-plugins -y
sudo systemctl enable --now auditd

# RHEL/CentOS/Rocky
sudo dnf install audit audispd-plugins -y
sudo systemctl enable --now auditd
```

**Windows:**
```powershell
auditpol /set /subcategory:"File System" /success:enable /failure:enable
```

### 2. Централизованная конфигурация

Конфигурация задается в `ossec.conf` агента или централизованно в `agent.conf` на менеджере.

```xml
<syscheck>
  <!-- Частота полного сканирования для синхронизации базы (раз в 12 часов) -->
  <frequency>43200</frequency>

  <!-- Глобальные настройки Whodata -->
  <whodata>
    <provider>ebpf</provider> <!-- Рекомендуется для современных Linux ядер -->
  </whodata>

  <!-- Критические системные файлы с Whodata и Diff -->
  <directories check_all="yes" whodata="yes" report_changes="yes">/etc,/usr/bin,/usr/sbin</directories>

  <!-- Защита конфиденциальных данных: мониторинг без сохранения diff (запрет отправки содержимого на менеджер) -->
  <directories check_all="yes" whodata="yes" report_changes="no">/etc/shadow,/etc/sudoers</directories>

  <!-- Игнорирование часто меняющихся или временных файлов (снижение шума) -->
  <ignore>/etc/mtab</ignore>
  <ignore>/etc/hosts.deny</ignore>
  <ignore>/etc/passwd-</ignore>
  <ignore type="sregex">.tmp$|.swp$</ignore>

  <!-- Дополнительные параметры -->
  <alert_new_files>yes</alert_new_files>
  <scan_on_start>yes</scan_on_start>
  <auto_ignore frequency="10" timeframe="3600">no</auto_ignore>
</syscheck>
```

### 3. Настройка правил алертинга

В файле правил агента (`/var/ossec/etc/rules/local_rules.xml`) или менеджера (`/var/wazuh-manager/etc/rules/local_rules.xml` для 5.x) можно переопределить стандартные уровни важности.

```xml
<group name="syscheck,">
  <!-- Повышение уровня важности для изменений в /etc/shadow -->
  <rule id="100201" level="13">
    <if_sid>550</if_sid>
    <field name="file">/etc/shadow</field>
    <description>КРИТИЧЕСКОЕ СОБЫТИЕ: Попытка изменения хешей паролей в /etc/shadow</description>
    <mitre>
      <id>T1003.008</id>
    </mitre>
  </rule>

  <!-- Отслеживание конкретного пользователя в whodata -->
  <rule id="100202" level="10">
    <if_sid>554</if_sid>
    <field name="audit.user.name">root</field>
    <description>Файловая система изменена пользователем root (Whodata)</description>
  </rule>
</group>
```

### 4. Проверка работоспособности FIM

#### Проверка статуса агента

```bash
# На агенте
sudo /var/ossec/bin/wazuh-control status

# На менеджере (Wazuh 4.x)
sudo /var/ossec/bin/ossec-control status

# На менеджере (Wazuh 5.x)
sudo /var/wazuh-manager/bin/wazuh-control status
```

#### Проверка списка зарегистрированных агентов

```bash
sudo /var/ossec/bin/agent_control -l
# → ID: 001, Name: web-server-01, IP: 10.0.0.5, ...
```

#### Тестовое событие: создание файла в отслеживаемой директории

```bash
# На агенте
sudo touch /etc/test_fim_trigger
sudo chmod 600 /etc/test_fim_trigger

# Проверка логов агента
sudo tail -f /var/ossec/logs/ossec.log
# → Expected: "alert: syscheck: ... file /etc/test_fim_trigger added"

# Проверка входящих событий на менеджере
sudo tail -f /var/wazuh-manager/logs/alerts/alerts.log
# → Expected: JSON с полем "syscheck" и путем "/etc/test_fim_trigger"
```

#### Проверка событий FIM через CLI менеджера

```bash
# Wazuh 4.x
sudo /var/ossec/bin/wazuh-logtest -t alert
# Вставить JSON алерта из alerts.log → вывод с полями "rule", "decoder", "srcuser"

# Wazuh 5.x
sudo /var/wazuh-manager/bin/wazuh-logtest -t alert
```

### 5. Baseline и первоначальное сканирование

При первом запуске агента или после сброса базы FIM происходит первоначальное сканирование, в результате которого формируется baseline. На больших файловых системах (200k+ файлов) это может создавать нагрузку на диск и CPU.

#### Параметры управления baseline

```xml
<syscheck>
  <scan_on_start>yes</scan_on_start>
  <frequency>43200</frequency>
  <skip_nfs>yes</skip_nfs>
  <skip_cifs>yes</skip_cifs>
  <skip_perm>no</skip_perm>
  <check_umask>yes</check_umask>
  <check_all>yes</check_all>
  <check_sum>yes</check_sum>
  <check_sha1>yes</check_sha1>
  <check_sha256>yes</check_sha256>
  <check_md5>yes</check_md5>
  <check_size>yes</check_size>
  <check_owner>yes</check_owner>
  <check_group>yes</check_group>
  <check_perm>yes</check_perm>
</syscheck>
```

#### Сброс baseline без перезагрузки агента

```bash
# На агенте
sudo /var/ossec/bin/wazuh-control restart
# Или принудительно:
sudo find /var/ossec/syscheck/ -name "*.db" -delete
sudo /var/ossec/bin/wazuh-control restart
```

### 6. Настройка через Ansible (Detection as Code)

Для массового развертывания FIM в инфраструктуре рекомендуется использовать Ansible для управления `ossec.conf` и правилами.

```yaml
- name: "Применение конфигурации FIM через шаблон"
  become: true
  ansible.builtin.template:
    src: "templates/syscheck_block.xml.j2"
    dest: "/var/ossec/etc/ossec.conf"
    mode: "0640"
    owner: root
    group: wazuh
  notify: "Restart wazuh-agent"
```

Шаблон `syscheck_block.xml.j2`:
```xml
<syscheck>
  <frequency>{{ wazuh_fim_frequency | default(43200) }}</frequency>
  <whodata>
    <provider>{{ wazuh_fim_whodata_provider | default('ebpf') }}</provider>
  </whodata>
  {% for dir in wazuh_fim_dirs %}
  <directories check_all="yes" whodata="{{ dir.whodata | default('no') }}" report_changes="{{ dir.report_changes | default('no') }}">{{ dir.path }}</directories>
  {% endfor %}
  {% for ign in wazuh_fim_ignores %}
  <ignore>{{ ign }}</ignore>
  {% endfor %}
  <auto_ignore frequency="10" timeframe="3600">yes</auto_ignore>
</syscheck>
```

Переменные инвентаря (`host_vars/web-server-01.yml`):
```yaml
wazuh_fim_dirs:
  - { path: "/etc", whodata: "yes", report_changes: "yes" }
  - { path: "/usr/bin", whodata: "yes", report_changes: "no" }
  - { path: "/etc/ssh", whodata: "yes", report_changes: "yes" }
wazuh_fim_ignores:
  - "/etc/mtab"
  - "/etc/hosts.deny"
```

### 7. Active Response на изменение критического файла

Wazuh позволяет автоматически блокировать пользователя или IP при изменении критических файлов. Пример: блокировка учетной записи пользователя, изменившего `/etc/sudoers`.

#### Шаг 1: Создание скрипта Active Response

Файл `/var/wazuh-manager/active-response/bin/lock-user.sh`:
```bash
#!/bin/bash
# Wazuh Active Response: блокировка пользователя при изменении /etc/sudoers
# Параметры передаются Wazuh через stdin JSON

USERNAME=$(cat $1 | jq -r .syscheck.audit.user.name)
LOCKED=$(grep -c "^${USERNAME}:!" /etc/shadow || true)

if [ "$LOCKED" -eq 0 ] && [ "$USERNAME" != "root" ]; then
  usermod -L "$USERNAME"
  echo "$(date) - FIM: User $USERNAME locked due to /etc/sudoers change" >> /var/log/wazuh-active-response.log
fi

exit 0
```

```bash
sudo chmod +x /var/wazuh-manager/active-response/bin/lock-user.sh
sudo chown root:wazuh /var/wazuh-manager/active-response/bin/lock-user.sh
```

#### Шаг 2: Настройка правил в `local_rules.xml`

```xml
<group name="syscheck,">
  <rule id="100301" level="15">
    <if_sid>550</if_sid>
    <field name="file">/etc/sudoers</field>
    <field name="audit.user.name">!root</field>
    <description>CRITICAL: /etc/sudoers modified by non-root user</description>
    <options>no_full_log</options>
  </rule>
</group>

<active-response>
  <command>lock-user.sh</command>
  <local_id>100301</local_id>
  <timeout>0</timeout>
  <rules_id>100301</rules_id>
</active-response>
```

#### Шаг 3: Перезагрузка менеджера

```bash
# Wazuh 4.x
sudo /var/ossec/bin/ossec-control restart

# Wazuh 5.x
sudo /var/wazuh-manager/bin/wazuh-control restart
```

### 8. Валидация и отладка

#### Проверка подключения eBPF провайдера

```bash
# На агенте
sudo bpftool prog list | grep -i wazuh
# → Expected: список программ с тегом wazuh

# Проверка логов syscheck
sudo tail -f /var/ossec/logs/wazuh.log | grep -i "fim\|syscheck\|whodata"
# → Expected: "whodata: Using ebpf provider"
```

#### Проверка целостности SQLite базы

```bash
sudo sqlite3 /var/ossec/queue/syscheck/syscheck.db "SELECT COUNT(*) FROM file_entry;"
# → Количество записей должно совпадать с количеством отслеживаемых файлов

sudo sqlite3 /var/ossec/queue/syscheck/syscheck.db "PRAGMA integrity_check;"
# → Expected: ok
```

#### Принудительная отправка события для отладки

```bash
sudo /var/ossec/bin/wazuh-control restart
sudo /var/ossec/bin/wazuh-logtest -t alert -u 001
```

## Дополнительная информация

### Сравнение с аналогичными инструментами

| Особенность | Wazuh FIM | AIDE | Auditd (Standalone) |
| :--- | :--- | :--- | :--- |
| **Реакция** | В реальном времени | По расписанию | В реальном времени |
| **Атрибуция (Кто?)** | Да (Whodata) | Нет | Да |
| **Хранение хешей** | Централизованно (Manager) | Локально | Нет (только логи) |
| **Active Response** | Да (блокировка IP/пользователя) | Нет | Нет |
| **Интеграция с SIEM** | Нативная | Требует обертки | Требует обертки |
| **Автомасштабирование** | Высокое (Manager 5.x) | Ограничено | Ограничено |

### Ограничения и edge cases

* **Сетевые ФС:** Мониторинг NFS/CIFS в режиме Real-time/Whodata не поддерживается большинством механизмов ядра на стороне клиента (требуется установка агента на сервер хранения). Рекомендуется использовать периодическое сканирование (`<frequency>`) для сетевых путей.
* **Объем данных:** Включение `report_changes="yes"` (diff) для больших файлов (>1 MB) может быстро переполнить хранилище менеджера. Для таких файлов используйте `report_changes="no"` и полагайтесь на изменение хеша.
* **Количество файлов:** По умолчанию лимит мониторинга — 100 000 файлов на агента (регулируется в `internal_options.conf` параметром `syscheck.max_files`).
* **tmpfs и виртуальные ФС:** Изменения в `/proc`, `/sys`, `/dev` не отслеживаются, так как они генерируются ядром. Используйте отдельные директории для приложения.
* **Контейнеры:** FIM работает на уровне хоста. Для мониторинга контейнеров используйте `hostPath`-монтирования и отслеживайте пути внутри контейнера как обычные директории хоста. Не монтируйте `/var/lib/containers` в режиме Whodata — это вызывает event flood.
* **Журналы Auditd:** При использовании Audit-провайдера настройте ротацию логов через `logrotate`, иначе диск заполнится быстрее, чем Wazuh обработает события. Пример конфигурации: `/etc/logrotate.d/auditd`.

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **FIM не отправляет события** | Агент не подключен к менеджеру | Проверьте `agent_control -l`, убедитесь, что нет блока по ключу. Проверьте сетевое подключение и firewall (порт 1514 TCP/UDP). |
| **Нет событий whodata** | Неправильный провайдер или ядро < 4.14 | Проверьте `uname -r`, для eBPF требуется минимум 4.14. Для auditd убедитесь, что служба запущена и не переполнена логом. |
| **Event flood (алерты каждые секунды)** | Мониторинг логов или базы данных без исключений | Добавьте `<ignore>` для шумных путей. Используйте `auto_ignore`. Переключитесь с auditd на eBPF. |
| **Изменения детектируются с задержкой** | Большая `<frequency>` полного сканирования или отсутствие real-time | Убедитесь, что `<frequency>` не используется как единственный источник детекции. Проверьте, что `inotify`/`auditd` работают. |
| **База FIM повреждена (SQLite error)** | Нештатное завершение агента или переполнение диска | Удалите `syscheck.db` для сброса baseline. Проверьте место на диске (`df -h`). |
| **report_changes переполняет менеджер** | Мониторинг больших файлов с включенным diff | Установите `report_changes="no"` для файлов >1 MB. Включите `auto_ignore`. |
| **eBPF провайдер не загружается** | Ядро без поддержки eBPF или отсутствуют заголовки | Проверьте `/proc/filesystems` и `zcat /proc/config.gz | grep CONFIG_BPF`. На Ubuntu/Debian установите `linux-headers-$(uname -r)`. |

### Best Practices

1. **Приоритет eBPF:** Используйте `ebpf` провайдер для Linux ядер 4.14+. Он обеспечивает минимальную задержку и нагрузку на CPU по сравнению с `auditd`.
2. **Сегментация директорий:** Разделяйте критические пути с `report_changes="yes"` и высоконагруженные с `report_changes="no"` и `whodata="no"`.
3. **Защита diff:** Для файлов с секретами (`shadow`, `sudoers`, `sshd_config`) используйте `report_changes="no"`, чтобы предотвратить утечку содержимого через SIEM.
4. **Белые списки:** Используйте `<ignore>` и `<ignore type="sregex">` для временных файлов, логов и кэшей приложений.
5. **Базовая синхронизация:** Храните хеш `syscheck.db` в Git или отправляйте его на внешний хранение после каждого развертывания. Это позволяет детектировать компрометацию самой базы FIM.
6. **Ограничение scope:** Не мониторьте корень файловой системы (`/`) без фильтров. Указывайте конкретные директории, чтобы избежать переполнения менеджера.
7. **Комплаенс:** Для проверки PCI DSS, GDPR и ФЗ-152 настройте SCA-политики (см. [wazuh-sca.md](./wazuh-sca.md)) в дополнение к FIM для полного покрытия требований к отслеживанию изменений.

### Взаимодействие с Wazuh Dashboard

События FIM отображаются в разделе **Security Events → syscheck** Wazuh Dashboard. Для быстрого поиска используйте фильтры:
- `rule.group: syscheck` — все события модуля
- `data.syscheck.path: "/etc/ssh"` — события по конкретному пути
- `data.syscheck.audit.user.name: root` — изменения определенного пользователя
- `rule.id: 550` — стандартное правило обнаружения изменения файла

Для построения отчета по дрифту конфигурации используйте **Security Events (Overview)** с группировкой по `agent.name` и `file` path.

### MITRE ATT&CK маппинг для FIM событий

Стандартные правила Wazuh для syscheck покрывают следующие техники:
- **T1003.008** — `/etc/shadow` и `/etc/passwd`: обнаружение кражи учетных данных через изменение хешей паролей.
- **T1048** — Изменение системных бинарников (`/usr/bin`, `/usr/sbin`): подмена исполняемых файлов.
- **T1059.003** — Изменение `/etc/ssh/sshd_config`: подмена параметров SSH для бэкдоров.
- **T1543.002** — Изменение systemd-юнитов (`/etc/systemd/system`, `/usr/lib/systemd/system`): установка вредоносных сервисов.
- **T1574.002** — Изменение `/etc/ld.so.preload` или `/etc/ld.so.conf`: внедрение в процесс через LD_PRELOAD.

### Интеграция с внешним мониторингом (SRE подход)

#### Передача метрик FIM в Zabbix

```bash
# На агенте: скрипт /etc/zabbix/scripts/wazuh_fim_count.sh
#!/bin/bash
AGENT_ID="001"
EVENT_COUNT=$(sudo /var/ossec/bin/ossec-logtest -t alert -u "$AGENT_ID" 2>/dev/null | grep -c "syscheck" || true)
echo "$EVENT_COUNT"
```

```bash
# Zabbix Agent конфиг (UserParameter)
UserParameter=wazuh.fim.event.count,sudo /etc/zabbix/scripts/wazuh_fim_count.sh
```

#### Мониторинг здоровья FIM через Prometheus (node_exporter + textfile)

```bash
# На агенте: /var/lib/node_exporter/textfile_collector/wazuh_fim.prom
wazuh_fim_events_total{agent="web-01"} 1520
wazuh_fim_baseline_files{agent="web-01"} 98432
wazuh_fim_ignored_files{agent="web-01"} 1284
```

### Ротация и retention событий FIM

Wazuh Indexer (OpenSearch) хранит события FIM в индексе `wazuh-alerts-*`. Управление временем хранения:

```json
# /etc/wazuh-indexer/opensearch-index-mapper/default-index-template.json
PUT _index_template/wazuh-alerts
{
  "index_patterns": ["wazuh-alerts-*"],
  "template": {
    "settings": {
      "index": {
        "lifecycle": {
          "name": "wazuh-alerts-policy",
          "rollover_alias": "wazuh-alerts"
        },
        "number_of_shards": 1,
        "number_of_replicas": 1
      }
    }
  }
}
```

Политика ILM (Index Lifecycle Management):
```json
PUT _plugins/_ism/policies/wazuh-alerts-policy
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": {
            "max_size": "50GB",
            "max_age": "30d"
          }
        }
      },
      "warm": {
        "min_age": "30d",
        "actions": {
          "allocate": {
            "number_of_replicas": 0
          }
        }
      },
      "delete": {
        "min_age": "90d",
        "actions": {
          "delete": {}
        }
      }
    }
  }
}
```

### См. также

- [auditd: аудит системных вызовов](../../../Linux/SystemAdministration/Logging/auditd.md)
- [Мониторинг ядра через Wazuh](./kernel_monitoring.md)
- [Wazuh: обзор SIEM](../wazuh.md)
- [Оценка конфигурации безопасности (SCA) в Wazuh](./wazuh-sca.md)
- [Автоматизация Wazuh через Ansible](./ansible-automation-per-agent.md)
- [Проверка целостности файлов в Linux](../../../Linux/Security/Concepts/file-integrity-checking.md)
