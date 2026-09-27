# Active Response в Wazuh: автоматическое реагирование

## Определения

**Active Response** — механизм Wazuh для автоматического выполнения действий при срабатывании правил: блокировка IP, отключение пользователя, quarantine файла, обновление firewall-правил. В **Wazuh 5.0** поддерживает скрипты на bash/python и интеграцию с внешними системами (Firewall, Ansible).

**Command** — исполняемый скрипт в директории `/var/wazuh-manager/active-response/bin/`. Принимает JSON через stdin с данными о событии (IP, пользователь, агент).

**Timeout** — период блокировки (в секундах). Если timeout=0 — действие необратимое (требует ручного undo).

**Local vs Agent** — local: команда выполняется на менеджере (IP blocking на менеджере); agent: команда выполняется на целевом агенте (kill process, lock user).

## Основные концепции

### Архитектура Active Response

```
Событие → Rule (level >= 10)
  │
  ▼
Active Response Config (ossec.conf)
  │
  ▼
Command Script (/active-response/bin/)
  │
  ├── firewall-drop.sh   → iptables -A INPUT -s <IP> -j DROP
  ├── host-deny.sh       → echo "IP" >> /etc/hosts.deny
  ├── kill-process.sh    → kill -9 <PID>
  ├── disable-user.sh    → usermod -L <USER>
  └── custom-script.sh   → ваш скрипт
```

### Типы Active Response

| Тип | Действие | Пример |
|:---|:---|:---|
| **IP Blocking** | Блокировка IP через firewall | `firewall-drop.sh` |
| **Host Deny** | Блокировка в hosts.deny | `host-deny.sh` |
| **Process Kill** | Завершение процесса | `kill-process.sh` |
| **User Lock** | Блокировка учётной записи | `disable-user.sh` |
| **Custom** | Любой скрипт | Интеграция с SOAR |

## Практические сценарии

### 1. firewall-drop.sh — блокировка IP

```bash
#!/bin/bash
# /var/wazuh-manager/active-response/bin/firewall-drop.sh
# Блокировка IP-адреса через iptables

SRCIP=$(cat $1 | jq -r .data.srcip)
ACTION=$(cat $1 | jq -r .action)
LOG_FILE="/var/log/wazuh-active-response.log"

if [ -z "$SRCIP" ] || [ "$SRCIP" = "null" ]; then
  exit 0
fi

case "$ACTION" in
  add)
    if ! iptables -C INPUT -s "$SRCIP" -j DROP 2>/dev/null; then
      iptables -A INPUT -s "$SRCIP" -j DROP
      echo "$(date) - ADD: Blocked $SRCIP" >> "$LOG_FILE"
    fi
    ;;
  delete)
    iptables -D INPUT -s "$SRCIP" -j DROP 2>/dev/null
    echo "$(date) - DELETE: Unblocked $SRCIP" >> "$LOG_FILE"
    ;;
esac

exit 0
```

```bash
chmod +x /var/wazuh-manager/active-response/bin/firewall-drop.sh
chown root:wazuh /var/wazuh-manager/active-response/bin/firewall-drop.sh
```

### 2. disable-user.sh — блокировка пользователя

```bash
#!/bin/bash
# /var/wazuh-manager/active-response/bin/disable-user.sh

USER=$(cat $1 | jq -r .data.win.system.user)
ACTION=$(cat $1 | jq -r .action)
LOG_FILE="/var/log/wazuh-active-response.log"

if [ -z "$USER" ] || [ "$USER" = "null" ] || [ "$USER" = "root" ]; then
  exit 0
fi

case "$ACTION" in
  add)
    if ! grep -q "^${USER}:!" /etc/shadow 2>/dev/null; then
      usermod -L "$USER"
      echo "$(date) - ADD: Locked user $USER" >> "$LOG_FILE"
    fi
    ;;
  delete)
    usermod -U "$USER" 2>/dev/null
    echo "$(date) - DELETE: Unlocked user $USER" >> "$LOG_FILE"
    ;;
esac

exit 0
```

### 3. kill-process.sh — завершение вредоносного процесса

```bash
#!/bin/bash
# /var/wazuh-manager/active-response/bin/kill-process.sh

PID=$(cat $1 | jq -r .data.win.system.processId)
PROC_NAME=$(cat $1 | jq -r .data.win.eventdata.newProcessName)
LOG_FILE="/var/log/wazuh-active-response.log"

if [ -z "$PID" ] || [ "$PID" = "null" ] || [ "$PID" = "0" ]; then
  exit 0
fi

# Проверка что процесс опасный
DANGEROUS_PROCS="mimikatz|nc |ncat |socat |cryptominer|cobalt"
if echo "$PROC_NAME" | grep -qiE "$DANGEROUS_PROCS"; then
  kill -9 "$PID" 2>/dev/null
  echo "$(date) - KILL: Killed process $PROC_NAME (PID:$PID)" >> "$LOG_FILE"
fi

exit 0
```

### 4. ossec.conf: настройка Active Response

```xml
<ossec_config>
  <!-- Блокировка IP при brute-force SSH -->
  <active-response>
    <command>firewall-drop</command>
    <location>local</location>
    <rules_id>5720</rules_id>
    <timeout>600</timeout>
  </active-response>

  <!-- Блокировка IP при множественных failed logins -->
  <active-response>
    <command>firewall-drop</command>
    <location>local</location>
    <rules_id>100500</rules_id>
    <timeout>3600</timeout>
  </active-response>

  <!-- Блокировка IP при обнаружении backdoor -->
  <active-response>
    <command>firewall-drop</command>
    <location>local</location>
    <rules_id>100100</rules_id>
    <timeout>0</timeout>
  </active-response>

  <!-- Отключение пользователя при compromised credentials -->
  <active-response>
    <command>disable-user</command>
    <location>local</location>
    <rules_id>100505</rules_id>
    <timeout>0</timeout>
  </active-response>
</ossec_config>
```

### 5. Правила для триггеров Active Response

```xml
<group name="active_response,">
  <!-- SSH Brute Force → IP Block -->
  <rule id="5720" level="10" frequency="5" timeframe="360">
    <if_matched_sid>5716</if_matched_sid>
    <same_source_ip />
    <description>SSH brute force detected - IP will be blocked</description>
  </rule>

  <!-- Failed login from external IP -->
  <rule id="100600" level="10" frequency="3" timeframe="300">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4625</field>
    <same_field>data.win.eventdata.ipAddress</same_field>
    <description>Multiple failed logins - IP will be blocked</description>
  </rule>

  <!-- Suspicious process → Kill -->
  <rule id="100601" level="15">
    <decoded_as>json</decoded_as>
    <field name="data.win.eventdata.originalFileName">(?i)(mimikatz|sekurlsa)</field>
    <description>CRITICAL: Mimikatz detected - process will be killed</description>
  </rule>

  <!-- Compromised user → Lock -->
  <rule id="100602" level="12">
    <decoded_as>json</decoded_as>
    <field name="data.win.system.channel">Security</field>
    <field name="data.win.system.eventID">4624</field>
    <field name="data.win.eventdata.logonType">9</field>
    <field name="data.win.eventdata.authenticationPackage">NTLM</field>
    <description>Potential pass-the-hash - user will be locked</description>
  </rule>
</group>
```

### 6. Интеграция Active Response с iptables/nftables

```bash
#!/bin/bash
# /var/wazuh-manager/active-response/bin/firewall-nft.sh
# Современный вариант для nftables

SRCIP=$(cat $1 | jq -r .data.srcip)
ACTION=$(cat $1 | jq -r .action)
CHAIN="wazuh_blocklist"

# Создание цепочки если не существует
nft list chain inet filter $CHAIN 2>/dev/null || \
  nft add chain inet filter $CHAIN

case "$ACTION" in
  add)
    nft add rule inet filter $CHAIN ip saddr "$SRCIP" drop
    echo "$(date) - nftables: Blocked $SRCIP" >> /var/log/wazuh-active-response.log
    ;;
  delete)
    nft delete rule inet filter $CHAIN handle $(nft -a list chain inet filter $CHAIN | \
      grep "$SRCIP" | awk '{print $NF}') 2>/dev/null
    echo "$(date) - nftables: Unblocked $SRCIP" >> /var/log/wazuh-active-response.log
    ;;
esac
```

### 7. Ansible: деплой Active Response скриптов

```yaml
---
- name: Deploy Active Response scripts
  hosts: wazuh_managers
  become: yes
  tasks:
    - name: Copy Active Response scripts
      copy:
        src: "files/active-response/{{ item }}"
        dest: "/var/wazuh-manager/active-response/bin/{{ item }}"
        owner: root
        group: wazuh
        mode: '0755'
      loop:
        - firewall-drop.sh
        - disable-user.sh
        - kill-process.sh

    - name: Configure Active Response in ossec.conf
      blockinfile:
        path: /var/wazuh-manager/etc/ossec.conf
        marker: "# {mark} ACTIVE RESPONSE"
        block: |
          <active-response>
            <command>firewall-drop</command>
            <location>local</location>
            <rules_id>5720</rules_id>
            <timeout>600</timeout>
          </active-response>
      notify: restart wazuh-manager

  handlers:
    - name: restart wazuh-manager
      systemd:
        name: wazuh-manager
        state: restarted
```

### 8. Undo: разблокировка IP

```bash
#!/bin/bash
# /var/wazuh-manager/active-response/bin/firewall-undo.sh
# Разблокировка IP после timeout

# Все заблокированные IP
BLOCKED=$(iptables -L INPUT -n | grep DROP | awk '{print $4}')

for IP in $BLOCKED; do
  # Проверка времени блокировки (лог)
  LAST_BLOCK=$(grep "ADD: Blocked $IP" /var/log/wazuh-active-response.log | tail -1 | awk '{print $1, $2, $3}')
  if [ -n "$LAST_BLOCK" ]; then
    BLOCK_EPOCH=$(date -d "$LAST_BLOCK" +%s 2>/dev/null || date -j -f "%b %d %T %Y" "$LAST_BLOCK" +%s 2>/dev/null)
    NOW_EPOCH=$(date +%s)
    ELAPSED=$(( NOW_EPOCH - BLOCK_EPOCH ))

    # Разблокировка после timeout (600 сек по умолчанию)
    if [ "$ELAPSED" -gt 600 ]; then
      iptables -D INPUT -s "$IP" -j DROP 2>/dev/null
      echo "$(date) - UNDO: Unblocked $IP after ${ELAPSED}s" >> /var/log/wazuh-active-response.log
    fi
  fi
done
```

## Дополнительная информация

### Best Practices

1. **Canary**: сначала тестируйте Active Response на 1% агентов.
2. **Whitelist**: всегда создавайте белые списки (VPN, monitoring IPs).
3. **Logging**: логируйте каждое действие в отдельный файл.
4. **Timeout**: для IP blocking используйте timeout 600–3600 сек.
5. **Undo**: всегда имейте скрипт разблокировки.
6. **Monitoring**: мониторьте Active Response через отдельные правила (log每 action).
7. **Ограничение**: не более 3 Active Response правил на агент (performance).

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **IP не блокируется** | Нет прав iptables | Запустите от root |
| **Двойная блокировка** | Два правила на один IP | Проверьте `iptables -L INPUT -n` |
| **Active Response не срабатывает** | Правило не триггерится | Проверьте `wazuh-logtest` |
| **Все IP блокируются** | Слишком широкое правило | Добавьте whitelist в скрипт |

### См. также
- [Правила](./wazuh-rules.md) — настройка триггеров.
- [FIM](./wazuh-fim.md) — Active Response для файловых изменений.
- [Health Monitoring](./wazuh-health-monitoring.md) — мониторинг Active Response.
