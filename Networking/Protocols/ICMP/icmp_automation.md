# ICMP: Автоматизация и IaC

## Определения

**Ansible ping module** — встроенный модуль Ansible для проверки доступности управляемого узла. Важно: по умолчанию он проверяет доступность Python на целевом хосте, **не ICMP**.

**Real ICMP check в Ansible** — использование `command`/`shell` модулей с утилитой `ping`, или специализированных коллекций (`community.general.ping`).

**Health Check** — автоматизированная проверка работоспособности сервиса/узла. ICMP часто используется как L3-check в пайплайнах部署 и мониторинга.

## Основные концепции

### Ansible: настоящий ICMP vs встроенный ping

```yaml
# Встроенный модуль (НЕ ICMP):
- name: Проверка доступности узла
  ansible.builtin.ping:
  # → проверяет, что Python доступен на целевом хосте

# Настоящий ICMP ping:
- name: ICMP ping через command
  ansible.builtin.command: ping -c 1 -W 2 {{ inventory_hostname }}
  delegate_to: localhost
  register: icmp_result
  changed_when: false
  failed_when: icmp_result.rc != 0

# Или через community.general.ping:
- name: ICMP ping (коллекция community.general)
  community.general.ping:
    host: "{{ inventory_hostname }}"
    count: 1
    timeout: 2
  delegate_to: localhost
```

### Terraform / Cloud-init и ICMP

В облачных окружениях ICMP часто блокируется Security Groups. При部署 через IaC нужно явно разрешать ICMP.

```hcl
# AWS Security Group (Terraform)
resource "aws_security_group_rule" "allow_icmp" {
  type            = "ingress"
  from_port       = -1
  to_port         = -1
  protocol        = "icmp"
  cidr_blocks     = ["10.0.0.0/8"]
  security_group_id = aws_security_group.web.id
}
```

## Практические сценарии

### 1. Ansible playbook: ICMP мониторинг

```yaml
---
- name: ICMP Health Check
  hosts: webservers
  gather_facts: no
  tasks:
    - name: Ping all hosts from control node
      ansible.builtin.command: ping -c 1 -W 2 {{ item }}
      delegate_to: localhost
      register: ping_result
      loop: "{{ groups['webservers'] }}"
      failed_when: ping_result.rc != 0

    - name: Show results
      ansible.builtin.debug:
        msg: "{{ item.item }} is {{ 'UP' if item.rc == 0 else 'DOWN' }}"
      loop: "{{ ping_result.results }}"

    - name: Fail if any host is down
      ansible.builtin.fail:
        msg: "Some hosts are unreachable!"
      when: ping_result.results | selectattr('rc', 'equalto', 0) | list | length < groups['webservers'] | length
```

### 2. Ansible: TCping (когда ICMP заблокирован)

```yaml
---
- name: TCP port check
  hosts: webservers
  gather_facts: no
  tasks:
    - name: Check TCP port 443
      ansible.builtin.wait_for:
        host: "{{ inventory_hostname }}"
        port: 443
        timeout: 5
        state: started
      delegate_to: localhost
      register: tcp_check

    - name: Fail if port closed
      ansible.builtin.fail:
        msg: "Port 443 closed on {{ inventory_hostname }}"
      when: not tcp_check.elapsed | default(0) > 0
```

### 3. Скрипт для deployment pipeline

```bash
#!/bin/bash
# icmp_health_check.sh — проверка доступности после deployment

TARGETS=("10.0.0.10" "10.0.0.11" "10.0.0.12")
TIMEOUT=2
PACKETS=3

for target in "${TARGETS[@]}"; do
    if ping -c $PACKETS -W $TIMEOUT $target > /dev/null 2>&1; then
        echo "OK: $target is reachable"
    else
        echo "CRITICAL: $target is unreachable"
        exit 1
    fi
done

# Дополнительная проверка: MTU
if ! ping -c 1 -M do -s 1472 10.0.0.10 > /dev/null 2>&1; then
    echo "WARNING: PMTUD issue detected on 10.0.0.10"
fi

exit 0
```

### 4. GitLab CI/CD: ICMP check stage

```yaml
stages:
  - deploy
  - health_check

icmp_health_check:
  stage: health_check
  image: alpine:latest
  script:
    - apk add --no-cache iputils
    - |
      for host in 10.0.0.10 10.0.0.11; do
        if ping -c 1 -W 2 $host; then
          echo "$host is UP"
        else
          echo "$host is DOWN"
          exit 1
        fi
      done
  only:
    - main
```

### 5. Systemd service для автоматического мониторинга

```ini
# /etc/systemd/system/icmp-monitor.service
[Unit]
Description=ICMP Monitor
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/icmp_monitor.sh
User=root

# /etc/systemd/system/icmp-monitor.timer
[Unit]
Description=Run ICMP monitor every 5 minutes

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
```

```bash
#!/bin/bash
# /usr/local/bin/icmp_monitor.sh
TARGETS="10.0.0.1 10.0.0.2 10.0.0.3"
ALERT_WEBHOOK="https://hooks.slack.com/services/XXX"

for target in $TARGETS; do
    if ! ping -c 1 -W 2 $target > /dev/null 2>&1; then
        curl -X POST -H 'Content-type: application/json' \
          --data "{\"text\":\"CRITICAL: $target unreachable\"}" \
          $ALERT_WEBHOOK
    fi
done
```

## Дополнительная информация

*   **[ICMP: Диагностика и безопасность](./icmp_diagnostics_security.md)** — hardening.
*   **[ICMP: Мониторинг в продакшене](./icmp_monitoring.md)** — Blackbox Exporter, Prometheus, Zabbix.
*   **[Ansible документация](https://docs.ansible.com/ansible/latest/collections/ansible/builtin/ping_module.html)** — встроенный ping модуль.
*   **[community.general.ping](https://docs.ansible.com/ansible/latest/collections/community/general/ping_module.html)** — настоящий ICMP ping.
