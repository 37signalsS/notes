# Безопасность etcd: TLS, RBAC и шифрование

**Актуально для:** etcd 3.5.x / 3.6.x / 3.7.x

**etcd** хранит все секреты Kubernetes и конфигурации кластера. Компрометация etcd = компрометация всего кластера. Данный документ описывает практические меры безопасности для production.

etcd по умолчанию не включает ни RBAC, ни аутентификацию на транспортном уровне: кластер без настроенной безопасности открывает свои данные любому клиенту с сетевым доступом к портам 2379/2380.

## Определения

| Термин | Описание |
| :--- | :--- |
| **mTLS** | Взаимная TLS-аутентификация. И клиент, и сервер проверяют сертификаты друг друга. |
| **Peer TLS** | Шифрование и аутентификация коммуникации между узлами кластера (порт 2380). |
| **Client TLS** | Шифрование и аутентификация коммуникации между клиентами и etcd (порт 2379). |
| **RBAC** | Role-Based Access Control. Разграничение прав доступа к ключам. |
| **CN-based auth** | С v3.2 при `--client-cert-auth=true` поле CN клиентского сертификата используется как имя пользователя etcd. |
| **Encryption at Rest** | Шифрование данных на диске. etcd не поддерживает его нативно — реализуется на уровне kube-apiserver (KMS) или хранилища (dm-crypt). |
| **Certificate Rotation** | Замена сертификатов до истечения срока. Листовые сертификаты перечитываются при каждом TLS-соединении (с v3.2.0). |
| **CRL** | Certificate Revocation List. etcd проверяет отзыв клиентских сертификатов через `--client-crl-file`. OCSP не поддерживается. |
| **SAN (Subject Alternative Name)** | Альтернативное имя в сертификате, по которому клиент проверяет сервер. |

---

## Основные концепции

### Peer TLS (обязательно для production)

Без шифрования peer-соединений:
- Raft-лог передается в открытом виде.
- Снапшоты передаются в открытом виде.
- Любой, имеющий доступ к сети 2380, может получить полный дамп данных.

**Требования к сертификатам:**
- **CN:** Имя узла (например, `etcd-node-1`).
- **SAN:** Должен содержать `peer-IP`, `peer-DNS`, `DNS:etcd-node-1`.
- **keyUsage:** `digitalSignature`, `keyEncipherment`.
- **extendedKeyUsage:** `serverAuth` и `clientAuth` — peer-сертификат работает одновременно как серверный и клиентский.

```bash
# Пример CN/SAN для peer сертификата
Subject: CN = etcd-node-1
X509v3 Subject Alternative Name:
  DNS:etcd-node-1, DNS:etcd-node-1.default.svc.cluster.local,
  IP Address: 10.0.1.10, IP Address: 10.0.1.11
```

**Ошибка:**
```
x509: certificate is valid for node1, not etcd-node-2
```
— означает, что `--name` или `--initial-advertise-peer-urls` не совпадают с CN/SAN сертификата.

**Дополнительная защита peer-соединений (v3.3.0+):**
```bash
# Разрешить присоединение только узлам с точным CN (без wildcard и префиксов)
--peer-cert-allowed-cn=etcd-node-1
```
Полезно, когда все участники подписаны одним CA (например, при Kubernetes TLS bootstrapping): даже с общим CA присоединиться сможет только узел с совпадающим CN. Для фильтрации по hostname есть `--peer-cert-allowed-hostname` и `--client-cert-allowed-hostname` (сравнение через Go `VerifyHostname()`, поддерживает wildcard вида `*.example.com`).

### Client TLS

Клиенты (etcdctl, kube-apiserver) подключаются к порту 2379.

**Ключевые флаги сервера:**

| Флаг | Назначение |
| :--- | :--- |
| `--cert-file`, `--key-file` | Сертификат и ключ сервера для client-подключений |
| `--trusted-ca-file` | CA, которым подписаны клиентские сертификаты |
| `--client-cert-auth` | Требовать клиентский сертификат, подписанный trusted CA |
| `--cipher-suites` | Разрешённые TLS cipher suites (пусто — выбор Go по умолчанию) |
| `--auto-tls` | Автогенерируемые self-signed сертификаты (только для dev) |

**CN как имя пользователя (с v3.2):** при `--client-cert-auth=true` поле CN клиентского сертификата используется как имя пользователя etcd — пароль не требуется. Если клиент передаёт и CN, и `--user=login:password`, приоритет у username/password. Механизм несовместим с gRPC-proxy и gRPC-gateway: они терминируют TLS, и сервер видит CN прокси вместо CN клиента.

**Требования к клиентскому сертификату:** keyUsage `digitalSignature`, `keyEncipherment`; extendedKeyUsage `clientAuth`. Без `clientAuth` в EKU сервер отклоняет рукопожатие с ошибкой `SSLv3 alert handshake failure`.

**`--auto-tls` / `--peer-auto-tls`:** шифруют трафик, но НЕ аутентифицируют стороны (self-signed, срок действия 1 год, настраивается через `--self-signed-cert-validity`). Только для dev/тестов, никогда для production.

### RBAC в etcd

etcd имеет собственную систему RBAC (не путать с Kubernetes RBAC).

**Базовый сценарий:**
```bash
# 1. Создать пользователя
etcdctl user add admin --new-user-password=secret

# 2. Создать роль с правами на префикс
etcdctl role add admin-role
etcdctl role grant-permission admin-role readwrite /k8s --prefix

# 3. Привязать роль к пользователю
etcdctl user grant-role admin admin-role

# 4. Включить аутентификацию
etcdctl auth enable
```

**Важно:**
- После `auth enable` все клиенты должны предоставлять учетные данные.
- RBAC проверяется на каждом gRPC-запросе. Нет кэширования прав на стороне клиента.
- Права хранятся в etcd (в `/auth/`). При восстановлении из снапшота права восстанавливаются.
- Тип токена задаётся флагом `--auth-token` (`simple` по умолчанию; `jwt` — stateless, требует настройки ключей подписи); TTL кэша токенов — `--auth-token-cache-ttl`.
- Полный набор команд (`user passwd`, `user revoke-role`, `role revoke-permission`, `role delete` и др.) — в **[Шпаргалке etcdctl](./etcdctl_cheatsheet.md)**.

### Encryption at Rest

**etcd не шифрует данные на диске нативно** — ни в 3.5, ни в 3.6, ни в 3.7 (официальный FAQ: «Does etcd encrypt data stored on disk drives? No»). Данные в data-dir и снапшотах лежат в открытом виде. Варианты защиты:

1. **KMS через kube-apiserver (рекомендуется для Kubernetes):** `EncryptionConfiguration` шифрует ресурсы (Secrets, ConfigMaps и др.) на стороне API-сервера **до** записи в etcd. KMS v2 использует envelope encryption: уникальный DEK на ресурс шифруется KEK из внешнего KMS. Настройка, включение на работающем кластере, ротация ключей — **[Хранение Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md)** (SSoT).
2. **Шифрование хранилища (dm-crypt/LUKS):** шифрование раздела `/var/lib/etcd` на уровне ОС. Защищает от кражи диска, но не от компрометации работающего хоста.
3. **Client-side encryption:** приложение шифрует данные перед записью. Максимальная защита, но теряются индексация и watch по зашифрованным полям.

**Локальный AES-ключ в EncryptionConfiguration** — single point of failure: если конфиг украден, данные расшифровываются. KMS v2 хранит KEK вне хоста.

---

## Практические сценарии

### Проверка TLS-соединения

```bash
# Проверить peer TLS (сервер должен предъявить сертификат)
openssl s_client -connect 10.0.1.10:2380 -showcerts

# Проверить client TLS (с клиентским сертификатом)
openssl s_client -connect 10.0.1.10:2379 \
  -cert /etc/etcd/pki/client.crt -key /etc/etcd/pki/client.key \
  -CAfile /etc/etcd/pki/ca.crt

# Проверить цепочку сертификата (без проверки отзыва!)
openssl verify -CAfile /etc/etcd/pki/ca.crt /etc/etcd/pki/server.crt
# → OK
```

**Отзыв сертификатов (CRL):** etcd поддерживает проверку отзыва клиентских сертификатов через флаг сервера `--client-crl-file=<path.crl>`. OCSP не поддерживается. Внимание: в июне 2026 исправлена обходная уязвимость, когда gRPC-слушатель не применял CRL (GHSA-3wh4-j44w-pg92) — используйте актуальные патчные версии веток 3.5/3.6/3.7.

### Ротация сертификатов без даунтайма

**Листовые сертификаты (server/client/peer) — без перезапуска (с v3.2.0):** etcd перечитывает файлы сертификатов при каждом новом TLS-соединении. Достаточно подложить новые файлы на место старых:

```bash
# 1. Выпустить новый сертификат с теми же CN/SAN
# 2. Атомарно заменить файлы на узле
mv /etc/etcd/pki/server.crt /etc/etcd/pki/server.crt.old
cp new-server.crt /etc/etcd/pki/server.crt
# 3. Новые соединения подхватят новый сертификат автоматически
etcdctl endpoint health --cluster
```

**Ротация CA — rolling restart:** новый CA загружается только при старте, поэтому требуется поочерёдный перезапуск узлов:

1. Подписать новые сертификаты новым CA, сохранив прежние SAN.
2. Перезапускать узлы по одному (`systemctl restart etcd`), после каждого — `etcdctl endpoint health --cluster`.
3. Старый CA должен оставаться в trust bundle, пока все узлы не перейдут на новый.

**Важно:**
- Старые сертификаты должны оставаться валидными во время ротации, иначе peer-соединения разорвутся.
- Сертификаты с SAN только из IP-адресов (без DNS-имён) корректно перезагружаются только с v3.2.19/v3.3.4 — на более старых версиях hot-reload не срабатывал при пустом SNI.
- В Kubernetes (kubeadm) ротация автоматизирована через `kubeadm certs renew`; в OpenShift — cluster-etcd-operator ротирует сертификаты автоматически.

### Аудит прав доступа

```bash
# Состояние аутентификации
etcdctl auth status

# Список пользователей и роли пользователя
etcdctl user list
etcdctl user get admin

# Права роли
etcdctl role get-permission admin-role

# Проверить доступ
ETCDCTL_API=3 etcdctl --user=admin:secret get /k8s/secret --prefix
```

**Gap аудита:** прямые запросы к etcd (etcdctl, kube-apiserver) не попадают в Kubernetes audit log — аудит фиксирует только запросы к API-серверу. Для отслеживания прямого доступа используйте RBAC etcd и сетевую изоляцию (см. [Аудит Kubernetes](../Kubernetes/Security/audit.md)).

### Сетевая изоляция и файловые разрешения

```bash
# Привязать client-порт только к внутреннему интерфейсу, не к 0.0.0.0
--listen-client-urls=https://10.0.1.10:2379
--advertise-client-urls=https://10.0.1.10:2379

# Firewall: 2379/2380 только с control-plane узлов
# (iptables/nftables/SecurityGroup — по среде)

# Права на ключи: только пользователь etcd
chown etcd:etcd /etc/etcd/pki/*.key
chmod 600 /etc/etcd/pki/*.key
```

- Порт 2379 должен быть доступен только control-plane узлам (kube-apiserver, хосты etcdctl).
- Порт 2380 — только между узлами etcd.
- etcd запускать от непривилегированного пользователя (не root).
- Метрики (`--listen-metrics-urls`) — на приватный интерфейс.

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate is valid for ..., not ...` | CN/SAN не совпадает с `--name` или `--advertise-client-urls` | Проверить сертификат и конфиг |
| `tls: first record does not look like a TLS handshake` | Клиент не использует TLS, а сервер требует | Проверить `ETCDCTL_CACERT`, `ETCDCTL_CERT`, `ETCDCTL_KEY` |
| `etcdserver: authentication is enabled but no credentials provided` | RBAC включен, клиент не передал credentials | Добавить `--user` или env vars |
| `etcdserver: permission denied` | Роль не имеет прав на ключ | Проверить `etcdctl role get-permission` |
| `etcdserver: invalid auth token` | Токен истек или поврежден | Пересоздать token; проверить `etcdctl auth status` |
| `SSLv3 alert handshake failure` при client-auth | В клиентском сертификате нет `clientAuth` в extendedKeyUsage | Перевыпустить сертификат с EKU `clientAuth` |
| `remote error: tls: unknown certificate authority` | Peer-сертификат подписан CA, которого нет в trust bundle остальных узлов | Проверить `--trusted-ca-file`/`--peer-trusted-ca-file` на всех узлах |

---

## Best Practices

- **Peer TLS — обязательно:** Никогда не запускайте production-кластер без шифрования peer-соединений.
- **Отдельный CA для etcd:** Не используйте тот же CA, что и для Kubernetes API. Компрометация etcd-CA = компрометация всего кластера. В kubeadm-схеме используются два CA: для peer-соединений и для server/client-соединений.
- **Ротируйте сертификаты до истечения срока:** листовые — подменой файлов (hot-reload), CA — rolling restart. Автоматизация: `kubeadm certs renew`, `cert-manager`, `cfssl`; в OpenShift — cluster-etcd-operator.
- **KMS для Encryption at Rest:** Никогда не храните ключи шифрования в том же месте, что и данные.
- **RBAC:** Ограничьте доступ к `/` только для `root`. Используйте префиксы для разделения прав.
- **Снапшоты = plaintext:** снапшоты содержат все данные (включая секреты) в открытом виде, если не включено шифрование на уровне API-сервера. Храните бэкапы с теми же правами, что и сами секреты (см. [Стратегии бэкапа](./backup_strategies.md)).
- **Не используйте `--auto-tls` в production:** self-signed сертификаты шифруют, но не аутентифицируют стороны.

---

## Edge Cases

- **Self-signed CA:** В production используйте Intermediate CA, а не self-signed root. Root CA должен быть offline.
- **Wildcard SAN:** Не используйте wildcard (`*.example.com`) для peer сертификатов. Указывайте явные IP/DNS.
- **etcdctl auth enable без root:** Ошибка. Всегда создавайте пользователя `root` с правами `readwrite /` перед `auth enable`.
- **Mixed TLS modes:** Нельзя иметь часть узлов с TLS, часть без. Все узлы должны иметь одинаковую конфигурацию TLS.
- **CN-auth + gRPC-proxy/gateway:** CN-based аутентификация несовместима с gRPC-proxy и gRPC-gateway — они терминируют TLS, и сервер видит CN прокси вместо CN клиента.
- **Логическая миграция (get/put):** перенос ключей через `etcdctl get`/`put` не переносит RBAC-пользователей и роли — их нужно воссоздать отдельно (см. [Аварийное восстановление](./emergency_recovery.md)).

---

## См. также

* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — TLS параметры в etcd.conf.yml.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — полный набор RBAC команд.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — Peer TLS в K8s.
* **[etcd в Kubernetes: интеграция](./kubernetes_integration.md)** — сертификаты etcd в kubeadm, проверка срока действия.
* **[Хранение Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md)** — EncryptionConfiguration и KMS v2 (SSoT по шифрованию).
* **[Альтернативы etcd и безопасность](../Kubernetes/Concepts/etcd_alternatives_and_security.md)** — mTLS, RBAC и аудит на уровне K8s.
* **[Аудит Kubernetes](../Kubernetes/Security/audit.md)** — почему прямой доступ к etcd не логируется.
