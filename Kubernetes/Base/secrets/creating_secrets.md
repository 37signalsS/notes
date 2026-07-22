# Создание Secret в Kubernetes

## Определения

**Создание Secret** — процесс формирования объекта API Kubernetes для хранения чувствительных данных. Секреты позволяют безопасно передавать учетные данные, ключи и сертификаты в контейнеры без их жесткой прошивки (hardcoding) в образы или манифесты.

**Base64 кодирование** — стандартный метод представления двоичных данных в формате ASCII, используемый в поле `data` объектов Secret. 
> **Внимание:** Base64 — это **не шифрование**. Любой пользователь с доступом к манифесту может мгновенно декодировать данные (`echo <base64> | base64 -d`).

Подробнее о защите данных см. [Безопасность Secret](security.md) и [Хранение в etcd](etcd_storage.md).

## Основные концепции

### Методы создания

Существует три основных подхода к управлению жизненным циклом секретов:

1.  **Императивный (CLI):** создание через `kubectl create secret`. Удобно для разовых операций и отладки.
2.  **Декларативный (YAML):** описание в файлах манифестов. Позволяет использовать поля `data` (Base64) и `stringData` (Plain text).
3.  **Генеративный (Kustomize/Helm):** автоматическая генерация секретов из внешних файлов или переменных окружения во время деплоя.

### Изменение в ServiceAccount Tokens (1.24+)

Начиная с Kubernetes 1.24, токены ServiceAccount **не создаются автоматически** в виде объектов Secret. Вместо этого используется [TokenRequest API](https://kubernetes.io/docs/reference/kubernetes-api/authentication-resources/token-request-v1/) для получения кратковременных токенов. Если вам нужен долгоживущий секрет для SA, его необходимо создавать вручную с аннотацией `kubernetes.io/service-account.name`.

## Практические сценарии

### Императивное создание (kubectl)

Команда `kubectl` автоматически кодирует входные данные в Base64.

#### Из отдельных значений (literals)
```bash
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password='P@ssw0rd123!'
```

#### Из файлов или директорий
```bash
# Весь файл будет помещен в ключ с именем файла
kubectl create secret generic ssh-key --from-file=~/.ssh/id_rsa

# Все файлы в директории будут добавлены как отдельные ключи
kubectl create secret generic app-configs --from-file=./configs/
```

#### Генерация манифеста без создания объекта
Для GitOps часто требуется получить YAML-манифест, чтобы потом зашифровать его (например, через SOPS):
```bash
kubectl create secret generic my-secret \
  --from-literal=key=value \
  --dry-run=client -o yaml > secret.yaml
```

### Декларативное создание (YAML)

#### Использование stringData (Рекомендуется)
Поле `stringData` позволяет писать секреты в открытом виде. Kubernetes сам преобразует их в Base64 при сохранении.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: app-secret
type: Opaque
stringData:
  # Поле доступно только для записи. При чтении (get -o yaml) оно исчезнет, 
  # а данные переместятся в поле 'data' в кодировке Base64.
  api_key: "7f5a8c..."
  db_url: "postgresql://user:pass@host:5432/db"
```

#### Использование data
Требует предварительного кодирования данных.

```bash
# ВАЖНО: флаг -n исключает перенос строки, который может сломать секрет
echo -n "my-password" | base64 
# → bXktcGFzc3dvcmQ=
```

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: manual-secret
data:
  password: bXktcGFzc3dvcmQ=
```

### Генерация через Kustomize (secretGenerator)

Это стандарт индустрии для управления секретами в манифестах. Kustomize автоматически добавляет хеш содержимого к имени секрета, что инициирует автоматический перезапуск Подов при изменении данных.

```yaml
# kustomization.yaml
secretGenerator:
- name: app-secrets
  literals:
    - API_TOKEN=super-secret-token
  files:
    - .env.prod
```
Подробнее см. [Kustomize: Генераторы секретов](../ToolsUtilities/kustomize/kustomize_advanced_features.md).

### Специализированные типы секретов

#### TLS Secret
Для сертификатов Ingress и mTLS.
```bash
kubectl create secret tls ingress-cert \
  --cert=path/to/tls.crt \
  --key=path/to/tls.key
```

#### Docker Registry Secret
Для скачивания образов из приватных репозиториев.
```bash
kubectl create secret docker-registry regcred \
  --docker-server=<your-registry-server> \
  --docker-username=<your-name> \
  --docker-password=<your-pword> \
  --docker-email=<your-email>
```

## Дополнительная информация

### Ловушки Base64
Самая частая ошибка при ручном создании `data` — лишний символ переноса строки (`\n`). 
- **Неправильно:** `echo "password" | base64` (добавит перенос строки в конец).
- **Правильно:** `echo -n "password" | base64`.

Если приложение жалуется на "invalid password", проверьте секрет: 
`kubectl get secret my-secret -o jsonpath='{.data.password}' | base64 -d | cat -A`. Символ `$` в конце укажет на лишний перенос.

### Автоматизация и GitOps
Никогда не храните файлы манифестов с секретами в Git в открытом виде. Используйте:
- **[Sealed Secrets](../../Security/sealed_secrets_overview.md)**
- **[SOPS](../../../Security/Tools/sops_overview.md)**
- **External Secrets Operator** (для синхронизации из Vault/AWS SM)

### Смотрите также
- [Основы Secret](secrets_basics.md) — обзор типов и структуры.
- [Использование Secret](using_secrets.md) — как подключить секрет к Pod.
- [Безопасность Secret](security.md) — лучшие практики защиты.
- [RBAC](../../Security/rbac/rbac_overview.md) — ограничение прав на создание секретов.
