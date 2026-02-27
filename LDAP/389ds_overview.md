# Определения

## 389 Directory Server (389DS)

**389DS** — это enterprise-класс сервер каталогов (LDAP), разработанный Red Hat. Является открытым программным обеспечением и считается **рекомендуемой заменой** для устаревшего OpenLDAP.

**Ключевые преимущества перед OpenLDAP:**
* Более стабильная и предсказуемая работа
* Встроенная поддержка репликации
* Удобное управление через консоль (389 Console) или командную строку
* Активно используется в продакшене многими компаниями

## Основные концепции

### Запуск в Docker-контейнере

389DS распространяется в виде официального Docker-образа. Установка сводится к запуску контейнера с необходимыми параметрами.

#### Базовая команда запуска

```bash
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=example,dc=com \
  -e DM_PASSWORD=mysecretpassword \
  -e DS_SCHEMA_INETPERSON=false \
  389ds/ds-container:latest
```

#### Переменные окружения

| Переменная | Описание | Обязательно |
| :--- | :--- | :--- |
| `SUFFIX` | Корневой DN дерева LDAP (например, `dc=example,dc=com`) | Да |
| `DM_PASSWORD` | Пароль администратора (Directory Manager) | Да |
| `DS_SCHEMA_INETPERSON` | Включить схему inetPerson (по умолчанию `true`) | Нет |
| `DS_INDEX` | Включить индексацию при старте (`true`/`false`) | Нет |

#### Порты

* **3389** — LDAP (стандартный порт)
* **3636** — LDAPS (LDAP over SSL/TLS)

> **Примечание:** Использование портов > 1024 позволяет запускать контейнер от непривилегированного пользователя.

### Структура данных

* **Database** — хранение данных в `/data/db`
* **Backups** — резервные копии в `/data/backups`
* **Config** — конфигурация в `/data/config`
* **Schemas** — схемы (обычно не требуют изменений, добавляются редко)

### Утилиты управления

После запуска контейнера внутри доступны стандартные LDAP-утилиты:
* `ldapsearch` — поиск по дереву
* `ldapmodify` — модификация записей
* `ldapadd` — добавление записей
* `dsconf` — утилита управления 389DS

### Проверка работоспособности

```bash
# Подключение к контейнеру
docker exec -it 389ds /bin/bash

# Проверка конфигурации
dsconf -D "cn=Directory Manager" ldap://localhost:3389 config get

# Поиск базовой записи
ldapsearch -x -H ldap://localhost:3389 -D "cn=Directory Manager" -W -b "dc=example,dc=com"
```

# Практические сценарии

## Создание одноузлового кластера

1. Создать директорию для данных: `mkdir -p /data/ldap`
2. Запустить контейнер с параметрами
3. Проверить логи: `docker logs -f 389ds`
4. Дождаться сообщения `389DS container started`

## Настройка репликации (Multi-Master)

Для обеспечения высокой доступности настраивается репликация между несколькими экземплярами 389DS. Рассматривается кластер из двух узлов (master-master).

### Предварительные требования

* Две машины с Docker/Podman
* Сетевая связность между машинами
* DNS-имена серверов (ldap01, ldap02)
* Директория для данных: `mkdir -p /data/ldap`

### Запуск контейнеров на обеих нодах

```bash
docker run -d \
  --name 389ds \
  -p 3389:3389 \
  -p 3636:3636 \
  -v /data/ldap:/data \
  --memory=2g \
  -e SUFFIX=dc=test,dc=local \
  -e DM_PASSWORD=password \
  -e DS_REINDEX=true \
  389ds/ds-container:latest
```

### Проверка статуса серверов

```bash
# На каждом сервере проверить список backends
docker exec 389ds dsconf backend suffix list
```

### Создание backend (выполнить на обеих нодах)

```bash
docker exec 389ds dsconf backend create \
  --suffix "dc=test,dc=local" \
  --be-name user-root \
  --create-suffix
```

### Включение репликации

#### На первом сервере (ldap01)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 1 \
  "cn=replication manager,cn=config" \
  --password password
```

#### На втором сервере (ldap02)

```bash
docker exec 389ds dsconf replica enable \
  --suffix "dc=test,dc=local" \
  --role supplier \
  --replica-id 2 \
  "cn=replication manager,cn=config" \
  --password password
```

### Создание replication agreement

#### На ldap01 (к ldap02)

```bash
docker exec 389ds dsconf repl-agmt create \
  --suffix "dc=test,dc=local" \
  --host-name ldap02 \
  --port 3389 \
  --bind-method simple \
  --bind-dn "cn=replication manager,cn=config" \
  --password password \
  me-to-ldap02
```

#### На ldap02 (к ldap01)

```bash
docker exec 389ds dsconf repl-agmt create \
  --suffix "dc=test,dc=local" \
  --host-name ldap01 \
  --port 3389 \
  --bind-method simple \
  --bind-dn "cn=replication manager,cn=config" \
  --password password \
  me-to-ldap01
```

### Инициализация репликации

```bash
# На любом сервере
docker exec 389ds dsconf repl-agmt init \
  --suffix "dc=test,dc=local" \
  me-to-ldap02
```

### Проверка статуса репликации

```bash
docker exec 389ds dsconf replication status \
  --suffix "dc=test,dc=local" \
  me-to-ldap02
```

Ключевые параметры:
* `Replication Enable` — репликация включена
* `Last Update` — время последней синхронизации
* `Replica Status` — статус синхронизации

> **Примечание:** Конфигурация серверов (cn=config) не реплицируется — каждый сервер имеет собственную конфигурацию.

> **Рекомендуемая последовательность:**
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Перенести работающую конфигурацию в Kubernetes
> 4. Создать Helm chart для повторяемости

## Развертывание в Kubernetes

После освоения запуска в контейнерах, 389DS переносится в Kubernetes с использованием:
* **StatefulSet** — для сохранения состояния
* **PersistentVolumeClaim** — для персистентных данных
* **ConfigMap/Secret** — для конфигурации
* **Helm chart** — для автоматизации развертывания

> **Рекомендуемая последовательность:**
> 1. Запустить 389DS в Docker на отдельных машинах
> 2. Настроить кластер и репликацию
> 3. Перенести работающую конфигурацию в Kubernetes
> 4. Создать Helm chart для повторяемости

### Требования к кластеру Kubernetes

* Минимум 2 worker nodes (для отказоустойчивости)
* Ingress/LoadBalancer для доступа к сервису (MetalLB)
* Cert-manager для TLS-сертификатов

### StatefulSet конфигурация

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: 389ds
spec:
  serviceName: 389ds-headless
  replicas: 2
  selector:
    matchLabels:
      app: 389ds
  template:
    metadata:
      labels:
        app: 389ds
    spec:
      affinity:
        podAntiAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            - labelSelector:
                matchLabels:
                  app: 389ds
              topologyKey: kubernetes.io/hostname
      initContainers:
        - name: check-replicas
          image: busybox
          command: ["/bin/sh", "-c"]
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          args:
            - |
              POD_NUM=${POD_NAME##*-}
              if [ "$POD_NUM" -gt 1 ]; then
                echo "Maximum 2 replicas allowed, found: $POD_NUM"
                exit 1
              fi
      containers:
        - name: 389ds
          image: 389ds/ds-container:latest
          env:
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
            - name: SUFFIX
              value: "dc=example,dc=com"
            - name: DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: password
          ports:
            - containerPort: 3389
              name: ldap
            - containerPort: 3636
              name: ldaps
          volumeMounts:
            - name: data
              mountPath: /data
            - name: tls
              mountPath: /data/tls
              readOnly: true
            - name: tls-ca
              mountPath: /data/tls/ca
              readOnly: true
          livenessProbe:
            exec:
              command: ["/bin/sh", "-c", "nslookup localhost"]
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            exec:
              command: ["/bin/sh", "-c", "nslookup localhost"]
            initialDelaySeconds: 30
            periodSeconds: 10
          resources:
            requests:
              memory: "2Gi"
              cpu: "1"
            limits:
              memory: "2Gi"
              cpu: "2"
      volumes:
        - name: tls
          secret:
            secretName: 389ds-tls
        - name: tls-ca
          secret:
            secretName: 389ds-tls
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: "standard"
        resources:
          requests:
            storage: 10Gi
```

### Сервисы

```yaml
# Headless service для discovery подов
apiVersion: v1
kind: Service
metadata:
  name: 389ds-headless
spec:
  clusterIP: None
  selector:
    app: 389ds
  ports:
    - port: 3389
      name: ldap

---
# LoadBalancer для доступа к LDAP
apiVersion: v1
kind: Service
metadata:
  name: 389ds
  annotations:
    metallb.universe.tf/loadBalancerIPs: 192.168.1.100
spec:
  type: LoadBalancer
  selector:
    app: 389ds
  ports:
    - port: 389
      targetPort: 3389
      name: ldap
    - port: 636
      targetPort: 3636
      name: ldaps
```

### Инициализация и репликация через Job

Для автоматической инициализации 389DS (создание backend, настройка репликации) используется Job. Job выполняет shell-скрипт внутри контейнера 389DS.

#### RBAC для Job

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: 389ds-init
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: 389ds-init
rules:
  - apiGroups: ["apps"]
    resources: ["statefulsets"]
    verbs: ["get", "list", "patch"]
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: 389ds-init
subjects:
  - kind: ServiceAccount
    name: 389ds-init
roleRef:
  kind: Role
  name: 389ds-init
  apiGroup: rbac.authorization.k8s.io
```

#### Пример Job

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: 389ds-init
spec:
  template:
    spec:
      serviceAccountName: 389ds-init
      restartPolicy: OnFailure
      containers:
        - name: init
          image: 389ds/ds-container:latest
          command: ["/bin/bash", "/init/init.sh"]
          env:
            - name: SUFFIX
              value: "dc=example,dc=com"
            - name: DM_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: password
            - name: REPLICATION_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: 389ds-admin-secret
                  key: repl-password
            - name: NAMESPACE
              valueFrom:
                fieldRef:
                  fieldPath: metadata.namespace
          volumeMounts:
            - name: init-script
              mountPath: /init
            - name: config
              mountPath: /config
      volumes:
        - name: init-script
          configMap:
            name: 389ds-init-script
        - name: config
          configMap:
            name: 389ds-config
```

#### Основные задачи init-скрипта

1. **Проверка количества реплик** — не более 2 для простоты
2. **Настройка логирования** — JSON формат для логов
3. **Инициализация backend** — `dsconf backend create`
4. **Включение репликации** — `dsconf replica enable`
5. **Создание replication agreement** — между подами
6. **Заполнение LDAP-дерева** — базовые OU (people, groups, service)
7. **Включение плагинов** — RetroChangelog, MemberOf
8. **Перезапуск подов** — через `kubectl patch statefulset`

### Настройка TLS (cert-manager)

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: 389ds-tls
spec:
  secretName: 389ds-tls
  dnsNames:
    - 389ds-headless.ldap.svc.cluster.local
    - 389ds-0.389ds-headless.ldap.svc.cluster.local
    - 389ds-1.389ds-headless.ldap.svc.cluster.local
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

# Дополнительная информация

## Плагины 389DS

389DS поддерживает множество плагинов для расширения функциональности. Основные плагины:

### RetroChangeLog

Плагин сохраняет все изменения в отдельной ветке `cn=changelog`. Полезен для:
* Отладки репликации
* Аудита изменений
* Восстановления данных

### MemberOf

Автоматически добавляет атрибут `memberOf` к пользовательским записям, показывая группы, в которых состоит пользователь. Решает проблему "обратного" поиска — вместо поиска групп по пользователю, информация о группах хранится в самой записи пользователя.

### Включение плагинов

Плагины конфигурируются в ветке `cn=config,cn=plugins`. Изменения требуют перезапуска контейнера.

#### Пример LDIF для включения плагинов

```ldif
dn: cn=Retro Changelog,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on

dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: nsslapd-pluginEnabled
nsslapd-pluginEnabled: on
```

#### Настройка MemberOf для uniqueMember

```ldif
dn: cn=MemberOf Plugin,cn=plugins,cn=config
changetype: modify
replace: memberOfGroupAttr
memberOfGroupAttr: uniqueMember
```

#### Применение изменений

```bash
# На каждом сервере (конфигурация не реплицируется)
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f plugin-config.ldif

# Перезапуск контейнера
docker restart 389ds
```

#### Проверка конфигурации плагинов

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "cn=MemberOf Plugin,cn=plugins,cn=config"
```

## ACI (Access Control Instructions)

ACI в 389DS определяют права доступа на уровне отдельных записей. В отличие от OpenLDAP (ACL), ACI привязываются к конкретным записям в дереве LDAP.

### Отличие от OpenLDAP

| OpenLDAP | 389DS |
| :--- | :--- |
| ACL (Access Control List) | ACI (Access Control Instructions) |
| Конфигурация в `cn=config` | ACI в атрибутах записей |
| Глобальные правила | Правила на уровне записей |

### Примеры ACI

#### Разрешить доступ всем (чтение)

```ldif
dn: dc=test,dc=local
changetype: modify
add: aci
aci: (target="ldap:///dc=test,dc=local")(targetattr="*")(version 3.0; acl "Allow read access"; allow (read,search,compare);)
```

#### Разрешить доступ группе администраторов

```ldif
dn: dc=test,dc=local
changetype: modify
add: aci
aci: (target="ldap:///dc=test,dc=local")(targetattr="*")(version 3.0; acl "Admin group access"; allow (all)(groupdn="ldap:///cn=admins,ou=groups,dc=test,dc=local");)
```

### Применение ACI

```bash
docker exec 389ds ldapmodify -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W -f aci-config.ldif
```

### Проверка ACI

```bash
docker exec 389ds ldapsearch -x -H ldap://localhost:3389 \
  -D "cn=Directory Manager" -W \
  -b "dc=test,dc=local" -A aci
```

> **Примечание:** ACI реплицируются между серверами вместе с данными.

## Требования к ресурсам

* **CPU:** 2 ядра (минимум)
* **RAM:** 2+ ГБ (зависит от размера базы)
* **Диск:** SSD рекомендуется для производительности

389DS активно использует кэширование в оперативной памяти — чем больше RAM, тем быстрее ответы на запросы.

## Безопасность

* Рекомендуется использовать LDAPS (порт 3636) вместо открытого LDAP
* Своевременно обновлять образы
* Ограничить доступ к портам firewall'ом

## Связанные темы

* [LDAP](../Linux/SystemAdministration/users_management.md#LDAP-Lightweight-Directory-Access-Protocol) — основы протокола LDAP
* [OpenLDAP в Kubernetes](openldap_kubernetes.md) — развёртывание и эксплуатация OpenLDAP в Kubernetes
* [Kubernetes](../Kubernetes/overview.md) — оркестрация контейнеров
* [Helm](../Kubernetes/Installation/Kubespray/overview.md) — менеджер пакетов для Kubernetes
