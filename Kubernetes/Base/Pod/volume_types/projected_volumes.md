# Projected Volumes в Kubernetes

**Актуально для:** Kubernetes 1.30+

## Определения

* **Projected Volume (проектируемый том)** — специализированный тип тома в Kubernetes (`spec.volumes[*].projected`), предназначенный для объединения (проекции) нескольких разнородных источников конфигурационных данных и учетных данных в единую директорию файловой системы контейнера.
* **VolumeProjection** — атомарный элемент спецификации в массиве `sources`, описывающий один конкретный источник данных (`secret`, `configMap`, `downwardAPI`, `serviceAccountToken`, `clusterTrustBundle` или `podCertificate`).
* **Bound Service Account Token** — криптографический JWT-токен ServiceAccount с ограниченным временем жизни (TTL), жестко привязанный к конкретному Pod (UID) и целевому сервису (Audience), генерируемый kubelet через `TokenRequest` API без сохранения в `etcd`.
* **Atomic Symlink Rotation** — механизм обновления файлов тома на базе тройной структуры символических ссылок (`..timestamp`, `..data_tmp`, `..data`), гарантирующий атомарную смену версий файлов без промежуточного состояния частичного чтения.
* **kube-api-access** — стандартный системный проектируемый том, автоматически внедряемый контроллером admission `ServiceAccount` во все Pod, которым не отключено монтирование токена.

---

## Архитектура и принцип работы

### Архитектурная схема подсистемы Projected Volumes

```
API-сервер Kubernetes
   │  ▲
   │  │ (Watch / TokenRequest / CertificateRequest)
   ▼  │
kubelet (Node VolumeManager)
   │
   ├── 1. Разрешение источников (Fetch Secret, ConfigMap, downwardAPI)
   ├── 2. Генерация токенов (TokenRequest API → Bound SA Token)
   ├── 3. Запись на локальный узел (/var/lib/kubelet/pods/<Pod-UID>/volumes/kubernetes.io~projected/<Vol-Name>/)
   │      ├── [tmpfs] (для секретов и токенов)
   │      └── Символические ссылки:
   │          ├── ..2026_10_13_12_00_00.987654321/ (директория с физическими файлами)
   │          ├── ..data -> ..2026_10_13_12_00_00.987654321
   │          ├── config.yaml -> ..data/config.yaml
   │          └── token -> ..data/token
   └── 4. Передача точки монтирования в Container Runtime (CRI bind mount)
          ▼
   Mount Namespace контейнера (/etc/app/config)
```

### Механизм атомарного обновления (Atomic Symlink Swapping)

Когда данные в `ConfigMap` или `Secret` изменяются в API-сервере:

1. **Обнаружение изменений:** Kubelet отслеживает обновления ресурсов через локальный кэш, Watch или периодический опрос (параметр `--configmap-and-secret-change-detection-strategy`, по умолчанию `Watch`).
2. **Создание нового каталога:** В директории тома на узле создается новая папка с временной меткой, например `..2026_10_13_12_05_00.123456789`.
3. **Запись файлов:** Все файлы текущей проекции записываются в эту новую папку с учетом прав доступа `defaultMode`.
4. **Переключение ссылки:** Kubelet создает временный симлинк `..data_tmp`, указывающий на новую папку, и выполняет атомарный системный вызов `rename("..data_tmp", "..data")`.
5. **Очистка старых данных:** Предыдущая директория с устаревшими файлами удаляется после успешного переключения ссылки.
6. **Консистентность чтения:** Приложение, открывающее файл по пути `/mountPath/file`, всегда видит либо целиком старую версию, либо целиком новую. Чтение поврежденного файла исключено на уровне файловой системы.

> [!WARNING]
> Если проектируемый том монтируется с параметром `subPath` (монтирование отдельного файла, а не директории), Container Runtime привязывает конкретный inode файла в момент старта контейнера. Атомарное обновление symlink на уровне директории не затронет привязанный inode, и файлы внутри контейнера **никогда не обновятся** без перезапуска Pod.

### Хранение на узле: tmpfs vs Диск

* По умолчанию для проектируемых томов, содержащих `secret` или `serviceAccountToken`, kubelet монтирует директорию тома с типом файловой системы `tmpfs` (оперативная память узла).
* Это предотвращает утечку конфиденциальных данных и криптографических ключей на постоянные дисковые накопители узла.
* Память, занятая томом `tmpfs`, учитывается в общем объеме потребления памяти Pod и входит в расчет лимитов `ephemeral-storage`.

### Автоматически внедряемый том `kube-api-access`

В каждом Pod, где не задано `automountServiceAccountToken: false`, Admission Controller Kubernetes автоматически генерирует проектируемый том следующего вида:

```yaml
volumes:
- name: kube-api-access-7x89q
  projected:
    defaultMode: 420 # Восьмеричное 0644
    sources:
    - serviceAccountToken:
        expirationSeconds: 3607
        path: token
    - configMap:
        name: kube-root-ca.crt
        items:
        - key: ca.crt
          path: ca.crt
    - downwardAPI:
        items:
        - fieldRef:
            apiVersion: v1
            fieldPath: metadata.namespace
          path: namespace
```

Этот том монтируется по пути `/var/run/secrets/kubernetes.io/serviceaccount` в режиме `readOnly: true`, обеспечивая клиентским библиотекам доступ к API-серверу без использования статических секретов.

---

## Поддерживаемые типы источников и параметры конфигурации

### Сводная таблица источников данных

| Источник (`sources[]`) | Описание | Статус в Kubernetes | Требуемый Feature Gate |
| :--- | :--- | :--- | :--- |
| `secret` | Данные из объектов `Secret` текущего Namespace | Stable | — |
| `configMap` | Данные из объектов `ConfigMap` текущего Namespace | Stable | — |
| `downwardAPI` | Метаданные Pod и контейнеров (имена, метки, лимиты) | Stable | — |
| `serviceAccountToken` | Динамический JWT-токен учетной записи с заданным Audience и TTL | Stable | — |
| `clusterTrustBundle` | Общекластерные доверенные корневые сертификаты (CA anchors) | Alpha | `ClusterTrustBundleProjection` |
| `podCertificate` | Автоматически выпускаемые X.509 сертификаты и приватные ключи для mTLS | Alpha | `PodCertificateProjection` |

### Параметры каждого источника

#### 1. `secret` и `configMap`

```yaml
sources:
- secret:
    name: app-secret          # string: имя объекта в том же Namespace (обязательно)
    optional: false           # bool: если true, отсутствие объекта не блокирует запуск Pod
    items:                    # []Item: список монтируемых ключей (по умолчанию — все ключи)
    - key: db-password        # string: ключ в Secret/ConfigMap
      path: db/password.txt   # string: относительный путь внутри тома
      mode: 0400              # int: индивидуальные права доступа (переопределяют defaultMode)
- configMap:
    name: app-config
    optional: true
    items:
    - key: config.yaml
      path: config.yaml
```

#### 2. `downwardAPI`

```yaml
sources:
- downwardAPI:
    items:
    - path: metadata/labels
      mode: 0444
      fieldRef:
        fieldPath: metadata.labels
    - path: resources/cpu-limit
      resourceFieldRef:
        containerName: main-app
        resource: limits.cpu
        divisor: 1m
```

#### 3. `serviceAccountToken`

```yaml
sources:
- serviceAccountToken:
    path: token               # string: имя файла токена в томе (обязательно)
    audience: vault.internal  # string: целевая аудитория токена (aud)
    expirationSeconds: 3600   # int: время жизни токена (минимум 600, по умолчанию 3600)
```

* Kubelet запрашивает новый токен через TokenRequest API и автоматически ротирует его на диске при достижении ~80% от времени жизни или если возраст токена превысил 24 часа.
* Токен содержит утверждения (claims): `sub` (ServiceAccount), `aud` (Audience), `nbf`, `exp`, а также идентификаторы пода `kubernetes.io/pod/name` и `kubernetes.io/pod/uid`.

#### 4. `clusterTrustBundle` (Alpha)

Используется для централизованной доставки корневых сертификатов доверия во все поды кластера без необходимости копировать их в каждый Namespace через ConfigMap.

```yaml
sources:
- clusterTrustBundle:
    path: pki/company-ca.crt # string: относительный путь к бандлу в томе (обязательно)
    name: corporate-root-ca  # string: выбор конкретного ClusterTrustBundle по имени
    # Либо выбор через signerName и лейблы (взаимоисключающе с name):
    # signerName: "example.com/internal-ca"
    # labelSelector:
    #   matchLabels:
    #     environment: production
    optional: false          # bool: не блокировать старт пода при отсутствии бандла
```

#### 5. `podCertificate` (Alpha)

Позволяет kubelet генерировать ключевую пару для Pod на узле, отправлять CSR через `PodCertificateRequest` API и монтировать подписанный сертификат непосредственно в файловую систему контейнера.

```yaml
sources:
- podCertificate:
    signerName: "internal.corp/workload-id" # string: имя подписанта (обязательно)
    keyType: "ECDSAP256"                    # string: RSA3072, RSA4096, ECDSAP256, ECDSAP384, ED25519
    maxExpirationSeconds: 86400             # int: максимальный срок действия (3600..7862400)
    credentialBundlePath: "tls/bundle.pem"  # string: единый PEM-файл (приватный ключ + сертификаты)
    # Либо раздельные пути:
    # keyPath: "tls/tls.key"
    # certificateChainPath: "tls/tls.crt"
```

### Правила разрешения коллизий путей

Если два или более источников в списке `sources` содержат одинаковый путь (`path`), приоритет определяется порядком их объявления:

1. **Побеждает последний источник:** Файл из источника, указанного ниже по списку, полностью перезаписывает файл из источника, расположенного выше.
2. **Права доступа:** Права файла определяются настройкой `mode` последнего записанного элемента либо общим `defaultMode`.

---

## Сравнение: Projected Volume vs Отдельные тома

| Критерий | Projected Volume | Отдельные тома (`secret`, `configMap`) |
| :--- | :--- | :--- |
| **Количество точек монтирования (`volumeMounts`)** | **Одна** для всех агрегируемых источников | Отдельная для каждого источника |
| **Монтирование в одну директорию** | Да, без затирания соседних файлов | Нет, монтирование нескольких томов в один `mountPath` затирает предыдущие |
| **Токены ServiceAccount с Audience** | **Поддерживается** только через `projected` | Не поддерживается (статические Secret-токены устарели) |
| **Атомарность обновления** | Единая symlink-структура на всю директорию | Независимые циклы обновления для каждого тома |
| **Управление правами доступа** | Единый `defaultMode` с возможностью точечного переопределения | Отдельный `defaultMode` в каждом томе |
| **Контроль `readOnly`** | Единая точка контроля на уровне контейнера | Контроль каждого тома по отдельности |

---

## Практические сценарии

### Сценарий 1: Комплексная агрегация конфигураций и секретов сервиса

Агрегация файлов конфигурации приложения, секретов базы данных и метаданных окружения в общую директорию `/etc/app`.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: api-service
  namespace: backend
  labels:
    app.kubernetes.io/name: api-service
    env: production
spec:
  containers:
  - name: application
    image: alpine:3.20
    command: ["sh", "-c", "while true; do ls -la /etc/app; sleep 60; done"]
    volumeMounts:
    - name: application-bundle
      mountPath: /etc/app
      readOnly: true
  volumes:
  - name: application-bundle
    projected:
      defaultMode: 0440 # Чтение владельцу и группе процесса
      sources:
      - configMap:
          name: api-config
          items:
          - key: application.yaml
            path: config/application.yaml
      - secret:
          name: api-db-credentials
          items:
          - key: password
            path: secrets/db_password.txt
            mode: 0400 # Более строгие права для пароля
      - downwardAPI:
          items:
          - path: info/pod_name
            fieldRef:
              fieldPath: metadata.name
          - path: info/pod_ip
            fieldRef:
              fieldPath: status.podIP
```

### Сценарий 2: Аутентификация во внешней системе через Bound Token (HashiCorp Vault / SPIFFE)

Получение кратковременного токена с кастомной аудиторией для последующего обмена на клиентский токен Vault через метод аутентификации Kubernetes.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: vault-client-app
  namespace: payment
spec:
  serviceAccountName: payment-processor
  containers:
  - name: app
    image: alpine:3.20
    command: ["sh", "-c", "cat /var/run/secrets/tokens/vault-token && sleep 3600"]
    volumeMounts:
    - name: vault-token-vol
      mountPath: /var/run/secrets/tokens
      readOnly: true
  volumes:
  - name: vault-token-vol
    projected:
      defaultMode: 0400
      sources:
      - serviceAccountToken:
          path: vault-token
          audience: "https://vault.internal.net"
          expirationSeconds: 1800 # 30 минут
```

### Сценарий 3: Защита от сбоя при отсутствии опциональных конфигураций

Подключение конфигураций окружения с флагом `optional: true`. Если разработчик не создал ConfigMap с переопределениями для локальной отладки, Pod все равно запустится.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: resilient-service
  namespace: default
spec:
  containers:
  - name: worker
    image: busybox:1.36
    command: ["sh", "-c", "test -f /etc/config/overrides.json && echo 'Overrides loaded' || echo 'Using defaults'; sleep 3600"]
    volumeMounts:
    - name: configs
      mountPath: /etc/config
      readOnly: true
  volumes:
  - name: configs
    projected:
      defaultMode: 0444
      sources:
      - configMap:
          name: base-config
          optional: false # Базовый конфиг обязателен
          items:
          - key: base.json
            path: base.json
      - configMap:
          name: custom-overrides
          optional: true # Отсутствие не вызовет ошибку CreateContainerConfigError
          items:
          - key: overrides.json
            path: overrides.json
```

### Сценарий 4: Безопасное отключение системного токена `kube-api-access`

Если сервису не требуется доступ к Kubernetes API-серверу (например, статическому nginx или воркеру очередей), системный проектируемый том отключается для исключения рисков эскалации привилегий.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: isolated-worker
  namespace: default
spec:
  automountServiceAccountToken: false # Отключает автоматическую инъекцию kube-api-access
  containers:
  - name: worker
    image: alpine:3.20
    command: ["sleep", "3600"]
```

---

## Операции и команды

### 1. Проверка структуры тома внутри работающего Pod

```bash
kubectl exec -n backend api-service -- ls -la /etc/app
# → total 0
# → drwxrwxrwt 5 root root 120 Oct 13 19:40 .
# → drwxr-xr-x 1 root root  40 Oct 13 19:40 ..
# → drwxr-xr-x 2 root root  60 Oct 13 19:40 ..2026_10_13_16_40_12.183748291
# → lrwxrwxrwx 1 root root  34 Oct 13 19:40 ..data -> ..2026_10_13_16_40_12.183748291
# → lrwxrwxrwx 1 root root  28 Oct 13 19:40 config -> ..data/config
# → lrwxrwxrwx 1 root root  26 Oct 13 19:40 info -> ..data/info
# → lrwxrwxrwx 1 root root  29 Oct 13 19:40 secrets -> ..data/secrets
```

### 2. Декодирование и валидация JWT-токена ServiceAccount

Проверка аудитории (`aud`), субъекта (`sub`) и срока действия (`exp`) смонтированного токена:

```bash
kubectl exec -n payment vault-client-app -- cat /var/run/secrets/tokens/vault-token \
  | jq -R 'split(".") | .[1] | @base64d | fromjson'
# → {
# →   "aud": [
# →     "https://vault.internal.net"
# →   ],
# →   "exp": 1791912012,
# →   "iat": 1791910212,
# →   "iss": "https://kubernetes.default.svc.cluster.local",
# →   "kubernetes.io": {
# →     "namespace": "payment",
# →     "pod": {
# →       "name": "vault-client-app",
# →       "uid": "e7b0a708-4e89-4e1b-9443-41bbd985a9df"
# →     },
# →     "serviceaccount": {
# →       "name": "payment-processor",
# →       "uid": "3b29c940-062e-4b7b-9ad0-f6551b8a34de"
# →     }
# →   },
# →   "nbf": 1791910212,
# →   "sub": "system:serviceaccount:payment:payment-processor"
# → }
```

### 3. Инспекция томов на хосте узла (для системных администраторов)

Для отладки файловой системы тома непосредственно на хосте узла под управлением kubelet:

```bash
# Получение UID пода
POD_UID=$(kubectl get pod -n backend api-service -o jsonpath='{.metadata.uid}')

# Просмотр директорий тома в файловой системе ноды (выполняется на ноде под root)
ls -la /var/lib/kubelet/pods/${POD_UID}/volumes/kubernetes.io~projected/application-bundle/
# → total 0
# → drwxr-xr-x 3 root root 100 Oct 13 19:40 .
# → drwxr-x--- 3 root root  60 Oct 13 19:40 ..
# → drwxr-xr-x 5 root root 120 Oct 13 19:40 ..2026_10_13_16_40_12.183748291
# → lrwxrwxrwx 1 root root  34 Oct 13 19:40 ..data -> ..2026_10_13_16_40_12.183748291
```

Проверка типа файловой системы тома на узле (подтверждение tmpfs):

```bash
df -T /var/lib/kubelet/pods/${POD_UID}/volumes/kubernetes.io~projected/application-bundle/
# → Filesystem     Type   1K-blocks  Used Available Use% Mounted on
# → tmpfs          tmpfs   16384000     4  16383996   1% /var/lib/kubelet/pods/e7b0a708.../volumes/kubernetes.io~projected/application-bundle
```

---

## Диагностика и типичные ошибки

### 1. `CreateContainerConfigError` из-за отсутствия источника

**Симптомы:** Pod зависает в статусе `CreateContainerConfigError`.

```bash
kubectl get pod api-service -n backend
# → NAME          READY   STATUS                       RESTARTS   AGE
# → api-service   0/1     CreateContainerConfigError   0          45s
```

**Причина:** Один из объектов (`Secret` или `ConfigMap`), указанных в секции `sources`, не существует в данном Namespace, и для него не задан параметр `optional: true`.

**Диагностика:**
```bash
kubectl describe pod api-service -n backend | grep -A 5 Events:
# → Events:
# →   Type     Reason      Age                From               Message
# →   ----     ------      ----               ----               -------
# →   Warning  FailedMount 12s (x4 over 48s)  kubelet            MountVolume.SetUp failed for volume "application-bundle" : secret "api-db-credentials" not found
```

**Решение:**
1. Создать отсутствующий ресурс:
   ```bash
   kubectl create secret generic api-db-credentials -n backend --from-literal=password='SecurePass123'
   # → secret/api-db-credentials created
   ```
2. Либо добавить `optional: true` в манифест Pod, если источник не является критически важным для старта контейнера.

### 2. Данные не обновляются при изменении ConfigMap/Secret

**Симптомы:** ConfigMap обновлен через `kubectl edit cm`, но файлы внутри контейнера содержат старые значения более 5 минут.

**Причины:**
* В манифесте контейнера использован параметр `subPath` (например, `subPath: config.yaml`). Монтирование через `subPath` фиксирует inode файла и отключает симлинк-ротацию.
* Объект ConfigMap или Secret помечен как неизменяемый (`immutable: true`).

**Диагностика:**
```bash
# Проверка наличия subPath в описании контейнеров
kubectl get pod api-service -n backend -o jsonpath='{.spec.containers[*].volumeMounts[*].subPath}'
# → config.yaml

# Проверка флага immutable у исходного объекта
kubectl get cm api-config -n backend -o jsonpath='{.immutable}'
# → true
```

**Решение:**
1. Отказаться от `subPath` при монтировании тома. Монтировать весь проектируемый том в отдельный каталог (например `/etc/app/config`), а требуемые пути формировать через секцию `items[].path`.
2. Если используется приложение, не умеющее читать из симлинков (некоторые JVM-приложения): настроить процесс перечитывания по SIGHUP или выполнять rolling restart Pod (`kubectl rollout restart deployment/<name>`).

### 3. Ошибка прав доступа `Permission Denied` в non-root контейнерах

**Симптомы:** Контейнер запускается под непривилегированным пользователем (`runAsNonRoot: true`, UID `10001`) и завершается аварийно с ошибкой `EACCES: permission denied` при чтении файла из `/etc/app/secrets/db_password.txt`.

**Причина:** Параметр `defaultMode` или индивидуальный `mode` установлен в `0400` (чтение только владельцу `root:root`), поэтому процесс с UID `10001` не имеет прав на чтение.

**Диагностика:**
```bash
kubectl logs api-service -n backend
# → open /etc/app/secrets/db_password.txt: permission denied
```

**Решение:**
1. Настроить группу доступа `fsGroup` в контексте безопасности Pod:
   ```yaml
   spec:
     securityContext:
       runAsNonRoot: true
       runAsUser: 10001
       fsGroup: 10001
   ```
2. Установить `defaultMode: 0440` или `defaultMode: 0444`, чтобы предоставить право на чтение группе процесса или всем пользователям:
   ```yaml
   projected:
     defaultMode: 0440
   ```

### 4. Ошибка валидации токена `TokenRequest failed: audience mismatch`

**Симптомы:** Внешний сервис аутентификации (например, Vault) отклоняет JWT-токен пода с ошибкой `audience claim is invalid`.

**Диагностика:**
```bash
# Проверить аудиторию, записанную в манифесте
kubectl get pod vault-client-app -n payment -o jsonpath='{.spec.volumes[?(@.projected)].projected.sources[?(@.serviceAccountToken)].serviceAccountToken.audience}'
# → https://wrong-vault-url.internal

# Декодировать токен из пода и сверить aud (см. раздел "Операции и команды")
```

**Решение:**
Скорректировать значение `audience` в блоке `serviceAccountToken`, чтобы оно в точности соответствовало значению, сконфигурированному на сервере проверки токенов.

---

## Рекомендации для DevOps, SRE и системных администраторов

### Безопасность и контроль доступа
* **Всегда монтируйте тома в режиме `readOnly: true`:** Проектируемые тома предназначены исключительно для доставки конфигураций и учетных данных в контейнер. Запись в них недопустима.
* **Используйте принцип наименьших прав (Least Privilege) для `defaultMode`:** Избегайте использования `0666`, `0777` или `0644` для файлов, содержащих пароли и токены. Оптимальные значения: `0400` (если процесс запускается под root) или `0440` (совместно с `fsGroup` для непривилегированных процессов).
* **Отключайте `automountServiceAccountToken` по умолчанию:** Если подам не требуется взаимодействие с API-сервером Kubernetes, задавайте `automountServiceAccountToken: false` в манифестах `ServiceAccount` или `Pod`.
* **Предпочитайте Bound Service Account Tokens статическим секретам:** Статические секреты ServiceAccount бессрочны и хранятся в `etcd`. Токены `serviceAccountToken` ограничены по времени, автоматически ротируются и привязаны к целевой аудитории (`audience`).

### Надежность и эксплуатация (SRE)
* **Не используйте `subPath` для динамически обновляемых конфигов:** Использование `subPath` приводит к невидимости обновлений внутри контейнера и требует принудительного перезапуска подов.
* **Используйте `optional: true` только для вторичных конфигураций:** Критические параметры (строки подключения к БД, сертификаты) должны монтироваться с `optional: false`, чтобы pod не переходил в статус `Running` с полупустой конфигурацией.
* **Учитывайте задержку обновления кэша kubelet:** После обновления `ConfigMap` файлы в томе обновляются с задержкой, определяемой параметром `--sync-frequency` в kubelet (обычно до 60–90 секунд). Если требуется мгновенное применение новой конфигурации, инициируйте rolling restart деплоймента.
* **Учитывайте лимиты памяти при использовании больших секретов:** Поскольку projected тома с секретами монтируются в `tmpfs`, большой объем секретов (допустимый лимит объекта в etcd — 1 MiB) расходует оперативную память контейнера и лимиты `ephemeral-storage`.

---

## Дополнительная информация

### Связанные разделы базы знаний

* [Обзор типов томов в Kubernetes](./volume_types.md) — классификация и сравнение всех типов томов Pod.
* [Downward API в Kubernetes](../downward_api.md) — детальная передача метаданных и лимитов Pod через файловую систему.
* [Использование секретов в Pod](../../secrets/using_secrets.md) — механизмы работы с объектами `Secret`.
* [Использование ConfigMap в Pod](../../ConfigMap/pod_usage.md) — правила монтирования конфигураций.
* [CreateContainerConfigError: Проблемы с томами](../../../Troubleshooting/Common_Errors/CreateContainerConfigError/volume_issues.md) — устранение сбоев монтирования томов kubelet.
* [Аутентификация в Kubernetes](../../../Security/authentication.md) — методы проверки подлинности, ServiceAccount токена и TokenRequest API.

### Официальная документация

* [Kubernetes Documentation: Projected Volumes](https://kubernetes.io/docs/concepts/storage/projected-volumes/)
* [Kubernetes Documentation: Service Account Token Volume Projection](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/#service-account-token-volume-projection)
* [Kubernetes KEP-3257: ClusterTrustBundle](https://github.com/kubernetes/enhancements/tree/master/keps/sig-auth/3257-cluster-trust-bundle)
* [Kubernetes KEP-4316: Pod Certificate Projection](https://github.com/kubernetes/enhancements/tree/master/keps/sig-auth/4316-pod-certificate-projection)
