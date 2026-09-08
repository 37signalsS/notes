# Безопасность etcd: TLS, RBAC и шифрование

**etcd** хранит все секреты Kubernetes и конфигурации кластера. Компрометация etcd = компрометация всего кластера. Данный документ описывает практические меры безопасности для production.

## Определения

| Термин | Описание |
| :--- | :--- |
| **mTLS** | Взаимная TLS-аутентификация. И клиент, и сервер проверяют сертификаты друг друга. |
| **Peer TLS** | Шифрование и аутентификация коммуникации между узлами кластера (порт 2380). |
| **Client TLS** | Шифрование и аутентификация коммуникации между клиентами и etcd (порт 2379). |
| **RBAC** | Role-Based Access Control. Разграничение прав доступа к ключам. |
| **Encryption at Rest** | Шифрование данных на диске. В etcd 3.7+ поддерживается через KMS или анн. |
| **Certificate Rotation** | Автоматическая или ручная замена сертификатов до истечения срока. |
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

### Client TLS

Клиенты (etcdctl, kube-apiserver) подключаются к порту 2379.
- **Требование:** `--client-cert-auth=true` на сервере.
- **Сертификаты:** Обычно выписываются на `kube-apiserver`, CN/SAN должны включать `kube-apiserver`.

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

### Encryption at Rest

etcd 3.7+ поддерживает шифрование данных на диске через KMS или встроенный encryption provider. На уровне Kubernetes шифрование реализуется через `EncryptionConfiguration` в `kube-apiserver` и применяется **до** отправки данных в etcd.

**Best Practice:** Используйте KMS (KMS v2) для управления ключами. Локальный AES-key в конфиге — single point of failure (если конфиг украдут, данные расшифровываются). Настройка EncryptionConfiguration, процедура включения шифрования на работающем кластере, ротация ключей и полная шпаргалка по `etcdctl` — см. **[Хранение Secret в etcd](../Kubernetes/Base/secrets/etcd_storage.md)** (SSoT).

---

## Практические сценарии

### Проверка TLS-соединения

```bash
# Проверить peer TLS
openssl s_client -connect 10.0.1.10:2380 -showcerts

# Проверить client TLS
openssl s_client -connect 10.0.1.10:2379 -showcerts

# Проверить отзыв сертификата (CRL)
openssl verify -CAfile /etc/etcd/pki/ca.crt /etc/etcd/pki/server.crt
# → OK
```

### Ротация сертификатов без даунтайма

etcd поддерживает graceful certificate rotation (v3.5+):

1. **Новый CA:** Сгенерируйте новый CA (или используйте существующий).
2. **Новые сертификаты:** Выпустите новые сертификаты с тем же CN/SAN.
3. **Перезапуск с новыми сертификатами:**
   ```bash
   systemctl restart etcd
   ```
4. **Проверка:**
   ```bash
   etcdctl endpoint health --cluster
   ```

**Важно:** Старые сертификаты должны оставаться валидными во время ротации, иначе peer-соединения разорвутся.

### Аудит прав доступа

```bash
# Список пользователей
etcdctl user list

# Права роли
etcdctl role get-permission admin-role

# Проверить доступ
ETCDCTL_API=3 etcdctl --user=admin:secret get /k8s/secret --prefix
```

---

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `x509: certificate is valid for ..., not ...` | CN/SAN не совпадает с `--name` или `--advertise-client-urls` | Проверить сертификат и конфиг |
| `tls: first record does not look like a TLS handshake` | Клиент не использует TLS, а сервер требует | Проверить `ETCDCTL_CACERT`, `ETCDCTL_CERT`, `ETCDCTL_KEY` |
| `etcdserver: authentication is enabled but no credentials provided` | RBAC включен, клиент не передал credentials | Добавить `--user` или env vars |
| `etcdserver: permission denied` | Роль не имеет прав на ключ | Проверить `etcdctl role get-permission` |
| `etcdserver: invalid auth token` | Токен истек или поврежден | Пересоздать token; проверить `etcdctl auth status` |

---

## Best Practices

- **Peer TLS — обязательно:** Никогда не запускайте production-кластер без шифрования peer-соединений.
- **Отдельный CA для etcd:** Не используйте тот же CA, что и для Kubernetes API. Компрометация etcd- CA = компрометация всего кластера.
- **Rotate сертификаты каждые 12 месяцев:** Автоматизируйте через `cert-manager` или `etcd-certificates`.
- **KMS для Encryption at Rest:** Никогда не храните ключи шифрования в том же месте, что и данные.
- **RBAC:** Ограничьте доступ к `/` только для `root`. Используйте префиксы для разделения прав.

---

## Edge Cases

- **Self-signed CA:** В production используйтеIntermediate CA, а не self-signed root. Root CA должен быть offline.
- **Wildcard SAN:** Не используйте wildcard (`*.example.com`) для peer сертификатов. Указывайте явные IP/DNS.
- **etcdctl auth enable без root:** Ошибка. Всегда создавайте пользователя `root` с правами `readwrite /` перед `auth enable`.
- **Mixed TLS modes:** Нельзя иметь часть узлов с TLS, часть без. Все узлы должны иметь одинаковую конфигурацию TLS.

---

## См. также

* **[Конфигурация и развертывание](./configuration_and_deployment.md)** — TLS параметры в etcd.conf.yml.
* **[Шпаргалка etcdctl](./etcdctl_cheatsheet.md)** — RBAC команды.
* **[Кластеризация и восстановление](./clustering_and_recovery.md)** — Peer TLS в K8s.
