# Мониторинг ядра Linux через Wazuh

## Определения

**Wazuh Kernel Monitoring** — специализированный сценарий использования платформы Wazuh для непрерывного контроля состояния ядра Linux. Включает обнаружение атак в реальном времени, инвентаризацию загруженных модулей (LKM) и автоматизированную оценку соответствия политикам безопасности (Hardening).

**Поверхность атаки ядра**: динамические модули, системные вызовы (syscalls), параметры `sysctl` и уязвимости в механизмах управления памятью (например, Page Cache).

**Архитектура сбора событий ядра в Wazuh**:
```
Источник (ядро) → Агент (wodle/FIM/SCA) → Менеджер (analysisd) → Правила (rules) → Alert/Active Response
```

Агент собирает данные из трёх источников:
1. **Wodle Command** — кастомные скрипты для инвентаризации (`/proc/modules`, `lsmod`, `modinfo`).
2. **FIM (Syscheck)** — мониторинг `/proc/modules`, `/sys/module`, `/dev` через `inotify`/`eBPF`/`Audit`-провайдер.
3. **SCA** — статическая проверка `sysctl`, версий ядра и статуса LSM.

**Жизненный цикл события ядра**:
1. Драйвер/скрипт генерирует событие (JSON/syslog).
2. Агент отправляет на менеджер (порт 1514/55000).
3. `analysisd` применяет декодеры и правила.
4. При совпадении — генерируется alert с уровнем severity.
5. Опционально — Active Response (блокировка, изоляция, скрипт).

**LKM (Loadable Kernel Module) Rootkit** — модуль ядра, загруженный без подписи или из нестандартного пути, маскирующий свою присутствие (скрывает себя из `/proc/modules`, перехватывает системные вызовы). Détecté по сочетанию признаков: отсутствие файла `.ko`, подозрительный `taint`, расхождение между `/proc/modules` и `/sys/module`.

**Taint flag** — метка в `/sys/module/<name>/taint`, указывающая на проприетарный (`P`), GPL-несовместимый (`G`), загруженный из внешнего источника (`?`) или иной нестандартный статус модуля. Значение `0` = чистый GPL.

## Основные концепции

### Механизмы мониторинга

Для обеспечения полной видимости Wazuh комбинирует несколько подходов:

| Механизм | Метод реализации | Цель | Оверхед | Требования к ядру |
| :--- | :--- | :--- | :--- | :--- |
| **eBPF (Modern)** | Драйвер ядра (JIT/CO-RE) | Мониторинг активности файлов и процессов с минимальным оверхедом. | Низкий (user-space) | 4.14+, CONFIG_BPF, CONFIG_BPF_SYSCALL |
| **Auditd (Legacy)** | Подсистема аудита ядра | Глубокий анализ системных вызовов (например, `splice`, `ptrace`). | Средний/Высокий (sync write) | Любое с auditd пакетом |
| **Wodle Command** | Кастомные скрипты | Периодическая инвентаризация модулей и проверка их целостности. | Зависит от интервала | Любое |
| **FIM (Syscheck)** | Inotify / Whodata | Мониторинг `/proc/modules` и `/sys/module` для обнаружения скрытой загрузки модулей. | Низкий/Средний | 4.14+ для eBPF |
| **SCA** | YAML-политики | Проверка параметров `sysctl`, версий ядра и статуса LSM (AppArmor/SELinux). | Нулевой (on-demand) | Любое |

### Детекция современных эксплойтов (CVE-2022-0847)

Эксплойт **Dirty Pipe** позволяет непривилегированному пользователю модифицировать данные в кэше страниц ядра (Page Cache), что ведет к эскалации привилегий. Детекция строится на мониторинге системного вызова `splice()`, который используется для манипуляции с pipe-буферами.

### Дополнительные векторы мониторинга

#### Кольцевой буфер ядра (dmesg / kernel log)

Сбор сообщений ядра через Logcollector или wodle для детекции panics, OOPS, аппаратных ошибок и подозрительных сообщений от LKM.

**Wodle для dmesg (`/var/ossec/custom-scripts/kernel_dmesg.sh`):**
```bash
#!/bin/sh
dmesg -T --level=err,warn,crit,alert,emerg 2>/dev/null | while read -r line; do
  printf '{"type":"kernel_dmesg","message":"%s"}\n' "$(echo "$line" | sed 's/"/\\"/g')"
done
```

**Конфигурация:**
```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>kernel_dmesg</tag>
  <command>/var/ossec/custom-scripts/kernel_dmesg.sh</command>
  <interval>5m</interval>
  <run_on_start>yes</run_on_start>
  <log_format>json</log_format>
</wodle>
```

#### Статус LSM (Linux Security Modules)

Проверка активного модуля безопасности через `sca` или wodle:
```bash
cat /sys/kernel/security/lsm 2>/dev/null || echo "none"
# → Пример: "selinux,apparmor"
```

## Практические сценарии

### Предварительные требования

- **Wazuh Manager** 4.9+ (рекомендуется 5.x).
- **Wazuh Agent** на каждом целевом хосте (Linux kernel 4.14+ для eBPF).
- Права `root` на агенте для доступа к `/proc/modules`, `/sys/module`, `dmesg`.
- `auditd` установлен и активен (если используется Audit-провайдер).
- Заголовки ядра (`linux-headers-$(uname -r)`) для eBPF-программ.
- Доступ к менеджеру для загрузки SCA-политик и правил.

### 1. Инвентаризация модулей ядра

Сбор данных о модулях, их статусе (taint) и наличии соответствующих файлов на диске.

**Скрипт инвентаризации (`/var/ossec/custom-scripts/kernel_inventory.sh`):**
```bash
#!/bin/sh
while read -r mod_name size refcount deps state addr; do
  name=$(echo "$mod_name" | tr -d ',')
  taint=$(cat "/sys/module/${name}/taint" 2>/dev/null || echo "0")
  path=$(modinfo -F filename "$name" 2>/dev/null | head -1)
  [ -z "$path" ] && path="N/A"
  
  printf '{"type":"kernel_module","name":"%s","size":%s,"taint":"%s","path":"%s"}\n' \
    "$name" "$size" "$taint" "$path"
done < /proc/modules
```

**Разбор скрипта:**
- `taint=0` — модуль чистый GPL.
- `taint!=0` — требуется проверка: может быть легальным (виртуализация, драйверы) или признаком руткита.
- `path=N/A` — критичный признак: модуль загружен, но файл `.ko` отсутствует (возможна инъекция через `/dev/mem` или `kexec`).

**Валидация:**
```bash
sudo bash /var/ossec/custom-scripts/kernel_inventory.sh
# → Должен выводить JSON для каждого модуля
sudo /var/ossec/bin/wazuh-logtest -t alert -u 001 < <(sudo bash /var/ossec/custom-scripts/kernel_inventory.sh)
```

**Конфигурация Wodle (`ossec.conf`):**
```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>kernel_inventory</tag>
  <command>/var/ossec/custom-scripts/kernel_inventory.sh</command>
  <interval>1h</interval>
  <run_on_start>yes</run_on_start>
</wodle>
```

### 2. Настройка детекции Dirty Pipe (CVE-2022-0847)

Для обнаружения попыток эксплуатации необходимо использовать гибридный подход: аудит системных вызовов через `auditd` и проверку версии ядра через `SCA`.

#### Шаг А: Правило Auditd
Добавьте в `/etc/audit/rules.d/audit.rules`:
```bash
-a always,exit -F arch=b64 -S splice -k dirty_pipe
```

#### Шаг Б: Правила Wazuh (Менеджер)
```xml
<group name="kernel_exploit,">
  <!-- Детекция аномального вызова splice -->
  <rule id="100350" level="12">
    <if_sid>80700</if_sid>
    <field name="audit.key">dirty_pipe</field>
    <field name="audit.uid" negate="yes">^0$</field>
    <description>Подозрительный вызов splice() от пользователя uid=$(audit.uid) — возможная атака Dirty Pipe (CVE-2022-0847)</description>
    <mitre><id>T1068</id></mitre>
  </rule>

  <!-- Детекция модуля без файла (Rootkit) -->
  <rule id="100351" level="14">
    <decoded_as>json</decoded_as>
    <field name="type">^kernel_module$</field>
    <field name="path">^N/A$</field>
    <description>Модуль ядра не имеет файла на диске: $(name) — признак руткита!</description>
  </rule>
</group>
```

### 3. Проактивный аудит через SCA

Использование модуля **SCA (Security Configuration Assessment)** для поиска уязвимых версий ядра (5.8 – 5.16.10). Подробнее о модуле: **[Оценка конфигурации безопасности (SCA) в Wazuh](./wazuh-sca.md)**.

**Пример SCA политики (`/var/ossec/etc/sca/kernel_cve.yml`):**
```yaml
policy:
  id: "kernel_vulnerability_check"
  description: "Анализ уязвимостей ядра Linux"
  file: "kernel_cve.yml"
checks:
  - id: 20001
    title: "Проверка уязвимости ядра к Dirty Pipe (CVE-2022-0847)"
    condition: all
    rules:
      - 'c:uname -r -> r:^5\.(8|9|10|11|12|13|14|15|16)'
```

**Валидация политики:**
```bash
sudo /var/ossec/bin/wazuh-control restart
# На менеджере:
sudo tail -f /var/ossec/logs/wazuh.log | grep -i "sca\|policy"
# → Expected: "SCA: Policy loaded successfully"
```

### 4. Мониторинг загрузки/выгрузки модулей через FIM

Используйте `syscheck` для отслеживания изменений в `/proc/modules` и `/sys/module`:

```xml
<syscheck>
  <directories real_time="yes">/proc/modules</directories>
  <directories real_time="yes">/sys/module</directories>
  <ignore>/proc/modules/.*</ignore>
</syscheck>
```

**Примечание:** `/proc/modules` — виртуальный файл, изменения детектируются только через `inotify`/`eBPF`/`Audit`. На ядрах < 4.14 используйте Audit-провайдер.

### 5. Обнаружение изменений sysctl

Скрипт для wodle, фиксирующий отклонения от baseline:

```bash
#!/bin/sh
BASELINE="/etc/sysctl.d/99-kernel-baseline.conf"
if [ -f "$BASELINE" ]; then
  diff <(sysctl -a | sort) <(grep -E '^[a-zA-Z]' "$BASELINE" | sort) 2>/dev/null && exit 0
  printf '{"type":"sysctl_change","message":"Detected sysctl drift from baseline"}\n'
fi
```

### 6. Active Response для ядерных угроз

Настройка автоматической реакции на загрузку модуля без файла:

```xml
<command>
  <name>kernel-isolate</name>
  <executable>kernel-isolate.sh</executable>
  <expect>srcip</expect>
  <timeout>30</timeout>
</command>

<active-response>
  <command>kernel-isolate</command>
  <location>local</location>
  <rules_id>100351</rules_id>
</active-response>
```

Скрипт `/var/ossec/active-response/bin/kernel-isolate.sh`:
```bash
#!/bin/bash
# Изоляция хоста при детекции руткита: перевод в quarantine-зону через iptables
QUARANTINE_CHAIN="QUARANTINE"
iptables -I INPUT -j "$QUARANTINE_CHAIN" 2>/dev/null
logger "Wazuh Active Response: Host quarantined due to kernel rootkit detection"
```

### 7. Автоматизация развертывания через Ansible

```yaml
- name: Deploy kernel monitoring scripts
  copy:
    src: files/kernel_inventory.sh
    dest: /var/ossec/custom-scripts/kernel_inventory.sh
    owner: root
    mode: '0755'

- name: Configure Wodle for kernel inventory
  xml:
    path: /var/ossec/etc/ossec.conf
    xpath: /ossec-config/wodle[tag='kernel_inventory']
    pretty_print: yes
  notify: restart wazuh

- name: Deploy SCA policy for kernel CVE
  copy:
    src: files/kernel_cve.yml
    dest: /var/ossec/etc/sca/kernel_cve.yml
  notify: restart wazuh-modulesd
```

### 8. CI/CD пайплайн для политик ядра

```yaml
name: Kernel Security Policy CI/CD

on: [push, pull_request]

jobs:
  validate-sca:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate YAML syntax
        run: python3 -c "import yaml; yaml.safe_load(open('sca/kernel_cve.yml'))"
      - name: Lint XML rules
        run: python3 scripts/lint_wazuh_rules.py rules/kernel_exploit.xml
      - name: Deploy to staging
        if: github.ref == 'refs/heads/main'
        run: ansible-playbook -i inventory/staging playbooks/deploy_kernel_monitoring.yml
```

### 9. Бэкап и восстановление конфигурации

```bash
# Бэкап
tar -czf /backup/wazuh-kernel-$(date +%Y%m%d).tar.gz \
  /var/ossec/etc/sca/kernel_cve.yml \
  /var/ossec/custom-scripts/kernel_inventory.sh \
  /var/ossec/etc/ossec.conf

# Восстановление
tar -xzf /backup/wazuh-kernel-20250918.tar.gz -C /
sudo /var/ossec/bin/wazuh-control restart
```

## Дополнительная информация

### Гибридный мониторинг (eBPF + Auditd)

В современных инсталляциях (Wazuh 4.9+) рекомендуется:
- **eBPF**: Использовать как провайдер для модуля FIM (`<whodata><provider>ebpf</provider></whodata>`) для снижения нагрузки на CPU при мониторинге файлов.
- **Auditd**: Использовать для точечного мониторинга критических системных вызовов (`splice`, `execve`), которые пока не полностью покрываются стандартным eBPF-драйвером Wazuh.

### Производительность и масштабирование

| Сценарий | Механизм | Рекомендация |
| :--- | :--- | :--- |
| < 100 агентов | Auditd | Достаточно для старта; настройте `logrotate` |
| 100–1000 агентов | eBPF + Auditd (hybrid) | eBPF для массовых путей, auditd для критических syscalls |
| > 1000 агентов | eBPF + Wodle Command | Минимизируйте auditd; используйте wodle с интервалом ≥5m |
| Высоконагруженные хосты | Только eBPF | Отключите auditd, чтобы избежать задержек I/O |

**Оверхед auditd на высоконагруженных системах:**
- Синхронная запись в `/var/log/audit/audit.log` может вызывать задержки до 10–50 ms на syscall.
- Используйте `audispd` с асинхронным плагином (`audispd-plugins`) для пересылки в Wazuh.
- Настройте `max_log_file` и `num_logs` в `/etc/audit/auditd.conf` для ротации.

### Телеметрия и метрики

```bash
# Проверка статуса eBPF программ
sudo bpftool prog list | grep -i wazuh
# → expected: список программ с тегом "wazuh"

# Проверка загруженных модулей
lsmod | grep -E 'wazuh|rootkit|suspicious'
# → expected: пусто (если только FIM/eBPF)

# Мониторинг логов auditd
sudo ausearch -k dirty_pipe --start recent -i | tail -20
```

### Сравнение с другими инструментами

| Инструмент | LKM detection | Syscall monitoring | Sysctl audit | Active Response | Требует агента |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Wazuh** | Да (FIM + wodle) | Да (auditd/eBPF) | Да (SCA) | Да | Да |
| **Falco** | Ограничено | Да (eBPF) | Нет | Да (外部) | Да |
| **Osquery** | Ограничено | Нет | Да | Нет | Да |
| **AIDE** | Нет | Нет | Нет | Нет | Нет |

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Модуль не детектируется** | FIM не настроен для `/proc/modules` | Добавьте `<directories real_time="yes">/proc/modules</directories>` в `ossec.conf` |
| **Ложные срабатывания модулей** | Легальные драйверы (nvidia, vboxguest) | Добавьте исключения в правило по `taint` или `path` |
| **Auditd переполняет лог** | Высокая частота syscalls | Переключитесь на eBPF; добавьте `-S splice` вместо `always,exit` |
| **eBPF провайдер не загружается** | Ядро < 4.14 или нет заголовков | Установите `linux-headers-$(uname -r)`, проверьте `CONFIG_BPF` |
| **SCA политика не применяется** | Хеш не обновлён | Перезапустите `wazuh-modulesd` на менеджере |
| **Нет событий whodata** | Неправильный провайдер | Проверьте `uname -r`, для eBPF ≥4.14; проверьте `bpftool prog list` |
| **Высокий CPU auditd** | Нет ротации или слишком много правил | Настройте `logrotate`, добавьте исключения, перейдите на eBPF |

### Миграционные заметки (4.x → 5.x)

- В Wazuh 5.x формат SCA-политик изменился: добавлены поля `file` и `requirements`.
- Пути конфигурации остались прежними: `/var/ossec/etc/sca/`, `/var/ossec/custom-scripts/`.
- `wazuh-modulesd` теперь имеет расширенные метаданные; используйте `wazuh-control status modules` для диагностики.
- eBPF-провайдер в 5.x требует `libbpf` 1.0+; на старых дистрибутивах может потребоваться обновление `bcc`/`libbpf`.

### Best Practices

1. **Приоритет eBPF:** Используйте `ebpf` провайдер для Linux ядер 4.14+. Он обеспечивает минимальную задержку и нагрузку на CPU по сравнению с `auditd`.
2. **Сегментация:** Разделяйте критические модули (сеть, криптография) и штатные драйверы (виртуализация, GPU).
3. **Тюнинг SCA:** Запускайте SCA-проверки по расписанию (не чаще 1 раз в 4 часа), чтобы не перегружать агенты.
4. **Ротация auditd:** Настройте `logrotate` для `/var/log/audit/audit.log`, иначе диск заполнится за часы при высокой активности.
5. **Верификация модулей:** Для критических хостов используйте `modsign` и `kernel_lockdown`; Wazuh обнаружит только факт загрузки, но не подлинность.
6. **Кластеризация:** При >500 агентах используйте Wazuh HA (менеджер в кластере), чтобы избежать потерь событий при burst-активности ядра.

### Edge Cases и ограничения

- **Виртуальные файлы `/proc` и `/sys`:** FIM не отслеживает их содержимое напрямую. Используйте wodle или auditd для детекции изменений.
- **Жадные regex в правилах:** Избегайте `.*` в правилах для `audit.uid` — это вызывает backtracking и замедляет `analysisd`.
- **Кодировка audit.log:** Убедитесь, что `LC_ALL=C` на агенте; иначе Wazuh может некорректно декодировать сообщения auditd.
- **LVM / container layer:** Модули, загруженные внутри контейнера, видны на хосте только через `/proc/modules` (если контейнер использует host pid namespace).
- **Живые обновления ядра (kpatch/kgraft):** Не меняют `/proc/modules`; детектируются только по изменению версии в `uname -r` или `utsname` через SCA.
- **Ограничение полей Wazuh:** Alert содержит не более 64 полей; для LKM-инвентаря используйте JSON-разбиение или хранилище (Indexer).

### См. также
- [Харденинг ядра Linux](../../../Linux/Security/Mechanisms/Kernel/hardening.md) — детальные параметры `sysctl` и их значения.
- [auditd: аудит системных вызовов](../../../Linux/SystemAdministration/Logging/auditd.md) — настройка логирования событий ядра.
- [Мониторинг целостности файлов (FIM) в Wazuh](./wazuh-fim.md) — детали настройки eBPF провайдера.
- [Wazuh: обзор SIEM](../wazuh.md)

