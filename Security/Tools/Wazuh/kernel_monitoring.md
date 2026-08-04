# Мониторинг ядра Linux через Wazuh

## Определения

**Wazuh Kernel Monitoring** — специализированный сценарий использования платформы Wazuh для обнаружения атак на ядро, контроля целостности загруженных модулей и аудита параметров безопасности (Hardening).

## Базовые концепции

Для обнаружения атак класса Page Cache Write (Dirty Frag, Copy Fail) Wazuh использует комбинацию инвентаризации, аудита системных вызовов и SCA-проверок.

### Архитектура обнаружения

| Компонент | Механизм | Что обнаруживает |
| :--- | :--- | :--- |
| **Auditd Logs** | Анализ логов `/var/log/audit/audit.log` | Сокеты `AF_ALG`, вызовы `splice()`, подозрительные флаги. |
| **Wodle Command** | Периодический запуск кастомных скриптов | Новые/неподписанные модули, незакрытые обновления ядра. |
| **FIM (File Integrity)** | Мониторинг `/proc/modules` и `/sys/module` | Динамическую загрузку модулей в реальном времени. |
| **SCA** | Проверка `sysctl` и настроек загрузчика | Отклонения от политик харденинга. |

## Практические сценарии

### Шаг 1: Инвентаризация модулей ядра

Создайте скрипт на агенте `/var/ossec/custom-scripts/kernel_inventory.sh`:

```bash
#!/bin/sh
# Читаем /proc/modules и собираем метаданные
while read -r mod_name size refcount deps state addr; do
  name=$(echo "$mod_name" | tr -d ',')
  # Проверка статуса подписи (taint)
  taint=$(cat "/sys/module/${name}/taint" 2>/dev/null || echo "")
  # Путь к файлу
  path=$(modinfo -F filename "$name" 2>/dev/null | head -1)
  [ -z "$path" ] && path="N/A"
  
  printf '{"type":"kernel_module","name":"%s","size":%s,"taint":"%s","path":"%s"}\n' \
    "$name" "$size" "$taint" "$path"
done < /proc/modules
```

Настройте запуск в `ossec.conf` агента:

```xml
<wodle name="command">
  <disabled>no</disabled>
  <tag>kernel_inventory</tag>
  <command>/var/ossec/custom-scripts/kernel_inventory.sh</command>
  <interval>1h</interval>
  <run_on_start>yes</run_on_start>
</wodle>
```

### Шаг 2: Правила алертинга (Менеджер)

Добавьте правила в `/var/ossec/etc/rules/local_rules.xml` для корреляции событий и обнаружения аномалий.

```xml
<group name="kernel_security,">
  <!-- Детекция модуля без файла на диске (признак rootkit) -->
  <rule id="100302" level="14">
    <decoded_as>json</decoded_as>
    <field name="type">^kernel_module$</field>
    <field name="path">^N/A$</field>
    <description>Kernel module has no on-disk file: $(name) — possible rootkit!</description>
  </rule>

  <!-- Детекция эксплойтов Copy Fail / Dirty Frag (через auditd) -->
  <rule id="100321" level="8">
    <if_sid>80700</if_sid> <!-- Базовое правило auditd -->
    <field name="audit.key">af_alg_socket</field>
    <field name="audit.uid" negate="yes">^0$</field>
    <description>AF_ALG socket created by non-root user (uid=$(audit.uid))</description>
  </rule>

  <!-- Корреляция: AF_ALG + splice от одного процесса -->
  <rule id="100323" level="13" frequency="2" timeframe="5">
    <if_matched_sid>100321</if_matched_sid>
    <same_field>audit.pid</same_field>
    <description>Possible Page-Cache exploit indicator (AF_ALG + splice) pid=$(audit.pid)</description>
  </rule>
</group>
```

## Дополнительная информация

### См. также
- [Харденинг ядра Linux](../../Mechanisms/Kernel/hardening.md) — SCA-политики и параметры безопасности.
- [auditd: аудит системных вызовов](../../SystemAdministration/Logging/auditd.md) — подробные правила аудита.
- [Wazuh: обзор SIEM](../../wazuh.md)
