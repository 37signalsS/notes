# Основы Kubernetes Secret

## Определения

**Secret** — это объект Kubernetes, предназначенный для хранения и управления конфиденциальной информацией, такой как пароли, OAuth-токены, SSH-ключи и API-ключи. Секреты обеспечивают безопасный способ передачи чувствительных данных в Pod, отделяя их от манифестов приложений и системных журналов.

**Кодирование vs Шифрование:** По умолчанию данные в Secret хранятся в etcd в кодировке **Base64**. Это **не является шифрованием**. Любой пользователь с доступом к API Kubernetes или базе данных etcd может декодировать эти данные. Для обеспечения реальной безопасности необходимо настроить **Encryption at Rest** (шифрование на уровне хранилища).

Подробнее см. [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Архитектура и жизненный цикл Secret

Понимание внутренней механики критично для диагностики проблем и проектирования надёжных систем.

**Путь данных от создания до Pod:**

```
kubectl / CI Pipeline
        ↓
   API Server (валидация, RBAC, запись в etcd)
        ↓
   etcd (хранение; шифрование, если настроено)
        ↓
   Kubelet (опрос API → получение/обновление содержимого)
        ↓
   Pod (volume mount или переменные окружения)
```

1. **Создание:** клиент (kubectl, контроллер, CI/CD) отправляет POST-запрос к API Server.
2. **Хранение:** API Server валидирует данные и записывает в etcd. По умолчанию данные хранятся в Base64 **без шифрования**.
3. **Доставка:** Kubelet (или sidecar) получает данные через API Server. При монтировании как Volume — атомарное обновление через симлинки (обновление до 1 минуты).
4. **Ротация:** при изменении Secret Kubelet обновляет файлы в томе (кроме `subPath` и неизменяемых секретов).

Подробнее о хранении и шифровании см. [Хранение в etcd](etcd_storage.md). О доставке в Pod см. [Использование Secret](using_secrets.md).

### Разделение конфигурации и секретов

Следование принципу **Separation of Concerns** (разделение ответственности) требует отделения чувствительных данных от общих настроек:
- **ConfigMap:** для неконфиденциальных данных (имена хостов, порты, параметры логирования).
- **Secret:** для учетных данных, ключей и сертификатов.

Это позволяет менять учетные данные без изменения кода приложения и использовать разные секреты для сред разработки (Dev) и эксплуатации (Prod).

### Изоляция на уровне Namespace

Секреты являются ресурсами, ограниченными пространством имен (**Namespaced resources**). Pod может использовать только те секреты, которые находятся в том же Namespace. Это обеспечивает базовый уровень изоляции между командами и приложениями в одном кластере.

> **Исключение:** Secret типа `kubernetes.io/service-account-token` с аннотацией `kubernetes.io/service-account.name` привязан к конкретному ServiceAccount и не может быть использован другими Pod'ами без соответствующего RBAC.

### Сравнение Secret и ConfigMap

| Признак | Secret | ConfigMap |
| :--- | :--- | :--- |
| **Назначение** | Конфиденциальные данные | Общие настройки |
| **Доступ** | Ограничен через RBAC (по умолчанию более строгий) | Доступен большинству пользователей |
| **Шифрование** | Поддерживается (Encryption at Rest) | Хранится в открытом виде |
| **Поля данных** | `data` (Base64), `stringData` (Plain text) | `data` (Plain text), `binaryData` |
| **Типичные сценарии** | Пароли, API-токены, SSH-ключи, TLS | Переменные окружения, файлы конфигурации |
| **Макс. размер** | 1 MiB (лимит etcd) | 1 MiB (лимит etcd) |
| **Автообновление в Pod** | Да (Volume); Нет (env) | Да (Volume); Нет (env) |

### Поля data и stringData

В манифесте Secret используются два поля для ввода данных:
- **data:** принимает значения, уже закодированные в Base64. Используется при автоматизированном создании секретов.
- **stringData:** принимает значения в открытом виде. Удобно для ручного редактирования манифестов. При сохранении Kubernetes автоматически кодирует эти данные в Base64 и переносит в поле `data`.
  - **Приоритет:** Если один и тот же ключ указан и в `data`, и в `stringData`, значение из `stringData` будет иметь приоритет и перезапишет `data`.
  - **Скрытие:** Поле `stringData` доступно только для записи и не отображается при выполнении `kubectl get secret -o yaml`.

**Практический нюанс — пробелы и переносы строк:**
```bash
# ⚠ ОШИБКА: перенос строки попадёт в пароль
echo "my-password" | base64
# → bXktcGFzc3dvcmQK  (末尾 'K' = перенос строки)

# ✓ ПРАВИЛЬНО: флаг -n убирает перенос
echo -n "my-password" | base64
# → bXktcGFzc3dvcmQ=
```

Проверить наличие лишних символов в существующем секрете:
```bash
kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d | cat -A
# Если в конце строки символ $ — лишний перенос
```

### Неизменяемые секреты (Immutable Secrets)

Начиная с Kubernetes 1.21+, секреты можно помечать как `immutable: true`. После этого объект нельзя изменить (только удалить и создать заново).

**Когда использовать:**
- Секреты, которые не предполагается менять после создания (сертификаты, статические ключи).
- Защита от случайной перезаписи в CI/CD пайплайнах.
- Снижение нагрузки на API server: kubelet не опрашивает неизменяемые секреты после первого чтения.

**Ограничение:** Для обновления неизменяемого секрета необходимо удалить старый Pod и создать новый со ссылкой на новый объект Secret.

Подробнее об использовании в Pod см. [Использование Secret](using_secrets.md).

### Типы Secret

Kubernetes предоставляет встроенные типы для валидации и автоматизации:

| Тип | Назначение | Структура данных | Пример ключей |
| :--- | :--- | :--- | :--- |
| **Opaque** | Универсальный (по умолчанию) | Произвольная | Любые пары ключ-значение |
| **kubernetes.io/tls** | TLS-сертификаты | `tls.crt`, `tls.key` | Сертификат + приватный ключ |
| **kubernetes.io/dockerconfigjson** | Доступ к приватным реестрам | `.dockerconfigjson` | Логин, пароль, email реестра |
| **kubernetes.io/basic-auth** | Пары логин/пароль | `username`, `password` | Basic Auth данные |
| **kubernetes.io/ssh-auth** | SSH-ключи | `ssh-privatekey` | Приватный ключ SSH |
| **kubernetes.io/service-account-token** | Токены ServiceAccount | `token`, `ca.crt`, `namespace` | Токен аутентификации |
| **bootstrap.kubernetes.io/token** | Присоединение узлов | `token-id`, `token-secret`, `usage-*` | Bootstrap токены |

> **Важно:** Каждый тип (кроме `Opaque`) требует наличия определённых ключей в поле `data`. При несоблюдении структуры API Server вернёт ошибку валидации.

### Метки и аннотации (Labels & Annotations)

Секреты поддерживают стандартные метки Kubernetes для организации и фильтрации:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  labels:
    app: my-app
    env: production
    team: backend
  annotations:
    description: "Основные учетные данные PostgreSQL"
    managed-by: "helm"
```

**Практическое применение:**
```bash
# Поиск секретов по меткам
kubectl get secrets -l app=my-app,env=production

# Резервное копирование всех секретов команды
kubectl get secrets -l team=backend -o yaml > team-secrets-backup.yaml
```

> **Связь с RBAC:** Метки можно использовать в условиях `RoleBinding` для динамического контроля доступа. Однако встроенные условия RBAC поддерживают только `resourceNames`, а не селекторы меток. Для фильтрации по меткам используйте Policy Engines (OPA/Gatekeeper, Kyverno).

## Практические сценарии

### Императивное создание (kubectl)

Kubernetes предоставляет несколько вариантов `kubectl create secret` для разных типов данных:

| Команда | Тип Secret | Назначение |
| :--- | :--- | :--- |
| `kubectl create secret generic` | Opaque | Произвольные пары ключ-значение |
| `kubectl create secret generic --type=kubernetes.io/tls` | kubernetes.io/tls | TLS-сертификаты (ключ + сертификат) |
| `kubectl create secret tls` | kubernetes.io/tls | TLS-сертификаты (ключ + сертификат, отдельная подкоманда) |
| `kubectl create secret docker-registry` | kubernetes.io/dockerconfigjson | Учётные данные приватных реестров |
| `kubectl create secret generic --type=kubernetes.io/ssh-auth` | kubernetes.io/ssh-auth | SSH-приватные ключи |
| `kubectl create secret generic --type=kubernetes.io/basic-auth` | kubernetes.io/basic-auth | Пары логин/пароль |
| манифест + аннотация `kubernetes.io/service-account.name` | kubernetes.io/service-account-token | Долгоживущий токен SA (подкоманды нет) |

> **Примечание:** подкоманды `kubectl create secret ssh-auth|basic-auth|service-account-token` **не существуют**. Типизированные секреты создаются через `generic --type=...` (см. [Создание Secret](creating_secrets.md)).

#### Generic Secret — из литералов и файлов
```bash
# Из литералов (pairs key=value)
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password='P@ssw0rd123!'

# Из файла (имя ключа = имя файла)
kubectl create secret generic ssh-key --from-file=id_rsa=~/.ssh/id_rsa

# Все файлы из директории
kubectl create secret generic app-configs --from-file=./configs/
```

#### TLS Secret
```bash
kubectl create secret tls ingress-cert --cert=tls.crt --key=tls.key
```

#### Docker Registry Secret
```bash
kubectl create secret docker-registry regcred \
  --docker-server=my-private-reg.io \
  --docker-username=deployer \
  --docker-password='S3cur3P@ss' \
  --docker-email=deployer@example.com
```

#### Генерация манифеста (Dry-run)
Для последующего шифрования через SOPS или Sealed Secrets:
```bash
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=client -o yaml > secret.yaml
```

### Декларативное создание (YAML)

#### Поле stringData (Рекомендуется для ручного редактирования)
Позволяет писать секреты в открытом виде. Kubernetes сам закодирует их в Base64.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
stringData:
  api_key: "7f5a8c..."
  db_password: "S3cur3P@ss"
```

#### Поле data (Бинарные данные и CI/CD)
Для бинарных файлов (JKS, сертификаты) или автоматического создания через скрипты:
```bash
# Кодирование в Base64
echo -n "my-password" | base64
# → bXktcGFzc3dvcmQ=
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: binary-secret
data:
  keystore: <base64-encoded-jks>
  password: bXktcGFzc3dvcmQ=
```

### Генерация через Kustomize (secretGenerator)

Стандарт для управления секретами в GitOps. Автоматически добавляет хеш содержимого к имени, что инициирует Rolling Update Подов при смене данных.

```yaml
# kustomization.yaml
secretGenerator:
- name: app-secrets
  files:
    - .env.prod
  options:
    disableNameSuffixHash: false  # по умолчанию true для Opaque
```

### Жизненный цикл и ротация

Безопасное управление секретами включает обязательную ротацию (смену) ключей:

- **Монтирование как Volume:** данные обновляются автоматически (с задержкой до 1 минуты), что позволяет приложению перечитывать новые ключи без перезапуска.
- **Переменные окружения:** обновление требует перезапуска Pod (Rolling Update или recreate).
- **Неизменяемые секреты:** для обновления необходимо удалить Pod и создать новый со ссылкой на новый Secret.

Подробнее: [Использование Secret](using_secrets.md).

## Диагностика и типичные ошибки

### Команды инспекции

```bash
# Просмотр всех секретов в Namespace
kubectl get secrets

# Просмотр секрета (без значений)
kubectl describe secret my-secret

# Просмотр данных (Base64)
kubectl get secret my-secret -o yaml

# Извлечение конкретного ключа и декодирование
kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d

# Экспорт всех ключей в файлы
kubectl get secret my-secret -o json | \
  jq -r '.data | to_entries[] | "\(.key) \(.value)"' | \
  while read key val; do echo "$val" | base64 -d > "$key"; done
```

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `secret "xxx" not found` | Секрет не существует или не в том Namespace | `kubectl get secrets -n <ns>` |
| `Forbidden: unable to go against...` | RBAC запрещает доступ к Secret | Добавить Role/RoleBinding с `resourceNames` |
| `Secret is invalid` | Невалидная структура данных для типа | Проверить обязательные ключи для типа (например, `tls.crt`/`tls.key` для `kubernetes.io/tls`) |
| `RequestEntityTooLarge` | Размер секрета превышает 1 MiB | Разделить данные или использовать внешнее хранилище |
| `Secret не обновляется в Pod` | Используется `subPath` или `immutable: true` | Заменить `subPath` на полное монтирование; снять `immutable` или пересоздать Pod |
| `Permission denied` на файле | Неверный `fsGroup` или `defaultMode` | Установить `fsGroup` в `securityContext`; проверить `defaultMode` |
| `ImagePullBackOff` | Невалидный `imagePullSecret` | Проверить тип `kubernetes.io/dockerconfigjson`; пересоздать Secret |

### Проверка RBAC для Secret

```bash
# Может ли ServiceAccount читать конкретный Secret?
kubectl auth can-i get secret/db-credentials \
  --namespace=my-namespace \
  --as=system:serviceaccount:my-namespace:my-sa

# Может ли SA listing всех секретов ( Potential security issue)?
kubectl auth can-i list secrets \
  --namespace=my-namespace \
  --as=system:serviceaccount:my-namespace:my-sa
```

> **Важно:** Если `kubectl auth can-i list secrets` возвращает `yes` — ServiceAccount имеет доступ ко **всем** секретам Namespace. Ограничьте RBAC конкретными именами через `resourceNames`.

### Проверка способа монтирования

```bash
# Проверка, что Secret в tmpfs (а не на диске)
kubectl exec <pod-name> -- mount | grep /etc/secrets
# → result: tmpfs on /etc/secrets type tmpfs (rw,relatime)

# Просмотр файлов и прав
kubectl exec <pod-name> -- ls -la /etc/secrets/

# Проверка, обновляется ли Secret (сравнение с API)
kubectl exec <pod-name> -- cat /etc/secrets/password
```

## Дополнительная информация

### Ограничения и лимиты

- **Размер:** Максимальный размер объекта Secret составляет **1 МиБ** (лимит etcd). Большие файлы (например, объемные Java KeyStores) могут не поместиться.
- **Производительность:** Хранение тысяч секретов в одном Namespace может привести к высокому потреблению памяти `kube-apiserver` и `kubelet`.
- **RBAC:** Права на `list` и `watch` в пространстве имен позволяют прочитать содержимое **всех** секретов этого пространства. Всегда ограничивайте доступ конкретными именами ресурсов (`resourceNames`).
- **Количество Secret на Namespace:** Рекомендуется не более 1000–2000 secrets на Namespace для поддержания производительности API Server и etcd.

### Смотрите также

- [Создание Secret](creating_secrets.md) — декларативные и императивные методы.
- [Использование Secret](using_secrets.md) — доставка в Pod.
- [Безопасность Secret](security.md) — комплексная защита данных.
- [Хранение в etcd](etcd_storage.md) — детали реализации Encryption at Rest.
- [Внешние менеджеры](external_managers.md) — ESO, CSI Driver, Vault Agent.
- [Helm + секреты](helm_secrets.md) — управление секретами в Helm-чартах.
- [Секреты в StatefulSet](statefulset_secrets.md) — паттерны для баз данных и stateful-приложений.
- [Pod Security Standards и Secret](pod_security_and_secrets.md) — влияние PSA restricted на монтирование секретов.
- [Sealed Secrets](../../Security/sealed_secrets_overview.md) — шифрование секретов для Git.
- [SOPS](../../../Security/Tools/sops_overview.md) — шифрование файлов через Mozilla SOPS.
- [cert-manager](../../ToolsUtilities/cert_manager/definitions.md) — автоматизация TLS-сертификатов.
- [Vault + Kubernetes](../../../Vault/guides/vault_kubernetes_integration.md) — интеграция с HashiCorp Vault.
- [GitOps: управление секретами](../../../GitOps/secrets_encryption.md) — сравнение подходов к хранению секретов в Git.
