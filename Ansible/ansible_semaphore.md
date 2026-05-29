# Semaphore — веб-интерфейс для Ansible

## Определения

**Semaphore** — это легковесный и быстрый веб-интерфейс (UI, User Interface) с открытым исходным кодом для запуска Ansible-плейбуков. Он предоставляет централизованную панель для управления ИТ-инфраструктурой, аналогичную Ansible Tower или его open-source версии AWX, но является значительно более простой и менее требовательной к ресурсам альтернативой.

## Основные концепции

**Архитектура:** Semaphore состоит из веб-приложения и требует внешнюю базу данных (PostgreSQL или MySQL) для хранения состояния: инвентарь, учетные данные, шаблоны задач, история запусков.

**Конфигурация:** Основная конфигурация осуществляется через переменные окружения. В официальном Docker-образе используется внутренний shell-скрипт (`semaphore-wrapper`), который на основе этих переменных генерирует итоговый конфигурационный файл `config.json` при старте контейнера.

**Хранение данных:** Для хранения временных файлов (клонированные из Git репозитории с плейбуками) используется персистентное хранилище. В Kubernetes для этого используется `PersistentVolumeClaim` (PVC).

## Практические сценарии

### Развертывание в Kubernetes

Развертывание Semaphore в Kubernetes сводится к созданию набора манифестов, которые описывают все необходимые компоненты системы.

#### 1. Подготовка: Namespace и База Данных

Рекомендуется разворачивать Semaphore в отдельном пространстве имен (`namespace`).

```bash
kubectl create namespace semaphore
# → namespace/semaphore created
```

Перед установкой необходимо иметь работающий экземпляр PostgreSQL или MySQL, доступный из кластера Kubernetes.

#### 2. ConfigMap

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

#### 3. Secret

Используется для хранения паролей и ключа шифрования.

**Важно:** `SEMAPHORE_ACCESS_KEY_ENCRYPTION` — это ключ, которым Semaphore шифрует чувствительные данные в базе (например, ключи SSH). Он критически важен для бэкапов и миграций. Если вы переносите инсталляцию, этот ключ должен совпадать.

Сгенерировать ключ можно командой:

```bash
openssl rand -hex 16
# → 4a1e71f9a2b8b9d0c8e3f2a1b5c4d6e7
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

#### 4. PersistentVolumeClaim

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

#### 5. Deployment

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
          image: semaphoreui/semaphore:v2.17.28 
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

#### 6. Service и Ingress

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

### Безопасное разделение CI и CD

Semaphore часто используется как инструмент для физического разделения процессов сборки (CI, Continuous Integration — непрерывная интеграция) и развертывания (CD, Continuous Deployment — непрерывное развертывание) с целью защиты инфраструктуры от компрометации CI-системы (например, GitLab CI). Если CI-система и ее администраторы скомпрометированы, разделение не позволит злоумышленникам напрямую выкатить вредоносный код на продакшн.

**Архитектура решения:**

1. **Отсутствие продовых секретов в CI:** CI-раннеры лишаются доступа к production-окружению и секретам. Они только собирают артефакты.
2. **Независимые пайплайны деплоя:** Semaphore настраивается на поллинг репозитория (по cron) или реагирует на вебхуки для инициации деплоя.
3. **Каскад плейбуков (Auto-run):** Используется фича запуска плейбуков по цепочке:
   - *Плейбук 1 (Check Integrity):* Скачивает исходники или артефакты и **проверяет их подпись** (например, x509 сертификат или GPG). Если проверка не пройдена, процесс останавливается.
   - *Плейбук 2 (Deploy):* В случае успешной валидации, Semaphore автоматически запускает следующий плейбук, который подтягивает временные токены (через робота) и выполняет безопасный деплой.
4. **Разграничение прав в Semaphore:** Администраторы инфраструктуры настраивают учетные данные и пайплайны, в то время как разработчикам выдаются минимальные права на запуск задач (Task Runner) без возможности просматривать секреты или изменять логику развертывания.

## Дополнительная информация

**Ограничения конфигурации:** Встроенный wrapper-скрипт (`semaphore-wrapper.sh`) в Docker-образе обрабатывает не все параметры из `config.json`, что может ограничить настройку уведомлений (email, Telegram). Для полной кастомизации можно использовать `dockerize` для генерации `config.json` из шаблона при запуске контейнера (требует модификации образа или `command` в Deployment).

**Работа с Git:** Для доступа к публичным репозиториям без аутентификации в Semaphore необходимо создать ключ доступа типа `None`. Если в инвентаре используются хостнеймы, не разрешаемые внутренним Domain Name System (DNS) контейнера, может потребоваться явно прописать IP-адреса хостов в файле инвентаря.

**Миграция:** При переносе Semaphore на новую инсталляцию с сохранением базы данных критически важно сохранить значение `SEMAPHORE_ACCESS_KEY_ENCRYPTION` — без него Semaphore не сможет расшифровать секреты в БД.

**Протоколы аутентификации:** Semaphore поддерживает интеграцию с LDAP (Lightweight Directory Access Protocol) для централизованного управления пользователями.

### Смотрите также

- [Лучшие практики безопасности Ansible](ansible_security_best_practices.md)
- [Основы Ansible Vault](Vault/basics.md)
