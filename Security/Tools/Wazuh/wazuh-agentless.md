# Agentless-мониторинг в Wazuh: SSH, сетевые устройства

## Определения

**Agentless-мониторинг** — метод сбора логов и проверки конфигураций удалённых хостов без установки Wazuh-агента. Используется для устройств, куда агент нельзя установить: сетевое оборудование, legacy-системы, appliances, third-party VMs.

**SSH-based Collection** — сбор логов через SSH: Wazuh подключается к удалённому хосту, выполняет команды (grep, cat) и перенаправляет вывод в свою аналитику.

**SNMP Trap** — протокол для получения событий от сетевых устройств (роутеры, switch, firewall). Wazuh может принимать SNMP-трапы через внешний коллектор.

**Syslog Relay** — промежуточный сервер,转发 syslog-сообщения от устройств в Wazuh Manager. Используется для централизованного сбора с network equipment.

**Remote Configuration** — проверка конфигураций удалённых хостов через SSH (diff конфигов, проверка пакетов, статус сервисов).

## Основные концепции

### Сравнение: Agent vs Agentless

| Критерий | С агентом | Agentless |
|:---|:---|:---|
| **Установка** | Требуется доступ | Только SSH/SNMP |
| **Глубина** | Полная (FIM, syscollector) | Ограниченная (логи, команды) |
| **Производительность** | Локальная обработка | Нагрузка на сеть |
| **Безопасность** | mTLS, JWT | SSH-ключи, SNMP v3 |
| **Поддержка ОС** | Linux, Windows, macOS | Любая с SSH/Syslog |
| **Real-time** | Да | Задержка (polling interval) |
| **Использование** | Основной метод | Legacy, appliances |

### Архитектура agentless

```
┌──────────────┐    SSH/Syslog     ┌───────────────┐
│ Network      │──────────────────→│ Wazuh Manager │
│ Device       │                   │               │
└──────────────┘                   │  logcollector  │
                                   │  (remote SSH)  │
┌──────────────┐    SSH            │               │
│ Legacy       │──────────────────→│               │
│ Server       │                   └───────┬───────┘
└──────────────┘                           │
                                           ▼
┌──────────────┐    Syslog/UDP     ┌───────────────┐
│ Firewall     │──────────────────→│ Syslog Relay  │
│ (Cisco ASA)  │                   │ (rsyslog)     │
└──────────────┘                   └───────┬───────┘
                                           │ TCP 1514
                                           ▼
                                   ┌───────────────┐
                                   │ Wazuh Manager │
                                   └───────────────┘
```

## Практические сценарии

### 1. SSH-сбор логов с удалённого Linux-хоста

```xml
<!-- agent.conf на менеджере (agentless monitoring) -->
<ossec_config>
  <!-- SSH-based log collection -->
  <localfile>
    <log_format>syslog</log_format>
    <location>ssh://root@10.0.1.50:/var/log/auth.log</location>
  </localfile>
  <localfile>
    <log_format>syslog</log_format>
    <location>ssh://root@10.0.1.50:/var/log/syslog</location>
  </localfile>

  <!-- Command execution via SSH -->
  <localfile>
    <log_format>full_command</log_format>
    <command>ssh root@10.0.1.50 "ps aux --sort=-%cpu | head -20"</command>
    <frequency>300</frequency>
  </localfile>

  <!-- Remote configuration check -->
  <localfile>
    <log_format>full_command</log_format>
    <command>ssh root@10.0.1.50 "diff /etc/ssh/sshd_config /etc/ssh/sshd_config.baseline"</command>
    <frequency>3600</frequency>
  </localfile>
</ossec_config>
```

### 2. Сбор логов с Cisco IOS/NX-OS через SSH

```xml
<ossec_config>
  <localfile>
    <log_format>syslog</log_format>
    <location>ssh://admin@10.0.0.1:/var/log/messages</location>
  </localfile>

  <!-- Show commands через SSH -->
  <localfile>
    <log_format>full_command</log_format>
    <command>ssh admin@10.0.0.1 "show ip interface brief"</command>
    <frequency>300</frequency>
  </localfile>

  <localfile>
    <log_format>full_command</log_format>
    <command>ssh admin@10.0.0.1 "show interface status"</command>
    <frequency>300</frequency>
  </localfile>
</ossec_config>
```

### 3. Syslog-приём от сетевых устройств

```bash
# Настройка rsyslog на менеджере для приёма syslog от Cisco/Firewall
cat >> /etc/rsyslog.d/wazuh-network.conf << 'EOF'
# Приём syslog на порту 514
module(load="imudp")
input(type="imudp" port="514")

module(load="imtcp")
input(type="imtcp" port="514")

# Маршрутизация в Wazuh
if $fromhost-ip == '10.0.0.0/24' then {
    action(type="omfile" file="/var/log/network-devices.log")
    stop
}
EOF

systemctl restart rsyslog
```

```xml
<!-- Wazuh logcollector: чтение syslog от устройств -->
<ossec_config>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/network-devices.log</location>
  </localfile>
</ossec_config>
```

### 4. SNMP-трапы через внешний коллектор

```bash
# Установка SNMP-коллектора (snmptrapd → Wazuh)
apt install snmp snmpd snmp-mibs-downloader

# Конфигурация snmptrapd
cat > /etc/snmp/snmptrapd.conf << 'EOF'
authCommunity log wazuh_community
traphandle default /usr/local/bin/snmp-to-wazuh.sh
EOF

# Скрипт перенаправления в Wazuh
cat > /usr/local/bin/snmp-to-wazuh.sh << 'SCRIPT'
#!/bin/bash
while read input; do
  logger -t snmp-trap "$input"
done
SCRIPT
chmod +x /usr/local/bin/snmp-to-wazuh.sh
```

```xml
<!-- Wazuh: сбор SNMP-трапов -->
<ossec_config>
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/syslog</location>
  </localfile>
</ossec_config>
```

### 5. Декодер для Cisco Syslog

```xml
<!-- /var/wazuh-manager/etc/decoders/local_decoder.xml -->
<decoder name="cisco-ios">
  <prematch>%SYS-|%LINK-|%LINEPROTO-|%ACCESSLIST-|%IPACCESSLOG-</prematch>
</decoder>

<decoder name="cisco-ios-detail">
  <parent>cisco-ios</parent>
  <regex>%\w+-\d-\w+: %{data}</regex>
  <order>extra_data</order>
</decoder>
```

```xml
<!-- Правило для Cisco событий -->
<group name="cisco,syslog,">
  <rule id="100700" level="3">
    <decoded_as>cisco-ios</decoded_as>
    <description>Cisco IOS event</description>
  </rule>

  <rule id="100701" level="8">
    <decoded_as>cisco-ios</decoded_as>
    <match>%ACCESSLIST-|%IPACCESSLOG-</match>
    <description>Cisco ACL hit: potential security event</description>
    <mitre>
      <id>T1078</id>
    </mitre>
  </rule>

  <rule id="100702" level="10">
    <decoded_as>cisco-ios</decoded_as>
    <match>%SYS-.*-4-CONFIG_I</match>
    <description>Cisco configuration change via CLI</description>
    <mitre>
      <id>T1098</id>
    </mitre>
  </rule>
</group>
```

### 6. Ansible: настройка agentless-сбора

```yaml
---
- name: Configure agentless monitoring
  hosts: wazuh_manager
  become: yes
  vars:
    agentless_hosts:
      - host: "10.0.1.50"
        user: "root"
        key: "/root/.ssh/id_rsa"
        logs:
          - "/var/log/auth.log"
          - "/var/log/syslog"
      - host: "10.0.0.1"
        user: "admin"
        key: "/root/.ssh/id_rsa"
        logs:
          - "/var/log/messages"
  tasks:
    - name: Generate SSH keys for agentless
      command: ssh-keygen -t ed25519 -f /root/.ssh/wazuh_agentless -N ""
      args:
        creates: /root/.ssh/wazuh_agentless

    - name: Deploy agent.conf for agentless hosts
      template:
        src: templates/agentless.conf.j2
        dest: /var/wazuh-manager/etc/groups/agentless/agent.conf
        owner: root
        group: wazuh
        mode: '0640'
      notify: restart wazuh-manager

  handlers:
    - name: restart wazuh-manager
      systemd:
        name: wazuh-manager
        state: restarted
```

```jinja2
{# templates/agentless.conf.j2 #}
<ossec_config>
{% for host in agentless_hosts %}
{% for log in host.logs %}
  <localfile>
    <log_format>syslog</log_format>
    <location>ssh://{{ host.user }}@{{ host.host }}:{{ log }}</location>
  </localfile>
{% endfor %}
{% endfor %}
</ossec_config>
```

### 7. Правила для обнаружения аномалий на agentless-хостах

```xml
<group name="agentless,security,">
  <!-- Аномальный рост нагрузки -->
  <rule id="100800" level="8">
    <decoded_as>full_command</decoded_as>
    <match>ssh://.*10\.0\.1\.50</match>
    <field name="data">cpu.*9[0-9]%|load average: [5-9]</field>
    <description>High CPU detected on agentless host 10.0.1.50</description>
  </rule>

  <!-- Изменение SSH-конфигурации -->
  <rule id="100801" level="10">
    <decoded_as>full_command</decoded_as>
    <match>diff.*sshd_config</match>
    <field name="data">^[<>]</field>
    <description>SSH configuration changed on agentless host</description>
    <mitre>
      <id>T1556</id>
    </mitre>
  </rule>

  <!-- Неизвестный процесс -->
  <rule id="100802" level="8">
    <decoded_as>full_command</decoded_as>
    <match>ssh://.*ps aux</match>
    <field name="data">nc |ncat |socat |cryptominer</field>
    <description>Suspicious process detected on agentless host</description>
    <mitre>
      <id>T1059</id>
    </mitre>
  </rule>
</group>
```

## Дополнительная информация

### Когда использовать agentless

| Сценарий | Рекомендация |
|:---|:---|
| Legacy-серверы (Solaris 10, AIX) | Agentless (SSH) |
| Сетевое оборудование (Cisco, Juniper) | Syslog + SNMP |
| Third-party appliances | Syslog |
| Cloud VMs без возможности установки | Syslog forwarding |
| Временный мониторинг | Agentless (SSH) |
| Production Linux/Windows | **Агент** (всегда) |

### Best Practices

1. **SSH-ключи**: используйте отдельные SSH-ключи для agentless, не root-ключи.
2. **Read-only**: создайте отдельного пользователя с минимальными правами.
3. **Частота**: не чаще 1 раза в 5 минут для SSH-команд (нагрузка на сеть).
4. **Буферизация**: используйте syslog relay для network devices (rsyslog/syslog-ng).
5. **Fallback**: при потере SSH-доступа — алерт в Wazuh.

### Troubleshooting

| Проблема | Причина | Решение |
|:---|:---|:---|
| **SSH connection refused** | Firewall или SSH отключён | Проверьте доступность порта 22 |
| **Permission denied** | Неверный ключ или пользователь | Проверьте authorized_keys на удалённом хосте |
| **Syslog не приходит** | Порт 514 закрыт | Проверьте firewall: `nc -zv host 514` |
| **Дубли событий** | Syslog + agent на одном хосте | Используйте OR-логику, не AND |

### См. также
- [Log Collection](./wazuh-log-collection.md) — настройка лог-коллекции.
- [Кастомные декодеры](./custom-decoders.md) — создание декодеров для network devices.
- [Agent Groups](./wazuh-agent-groups.md) — группировка agentless-хостов.
