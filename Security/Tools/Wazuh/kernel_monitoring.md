# Мониторинг ядра Linux через Wazuh

## Определения

**Wazuh Kernel Monitoring** — специализированный сценарий использования платформы Wazuh для непрерывного контроля состояния ядра Linux. Включает обнаружение атак в реальном времени, инвентаризацию загруженных модулей (LKM) и автоматизированную оценку соответствия политикам безопасности (Hardening).

**Поверхность атаки ядра**: динамические модули, системные вызовы (syscalls), параметры `sysctl` и уязвимости в механизмах управления памятью (например, Page Cache).

## Основные концепции

### Механизмы мониторинга

Для обеспечения полной видимости Wazuh комбинирует несколько подходов:

| Механизм | Метод реализации | Цель |
| :--- | :--- | :--- |
| **eBPF (Modern)** | Драйвер ядра (JIT) | Мониторинг активности файлов и процессов с минимальным оверхедом. |
| **Auditd (Legacy)** | Подсистема аудита ядра | Глубокий анализ системных вызовов (например, `splice`, `ptrace`). |
| **Wodle Command** | Кастомные скрипты | Периодическая инвентаризация модулей и проверка их целостности. |
| **FIM (Syscheck)** | Inotify / Whodata | Мониторинг `/proc/modules` и `/sys/module` для обнаружения скрытой загрузки модулей. |
| **SCA** | YAML-политики | Проверка параметров `sysctl`, версий ядра и статуса LSM (AppArmor/SELinux). |

### Детекция современных эксплойтов (CVE-2022-0847)

Эксплойт **Dirty Pipe** позволяет непривилегированному пользователю модифицировать данные в кэше страниц ядра (Page Cache), что ведет к эскалации привилегий. Детекция строится на мониторинге системного вызова `splice()`, который используется для манипуляции с pipe-буферами.

## Практические сценарии

### 1. Инвентаризация модулей ядра

Сбор данных о модулях, их статусе (taint) и наличии соответствующих файлов на диске.

**Скрипт инвентаризации (`/var/ossec/custom-scripts/kernel_inventory.sh`):**
```bash
#!/bin/sh
while read -r mod_name size refcount deps state addr; do
  name=$(echo "$mod_name" | tr -d ',')
  # Проверка статуса (taint): 0 = OK, !0 = проприетарный или подозрительный
  taint=$(cat "/sys/module/${name}/taint" 2>/dev/null || echo "0")
  # Поиск пути к файлу модуля
  path=$(modinfo -F filename "$name" 2>/dev/null | head -1)
  [ -z "$path" ] && path="N/A"
  
  printf '{"type":"kernel_module","name":"%s","size":%s,"taint":"%s","path":"%s"}\n' \
    "$name" "$size" "$taint" "$path"
done < /proc/modules
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
checks:
  - id: 20001
    title: "Проверка уязвимости ядра к Dirty Pipe (CVE-2022-0847)"
    condition: all
    rules:
      - 'c:uname -r -> r:^5\.(8|9|10|11|12|13|14|15|16)'
```

## Дополнительная информация

### Гибридный мониторинг (eBPF + Auditd)
В современных инсталляциях (Wazuh 4.9+) рекомендуется:
- **eBPF**: Использовать как провайдер для модуля FIM (`<whodata><provider>ebpf</provider></whodata>`) для снижения нагрузки на CPU при мониторинге файлов.
- **Auditd**: Использовать для точечного мониторинга критических системных вызовов (`splice`, `execve`), которые пока не полностью покрываются стандартным eBPF-драйвером Wazuh.

### См. также
- [Харденинг ядра Linux](../../Mechanisms/Kernel/hardening.md) — детальные параметры `sysctl` и их значения.
- [auditd: аудит системных вызовов](../../SystemAdministration/Logging/auditd.md) — настройка логирования событий ядра.
- [Мониторинг целостности файлов (FIM) в Wazuh](./wazuh-fim.md) — детали настройки eBPF провайдера.
- [Wazuh: обзор SIEM](../wazuh.md)

