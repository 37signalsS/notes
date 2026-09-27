# DNS в CI/CD: автоматическая верификация и smoke-тесты

## Определения

**DNS Smoke Test** — минимальный набор проверок DNS-конфигурации, выполняемых после изменения DNS-записей или развёртывания DNS-сервера. Цель — убедиться, что изменения применены корректно и сервис доступен.

**Pre-deploy DNS Check** — проверка DNS перед деплоем приложения. Убеждается, что необходимые DNS-имена (сервисы, реестры, зависимости) разрешаются корректно из целевого окружения.

**Post-deploy DNS Verification** — проверка DNS после деплоем приложения. Подтверждает, что новые VIP/endpoint'ы зарегистрированы в DNS и доступны для резолвинга.

**DNS Propagation Check** — проверка распространения DNS-изменений на несколько независимых резолверов (публичных и внутренних) для подтверждения консистентности.

> **Примечание:** Концепция DNS-as-Code и автоматизация DNS через Ansible описаны в [DNS Automation](../../../../Ansible/ansible_dns_automation.md).

## Базовые концепции

### Зачем тестировать DNS в CI/CD

| Проблема | Последствие | Как предотвратить |
| :--- | :--- | :--- |
| DNS-запись не создана после деплоем | Сервис недоступен по имени | Post-deploy DNS check |
| Неверный IP в DNS-записи | Трафик идёт на несуществующий сервер | Pre-deploy + Post-deploy проверка |
| TTL слишком высокий | Приложение видит устаревший IP при миграции | Проверка TTL перед деплоем |
| DNS-запись не удалена после demote | Старый IP остаётся в DNS | Cleanup-стадия pipeline |
| Сертификат истёк (ACME/DNS-01) | HTTPS-соединения падают | Проверка TLS перед деплоем |

### Архитектура DNS-проверок в pipeline

```text
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  Code   │────>│  Build   │────>│  Deploy  │────>│  Verify  │
│  Change │     │  Image   │     │  Infra   │     │  DNS     │
└─────────┘     └──────────┘     └──────────┘     └──────────┘
                                       │                │
                                       ▼                ▼
                                  ┌──────────┐   ┌──────────────┐
                                  │  DNS     │   │  DNS Smoke   │
                                  │  Update  │   │  Test        │
                                  │  (API)   │   │  (dig/nslookup)│
                                  └──────────┘   └──────────────┘
```

### Инструменты проверки DNS в pipeline

| Инструмент | Назначение | Где использовать |
| :--- | :--- | :--- |
| `dig +short` | Быстрая проверка IP-адреса | Shell-скрипты, GitHub Actions |
| `nslookup` | Проверка разрешения имени | Windows/Linux pipeline |
| `curl` с `--resolve` | Проверка HTTP-сервиса по DNS-имени | Smoke-тест веб-сервисов |
| `dnspyre` | Нагрузочное тестирование DNS | Performance-тесты |
| `python` + `dnspython` | Программная проверка DNS | Сложные проверки в pipeline |
| `testdns` (custom) | Специализированный тестер | Готовые шаблоны проверок |

## Практические сценарии

### Сценарий 1: GitHub Actions — Post-deploy DNS Verification

```yaml
# .github/workflows/deploy.yml
name: Deploy with DNS Check

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Deploy Infrastructure
        run: |
          terraform apply -auto-approve

      - name: Wait for DNS Propagation
        run: sleep 30

      - name: DNS Verification
        run: |
          # Проверка A-записи
          IP=$(dig +short api.example.com A | head -1)
          if [[ -z "$IP" ]]; then
            echo "ERROR: DNS A record not found"
            exit 1
          fi
          echo "✓ DNS A record: $IP"

          # Проверка доступности сервиса
          HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
            --resolve "api.example.com:443:${IP}" \
            https://api.example.com/health)
          if [[ "$HTTP_CODE" != "200" ]]; then
            echo "ERROR: HTTP health check failed ($HTTP_CODE)"
            exit 1
          fi
          echo "✓ HTTP health check: $HTTP_CODE"

      - name: Multi-resolver Check
        run: |
          for resolver in 8.8.8.8 1.1.1.1 9.9.9.9; do
            IP=$(dig +short @"$resolver" api.example.com A | head -1)
            echo "Resolver $resolver → $IP"
            if [[ "$IP" != "10.0.1.10" ]]; then
              echo "ERROR: Unexpected IP from $resolver"
              exit 1
            fi
          done
```

### Сценарий 2: Bash-скрипт — DNS Smoke Test для Kubernetes

```bash
#!/bin/bash
# dns_smoke_test.sh — проверка DNS после деплоя в Kubernetes

set -euo pipefail

NAMESPACE="${1:-production}"
SERVICES=("api" "web" "grpc" "worker")
EXPECTED_IPS=("10.96.0.10" "10.96.0.11" "10.96.0.12" "10.96.0.13")
COREDNS_IP="10.96.0.10"
TIMEOUT=5

echo "=== DNS Smoke Test for namespace: $NAMESPACE ==="

# 1. Проверка CoreDNS
echo -n "CoreDNS availability: "
if kubectl exec -n "$NAMESPACE" test-pod -- nslookup kubernetes.default.svc.cluster.local "$COREDNS_IP" > /dev/null 2>&1; then
  echo "✓ OK"
else
  echo "✗ FAIL"
  exit 1
fi

# 2. Проверка каждого сервиса
for i in "${!SERVICES[@]}"; do
  SERVICE="${SERVICES[$i]}"
  EXPECTED="${EXPECTED_IPS[$i]}"

  echo -n "Service $SERVICE: "
  RESOLVED=$(kubectl exec -n "$NAMESPACE" test-pod -- \
    nslookup "${SERVICE}.${NAMESPACE}.svc.cluster.local" 2>/dev/null | \
    grep "Address:" | tail -1 | awk '{print $2}')

  if [[ "$RESOLVED" == "$EXPECTED" ]]; then
    echo "✓ $RESOLVED"
  else
    echo "✗ Expected $EXPECTED, got $RESOLVED"
    exit 1
  fi
done

# 3. Проверка TTL
echo -n "TTL check: "
TTL=$(dig +noall +answer "${SERVICES[0]}.${NAMESPACE}.svc.cluster.local" | awk '{print $2}')
if [[ "$TTL" -le 300 ]]; then
  echo "✓ TTL=$TTL"
else
  echo "⚠ TTL=$TTL (may be too high for quick failover)"
fi

echo "=== All DNS checks passed ==="
```

### Сценарий 3: Ansible — DNS-as-Code с валидацией

```yaml
---
# dns_update_playbook.yml — обновление DNS-записей с проверкой
- name: Update DNS records
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    dns_records:
      - name: "api.example.com"
        type: "A"
        value: "10.0.1.10"
        ttl: 300
      - name: "www.example.com"
        type: "CNAME"
        value: "api.example.com"
        ttl: 300
  tasks:
    - name: Apply DNS changes via PowerDNS API
      ansible.builtin.uri:
        url: "http://dns.internal:8081/api/v1/servers/localhost/zones/example.com."
        method: PATCH
        headers:
          X-API-Key: "{{ vault_pdns_api_key }}"
        body_format: json
        body:
          rrsets:
            - name: "{{ item.name }}"
              type: "{{ item.type }}"
              ttl: "{{ item.ttl }}"
              records:
                - content: "{{ item.value }}"
                  disabled: false
      loop: "{{ dns_records }}"

    - name: Wait for DNS propagation
      ansible.builtin.pause:
        seconds: 10

    - name: Verify DNS records
      ansible.builtin.shell: |
        dig +short +timeout=5 {{ item.name }} {{ item.type }}
      register: dns_result
      loop: "{{ dns_records }}"
      until: dns_result.stdout == item.value
      retries: 5
      delay: 5

    - name: Report results
      ansible.builtin.debug:
        msg: "✓ {{ item.item.name }} → {{ item.stdout }}"
      loop: "{{ dns_result.results }}"
      loop_control:
        label: "{{ item.item.name }}"
```

### Сценарий 4: Python-скрипт — Комплексная проверка DNS

```python
#!/usr/bin/env python3
"""dns_health_check.py — комплексная проверка DNS для CI/CD"""

import subprocess
import sys
import json
from dataclasses import dataclass

@dataclass
class DNSCheck:
    name: str
    record_type: str
    expected: str
    resolver: str = "8.8.8.8"

def run_dig(check: DNSCheck) -> str:
    """Выполнить dig-запрос и вернуть ответ."""
    cmd = [
        "dig", f"@{check.resolver}", check.name,
        check.record_type, "+short", "+timeout=3", "+tries=1"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    return result.stdout.strip()

def verify_dns(checks: list[DNSCheck]) -> bool:
    """Проверить список DNS-записей."""
    all_passed = True
    for check in checks:
        response = run_dig(check)
        if response == check.expected:
            print(f"✓ {check.name} ({check.record_type}) → {response}")
        else:
            print(f"✗ {check.name} ({check.record_type}): expected {check.expected}, got {response}")
            all_passed = False
    return all_passed

if __name__ == "__main__":
    checks = [
        DNSCheck("api.example.com", "A", "10.0.1.10"),
        DNSCheck("api.example.com", "AAAA", "2001:db8::1"),
        DNSCheck("mail.example.com", "MX", "mail.example.com."),
        DNSCheck("example.com", "TXT", '"v=spf1 include:_spf.google.com ~all"'),
    ]

    if verify_dns(checks):
        print("\n=== All DNS checks passed ===")
        sys.exit(0)
    else:
        print("\n=== DNS checks FAILED ===")
        sys.exit(1)
```

### Сценарий 5: Pre-deploy DNS Check перед деплоем Helm-чарта

```yaml
# .gitlab-ci.yml — Pre-deploy DNS check
stages:
  - precheck
  - deploy
  - verify

pre-dns-check:
  stage: precheck
  image: alpine:3.19
  script:
    - apk add --no-cache bind-tools curl
    - |
      # Проверка что целевой кластер доступен по DNS
      DOMAIN="k8s-prod.company.com"
      IP=$(dig +short $DOMAIN A)
      if [ -z "$IP" ]; then
        echo "ERROR: Cannot resolve $DOMAIN"
        exit 1
      fi
      # Проверка что реестр контейнеров доступен
      REGISTRY="registry.company.com"
      REGISTRY_IP=$(dig +short $REGISTRY A)
      if [ -z "$REGISTRY_IP" ]; then
        echo "ERROR: Cannot resolve $REGISTRY"
        exit 1
      fi
      echo "Pre-deploy DNS checks passed"
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### Сценарий 6: Проверка TTL перед миграцией

```bash
#!/bin/bash
# check_ttl.sh — проверка TTL перед миграцией сервиса
# Перед миграцией TTL должен быть снижен до минимального значения

DOMAIN="api.example.com"
MAX_TTL=60  # Максимально допустимый TTL перед миграцией

CURRENT_TTL=$(dig +noall +answer "$DOMAIN" | awk '{print $2}')
echo "Current TTL for $DOMAIN: $CURRENT_TTL"

if [ "$CURRENT_TTL" -gt "$MAX_TTL" ]; then
  echo "WARNING: TTL ($CURRENT_TTL) is higher than $MAX_TTL"
  echo "Recommendation: Lower TTL to $MAX_TTL at least 24h before migration"
  echo "This ensures clients will pick up the new IP within $MAX_TTL seconds"
  exit 1
fi

echo "✓ TTL is acceptable for migration"
```

## Best Practices

### По интеграции в pipeline

1. **Добавляйте DNS-проверки как отдельный stage** — после деплоя инфраструктуры, перед переключением трафика.
2. **Проверяйте несколько резолверов** — не только публичные (8.8.8.8), но и внутренние.
3. **Учитывайте propagation delay** — добавляйте `sleep 30` или retry-логику после изменений DNS.
4. **Проверяйте не только IP, но и HTTP** — используйте `curl --resolve` для end-to-end проверки.

### По TTL перед миграцией

1. **Снижайте TTL за 24–48 часов** до миграции (минимум до 60 секунд).
2. **После миграции** верните TTL к нормальному значению.
3. **Мониторьте старые IP** — убедитесь, что трафик на них упал до нуля.

### По DNS-as-Code

1. **Храните DNS-записи в Git** — версионируйте изменения через pull requests.
2. **Используйте Terraform/Ansible** для управления DNS вместо ручных изменений.
3. **Включайте валидацию** в pipeline — `named-checkzone`, `dig +short`, HTTP health checks.
4. **Используйте separated environments** — dev/staging/prod с разными DNS-записями.

### По мониторингу после деплоя

1. **Настройте blackbox-мониторинг** через Prometheus + Blackbox Exporter для DNS.
2. **Алерты при SERVFAIL** — أي SERVFAIL после деплоем указывает на проблему.
3. **Отслеживайте cache hit ratio** — резкое снижение указывает на проблему с TTL.

## Дополнительная информация

- [DNS Automation: PowerDNS, Route53, CloudFlare](../../../../Ansible/ansible_dns_automation.md) — автоматизация DNS через Ansible.
- [BIND: Автоматизация управления (IaC)](../../../../Linux/Networking/Services/BIND/automation-iac.md) — Ansible для BIND.
- [Мониторинг DNS](../../../../Networking/Protocols/DNS/dns_monitoring.md) — Prometheus, Grafana, алерты.
- [Тестирование производительности DNS](../../../../Networking/Protocols/DNS/dns_performance_testing.md) — бенчмаркинг.
- [Базовая диагностика DNS](./basic_diagnostics.md) — общий алгоритм поиска неисправностей.
- [Диагностика DNS-серверов](./dns_server_diagnostics.md) — проблемы серверов BIND/Unbound/CoreDNS.
- [Диагностика безопасности DNS](./dns_security_diagnostics.md) — DNSSEC, DoH/DoT, DDoS.
