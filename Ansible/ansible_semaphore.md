# Semaphore: Веб-интерфейс для Ansible

## Определения

**Semaphore** — это легковесный и быстрый веб-интерфейс (UI) с открытым исходным кодом для запуска Ansible-плейбуков. Он предоставляет централизованную панель для управления ИТ-инфраструктурой, аналогичную Ansible Tower или его open-source версии AWX, но является значительно более простой и менее требовательной к ресурсам альтернативой.

## Основные концепции

- **Архитектура**: Semaphore состоит из самого веб-приложения и требует внешнюю базу данных для хранения своего состояния, включая инвентарь, учетные данные, шаблоны задач и историю запусков. Поддерживаются PostgreSQL и MySQL.
- **Конфигурация**: Основная конфигурация приложения осуществляется через переменные окружения. В официальном Docker-образе используется внутренний shell-скрипт (`semaphore-wrapper`), который на основе этих переменных генерирует итоговый конфигурационный файл `config.json` при старте контейнера.
- **Хранение данных**: Для хранения временных файлов, таких как клонированные из Git репозитории с плейбуками, используется персистентное хранилище. В Kubernetes для этого используется `PersistentVolumeClaim`.

## Практический сценарий: Развертывание в Kubernetes

Развертывание Semaphore в Kubernetes сводится к созданию набора манифестов, которые описывают все необходимые компоненты системы.

### 1. Подготовка: Namespace и База Данных

Рекомендуется разворачивать Semaphore в отдельном `namespace`.

```bash
kubectl create namespace semaphore
```

Перед установкой необходимо иметь работающий экземпляр PostgreSQL или MySQL, доступный из кластера Kubernetes.

### 2. ConfigMap
Создается для хранения неконфиденциальных параметров, таких как адрес базы данных, имя пользователя и диалект.

```yaml
# semaphore-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: semaphore-cm
  namespace: semaphore
data:
  SEMAPHORE_DB_USER: "semaphore"
  SEMAPHORE_DB_HOST: "postgres.semaphore.svc.cluster.local" # Пример адреса БД
  SEMAPHORE_DB_DIALECT: "postgres"
  SEMAPHORE_DB: "semaphore"
  SEMAPHORE_ADMIN_NAME: "admin"
  SEMAPHORE_ADMIN_EMAIL: "admin@localhost"
  SEMAPHORE_ADMIN: "admin"
  SEMAPHORE_LDAP_ACTIVATED: "false"
```

### 3. Secret
Используется для хранения паролей и ключа шифрования.

**Важно:** `SEMAPHORE_ACCESS_KEY_ENCRYPTION` — это ключ, которым Semaphore шифрует чувствительные данные в базе (например, ключи SSH). Он критически важен для бэкапов и миграций. Если вы переносите инсталляцию, этот ключ должен совпадать.

Сгенерировать ключ можно командой:
```bash
openssl rand -hex 16
```

```yaml
# semaphore-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: semaphore-secret
  namespace: semaphore
type: Opaque
stringData:
  SEMAPHORE_DB_PASS: "your-db-password"
  SEMAPHORE_ADMIN_PASSWORD: "your-admin-password"
  SEMAPHORE_ACCESS_KEY_ENCRYPTION: "your-generated-16-byte-hex-key" # Например, 4a1e71f9a2b8b9d0c8e3f2a1b5c4d6e7
  SEMAPHORE_LDAP_PASSWORD: "" # Если LDAP не используется
```

### 4. PersistentVolumeClaim
Создается для хранения временных файлов, в основном плейбуков из Git.

```yaml
# semaphore-pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: semaphore-pvc
  namespace: semaphore
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi # Размер зависит от ожидаемого объема плейбуков
  storageClassName: your-storage-class # Укажите ваш StorageClass
```

### 5. Deployment
Основной манифест, описывающий запуск контейнера Semaphore.

```yaml
# semaphore-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: semaphore
  namespace: semaphore
  labels:
    app: semaphore
spec:
  replicas: 1
  selector:
    matchLabels:
      app: semaphore
  template:
    metadata:
      labels:
        app: semaphore
    spec:
      containers:
        - name: semaphore
          image: semaphoreui/semaphore:v2.8.90 # Рекомендуется указывать актуальную версию
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 3000
              protocol: TCP
          env:
            - name: SEMAPHORE_PLAYBOOK_PATH
              value: "/tmp/semaphore" # Путь монтирования PVC
          envFrom:
            - configMapRef:
                name: semaphore-cm
            - secretRef:
                name: semaphore-secret
          volumeMounts:
            - name: playbooks
              mountPath: "/tmp/semaphore"
          livenessProbe:
            tcpSocket:
              port: 3000
            initialDelaySeconds: 20
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/ping
              port: 3000
            initialDelaySeconds: 20
            periodSeconds: 10
      volumes:
        - name: playbooks
          persistentVolumeClaim:
            claimName: semaphore-pvc
```

### 6. Service и Ingress
Для доступа к веб-интерфейсу создаются `Service` и `Ingress`.

```yaml
# semaphore-service-ingress.yaml
apiVersion: v1
kind: Service
metadata:
  name: semaphore
  namespace: semaphore
spec:
  selector:
    app: semaphore
  ports:
    - protocol: TCP
      port: 80
      targetPort: 3000
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: semaphore-ingress
  namespace: semaphore
spec:
  rules:
    - host: "semaphore.your-domain.local"
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: semaphore
                port:
                  number: 80
```

## Дополнительная информация и особенности

- **Ограничения конфигурации**: Встроенный wrapper-скрипт (`semaphore-wrapper.sh`) в Docker-образе обрабатывает не все параметры, доступные в файле `config.json`. Это может ограничить настройку таких функций, как уведомления по email или в Telegram.
- **Альтернативный подход к конфигурации**: Для полной кастомизации можно отказаться от встроенного wrapper-скрипта. Один из способов — использовать инструмент `dockerize`, который позволяет сгенерировать `config.json` из шаблона при запуске контейнера. Это требует модификации Docker-образа или `command` в манифесте `Deployment`.
- **Работа с Git-репозиториями**: Для доступа к публичным репозиториям, не требующим аутентификации, в Semaphore необходимо создать ключ доступа типа `None`.
- **Проблемы с DNS в инвентаре**: Если в Ansible-инвентаре используются хостнеймы, которые не могут быть разрешены внутренним DNS-сервисом контейнера, может потребоваться явно прописать IP-адреса хостов в файле инвентаря.
- **Миграция**: При переносе Semaphore на новую инсталляцию с сохранением старой базы данных, ключевым является сохранение значения `SEMAPHORE_ACCESS_KEY_ENCRYPTION`. Без него Semaphore не сможет расшифровать секреты, хранящиеся в БД.
