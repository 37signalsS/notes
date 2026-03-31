# Хранение Secret в etcd

## Определения

**etcd** — распределённое key-value хранилище Kubernetes для всех объектов кластера.

**Структура хранения:**

```
/registry/secrets/<namespace>/<secret-name>
```

**Формат:** Secret хранятся в etcd в сериализованном виде. Поле `data` закодировано в Base64 (не шифрование!).

> Без Encryption at Rest любой, имеющий доступ к etcd, может прочитать секреты. Подробнее о безопасности см. [Безопасность Secret](security.md).

## Основные концепции

### Принцип хранения

- **Путь в etcd:** `/registry/secrets/<namespace>/<name>`
- **Кодировка:** Base64 (не шифрование) — данные легко декодировать
- **Ограничение:** до 1 MiB на один Secret (ограничение etcd)

### Encryption at Rest

**Минимальная защита для production-кластеров.**

**Провайдеры шифрования:**

- **aescbc** — AES-CBC (256-bit), рекомендуется для большинства сценариев
- **aesgcm** — AES-GCM (более современный, но требует больше CPU)
- **secretbox** — XSalsa20-Poly1305 (альтернатива от Kubernetes)
- **kms** — интеграция с внешними KMS (AWS KMS, GCP KMS, Azure Key Vault)
- **identity** — без шифрования (только для чтения старых данных)

> **Подробнее:** [Шифрование etcd в etcd_alternatives_and_security.md](../../Concepts/etcd_alternatives_and_security.md#конфигурация-encryptionconfiguration)

## Практические сценарии

### Просмотр ресурсов в etcd

#### Через kubectl (рекомендуется)

```bash
kubectl get secret my-secret -o yaml

echo "bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk" | base64 -d
kubectl get secrets
kubectl get secrets --all-namespaces
```

#### Через etcdctl

```bash
# Установка etcdctl
export ETCDCTL_API=3

# Подключение к etcd (требуются сертификаты)
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/secrets/default/my-secret

# Просмотр всех секретов
etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  get /registry/secrets --prefix --keys-only
```

### Шифрование at-rest (Encryption at Rest)

**Это обязательный уровень защиты Secret в production.**

```yaml
# /etc/kubernetes/encryption-config.yaml
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
    - secrets
    - configmaps
    providers:
    - aescbc:
        keys:
        - name: key1
          secret: <base64-encoded-32-byte-key>
    - identity: {} # fallback для нешифрованных данных
```

### Ротация ключей шифрования

```yaml
# Добавляем новый ключ
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources:
    - secrets
    providers:
    - aescbc:
        keys:
        - name: key2 # Новый ключ первым
          secret: <new-base64-encoded-key>
        - name: key1
          secret: <old-base64-encoded-key>
```

После перезапуска API-сервера перешифруйте старые секреты:

```bash
kubectl get secrets --all-namespaces -o json | kubectl replace -f -
```

## Дополнительная информация

### Ограничения

Подробнее об ограничениях размера Secret см. в [Основах Secret](secrets_basics.md#ограничения).

### Связанные темы

[Основы Secret](secrets_basics.md), [Создание Secret](creating_secrets.md), [Безопасность Secret](security.md), [Внешние менеджеры](external_managers.md), [Шифрование etcd](../../Concepts/etcd_alternatives_and_security.md).
