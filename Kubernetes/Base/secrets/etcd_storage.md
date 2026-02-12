# Хранение секретов в etcd

## Как хранятся секреты в etcd

**etcd** — это распределенное key-value хранилище, используемое Kubernetes для хранения всех объектов кластера.

**Структура хранения:**
```
/registry/secrets/<namespace>/<secret-name>
```

**Формат хранения:**
- Secrets хранятся в etcd в виде serialized объектов
- Данные в поле `data` закодированы в **Base64** (не шифрование!)
- Без Encryption at Rest, любой, кто имеет доступ к etcd, может прочитать секреты

## Как просмотреть ресурсы в etcd

### Использование etcdctl

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

### Просмотр через API Server (рекомендуется)

```bash
# Просмотр секрета через kubectl (автоматически декодирует base64)
kubectl get secret my-secret -o yaml

# Декодирование значения вручную
echo "bXktc3VwZXItc2VjcmV0LXBhc3N3b3Jk" | base64 -d

# Просмотр всех секретов в namespace
kubectl get secrets

# Просмотр секретов во всех namespaces
kubectl get secrets --all-namespaces
```

## Безопасность etcd

### Шифрование at-rest (Encryption at Rest)

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

# Перезапускаем API server
# Все новые секреты шифруются key2
# Перешифровываем старые:
kubectl get secrets --all-namespaces -o json | kubectl replace -f -
```
