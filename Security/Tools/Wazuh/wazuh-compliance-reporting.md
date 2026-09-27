# Compliance Reporting в Wazuh: PCI-DSS, GDPR, HIPAA

## Определения

**Compliance Reporting** — процесс генерации отчётов, подтверждающих соответствие инфраструктуры требованиям нормативных стандартов (PCI-DSS, GDPR, HIPAA, NIST, CIS). Wazuh 5.0 предоставляет встроенные SCA-политики и API для автоматической генерации отчётов.

**SCA (Security Configuration Assessment)** — модуль Wazuh для проверки конфигураций хостов по стандартам (CIS Benchmark, PCI-DSS, GDPR). Генерирует pass/fail результаты для каждого контроля.

**CIS Benchmark** — набор рекомендаций по настройке безопасности от Center for Internet Security. Wazuh содержит встроенные политики для Linux, Windows, PostgreSQL, Nginx.

**Control** — единица проверки в SCA-политике. Каждый контроль проверяет конкретный аспект конфигурации (например, "SSH Root Login disabled").

## Основные концепции

### Комплаенс-стек Wazuh

```
┌──────────────────────────────────────────┐
│          Compliance Dashboards            │
│  (OpenSearch Dashboards / Custom Reports)│
└──────────────────┬───────────────────────┘
                   │
┌──────────────────┴───────────────────────┐
│         SCA Engine (Wazuh 5.0)           │
│  CIS Benchmarks | PCI-DSS | GDPR | HIPAA│
└──────────────────┬───────────────────────┘
                   │
┌──────────────────┴───────────────────────┐
│        Agent-level Checks                │
│  SSH | Apache | PostgreSQL | Windows     │
└──────────────────┬───────────────────────┘
                   │
┌──────────────────┴───────────────────────┐
│        OpenSearch Index                  │
│  wazuh-sca-* indices                     │
└──────────────────────────────────────────┘
```

### Соответствие стандартам

| Стандарт | Описание | Wazuh-модуль | Ключевые контрольы |
|:---|:---|:---|:---|
| **PCI-DSS v4.0** | Безопасность платёжных данных | SCA + FIM + Rules | Access control, logging, encryption |
| **GDPR** | Защита персональных данных ЕС | SCA + FIM | Data protection, audit trails |
| **HIPAA** | Медицинские данные (USA) | SCA + Rules | Access control, integrity, audit |
| **NIST CSF** | Фреймворк кибербезопасности | SCA + Rules + FIM | Identify, Protect, Detect, Respond |
| **CIS Benchmark** | Стандарты настройки ОС/ПО | SCA | Hardening checks |

## Практические сценарии

### 1. Включение SCA-политики PCI-DSS

```xml
<!-- agent.conf для группы pci-servers -->
<ossec_config>
  <policy>
    <enabled>yes</enabled>
    <scan_on_start>yes</scan_on_start>
    <interval>12h</interval>
    <policies>
      <!-- CIS Benchmark for Linux -->
      <policy>/var/ossec/etc/sca/cis_debian_linux.yml</policy>
      <!-- PCI-DSS specific -->
      <policy>/var/ossec/etc/sca/pci_dss.yml</policy>
    </policies>
  </policy>
</ossec_config>
```

### 2. Результаты SCA через API

```bash
#!/bin/bash
API="https://localhost:55000"
TOKEN=$(curl -sk -X POST "$API/security/user/authenticate" \
  -d '{"username":"admin","password":"AdminPass123"}' | jq -r '.data.token')

# Все failed checks для конкретного агента
curl -sk "$API/sca/001?select=name,pass,fail,invalid" \
  -H "Authorization: Bearer $TOKEN" | jq '.data.affected_items[]'

# Все агенты с failed PCI-DSS checks
for AGENT_ID in $(curl -sk "$API/agents?status=active&select=id" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.data.affected_items[].id'); do

  RESULT=$(curl -sk "$API/sca/$AGENT_ID?select=pass,fail,policy_id" \
    -H "Authorization: Bearer $TOKEN" | jq '.data.affected_items[0]')

  FAIL=$(echo "$RESULT" | jq -r '.fail')
  POLICY=$(echo "$RESULT" | jq -r '.policy_id')

  if [ "$FAIL" -gt 0 ] && [ "$POLICY" = "pci_dss" ]; then
    AGENT_NAME=$(curl -sk "$API/agents/$AGENT_ID?select=name" \
      -H "Authorization: Bearer $TOKEN" | jq -r '.data.affected_items[0].name')
    echo "FAIL: $AGENT_NAME (ID:$AGENT_ID) - $FAIL failed checks"
  fi
done
```

### 3. CSV-отчёт для аудиторов

```python
#!/usr/bin/env python3
"""Генерация CSV-отчёта SCA для аудита PCI-DSS."""
import requests
import csv
from datetime import datetime

API = "https://localhost:55000"
token = requests.post(
    f"{API}/security/user/authenticate",
    json={"username": "admin", "password": "AdminPass123"},
    verify=False
).json()["data"]["token"]
headers = {"Authorization": f"Bearer {token}"}

# Получение всех агентов
agents = requests.get(f"{API}/agents?status=active&select=id,name,ip,group",
                       headers=headers, verify=False).json()["data"]["affected_items"]

# Генерация отчёта
report_date = datetime.now().strftime("%Y-%m-%d_%H-%M")
with open(f"/tmp/sca_pci_dss_report_{report_date}.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Agent Name", "Agent IP", "Group", "Policy", "Passed", "Failed", "Invalid", "Score %"])

    for agent in agents:
        sca = requests.get(
            f"{API}/sca/{agent['id']}",
            headers=headers, verify=False
        ).json()["data"]["affected_items"]

        for check in sca:
            total = check.get("pass", 0) + check.get("fail", 0)
            score = (check.get("pass", 0) / total * 100) if total > 0 else 0
            writer.writerow([
                agent.get("name"),
                agent.get("ip"),
                agent.get("group", "default"),
                check.get("policy_id"),
                check.get("pass"),
                check.get("fail"),
                check.get("invalid"),
                f"{score:.1f}"
            ])

print(f"Отчёт: /tmp/sca_pci_dss_report_{report_date}.csv")
```

### 4. Дашборд PCI-DSS в OpenSearch Dashboards

```json
// Сохранённый запрос для визуализации PCI-DSS compliance
{
  "attributes": {
    "title": "PCI-DSS Compliance Overview",
    "visState": {
      "title": "SCA Pass/Fail by Agent",
      "aggs": [
        {
          "id": "1",
          "enabled": true,
          "type": "terms",
          "params": {
            "field": "data.sca.check.result",
            "size": 10,
            "order": "desc",
            "orderBy": "1"
          },
          "schema": "segment"
        },
        {
          "id": "2",
          "enabled": true,
          "type": "count",
          "schema": "metric"
        }
      ],
      "params": {
        "type": "pie",
        "addTooltip": true,
        "addLegend": true,
        "legendPosition": "right"
      }
    }
  }
}
```

### 5. Автоматический compliance-отчёт через CronJob

```yaml
# Ansible: еженедельный отчёт
---
- name: Weekly compliance report
  hosts: wazuh_manager
  become: yes
  tasks:
    - name: Deploy compliance report script
      copy:
        src: files/compliance_report.py
        dest: /var/wazuh-manager/integrations/compliance_report.py
        mode: '0755'

    - name: Schedule weekly report
      cron:
        name: "Wazuh compliance report"
        minute: "0"
        hour: "6"
        day: "1"  # Понедельник
        job: "python3 /var/wazuh-manager/integrations/compliance_report.py --policy pci_dss --email security@company.com"
```

```python
#!/usr/bin/env python3
"""Еженедельный compliance-отчёт с отправкой по email."""
import argparse
import requests
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

def generate_report(policy, api_url, token):
    headers = {"Authorization": f"Bearer {token}"}

    # Агенты с failed checks
    agents = requests.get(f"{api_url}/agents?status=active", headers=headers, verify=False).json()["data"]["affected_items"]

    report = []
    for agent in agents:
        sca = requests.get(f"{api_url}/sca/{agent['id']}", headers=headers, verify=False).json()["data"]["affected_items"]
        for check in sca:
            if check.get("fail", 0) > 0:
                report.append({
                    "agent": agent["name"],
                    "ip": agent["ip"],
                    "policy": check.get("policy_id"),
                    "passed": check.get("pass"),
                    "failed": check.get("fail"),
                    "score": f"{check.get('pass',0)/(check.get('pass',0)+check.get('fail',0))*100:.1f}%"
                })

    return report

def send_email(report, policy, to_email):
    msg = MIMEMultipart()
    msg["Subject"] = f"Wazuh Compliance Report - {policy} - {datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = "wazuh@company.com"
    msg["To"] = to_email

    html = f"<h2>Compliance Report: {policy}</h2>"
    html += f"<p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>"
    html += "<table border='1' cellpadding='5'><tr><th>Agent</th><th>IP</th><th>Passed</th><th>Failed</th><th>Score</th></tr>"
    for r in report:
        html += f"<tr><td>{r['agent']}</td><td>{r['ip']}</td><td>{r['passed']}</td><td>{r['failed']}</td><td>{r['score']}</td></tr>"
    html += "</table>"

    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP("localhost") as s:
        s.send_message(msg)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default="pci_dss")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    API = "https://localhost:55000"
    token = requests.post(f"{API}/security/user/authenticate",
                          json={"username": "admin", "password": "AdminPass123"},
                          verify=False).json()["data"]["token"]

    report = generate_report(args.policy, API, token)
    send_email(report, args.policy, args.email)
    print(f"Report sent to {args.email} with {len(report)} findings")
```

### 6. SCA-политика для GDPR

```yaml
# custom_gdpr_policy.yml
policy:
  name: "GDPR Data Protection Checks"
  description: "Checks for GDPR Article 32 - Security of Processing"
  references:
    - https://gdpr-info.eu/art-32-gdpr/

checks:
  - id: 1001
    title: "Encryption at rest enabled"
    description: "Verify disk encryption is active"
    command: "dmsetup ls --target crypt"
    result: "not expected"
    remediation: "Enable LUKS encryption on data partitions"
    compliance:
      - pci_dss: ["3.4"]
      - gdpr: ["32.1.a"]

  - id: 1002
    title: "Audit logging enabled"
    description: "Verify auditd is running and configured"
    command: "systemctl is-active auditd"
    result: "expected"
    remediation: "Install and enable auditd: apt install auditd && systemctl enable auditd"
    compliance:
      - pci_dss: ["10.1"]
      - gdpr: ["32.1.d"]

  - id: 1003
    title: "SSH key-based authentication"
    description: "Verify password authentication is disabled for SSH"
    regex: "^PasswordAuthentication\s+no"
    regex_file: "/etc/ssh/sshd_config"
    result: "expected"
    remediation: "Set PasswordAuthentication no in /etc/ssh/sshd_config"
    compliance:
      - pci_dss: ["2.1"]
      - gdpr: ["32.1.a"]
```

## Дополнительная информация

### Best Practices

1. **Автоматизация**: запускайте SCA каждые 12 часов, а не раз в неделю.
2. **Remediation**: используйте Active Response для автоматического исправления.
3. **Baseline**: сохраняйте baseline результатов для сравнения между аудитами.
4. **Documentation**: каждый failed check должен иметь remediation step.
5. **Integration**: экспортируйте результаты в тикет-систему (Jira, ServiceNow).

### Частые failed checks (PCI-DSS)

| Контроль | Описание | Remediation |
|:---|:---|:---|
| 1.1.6 | Нет ненужных сервисов | Удалите неиспользуемые сервисы |
| 2.1 |弱 SSH пароли | Отключите password auth, используйте ключи |
| 3.4 | Нет шифрования данных | Включите LUKS/dm-crypt |
| 10.1 | Нет аудита | Включите auditd |
| 10.2 | Нет логирования | Настройте rsyslog + Wazuh |
| 11.1 | Нет сканирования | Настройте vulnerability detection |

### См. также
- [SCA](./wazuh-sca.md) — создание SCA-политик.
- [FIM](./wazuh-fim.md) — мониторинг критических файлов.
- [Vulnerability Detection](./wazuh-vulnerability-detector.md) —CVE-проверки.
