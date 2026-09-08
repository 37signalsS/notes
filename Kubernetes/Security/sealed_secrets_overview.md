# Sealed Secrets

## Определения

- **Sealed Secrets**: Инструмент от Bitnami для безопасного хранения Kubernetes Secrets в публичных Git-репозиториях через асимметричное шифрование. Позволяет реализовать полноценный GitOps для чувствительных данных.
- **SealedSecret**: Кастомный ресурс Kubernetes (CRD), содержащий зашифрованные данные. Предназначен для хранения в системе контроля версий.
- **Controller**: Оператор, развернутый в кластере. Управляет ключевыми парами и автоматически расшифровывает `SealedSecret` в нативные `Secret`.
- **kubeseal**: CLI-утилита для локального или CI/CD шифрования манифестов `Secret` публичным ключом контроллера.
- **Master Key**: Пара ключей RSA (публичный и приватный), генерируемая контроллером. Хранится в виде обычного Kubernetes Secret в пространстве имен контроллера (обычно `kube-system`) с меткой `sealedsecrets.bitnami.com/sealed-secrets-key`.
- **Scope**: Параметр шифрования, определяющий степень привязки зашифрованного секрета к метаданным (имя, namespace).
- **Certificate Rotation**: Процесс обновления пары ключей контроллера. По умолчанию автоматический каждые 30 дней. Старые ключи сохраняются для расшифровки ранее зашифрованных секретов.
- **Encryption at Rest**: Шифрование нативных Kubernetes Secret в etcd с использованием KMS (Kubernetes Management System). Дополняет Sealed Secrets, защищая расшифрованные секреты на уровне хранилища кластера.
- **External Secrets Operator (ESO)**: Альтернативный инструмент, который синхронизирует секреты из внешних хранилищ (Vault, AWS Secrets Manager) в нативные Kubernetes Secret. В отличие от Sealed Secrets, не хранит шифротекст в Git.
- **SOPS (Secrets OPerationS)**: Инструмент Mozilla для шифрования файлов (YAML, JSON, ENV) с использованием age-ключей или KMS (AWS/GCP/Azure). В отличие от Sealed Secrets, шифрует весь файл, а не отдельные значения.
- **Helm Secrets**: Плагин для Helm, интегрирующий SOPS или Sealed Secrets для шифрования секретов в values-файлах.

### Версии и совместимость

| Версия контроллера | Минимальная версия kubeseal | Формат | Примечания |
|:---|:---|:---|:---|
| v0.27.x | v0.27.x | `bitnami.com/v1alpha1` | Устаревший формат, не рекомендуется. |
| v0.28.x | v0.28.x | `bitnami.com/v1alpha1` | Обновленный формат с поддержкой scope. |
| v0.29.x | v0.29.x | `bitnami.com/v1alpha1` | Добавлена поддержка старых ключей. |
| v0.30.x | v0.30.x | `bitnami.com/v1alpha1` | Исправления безопасности. |
| v0.31.x | v0.31.x | `bitnami.com/v1alpha1` | Улучшенная поддержка scope. |
| v0.32.x | v0.32.x | `bitnami.com/v1alpha1` | Исправления для multi-tenant. |
| v0.33.x | v0.33.x | `bitnami.com/v1alpha1` | Улучшенная диагностика. |
| v0.34.x | v0.34.x | `bitnami.com/v1alpha1` | Улучшенная поддержка Helm. |
| v0.35.x | v0.35.x | `bitnami.com/v1alpha1` | Оптимизации производительности. |
| v0.36.x | v0.36.x | `bitnami.com/v1alpha1` | Улучшенная поддержка кастомных сертификатов. |
| v0.37.x | v0.37.x | `bitnami.com/v1alpha1` | Добавлена поддержка ED25519. |
| v0.38.x | v0.38.x | `bitnami.com/v1alpha1` | Улучшенная безопасность шифрования. |
| v0.39.x | v0.39.x | `bitnami.com/v1alpha1` | Актуальная стабильная версия. |

**Важно:** Версии kubeseal и контроллера должны совпадать по минорной версии (например, kubeseal v0.39.x работает с контроллером v0.39.x). Использование несовместимых версий может привести к ошибкам расшифровки.

### Сертификаты

Контроллер Sealed Secrets генерирует пару ключей RSA и соответствующий самоподписанный сертификат. Ключи хранятся в Secret в namespace контроллера:

```bash
# Просмотр ключей контроллера
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml

# Просмотр деталей сертификата
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o jsonpath='{.items[0].data.tls\.crt}' | base64 -d | openssl x509 -text -noout
```

**Типы ключей:**
- `tls.key` — приватный RSA ключ (ใช้ สำหรับ расшифровку)
- `tls.crt` — публичный сертификат (используется для шифрования)
- `sealed-secrets-key` — Kubernetes Secret, содержащий оба ключа

**Кастомные сертификаты:** Для соответствия политикам безопасности организации можно предоставить собственный сертификат:

```bash
# Генерация собственной пары ключей
openssl genrsa -out tls.key 4096
openssl req -x509 -new -nodes -key tls.key -sha256 -days 3650 -out tls.crt \
  -subj "/CN=sealed-secrets/O=MyOrg"

# Создание Secret с кастомными ключами
kubectl create secret tls sealed-secrets-custom-key \
  --cert=tls.crt --key=tls.key -n kube-system \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Метрики для мониторинга

Контроллер Sealed Secrets предоставляет Prometheus-метрики (по умолчанию на порту `:9090/metrics`):

```yaml
# Сервис для метрик
apiVersion: v1
kind: Service
metadata:
  name: sealed-secrets-metrics
  namespace: kube-system
  labels:
    app.kubernetes.io/name: sealed-secrets
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
spec:
  ports:
  - name: metrics
    port: 9090
    targetPort: 9090
  selector:
    app.kubernetes.io/name: sealed-secrets
```

**Ключевые метрики:**
- `sealed_secrets_controller_unsealed_total` — количество расшифрованных секретов.
- `sealed_secrets_controller_encrypted_total` — количество зашифрованных секретов.
- `sealed_secrets_controller_key_rotation_total` — количество ротаций ключей.
- `sealed_secrets_controller_sealed_secret_reconcile_errors_total` — ошибки при reconciliation.
- `sealed_secrets_controller_sealed_secret_reconcile_duration_seconds` — длительность reconciliation.

**Пример алерта в Prometheus:**
```yaml
groups:
- name: sealed-secrets
  rules:
  - alert: SealedSecretReconcileErrors
    expr: rate(sealed_secrets_controller_sealed_secret_reconcile_errors_total[5m]) > 0
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Sealed Secrets reconciliation errors"
      description: "Контроллер sealed-secrets обнаруживает ошибки reconciliation."
```

## Основные концепции

### Почему недостаточно стандартных Secrets?
Основная проблема нативных Kubernetes Secrets заключается в том, что они **не зашифрованы**, а только **закодированы в Base64**. Это означает, что любой, кто имеет доступ к YAML-файлу манифеста, может мгновенно получить пароли в открытом виде:
```bash
# Пример декодирования пароля из обычного манифеста Secret
echo "dGVzdC1wYXNzd29yZA==" | base64 --decode # → test-password
```
Хранение таких файлов в Git (даже приватном) нарушает принципы безопасности. Sealed Secrets решает эту проблему, позволяя хранить в Git зашифрованный `SealedSecret`, который может быть расшифрован только внутри целевого кластера.

### Архитектура и криптографическая схема

Компоненты системы:

| Компонент | Расположение | Функция |
|-----------|--------------|---------|
| Controller | В кластере | Генерация ключей, расшифровка |
| kubeseal | Локально/CI | Шифрование с публичным ключом |
| SealedSecret | Git-репозиторий | Безопасное хранение |
| Secret | В кластере | Расшифрованный секрет для Pod'ов |

### Гибридная схема шифрования

Для обеспечения безопасности и производительности Sealed Secrets использует гибридную схему. Для каждого значения секрета:

1. **Генерация сессионного ключа**: Генерируется случайный симметричный ключ.
2. **Шифрование данных**: Данные шифруются алгоритмом **AES-GCM** с использованием симметричного ключа.
3. **Шифрование ключа**: Симметричный ключ шифруется алгоритмом **RSA-OAEP** публичным ключом контроллера.
4. **Привязка контекста**: В зашифрованные данные вшивается информация об имени и пространстве имен секрета (в зависимости от Scope) для предотвращения атак подмены.

### Области шифрования (Scope)

Область определяет, насколько жестко зашифрованный секрет привязан к своим метаданным.

| Режим | Привязка | Переносимость | Назначение |
|-------|----------|---------------|------------|
| `strict` (по умолчанию) | Имя + namespace | Нет | Максимальная безопасность. Секрет нельзя переименовать или переместить в другой namespace. |
| `namespace-wide` | Только namespace | Ограниченная | Позволяет переименовывать секрет, но фиксирует его в рамках одного namespace. |
| `cluster-wide` | Нет | Высокая | Секрет можно переименовывать и перемещать между любыми namespace внутри кластера. |

### Жизненный цикл

1. **Создание**: Разработчик создаёт обычный манифест `Secret`.
2. **Шифрование**: Утилита `kubeseal` шифрует его публичным ключом контроллера.
3. **Хранение**: Ресурс `SealedSecret` коммитится в Git-репозиторий.
4. **Деплой**: Ресурс применяется в кластер (через `kubectl` или GitOps-оператор).
5. **Расшифровка**: Контроллер обнаруживает `SealedSecret` и создает нативный `Secret`.
6. **Использование**: Pod'ы монтируют созданный `Secret` стандартными средствами Kubernetes.

## Практические сценарии

### Сценарий 1: Установка и резервное копирование ключей

**Установка контроллера:**
```bash
# Установка с помощью Helm 3
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm repo update
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets
```

**Установка в пользовательский namespace (не рекомендуется, но возможно):**
```bash
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace sealed-secrets-system \
  --create-namespace \
  --set fullnameOverride=sealed-secrets

# Тогда kubeseal нужно вызывать с явными флагами:
kubeseal --controller-name=sealed-secrets --controller-namespace=sealed-secrets-system
```

**Резервное копирование мастер-ключа (КРИТИЧНО):**
Если вы потеряете мастер-ключ, все ваши зашифрованные секреты в Git станут бесполезны.
```bash
# Поиск секрета с ключом (имеет метку sealedsecrets.bitnami.com/sealed-secrets-key)
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-master-key.yaml

# Автоматический бэкап с таймстампом
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  > "sealed-secrets-master-key-$(date +%Y%m%d-%H%M%S).yaml"

# Бэкап всех ключей (включая старые, для расшифровки legacy-секретов)
kubectl get secrets -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml \
  > sealed-secrets-all-keys-backup.yaml
```

### Сценарий 2: Шифрование секрета

Для шифрования `kubeseal` должен иметь доступ к публичному сертификату контроллера.

**Вариант А: Онлайн-шифрование (нужен доступ к API кластера)**
```bash
kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system < secret.yaml > sealed-secret.yaml
```

**Вариант Б: Оффлайн-шифрование (рекомендуется для CI/CD)**
1. Получите сертификат один раз (требуется доступ к кластеру):
```bash
kubeseal --controller-name=sealed-secrets --controller-namespace=kube-system --fetch-cert > pub-cert.pem
```
2. Используйте сертификат для шифрования без доступа к кластеру:
```bash
kubeseal --cert pub-cert.pem --format yaml < secret.yaml > sealed-secret.yaml
```

**Шифрование с указанием scope:**
```bash
# Scope: strict (по умолчанию) — привязка к имени и namespace
kubeseal --scope strict --format yaml < secret.yaml > sealed-secret.yaml

# Scope: namespace-wide — секрет можно переименовать в рамках namespace
kubeseal --scope namespace-wide --format yaml < secret.yaml > sealed-secret.yaml

# Scope: cluster-wide — секрет можно перемещать между любыми namespace
kubeseal --scope cluster-wide --format yaml < secret.yaml > sealed-secret.yaml
```

**Полный пример создания с нуля:**
```bash
# 1. Создаем манифест обычного секрета (локально)
kubectl create secret generic my-db-secret \
  --from-literal=password='P@ssw0rd123!' \
  --dry-run=client -o yaml > secret.yaml

# 2. Шифруем его в SealedSecret
kubeseal --cert pub-cert.pem --format yaml < secret.yaml > my-sealed-secret.yaml

# 3. Применяем зашифрованный манифест
kubectl apply -f my-sealed-secret.yaml

# 4. Проверяем появление расшифрованного секрета контроллером
kubectl get secret my-db-secret
```

### Сценарий 3: Извлечение исходного секрета (decrypt/unseal)

Иногда необходимо извлечь исходное значение из SealedSecret для отладки или миграции:

```bash
# Извлечение значения из SealedSecret (требует приватного ключа контроллера)
kubectl get sealedsecret my-db-secret -o jsonpath='{.spec.encryptedData.password}' | \
  base64 -d | kubeseal --recovery-unseal --recovery-private-key <(kubectl get secret -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o jsonpath='{.items[0].data.tls\.key}' | base64 -d)

# Альтернативный способ (через(controller pod)
kubectl exec -n kube-system deploy/sealed-secrets -- \
  kubeseal --recovery-unseal --recovery-private-key /etc/sealed-secrets/tls.key \
  < sealed-secret.yaml
```

**Важно:** Этот процесс требует доступа к приватному ключу контроллера. Используйте только в экстренных ситуациях (потеря исходных секретов, миграция между кластерами).

### Сценарий 4: RBAC для CI/CD

Ограничение прав CI-системы только созданием и управлением `SealedSecret`, без доступа к расшифрованным секретам:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ci-sealed-writer
  namespace: app
rules:
- apiGroups: ["bitnami.com"]
  resources: ["sealedsecrets"]
  verbs: ["create", "get", "list", "patch", "update"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ci-sealed-writer
  namespace: app
subjects:
- kind: ServiceAccount
  name: ci-runner
  namespace: app
roleRef:
  kind: Role
  name: ci-sealed-writer
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 5: Интеграция с Argo CD

При использовании Argo CD для синхронизации `SealedSecret`, важно настроить политику синхронизации:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-app
spec:
  source:
    repoURL: https://github.com/org/repo.git
    targetRevision: main
    path: overlays/production
  destination:
    server: https://kubernetes.default.svc
    namespace: production
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
    - CreateNamespace=true
```

### Сценарий 5: Работа с Helm-чартами

Рекомендуется хранить зашифрованные строки в `values.yaml`, а в шаблонах использовать структуру `SealedSecret`:

```yaml
# templates/sealedsecret.yaml
apiVersion: bitnami.com/v1alpha1
kind: SealedSecret
metadata:
  name: {{ include "mychart.fullname" . }}-db-pass
spec:
  encryptedData:
    password: {{ .Values.secrets.dbPasswordEncrypted | quote }}
```

**Helm Secrets (альтернативный подход):**
Используйте плагин `helm-secrets` для шифрования secrets-файлов при деплое. Подробное руководство см. в [Helm + секреты](../../Base/secrets/helm_secrets.md).

```bash
# Установка плагина
helm plugin install https://github.com/jkroepke/helm-secrets --version v4.6.2

# Шифрование values-файла
sops -e secrets.yaml > secrets.enc.yaml

# Деплой с расшифрованными секретами
helm secrets upgrade --install my-app . -f values.yaml -f secrets.enc.yaml
```

### Сценарий 6: Интеграция с Kustomize

Kustomize не имеет нативной поддержки шифрования секретов. Sealed Secrets решает эту проблему:

```yaml
# kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- sealed-secret.yaml  # Зашифрованный SealedSecret
- deployment.yaml
- service.yaml
```

**Процесс:**
1. Создайте обычный `Secret` (никогда не коммитьте его в Git).
2. Зашифровать через `kubeseal`: `kubeseal --format yaml < secret.yaml > sealed-secret.yaml`.
3. Добавьте `sealed-secret.yaml` в Kustomize resources.
4. Kustomize применит `SealedSecret`, контроллер расшифрует его в нативный `Secret`.

### Сценарий 7: Ротация ключей и перешифрование

Контроллер по умолчанию создает новый ключ каждые 30 дней. Все старые ключи сохраняются. Для повышения безопасности рекомендуется перешифровывать секреты в Git актуальным ключом:

```bash
# Ручная ротация ключей
kubeseal --rotate-keys

# Перешифрование существующего SealedSecret на новый сертификат
kubeseal --re-encrypt < old.sealed.yaml --cert new-pub-cert.pem > new.sealed.yaml

# Полный цикл ротации (佳 Example for SRE)
kubeseal --rotate-keys
kubeseal --fetch-cert > pub-cert-$(date +%Y%m%d).pem

# Перешифровка всех SealedSecret в репозитории
for f in $(find . -name "*.sealed.yaml"); do
  kubeseal --re-encrypt < "$f" > "${f}.tmp" && mv "${f}.tmp" "$f"
done
```

### Сценарий 8: CI/CD пайплайн (GitHub Actions)

**Шаг 1: Настройка GitHub Secrets**
- `KUBE_CONFIG`: base64-encoded kubeconfig для доступа к кластеру.
- `PUB_CERT`: публичный сертификат контроллера (получен через `kubeseal --fetch-cert`).

**Шаг 2: GitHub Actions workflow**
```yaml
# .github/workflows/deploy-sealed-secrets.yml
name: Deploy Sealed Secrets

on:
  push:
    branches: [main]
    paths:
    - 'secrets/**'
    - 'manifests/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
    - name: Checkout
      uses: actions/checkout@v4

    - name: Install kubeseal
      run: |
        wget https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.39.1/kubeseal-linux-amd64 -O kubeseal
        chmod +x kubeseal
        sudo mv kubeseal /usr/local/bin/

    - name: Encrypt secrets
      run: |
        for f in secrets/*.yaml; do
          kubeseal --cert <(echo "${{ secrets.PUB_CERT }}") \
            --format yaml < "$f" > "manifests/$(basename "$f" .yaml)-sealed.yaml"
        done

    - name: Apply to cluster
      run: |
        echo "${{ secrets.KUBE_CONFIG }}" | base64 -d > /tmp/kubeconfig
        kubectl --kubeconfig=/tmp/kubeconfig apply -f manifests/
```

### Сценарий 9: Восстановление из бэкапа (Disaster Recovery)

**Ситуация:** Кластер потерян, но Git-репозиторий с SealedSecret и бэкап мастер-ключа сохранены.

**Шаг 1: Восстановление контроллера**
```bash
# Установка контроллера на новый кластер
helm install sealed-secrets sealed-secrets/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets

# Восстановление мастер-ключа из бэкапа
kubectl apply -f sealed-secrets-master-key-backup.yaml

# Проверка расшифровки (должен появиться нативный Secret)
kubectl get sealedsecret my-db-secret -n app
```

**Шаг 2: Проверка расшифровки**
```bash
# Ожидание создания Secret контроллером
kubectl wait --for=condition=Ready sealedsecret/my-db-secret -n app --timeout=60s

# Проверка наличия расшифрованного секрета
kubectl get secret my-db-secret -n app -o yaml
```

**Важно:** Если бэкап мастер-ключа утерян, расшифровка невозможна. Единственный выход — создать новые SealedSecret с нуля (шифрование новым ключом контроллера на новом кластере).

### Сценарий 10: Troubleshooting (Диагностика)

**Проблема:** `kubeseal` не может получить сертификат (`error: cannot get sealed secret service`).
- **Причина:** Сервис контроллера имеет нестандартное имя или находится в другом namespace, и `kubeseal` не может найти его автоматически.
- **Решение:** Укажите параметры контроллера явно через флаги:
  ```bash
  # Если сервис называется по-другому или в другом namespace
  kubeseal --controller-name=имя-сервиса --controller-namespace=namespace-контроллера --fetch-cert
  ```

**Проблема:** SealedSecret не превращается в Secret.
1. Проверьте логи контроллера: `kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets`.
2. Проверьте события ресурса: `kubectl describe sealedsecret <name>`.
3. Ошибка `decryption error: no key could decrypt secret` обычно означает:
   - Секрет зашифрован ключом другого кластера.
   - Изменены имя или namespace в режиме `strict`.
   - Мастер-ключ был удален/изменен без восстановления бэкапа.

### Диагностические команды

```bash
# Просмотр всех SealedSecret в кластере
kubectl get sealedsecret --all-namespaces

# Просмотр статуса конкретного SealedSecret
kubectl describe sealedsecret <name> -n <namespace>

# Проверка наличия расшифрованного секрета
kubectl get secret <name> -n <namespace>

# Просмотр логов контроллера (поиск ошибок расшифровки)
kubectl logs -n kube-system -l app.kubernetes.io/name=sealed-secrets --tail=100 | grep -i "error\|decrypt\|unmarshal"

# Проверка ключей контроллера
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml

# Просмотр деталей ключа (дата создания, серийный номер)
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o jsonpath='{.items[0].data.tls\.crt}' | base64 -d | openssl x509 -text -noout

# Проверка версии контроллера
kubectl get deployment -n kube-system -l app.kubernetes.io/name=sealed-secrets \
  -o jsonpath='{.items[0].spec.template.spec.containers[0].image}'

# Тест шифрования/расшифровки (проверка работы kubeseal)
echo -n "test" | kubeseal --cert pub-cert.pem --format yaml | kubeseal --recovery-unseal \
  --recovery-private-key <(kubectl get secret -n kube-system \
  -l sealedsecrets.bitnami.com/sealed-secrets-key \
  -o jsonpath='{.items[0].data.tls\.key}' | base64 -d) --format yaml
```

## Дополнительная информация

### Типичные ошибки (Antipatterns)

1. **Хранение исходного Secret в Git** — даже временно. Используйте `kubectl create secret --dry-run=client` и pipe в `kubeseal`.
2. **Потеря бэкапа мастер-ключа** — без приватного ключа расшифровка невозможна. Регулярно бэкапируйте и храните в безопасном месте (Vault, offline storage).
3. **Использование scope `cluster-wide` без необходимости** — снижает безопасность. Используйте `strict` по умолчанию.
4. **Некорректное именование** — в режиме `strict` переименование SealedSecret делает его нерасшифровываемым.
5. **Отсутствие ротации ключей** — старые ключи могут быть скомпрометированы. Ротируйте регулярно.
6. **Смешивание ключей разных кластеров** — SealedSecret зашифрован для конкретного кластера. Не применяйте манифесты из одного кластера в другой.
7. **Отсутствие мониторинга** — настройте алерты на ошибки reconciliation в Prometheus.

### Сравнение инструментов шифрования секретов

| Критерий | Sealed Secrets | SOPS | External Secrets Operator |
|:---|:---|:---|:---|
| **Хранение в Git** | Да (зашифрованный SealedSecret) | Да (зашифрованный файл) | Нет (ссылки на внешнее хранилище) |
| **Внешняя инфраструктура** | Не требуется | Требуется (age-ключ или KMS) | Требуется (Vault, AWS SM и т.д.) |
| **Привязка к кластеру** | Да (ключи уникальны) | Нет (ключи общие) | Нет (синхронизация извне) |
| **Ротация секретов** | Ручная (только шифрование) | Ручная | Автоматическая (sync из Vault) |
| **Динамические секреты** | Нет | Нет | Да (generate из Vault) |
| **Сложность настройки** | Низкая | Средняя | Высокая |
| **Поддержка Helm** | Да (через шаблоны) | Да (через helm-secrets) | Да (через chart) |
| **Поддержка Kustomize** | Да (через ресурсы) | Да (через patch) | Да (через ресурсы) |

### Преимущества

- **Безопасность**: Секреты в открытом виде никогда не попадают в Git.
- **Декларативность**: Полная совместимость с GitOps-пайплайнами.
- **Аудит**: История изменений через Git-логи.
- **Изоляция**: Каждый кластер имеет уникальную ключевую пару по умолчанию.

### Модель угроз

| Угроза | Уровень | Митигация |
|--------|---------|-----------|
| Компрометация приватного мастер-ключа | Критический | Защита [RBAC](./rbac/rbac_overview.md) к секретам контроллера, включение шифрования etcd (Encryption at rest). |
| Перенос между кластерами | Низкий | Ключи уникальны для каждого кластера по умолчанию. |
| Утечка в Git-репозиторий | Низкий | Данные зашифрованы асимметрично. |
| Физический доступ к etcd | Средний | Настройка [EncryptionConfiguration](../../Kubernetes/Base/secrets/security.md). |

### Ограничения

- Секреты жестко привязаны к кластеру (в режиме `strict` — также к namespace и имени).
- При потере всех приватных ключей контроллера расшифровка невозможна (требуется бэкап).
- Инструмент не обеспечивает автоматическую ротацию самих паролей (только шифрование для хранения).
- Для полноценной ротации паролей требуется автоматизация внешних систем.

### См. также

- **[External Secrets Operator](../Base/secrets/external_managers.md)** — интеграция с внешними KMS (Vault, AWS Secrets Manager).
- **[SOPS](../../Security/Tools/sops_overview.md)** — шифрование файлов с ключами AWS/GCP/Age без привязки к контроллеру.
- **[Vault](../../Vault/zero_trust.md)** — полноценная система управления секретами.
- Общий обзор стратегий — **[Secrets Management Overview](../../Security/Concepts/secrets_management_overview.md)**.
- Пайплайны GitOps — **[GitOps Secrets Encryption](../../GitOps/secrets_encryption.md)**.
- Паттерн динамической конфигурации — **[Application Secrets Management](./application_secrets_management.md)**.
