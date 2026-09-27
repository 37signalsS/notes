# Мониторинг сертификатов Traefik: expiration, ACME, proactive alerts

## Определения

**Certificate expiration monitoring** — proactive проверка срока действия TLS-сертификатов с алертингом до истечения.

**ACME renewal** — автоматическое продление сертификатов Traefik за 30 дней до истечения.

**Certificate transparency log** — публичный журнал выданных сертификатов, используемый для отслеживания.

**Self-signed certificate** — самоподписанный сертификат, используемый как fallback при отсутствии ACME-сертификата.

## Базовые концепции

### Жизненный цикл сертификата Traefik

1. **Выпуск**: Traefik получает сертификат через ACME (Let's Encrypt, ZeroSSL).
2. **Хранение**: Сертификат сохраняется в `acme.json`.
3. **Автопродление**: Traefik начинает продление за 30 дней до истечения.
4. **Истечение**: Если продление не удалось — сертификат становится недействительным.

### ACME storage

- `acme.json` — JSON-файл с сертификатами и приватными ключами.
- Права доступа: строго `600`, владелец — процесс Traefik.
- Не может быть разделен между несколькими инстансами Traefik (конфликт записи).

### Проблемы автоматического продления

- ACME rate limit Let's Encrypt (50 сертификатов на домен в неделю).
- Отсутствие внешнего monitoring может привести к пропуску продления.
- При отказе Traefik продление не происходит — нужен внешний watchdog.

## Практические сценарии

### Сценарий 1: Проверка срока действия через API

```bash
# Получить список сертификатов
curl -s http://localhost:8080/api/rawdata | jq '.tls.certificates'

# Проверить конкретный домен
curl -s https://app.example.com | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -dates
# → notBefore=...
# → notAfter=...

# Проверить через openssl
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -enddate -subject
# → notAfter=...
```

### Сценарий 2: Proactive monitoring через CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: traefik-cert-check
  namespace: traefik
spec:
  schedule: "0 6 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: cert-check
            image: alpine:latest
            command:
            - /bin/sh
            - -c
            - |
              apk add --no-cache openssl curl jq
              # Проверяем все домены через API
              curl -s http://traefik:8080/api/rawdata | jq -r '.tls.certificates[] | .certificate.domains[0] as $domain | .certificate.notAfter' | while read expiry; do
                expiry_epoch=$(date -d "$expiry" +%s)
                now_epoch=$(date +%s)
                days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
                echo "$days_left days left"
                if [ "$days_left" -lt 30 ]; then
                  echo "ALERT: Certificate expires in $days_left days"
                  # Отправка алерта (webhook, Slack, email)
                  curl -X POST -H 'Content-type: application/json' \
                    --data "{\"text\":\"ALERT: Traefik certificate expires in $days_left days\"}" \
                    https://hooks.slack.com/services/XXX/YYY/ZZZ
                fi
              done
          restartPolicy: Never
```

### Сценарий 3: Prometheus alert rules

```yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: traefik-cert-alerts
  namespace: traefik
spec:
  groups:
  - name: traefik.certificates
    interval: 1h
    rules:
    - alert: TraefikCertificateExpiringSoon
      expr: |
        (
          time() - timestamp without(traefik_certificate_expiration_timestamp_seconds)
          > (30 * 24 * 3600)
        )
      for: 0m
      labels:
        severity: warning
      annotations:
        summary: "Traefik certificate expiring soon"
        description: "Certificate {{ $labels.domain }} expires in {{ $value | humanizeDuration }}"
    - alert: TraefikCertificateExpired
      expr: |
        time() - timestamp without(traefik_certificate_expiration_timestamp_seconds)
        > (0)
      for: 0m
      labels:
        severity: critical
      annotations:
        summary: "Traefik certificate expired"
        description: "Certificate {{ $labels.domain }} has expired"
    - alert: TraefikACMEOrderFailed
      expr: increase(traefik_acme_certificate_renewal_total{status="fail"}[1h]) > 0
      labels:
        severity: warning
      annotations:
        summary: "ACME certificate renewal failed"
        description: "ACME renewal failed for certificate"
```

### Сценарий 4: ACME rate limit prevention

```yaml
# Используйте staging для тестирования
certificatesResolvers:
  letsencrypt-staging:
    acme:
      email: admin@example.com
      storage: /data/acme-staging.json
      caServer: https://acme-staging-v02.api.letsencrypt.org/directory
      httpChallenge:
        entryPoint: web
```

```bash
# Проверка rate limit
curl -s https://acme-staging-v02.api.letsencrypt.org/directory | jq '.meta'

# Очистка staging storage перед production
rm -f acme-staging.json
```

### Сценарий 5: Certificate transparency monitoring

```bash
# Проверка сертификата в CT логе
curl -s https://crt.sh/?q=%.example.com&output=json | jq '.[] | {issuer_name, not_before, not_after}'

# Проверка через certspotter
curl -s "https://certspotter.api.akamai.com/v1/issuances?domain=example.com&include_subdomains=true"
```

### Сценарий 6: Внешний ACME handler (cert-manager)

```yaml
# Вместо встроенного ACME Traefik используйте cert-manager
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: example-com
  namespace: traefik
spec:
  secretName: example-com-tls
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  dnsNames:
  - example.com
  - "*.example.com"
  - app.example.com
```

```yaml
# Gateway/Traefik использует существующий Secret
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: external-gw
  namespace: traefik
spec:
  gatewayClassName: traefik
  listeners:
  - name: https
    protocol: HTTPS
    port: 443
    tls:
      mode: Terminate
      certificateRefs:
      - name: example-com-tls
        kind: Secret
```

### Сценарий 7: Alertmanager конфигурация

```yaml
global:
  smtp_smarthost: 'localhost:587'
  smtp_from: 'alerts@example.com'

route:
  group_by: ['alertname', 'namespace']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'team-slack'
  routes:
  - match:
      severity: critical
    receiver: 'team-pagerduty'
  - match:
      alertname: TraefikCertificateExpiringSoon
    receiver: 'team-slack'

receivers:
- name: 'team-slack'
  slack_configs:
  - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
    channel: '#alerts'
    send_resolved: true
- name: 'team-pagerduty'
  pagerduty_configs:
  - service_key: 'xxx'
```

## Операции и команды

```bash
# Проверка сертификатов через Traefik API
curl -s http://localhost:8080/api/rawdata | jq '.tls.certificates'

# Проверка конкретного домена
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -dates -subject

# Проверка acme.json
sudo ls -la /var/lib/traefik/acme.json
sudo chown traefik:traefik /var/lib/traefik/acme.json
sudo chmod 600 /var/lib/traefik/acme.json

# Проверка логов ACME
kubectl logs -n traefik -l app.kubernetes.io/name=traefik | grep -i acme
docker logs traefik 2>&1 | grep -i acme
journalctl -u traefik | grep -i acme
```

## Устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Сертификат не обновляется** | ACME rate limit, ошибка вChallenge | Используйте staging, проверьте логи ACME |
| **ACME rate limit** | Слишком много запросов на issuance/renewal | Используйте DNS-01 challenge, staging для тестов |
| `acme.json` permission denied | Права не `600` или владелец не traefik | `chown traefik:traefik` + `chmod 600` |
| **Сертификат истек** | Traefik был остановлен > 30 дней | Вручную выпустите новый сертификат |
| **Let's Encrypt rate limit** | Превышен лимит 50 сертификатов/неделю | Ожидайте неделю или используйте ZeroSSL |
| **Certificate transparency не показывает** | Сертификат не в CT логе (не Let's Encrypt) | Проверьте CA, используйте ct.log |

