# Let's Encrypt: Соответствие требованиям (Compliance)

## Определения

**SOC 2 Type II** — стандарт аудита, оценивающий控制系统 организации по пяти принципам доверия: безопасность, доступность, целостность обработки, конфиденциальность и приватность. Для TLS-сертификатов критичны требования к безопасности (CC6.1 — логический доступ) и доступности (A1.2 — мониторинг).

**PCI DSS (Payment Card Industry Data Security Standard)** — стандарт безопасности для организаций, обрабатывающих платёжные данные. Требует шифрования передачи данных (PCI DSS 4.0, требование 4.2.1) через TLS 1.2+, регулярной ротации сертификатов и аудита доступа к криптографическим ключам.

**NIST SP 800-57** — рекомендации по управлению криптографическими ключами. Определяет максимальные сроки жизни ключей, процедуры ротации и требования к хранению. Для TLS-сертификатов: рекомендуемый срок жизни не более 398 дней (NIST), не более 90 дней (Let's Encrypt).

**X.509 Certificate Profile** — набор требований к полям и расширениям сертификата (Key Usage, Extended Key Usage, SAN, Basic Constraints). Compliance-требования определяют, какие расширения должны присутствовать в сертификате.

---

## Основные концепции

### Соответствие Let's Encrypt требованиям стандартов

| Стандарт | Требование к TLS | Let's Encrypt | cert-manager | Статус |
| :--- | :--- | :--- | :--- | :--- |
| **PCI DSS 4.0 (4.2.1)** | Шифрование передачи данных (TLS 1.2+) | TLS 1.2/1.3 | Настройка через Ingress | Соответствует |
| **PCI DSS 4.0 (6.2.4)** | Безопасная разработка | ACME-автоматизация | GitOps-подход | Соответствует |
| **PCI DSS 4.0 (12.3.1)** | Аудит доступа к ключам | Ключи в Kubernetes Secrets | RBAC + Audit Logging | Требует настройки |
| **SOC 2 CC6.1** | Логический доступ к системе | RBAC + NetworkPolicy | cert-manager RBAC | Соответствует |
| **SOC 2 CC7.2** | Мониторинг изменений | Prometheus + Audit Logs | cert-manager metrics | Требует настройки |
| **SOC 2 A1.2** | Мониторинг доступности | ARI + автоматическое продление | cert-manager controller | Соответствует |
| **NIST SP 800-57** | Срок жизни ключей не более 398 дней | 90 дней (переход на 45) | параметр `duration` | Соответствует |
| **ISO 27001 (A.10.1)** | Управление криптографией | ECDSA P-256 / RSA | `privateKey.algorithm` | Соответствует |

### Требования к сертификатам по стандартам

| Поле сертификата | PCI DSS | SOC 2 | NIST | Let's Encrypt |
| :--- | :--- | :--- | :--- | :--- |
| **TLS версия** | >= 1.2 | Рекомендуется 1.3 | >= 1.2 | 1.2/1.3 |
| **Алгоритм ключа** | RSA >= 2048 / ECDSA >= 256 | Рекомендуется ECDSA | RSA >= 2048 / ECDSA >= 256 | RSA + ECDSA |
| **Срок жизни** | Не более 1 года (рекомендуется) | Не более 1 года | Не более 398 дней | 90 дней (переход на 45) |
| **Key Usage** | digitalSignature, keyEncipherment | digitalSignature | digitalSignature | Поддерживается |
| **Extended Key Usage** | serverAuth | serverAuth | serverAuth | Только serverAuth |
| **SAN** | Обязательно | Обязательно | Обязательно | Поддерживается |
| **CT (Certificate Transparency)** | Рекомендуется | Рекомендуется | Рекомендуется | Обязательно (2026) |
| **OCSP Stapling** | Рекомендуется | Рекомендуется | Рекомендуется | Опционально |

### Audit Trail для сертификатов

Для соответствия SOC 2 CC7.2 и PCI DSS 10.x необходимо вести аудит-трейл всех операций с сертификатами:

| Событие | Источник | Хранение | Срок хранения |
| :--- | :--- | :--- | :--- |
| Создание Certificate CRD | Kubernetes Audit Log | ELK/Loki | 12 месяцев |
| Выпуск сертификата (ACME Order) | cert-manager logs | ELK/Loki | 12 месяцев |
| Продление сертификата | cert-manager logs | ELK/Loki | 12 месяцев |
| Удаление Certificate CRD | Kubernetes Audit Log | ELK/Loki | 12 месяцев |
| Изменение Issuer | Kubernetes Audit Log | ELK/Loki | 12 месяцев |
| Доступ к Secret с ключом | Kubernetes Audit Log | ELK/Loki | 12 месяцев |
| Rate limit ошибки | cert-manager logs | ELK/Loki | 12 месяцев |

---

## Практические сценарии

### Сценарий 1: Настройка Audit Logging для cert-manager

```yaml
# Audit Policy (audit-policy.yaml)
apiVersion: audit.k8s.io/v1
kind: Policy
rules:
# Логирование всех операций с cert-manager ресурсами
- level: RequestResponse
  resources:
  - group: "cert-manager.io"
    resources: ["certificates", "certificaterequest", "orders", "challenges"]
    verbs: ["create", "update", "patch", "delete"]

# Логирование доступа к Secret с сертификатами
- level: RequestResponse
  resources:
  - group: ""
    resources: ["secrets"]
    verbs: ["get", "list"]
  namespaces: ["cert-manager", "prod", "staging"]

# Логирование изменений Issuer
- level: RequestResponse
  resources:
  - group: "cert-manager.io"
    resources: ["issuers", "clusterissuers"]
    verbs: ["create", "update", "patch", "delete"]
```

```bash
# Проверка аудит-логов
kubectl logs -n kube-apiserver kube-apiserver-* | grep "cert-manager.io" | jq '.verb + " " + .objectRef.resource'

# Экспорт аудит-логов в файл
kubectl logs -n kube-apiserver kube-apiserver-* --since=24h | grep "cert-manager" > /tmp/cert-manager-audit.log
```

### Сценарий 2: Сертификаты для PCI DSS 4.0

Для соответствия PCI DSS 4.0 (требование 4.2.1 — шифрование передачи данных):

```yaml
# Certificate с параметрами PCI DSS compliance
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: payment-app-tls
  namespace: pci-compliant
  labels:
    compliance: pci-dss-4.0
spec:
  secretName: payment-app-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: payment.example.com
  dnsNames:
    - payment.example.com
    - api.payment.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
  # PCI DSS требует TLS >= 1.2 (настройка на уровне Ingress)
  usages:
    - server auth
    - digital signature
    - key encipherment
```

```yaml
# Nginx Ingress с PCI DSS TLS-настройками
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: payment-ingress
  namespace: pci-compliant
  annotations:
    # PCI DSS 4.0: TLS 1.2+ только
    nginx.ingress.kubernetes.io/ssl-protocols: "TLSv1.2 TLSv1.3"
    # Рекомендуемые cipher suites
    nginx.ingress.kubernetes.io/ssl-ciphers: "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384"
    # HSTS (PCI DSS 4.0, требование 6.2.4)
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
spec:
  tls:
  - hosts:
    - payment.example.com
    secretName: payment-app-tls-secret
  rules:
  - host: payment.example.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: payment-service
            port:
              number: 443
```

### Сценарий 3: Сертификаты для SOC 2 Type II

```yaml
# Certificate с метаданными для SOC 2
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-api-tls
  namespace: soc2-compliant
  labels:
    compliance: soc2-type2
    team: platform
    environment: production
spec:
  secretName: internal-api-tls-secret
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
  commonName: internal-api.example.com
  dnsNames:
    - internal-api.example.com
  privateKey:
    algorithm: ECDSA
    size: 256
```

```yaml
# NetworkPolicy для SOC 2 CC6.1 (микросегментация)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: cert-manager-egress
  namespace: cert-manager
spec:
  podSelector:
    matchLabels:
      app: cert-manager
  policyTypes:
  - Egress
  egress:
  # ACME API (Let's Encrypt)
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
    - protocol: TCP
      port: 443
  # DNS-резолверы
  - to:
    - namespaceSelector: {}
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
```

### Сценарий 4: Мониторинг соответствия через Prometheus

```yaml
# PrometheusRule для compliance-мониторинга
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: letsencrypt-compliance-rules
  namespace: cert-manager
spec:
  groups:
  - name: compliance.rules
    rules:
    # PCI DSS: сертификаты не должны истекать
    - alert: PCI_DSS_CertificateExpired
      expr: certmanager_certificate_expiration_timestamp_seconds < time()
      for: 1m
      labels:
        severity: critical
        compliance: pci-dss
      annotations:
        summary: "PCI DSS: сертификат просрочен"

    # SOC 2: сертификат истекает менее чем через 30 дней
    - alert: SOC2_CertificateExpiringSoon
      expr: certmanager_certificate_expiration_timestamp_seconds - time() < 30 * 24 * 3600
      for: 1h
      labels:
        severity: warning
        compliance: soc2
      annotations:
        summary: "SOC 2: сертификат истекает менее чем через 30 дней"

    # NIST: все сертификаты должны быть в статусе Ready
    - alert: NIST_CertificateNotReady
      expr: certmanager_certificate_ready_status == 0
      for: 15m
      labels:
        severity: warning
        compliance: nist
      annotations:
        summary: "NIST: сертификат не в статусе Ready"

    # Мониторинг rate limits (could impact compliance)
    - alert: ACME_RateLimited
      expr: increase(certmanager_http_acme_client_request_count{status="429"}[1h]) > 0
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "ACME rate limit - potential compliance impact"
```

---

## Дополнительная информация

### Чек-лист compliance-аудита для Let's Encrypt

| Проверка | Команда | Ожидаемый результат |
| :--- | :--- | :--- |
| TLS >= 1.2 | `openssl s_client -connect domain:443 -tls1_2` | Успешное рукопожатие |
| Сертификат не просрочен | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -dates` | not_after > now |
| ECDSA ключ | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -text \| grep "Public Key Algorithm"` | id-ecPublicKey |
| SAN присутствует | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -ext subjectAltName` | DNS:domain |
| CT присутствует | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -text \| grep "CT"` | CT Precertificate SCTs |
| Key Usage корректен | `openssl s_client -connect domain:443 2>/dev/null \| openssl x509 -noout -text \| grep -A 3 "Key Usage"` | Digital Signature, Key Encipherment |

### Различия требований по стандартам

| Требование | PCI DSS 4.0 | SOC 2 Type II | NIST SP 800-57 |
| :--- | :--- | :--- | :--- |
| Минимальная версия TLS | 1.2 | 1.2 (рек. 1.3) | 1.2 |
| Минимальный RSA ключ | 2048 бит | 2048 бит | 2048 бит |
| Максимальный срок жизни | Не регламентировано | Не регламентировано | 398 дней |
| Аудит-логи | 12 мес. (3 мес. горячие) | 12 мес. | 3 года |
| Ротация ключей | Рекомендуется | Рекомендуется | Обязательно |
| CT логирование | Рекомендуется | Рекомендуется | Рекомендуется |

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — лимиты, solvers и окружения
- **[cert-manager: Администрирование](../Administration/index.md)** — RBAC и безопасность
- **[Security: Compliance Overview](../../../../Security/audit_and_compliance_overview.md)** — обзор стандартов
- **[Kubernetes Audit Logging](../../../../Kubernetes/Security/audit.md)** — настройка аудита
- **[Let's Encrypt: Network Security](./letsencrypt_network_security.md)** — сетевая безопасность
