# Аутентификация через TLS-клиентские сертификаты (X.509)

## Определения

**TLS Client Certificate Authentication (X.509 Client Cert Auth)** — метод аутентификации в Kubernetes, при котором API-сервер проверяет клиентский сертификат, подписанный доверенным CA. Идентификатор пользователя извлекается из поля `Common Name (CN)`, а группы — из полей `Organization (O)` сертификата.

Это один из наиболее надёжных и широко используемых методов аутентификации в кластерах Kubernetes, применяемый как для компонентов кластера (Kubelet, Scheduler, Controller Manager), так и для административного доступа.

**Ключевые особенности:**
- **Нет механизма отзыва (CRL/OCSP):** Единственный способ аннулировать доступ — дождаться истечения срока действия сертификата или перевыпустить CA.
- **Не хранится в etcd:** Сертификаты проверяются на лету по CA, без сохранения в базу данных.
- **Работает без внешних зависимостей:** Не требует OIDC-провайдера или вебхука.

---

## Основные концепции

### Маппинг атрибутов из сертификата

При аутентификации через X.509 API-сервер извлекает идентификационные данные из полей сертификата:

| Поле сертификата | RBAC-атрибут | Пример |
|-----------------|-------------|--------|
| `Common Name (CN)` | `user.username` | `CN=alice@example.com` → `alice@example.com` |
| `Organization (O)` | `user.groups` | `O=developers;O=platform` → `["developers", "platform"]` |
| `Organizational Unit (OU)` | Игнорируется | Не используется в Kubernetes |

**Важно:** если CN содержит `system:`, это может конфликтовать с системными сущностями Kubernetes. Избегайте использования префикса `system:` в именах пользователей.

### PKI-инфраструктура Kubernetes

По умолчанию kubeadm создаёт следующую иерархию сертификатов:

```text
Kubernetes CA (ca.crt / ca.key) — корневой сертификат
├── kube-apiserver (apiserver.crt)
├── kubelet (kubelet-client.crt)
├── kube-proxy (proxy-client.crt)
├── etcd (peer.crt, server.crt)
├── front-proxy (front-proxy-ca.crt) — для агрегированных API
└── Клиентские сертификаты (вручную или через kubeadm)
    ├── admin (admin.crt) — CN=system:masters
    ├── controller-manager (controller-manager.crt)
    └── scheduler (scheduler.crt)
```

### Флаги API-сервера

| Флаг | Назначение | Пример |
|------|-----------|--------|
| `--client-ca-file` | CA для проверки клиентских сертификатов | `/etc/kubernetes/pki/ca.crt` |
| `--tls-cert-file` | Сертификат API-сервера | `/etc/kubernetes/pki/apiserver.crt` |
| `--tls-private-key-file` | Приватный ключ API-сервера | `/etc/kubernetes/pki/apiserver.key` |
| `--tls-min-version` | Минимальная версия TLS | `VersionTLS12` |
| `--client-cipher-suites` | Допустимые шифры | (оставьте по умолчанию) |
| `--oidc-*` | Флаги OIDC (альтернатива сертификатам) | См. [OIDC в authentication.md](../authentication.md) |

### Срок действия и ротация

| Тип сертификата | Срок по умолчанию | Ротация |
|----------------|-------------------|---------|
| CA | 10 лет | Ручная, требует обновления во всех компонентах |
| API-сервер | 1 год | kubeadm certs renew |
| Kubelet | 1 год | Автоматическая через `--rotate-certificates` |
| Клиентские | 1 год | Ручная через kubeadm или OpenSSL |

---

## Практические сценарии

### Создание клиентского сертификата через OpenSSL

**Шаг 1: Создание приватного ключа и CSR (Certificate Signing Request):**

```bash
# Генерация приватного ключа
openssl genrsa -out alice.key 2048

# Создание CSR с указанием CN и O
openssl req -new -key alice.key -out alice.csr \
  -subj "/CN=alice@example.com/O=developers/O=platform" \
  -config /etc/ssl/openssl.cnf
```

**Шаг 2: Подпись CSR через CA кластера:**

```bash
# Создание файла расширений для сертификата
cat > alice.ext <<EOF
authorityKeyIdentifier=keyid,issuer
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=clientAuth
EOF

# Подпись сертификата CA кластера
openssl x509 -req -in alice.csr \
  -CA /etc/kubernetes/pki/ca.crt \
  -CAkey /etc/kubernetes/pki/ca.key \
  -CAcreateserial \
  -out alice.crt \
  -days 365 \
  -extfile alice.ext

# Очистка промежуточных файлов
rm -f alice.csr alice.ext
```

**Шаг 3: Настройка kubeconfig:**

```bash
kubectl config set-credentials alice \
  --client-certificate=alice.crt \
  --client-key=alice.key

kubectl config set-context alice-context \
  --cluster=kubernetes \
  --user=alice

# Использование
kubectl --context=alice-context get pods -n production
```

### Создание сертификата через cfssl

**Установка cfssl:**

```bash
# macOS
brew install cfssl

# Linux
curl -sL https://github.com/cloudflare/cfssl/releases/latest/download/cfssl_1.6.5_linux_amd64 -o /usr/local/bin/cfssl
curl -sL https://github.com/cloudflare/cfssl/releases/latest/download/cfssljson_1.6.5_linux_amd64 -o /usr/local/bin/cfssljson
chmod +x /usr/local/bin/cfssl /usr/local/bin/cfssljson
```

**Конфигурация CA:**

```json
// ca-config.json
{
  "signing": {
    "default": {
      "expiry": "8760h"
    },
    "profiles": {
      "client": {
        "usages": ["signing", "digital signature", "key encipherment", "client auth"],
        "expiry": "8760h"
      }
    }
  }
}
```

**Создание CA:**

```json
// ca-csr.json
{
  "CN": "Kubernetes CA",
  "key": {
    "algo": "rsa",
    "size": 2048
  },
  "names": [
    {
      "O": "Kubernetes",
      "OU": "CA"
    }
  ]
}
```

```bash
# Генерация CA
cfssl gencert -initca ca-csr.json | cfssljson -bare ca
# → ca.pem, ca-key.pem, ca.csr
```

**Создание клиентского сертификата:**

```json
// alice-csr.json
{
  "CN": "alice@example.com",
  "hosts": [],
  "key": {
    "algo": "rsa",
    "size": 2048
  },
  "names": [
    {
      "O": "developers",
      "O": "platform"
    }
  ]
}
```

```bash
# Подпись сертификата через CA
cfssl gencert \
  -ca=ca.pem \
  -ca-key=ca-key.pem \
  -config=ca-config.json \
  -profile=client \
  alice-csr.json | cfssljson -bare alice
# → alice.pem (сертификат), alice-key.pem (ключ)
```

### Автоматическая ротация сертификатов Kubelet

```bash
# Включение автоматической ротации (включено по умолчанию в modern дистрибутивах)
# kubelet.conf содержит:
#   users:
#   - name: system:node:<node-name>
#     user:
#       client-certificate: /var/lib/kubelet/pki/kubelet-client-current.pem
#       client-key: /var/lib/kubelet/pki/kubelet-client-current.pem

# Проверка текущего сертификата Kubelet
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -subject -dates
# → subject=CN=system:node:worker-01
# → notBefore=... notAfter=...
```

### Проверка сертификата

```bash
# Просмотр информации о сертификате
openssl x509 -in alice.crt -noout -text | grep -A2 "Subject:"
# → Subject: CN = alice@example.com, O = developers, O = platform

# Проверка подписи CA
openssl verify -CAfile /etc/kubernetes/pki/ca.crt alice.crt
# → alice.crt: OK

# Проверка срока действия
openssl x509 -in alice.crt -noout -dates
```

### Диагностика проблем аутентификации

```bash
# 1. Проверка: какой пользователь аутентифицируется сертификатом?
kubectl config view --minify -o jsonpath='{.users[0].name}'

# 2. Проверка сертификата в текущем контексте
kubectl config view --raw --minify -o jsonpath='{.users[0].user.client-certificate-data}' | \
  base64 -d | openssl x509 -noout -subject

# 3. Тест аутентификации через API
kubectl auth whoami  # (v1.27+)
# или
kubectl get --raw /api/v1/namespaces | jq '.kind'

# 4. Проверка ошибок в логах API-сервера
kubectl logs -n kube-system -l component=kube-apiserver | grep -i "x509\|certificate"
```

---

## Дополнительная информация

### Безопасность

- **Защита приватных ключей:** Приватные ключи должны храниться в защищённом месте (HSM, Vault). Утечка ключа эквивалентна компрометации личности владельца сертификата.
- **Минимальный срок действия:** Используйте срок 1 год для клиентских сертификатов. Короткий срок минимизирует ущерб при компрометации.
- **CN ≠ system:** Не используйте `system:` префикс в CN — это зарезервировано для системных сущностей Kubernetes.
- **O-поля для групп:** Используйте Organization для назначения групп (RBAC привязывает права к группам удобнее, чем к отдельным пользователям).

### Сравнение с другими методами

| Критерий | TLS Certs | OIDC | Webhook | SA Token |
|----------|----------|------|---------|----------|
| **Сложность настройки** | Средняя | Высокая | Высокая | Низкая |
| **Зависимости** | Нет | OIDC-провайдер | Внешний сервис | Нет |
| **Отзыв доступа** | Невозможен без перевыпуска | Да (через провайдер) | Да | Да (удаление SA) |
| **Подходит для людей** | Да | Да (SSO) | Да | Нет (для приложений) |
| **Подходит для компонентов** | Да | Нет | Нет | Да |
| **Кластерный масштаб** | Средняя | Высокая | Средняя | Низкая |

### kubeadm: управление сертификатами

```bash
# Просмотр всех сертификатов
kubeadm certs check-expiration

# Обновление всех сертификатов
kubeadm certs renew all

# Обновление конкретного сертификата
kubeadm certs renew apiserver

# Генерация нового kubeconfig для admin
kubeadm kubeconfig user --client-name=alice --org=developers
```

### Связанные темы

- **[Аутентификация в Kubernetes](../authentication.md)** — обзор всех методов аутентификации
- **[Субъекты доступа](./subjects.md)** — маппинг сертификатных атрибутов на RBAC
- **[Обзор RBAC](./rbac_overview.md)** — как сертификатные данные используются при авторизации
