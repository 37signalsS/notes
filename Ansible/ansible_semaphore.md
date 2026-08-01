# Semaphore — веб-интерфейс для Ansible и Terraform

## Определения

**Semaphore (Semaphore UI)** — это легковесный веб-интерфейс (UI) с открытым исходным кодом для управления задачами автоматизации. Первоначально созданный как альтернатива **Ansible Automation Platform (ранее Ansible Tower)** или **AWX**, Semaphore значительно менее требователен к ресурсам.

Начиная с версий **v2.19/v2.20**, проект трансформировался в платформу оркестрации, поддерживающую **Ansible**, **Terraform**, **OpenTofu**, **Terragrunt**, а также выполнение произвольных Bash/Python-скриптов с поддержкой сложных рабочих процессов (**Workflows**).

## Основные концепции

### Архитектура и компоненты

Semaphore — это приложение на Go, которое использует внешнюю базу данных (PostgreSQL/MySQL) для хранения состояния. Основные сущности системы:
- **Инвентарь (Inventory):** Поддерживает как файлы (INI/YAML) из репозитория, так и **Structured Inventory** (встроенный редактор хостов и групп в UI).
- **Учетные данные (Credentials):** SSH-ключи, пароли, токены.
- **Шаблоны задач (Task Templates):** Описания запусков, объединяющие код, инвентарь, учетные данные и параметры окружения.
- **Проекты (Projects):** Изолированные пространства имен (RBAC).
- **Раннеры (Runners):** 
    - **Local:** Выполнение задач непосредственно на узле с Semaphore.
    - **Remote:** Распределенное выполнение задач на удаленных серверах для масштабирования и доступа к изолированным сетям.

### Современные возможности (v2.20+)

*   **Workflows (DAG):** Объединение нескольких шаблонов задач в направленный ациклический граф с возможностью условного выполнения и передачи переменных. Поддерживаются **Approval Gates** (ручное подтверждение шага).
*   **Security Audit & SIEM:** Полный аудит действий пользователей (включая IP, User-Agent, измененный объект) с возможностью интеграции в SIEM-системы.
*   **Интеграция с Secret Managers:** Поддержка HashiCorp Vault, AWS Secrets Manager и Azure Key Vault для динамического получения секретов.
*   **Многофункциональность:** Semaphore выступает как HTTP-бэкенд для хранения стейта Terraform/OpenTofu с поддержкой блокировок.

### Управление конфигурацией

В Docker-окружениях Semaphore настраивается через переменные окружения. При старте встроенный скрипт `semaphore-wrapper` генерирует `config.json`.
Критически важный параметр — `SEMAPHORE_ACCESS_KEY_ENCRYPTION`. Это 16-байтовый (32 символа в hex) ключ, которым шифруются все секреты в базе данных. Его потеря делает невозможным использование существующих учетных данных после миграции или переустановки.

## Практические сценарии

### Развертывание в Kubernetes

Ниже приведен пример манифестов для развертывания Semaphore (v2.20+) в кластере Kubernetes с внешней базой данных.

#### 1. Создание Secret и ConfigMap

Сгенерируйте ключ шифрования перед созданием секрета: `openssl rand -hex 16`.

```yaml
# semaphore-secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: semaphore-secret
  namespace: semaphore
type: Opaque
stringData:
  SEMAPHORE_DB_PASS: "secure-db-password"
  SEMAPHORE_ADMIN_PASSWORD: "admin-web-password"
  SEMAPHORE_ACCESS_KEY_ENCRYPTION: "4a1e71f9a2b8b9d0c8e3f2a1b5c4d6e7" # Замените на свой
---
# semaphore-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: semaphore-cm
  namespace: semaphore
data:
  SEMAPHORE_DB_USER: "semaphore"
  SEMAPHORE_DB_HOST: "postgres-svc.database.svc.cluster.local"
  SEMAPHORE_DB_DIALECT: "postgres"
  SEMAPHORE_DB: "semaphore"
  SEMAPHORE_ADMIN: "admin"
  SEMAPHORE_ADMIN_NAME: "Administrator"
  SEMAPHORE_ADMIN_EMAIL: "admin@example.com"
```

#### 2. Deployment и PersistentVolumeClaim

PVC необходим для хранения склонированных репозиториев и кэша выполнения.

```yaml
# semaphore-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: semaphore
  namespace: semaphore
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
          image: semaphoreui/semaphore:v2.20.2
          ports:
            - containerPort: 3000
          env:
            - name: SEMAPHORE_PLAYBOOK_PATH
              value: "/tmp/semaphore"
          envFrom:
            - configMapRef:
                name: semaphore-cm
            - secretRef:
                name: semaphore-secret
          volumeMounts:
            - name: data
              mountPath: "/tmp/semaphore"
          livenessProbe:
            tcpSocket:
              port: 3000
            initialDelaySeconds: 30
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: semaphore-pvc
```

### Использование Semaphore как Terraform Backend

Semaphore нативно поддерживает хранение стейта инфраструктуры с блокировками. Это позволяет объединить инструменты в одном интерфейсе.

```hcl
terraform {
  backend "http" {
    address        = "https://semaphore.example.com/api/project/<PROJECT_ID>/terraform/state/<STACK_NAME>"
    lock_address   = "https://semaphore.example.com/api/project/<PROJECT_ID>/terraform/state/<STACK_NAME>/lock"
    unlock_address = "https://semaphore.example.com/api/project/<PROJECT_ID>/terraform/state/<STACK_NAME>/lock"
    username       = "api-user"
    password       = "api-token-here"
  }
}
```

### Разделение CI и CD (Повышение безопасности)

Semaphore эффективно решает проблему "слишком широких прав" у CI-систем (GitLab CI, GitHub Actions).

**Логика разделения:**
1.  **CI (Build):** Собирает артефакты и пушит их в реестр. Не имеет SSH-ключей серверов и облачных токенов.
2.  **Semaphore (CD):** Обладает правами на деплой. Запускается по webhook из CI после успешной сборки.
3.  **Валидация:** Semaphore может скачивать артефакт, проверять его цифровую подпись (например, через Cosign) и только после этого применять Terraform/Ansible.

## Дополнительная информация

### Рекомендации по эксплуатации

-   **Бэкапы:** При мажорных обновлениях (например, v2.18 -> v2.19) Semaphore меняет структуру БД (особенно в части инвентаря). Обязательно делайте дамп базы данных и сохраняйте `SEMAPHORE_ACCESS_KEY_ENCRYPTION`.
-   **Galaxy Authentication:** Для приватных репозиториев можно прикрепить Credentials напрямую к Task Template, чтобы Semaphore автоматически аутентифицировался перед запуском `ansible-galaxy install`.
-   **Уведомления:** Настраивайте отправку уведомлений о сбоях (Discord, Telegram, Webhook) на уровне шаблонов для оперативного реагирования команды.

### Работа с внешними зависимостями

Если плейбуки требуют специфических коллекций (например, `community.crypto`) или Python-библиотек (например, `boto3`):
1.  Создайте кастомный Docker-образ `FROM semaphoreui/semaphore:v2.20.2`.
2.  Добавьте установку: `RUN ansible-galaxy collection install -r requirements.yml && pip install -r requirements.txt`.
3.  Используйте этот образ в Deployment Kubernetes.

### Смотрите также

- [Лучшие практики безопасности Ansible](./ansible_security_best_practices.md)
- [Основы Ansible Vault](./Vault/basics.md)
- [Модели управления конфигурацией](../Concepts/configuration_management_models.md)
