# Интеграция cert-manager с Step-CA (Smallstep)

## Определения

**Step-CA** — легковесный, open-source центр сертификации (CA) от Smallstep. Поддерживает ACME для автоматического выпуска сертификатов, SSH-сертификаты и короткоживущие сертификаты. В отличие от Vault PKI, Step-CA спроектирован специально как CA и не требует настройки secrets engine.

**Step Issuer** — Custom Resource Definition (CRD) для cert-manager, обеспечивающий интеграцию с Step-CA через ACME-протокол. Позволяет cert-manager выпускать сертификаты через Step-CA как через внешний ACME-сервер.

**Provisioner** — механизм аутентификации в Step-CA. Типы: `JWK` (JSON Web Key), `ACME` (для cert-manager), `X509` (client certificate), `SSHPOP` (для SSH). Для интеграции с cert-manager используется ACME provisioner.

---

## Основные концепции

### Step-CA vs Vault PKI vs Self-Signed

| Характеристика | Step-CA | Vault PKI | Self-Signed (cert-manager) |
| :--- | :--- | :--- | :--- |
| **Сложность настройки** | Низкая | Высокая | Минимальная |
| **ACME-поддержка** | Нативная | Нет (только через intermediate) | Да (Let's Encrypt) |
| **SSH-сертификаты** | Да | Да | Нет |
| **Короткоживущие сертификаты** | Да (по умолчанию) | Да | Да |
| **HSM** | Ограниченно | Да | Нет |
| **Audit log** | Да | Да (Enterprise) | Нет |
| **Хранение ключей** | Локально / генерация на лету | Разделенное (Shamir) | В Secret |
| **Рекомендация** | Air-gapped, простые среды | Enterprise, compliance | Dev/test |

### Архитектура интеграции

```
┌────────────────────────────────────────────────┐
│              Kubernetes Cluster                │
│                                                │
│  ┌──────────────┐    ┌──────────────────────┐  │
│  │ cert-manager │───►│ Step Issuer (CRD)    │  │
│  └──────┬───────┘    └──────────┬───────────┘  │
│         │                       │               │
│         ▼                       ▼               │
│  ┌──────────────┐    ┌──────────────────────┐  │
│  │ Certificate  │───►│ Step-CA (внутри K8s   │  │
│  │ (CRD)        │    │ или внешний)          │  │
│  └──────────────┘    └──────────┬───────────┘  │
│                                 │               │
│                                 ▼               │
│                        ┌──────────────────────┐ │
│                        │ Step-CA Server       │ │
│                        │  └─ ACME Provisioner │ │
│                        │  └─ Root/Intermediate│ │
│                        └──────────────────────┘ │
└────────────────────────────────────────────────┘
```

---

## Практические сценарии

### Сценарий 1: Установка Step-CA в Kubernetes

#### Шаг 1: Инициализация Step-CA

```bash
# Генерация корневого CA
step ca init \
  --name "Internal-CA" \
  --dns step-ca.step-ca.svc.cluster.local \
  --address ":9000" \
  --provisioner admin

# Результат: файлы в ./step/
# - ca.crt (корневой сертификат)
# - ca.key (приватный ключ)
# - root_ca.crt
# - config/ca.json
```

#### Шаг 2: Развертывание в Kubernetes

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: step-ca
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: step-ca-config
  namespace: step-ca
data:
  ca.json: |
    {
      "root": "/certs/root_ca.crt",
      "federatedRoots": null,
      "crt": "/certs/ca.crt",
      "key": "/certs/ca.key",
      "address": ":9000",
      "insecureAddress": "",
      "dnsNames": ["step-ca.step-ca.svc.cluster.local"],
      "logger": {"level": "info"},
      "db": {"type": "badgerv2", "dataSource": "/badgerv2/data"}
    }
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: step-ca
  namespace: step-ca
spec:
  replicas: 1
  selector:
    matchLabels:
      app: step-ca
  template:
    metadata:
      labels:
        app: step-ca
    spec:
      containers:
      - name: step-ca
        image: smallstep/step-ca:0.27.5
        ports:
        - containerPort: 9000
        volumeMounts:
        - name: certs
          mountPath: /certs
          readOnly: true
        - name: config
          mountPath: /home/step
        - name: data
          mountPath: /badgerv2/data
      volumes:
      - name: certs
        secret:
          secretName: step-ca-certs
      - name: config
        configMap:
          name: step-ca-config
      - name: data
        emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: step-ca
  namespace: step-ca
spec:
  selector:
    app: step-ca
  ports:
  - port: 9000
    targetPort: 9000
```

#### Шаг 3: Создание ACME Provisioner

```bash
# Добавление ACME provisioner в Step-CA
step ca provisioner add acme --type ACME --admin-provisioner admin --admin-password-file password.txt
```

#### Шаг 4: Установка Step Issuer для cert-manager

```bash
# Установка step-issuer через Helm
helm repo add smallstep https://smallstep.github.io/helm-charts
helm install step-issuer smallstep/step-issuer \
  --namespace cert-manager
```

---

### Сценарий 2: Step Issuer для cert-manager

```yaml
apiVersion: certmanager.step.sm/v1beta1
kind: StepClusterIssuer
metadata:
  name: step-ca-issuer
spec:
  url: https://step-ca.step-ca.svc.cluster.local:9000
  caBundle: |
    -----BEGIN CERTIFICATE-----
    <base64 root CA certificate>
    -----END CERTIFICATE-----
  provisioner:
    name: acme
    kid: <key ID from step ca provisioner list>
    passwordRef:
      name: step-ca-password
      namespace: cert-manager
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-tls
  namespace: production
spec:
  secretName: my-app-tls-secret
  issuerRef:
    name: step-ca-issuer
    kind: StepClusterIssuer
  dnsNames:
    - my-app.production.svc.cluster.local
  duration: 2160h    # 90 дней
  renewBefore: 168h  # 7 дней
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
```

---

### Сценарий 3: Короткоживущие сертификаты (Zero Trust)

Step-CA идеален для короткоживущих сертификатов в zero-trust архитектуре.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: zero-trust-service
  namespace: production
spec:
  secretName: zero-trust-tls
  issuerRef:
    name: step-ca-issuer
    kind: StepClusterIssuer
  dnsNames:
    - service-a.production.svc.cluster.local
  duration: 1h         # 1 час
  renewBefore: 10m     # 10 минут
  privateKey:
    algorithm: Ed25519
    rotationPolicy: Always
  usages:
    - server auth
    - client auth
```

---

## Дополнительная информация

### Когда использовать Step-CA вместо Vault

| Критерий | Step-CA | Vault PKI |
| :--- | :--- | :--- |
| Нужен ACME для приватных сертификатов | Да | Нет (нужен промежуточный CA) |
| Нужны SSH-сертификаты | Да | Да |
| Нужен HSM | Нет | Да |
| Нужен enterprise audit | Нет | Да (Enterprise) |
| Простота настройки | Высокая | Средняя |
| Встроенная поддержка short-lived | Да | Да |

### Частые ошибки

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `connection refused` | Step-CA недоступен из cert-manager | Проверить Service и NetworkPolicy |
| `unauthorized` | Неверный provisioner или kid | Проверить `step ca provisioner list` |
| `certificate verify failed` | caBundle не содержит корневой CA Step-CA | Обновить `caBundle` в StepIssuer |

### Смотрите также

- **[Приватный CA: Vault PKI](./vault_integration.md)** — сравнение с Vault
- **[Приватный CA: Обзор](./index.md)** — архитектура иерархий
- **[cert-manager: Определения](../definitions.md)** — базовые ресурсы
- **[PKI: Обзор](../../../../Security/Concepts/pki_overview.md)** — теоретическая база
