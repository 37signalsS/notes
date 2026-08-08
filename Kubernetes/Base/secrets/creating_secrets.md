# Создание Secret в Kubernetes

## Определения

**Создание Secret** — процесс формирования объекта API Kubernetes для хранения чувствительных данных. Секреты позволяют безопасно передавать учетные данные, ключи и сертификаты в контейнеры без их жесткой прошивки (hardcoding) в образы или манифесты.

**Base64 кодирование** — стандартный метод представления двоичных данных в формате ASCII, используемый в поле `data` объектов Secret. 
> **Критическое замечание:** Base64 — это **не шифрование**. Любой пользователь с доступом к манифесту (YAML) или etcd может мгновенно декодировать данные (`echo <base64> | base64 -d`).

Подробнее о защите данных см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Методы управления секретами

1.  **Императивный (CLI):** создание через `kubectl create secret`. Удобно для отладки и разовых операций.
2.  **Декларативный (YAML):** описание структуры в файлах. Позволяет использовать `data` и `stringData`.
3.  **Генеративный (Kustomize/Helm):** автоматическая генерация на основе файлов или шаблонов во время деплоя.
4.  **Операторы (External Secrets):** автоматическая синхронизация из внешних систем (Vault, AWS Secrets Manager).

### Неизменяемые секреты (Immutable)

При создании секрета можно добавить поле `immutable: true`. Это запретит любые изменения данных после создания объекта (защита от случайной перезаписи).

### Изменение в ServiceAccount Tokens (1.24+)

Токены ServiceAccount больше не создаются автоматически как объекты Secret. Если требуется статический секрет для SA, его нужно создать вручную:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: manual-sa-token
  annotations:
    kubernetes.io/service-account.name: "my-service-account"
type: kubernetes.io/service-account-token
```

## Практические сценарии

### Императивное создание (kubectl)

#### Из литералов (literals)
```bash
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password='P@ssw0rd123!'
```

#### Из файлов или директорий
```bash
# Имя ключа будет соответствовать имени файла
kubectl create secret generic ssh-key --from-file=id_rsa=~/.ssh/id_rsa

# Все файлы в директории будут добавлены как ключи
kubectl create secret generic app-configs --from-file=./configs/
```

#### Генерация манифеста (Dry-run)
Для последующего шифрования через SOPS или Sealed Secrets:
```bash
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=client -o yaml > secret.yaml
```

### Декларативное создание (YAML)

#### Поле stringData (Рекомендуется)
Позволяет писать секреты в открытом виде. Kubernetes сам закодирует их в Base64.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
stringData:
  api_key: "7f5a8c..."
```

#### Поле data (Бинарные данные)
Для бинарных файлов (JKS, сертификаты) используйте предварительное кодирование. 
**Важно:** флаг `-n` в `echo` исключает лишний перенос строки.
```bash
echo -n "my-password" | base64 
# → bXktcGFzc3dvcmQ=
```

### Генерация через Kustomize (secretGenerator)

Стандарт для управления секретами в GitOps. Автоматически добавляет хеш содержимого к имени, что инициирует Rolling Update Подов при смене данных.

```yaml
# kustomization.yaml
secretGenerator:
- name: app-secrets
  files:
    - .env.prod
```

### Специализированные типы

#### TLS Secret
Для сертификатов Ingress.
```bash
kubectl create secret tls ingress-cert --cert=tls.crt --key=tls.key
```

#### Docker Registry Secret
Для доступа к приватным реестрам.
```bash
kubectl create secret docker-registry regcred \
  --docker-server=<registry-url> \
  --docker-username=<user> \
  --docker-password=<pass>
```

### Обновление (Patching)

Для обновления конкретного ключа без перезаписи всего секрета:
```bash
kubectl patch secret db-credentials -p '{"stringData":{"password":"new-password"}}'
```

## Дополнительная информация

### Проверка на лишние символы
Если приложение не принимает пароль, проверьте наличие переноса строки (`$`) в конце:
`kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d | cat -A`.

### GitOps и безопасность
Никогда не храните секреты в Git в открытом виде. Используйте:
- **[Sealed Secrets](../../Security/sealed_secrets_overview.md)** — шифрование для конкретного кластера.
- **[SOPS](../../../Security/Tools/sops_overview.md)** — шифрование с использованием KMS/PGP.
- **External Secrets Operator** — синхронизация из внешних хранилищ (рекомендуется для Production).

### Смотрите также
- [Основы Secret](secrets_basics.md) — обзор типов.
- [Использование Secret](using_secrets.md) — доставка в Pod.
- [Безопасность Secret](security.md) — лучшие практики.
