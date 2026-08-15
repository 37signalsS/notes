# Sealed Secrets

## Определения

- **Sealed Secrets**: Инструмент от Bitnami для безопасного хранения Kubernetes Secrets в публичных Git-репозиториях через асимметричное шифрование. Позволяет реализовать полноценный GitOps для чувствительных данных.
- **SealedSecret**: Кастомный ресурс Kubernetes (CRD), содержащий зашифрованные данные. Предназначен для хранения в системе контроля версий.
- **Controller**: Оператор, развернутый в кластере. Управляет ключевыми парами и автоматически расшифровывает `SealedSecret` в нативные `Secret`.
- **kubeseal**: CLI-утилита для локального или CI/CD шифрования манифестов `Secret` публичным ключом контроллера.
- **Master Key**: Пара ключей RSA (публичный и приватный), генерируемая контроллером. Хранится в виде обычного Kubernetes Secret в пространстве имен контроллера (обычно `kube-system`) с меткой `sealedsecrets.bitnami.com/sealed-secrets-key`.

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

**Резервное копирование мастер-ключа (КРИТИЧНО):**
Если вы потеряете мастер-ключ, все ваши зашифрованные секреты в Git станут бесполезны.
```bash
# Поиск секрета с ключом (имеет метку sealedsecrets.bitnami.com/sealed-secrets-key)
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-master-key.yaml
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

### Сценарий 3: RBAC для CI/CD

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

### Сценарий 4: Интеграция с Argo CD

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

### Сценарий 6: Ротация ключей и перешифрование

Контроллер по умолчанию создает новый ключ каждые 30 дней. Все старые ключи сохраняются. Для повышения безопасности рекомендуется перешифровывать секреты в Git актуальным ключом:

```bash
# Перешифрование существующего SealedSecret на новый сертификат
kubeseal --re-encrypt < old.sealed.yaml --cert new-pub-cert.pem > new.sealed.yaml
```

### Сценарий 7: Troubleshooting (Диагностика)

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

## Дополнительная информация

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
