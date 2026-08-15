# Semaphore — веб-интерфейс для Ansible и Terraform

## Определения

**Semaphore (Semaphore UI)** — это легковесная платформа оркестрации и веб-интерфейс (UI) с открытым исходным кодом для управления задачами автоматизации. Первоначально созданный как альтернатива **Ansible Automation Platform (ранее Ansible Tower)** или **AWX**, Semaphore отличается минимальными требованиями к ресурсам и высокой скоростью работы.

Начиная с версий **v2.19/v2.20**, проект перерос рамки простого GUI для Ansible и стал полноценным инструментом оркестрации, поддерживающим:
- **Ansible:** выполнение плейбуков и управление ролями.
- **Terraform / OpenTofu / Terragrunt:** управление инфраструктурой как кодом (IaC).
- **Bash / Python:** запуск произвольных скриптов.
- **Workflows:** построение сложных цепочек задач с зависимостями.

## Основные концепции

### Архитектура и компоненты

Semaphore — это монолитное приложение на языке Go, использующее внешнюю базу данных для хранения состояния.

**Основные сущности системы:**
- **Инвентарь (Inventory):** Поддерживает статические файлы (INI/YAML) из репозитория, а также **Structured Inventory** (встроенный редактор хостов и групп в UI).
- **Учетные данные (Credentials):** Безопасное хранение SSH-ключей, паролей, токенов и ключей API.
- **Шаблоны задач (Task Templates):** Объединяют программный код (репозиторий), инвентарь, учетные данные и параметры окружения в единый объект запуска.
- **Проекты (Projects):** Изолированные пространства имен для разделения доступа (RBAC).
- **Раннеры (Runners):** 
    - **Local:** Выполнение задач непосредственно в контейнере/процессе Semaphore.
    - **Remote:** Удаленные агенты для масштабирования и выполнения задач в изолированных сетевых сегментах.
    - **Ephemeral (v2.20+):** Поддержка запуска исполнителей в Docker или Kubernetes «на лету» для каждой задачи.

### Аутентификация и безопасность

Semaphore поддерживает современные методы управления доступом, что позволяет интегрировать его в корпоративную среду:
- **LDAP / Active Directory:** Аутентификация пользователей через корпоративный каталог.
- **OIDC (OpenID Connect):** Интеграция с Keycloak, GitLab, Google, Okta. Поддерживается автоматическое создание пользователей при первом входе.
- **2FA / TOTP:** Двухфакторная аутентификация для локальных учетных записей.
- **RBAC:** Детальное разграничение прав внутри проектов (Owner, Manager, Task Runner, Guest).

### Современные возможности

*   **Workflows (DAG):** Визуальный редактор для объединения шаблонов задач в направленный ациклический граф. Поддерживаются **Approval Gates** (пауза для ручного подтверждения) и передача переменных между шагами.
*   **Security Audit & SIEM:** Логирование всех действий пользователей (IP, User-Agent, детали изменений) с возможностью экспорта в системы мониторинга безопасности.
*   **Secret Managers:** Динамическое получение секретов из HashiCorp Vault, AWS Secrets Manager или Azure Key Vault вместо хранения их в базе Semaphore.
*   **HTTP Backend для Terraform:** Semaphore выступает как сервер хранения стейта (`terraform.tfstate`) с поддержкой блокировок (locking), что исключает конфликты при одновременном запуске.

### Управление конфигурацией

В Docker-окружениях Semaphore настраивается через переменные окружения. При старте встроенный скрипт `semaphore-wrapper` генерирует `config.json`.

Критически важный параметр — `SEMAPHORE_ACCESS_KEY_ENCRYPTION`. Это 16-байтовый (32 символа в hex) ключ, которым шифруются все секреты в базе данных. **Его потеря делает невозможным использование существующих учетных данных после миграции или переустановки.**

## Практические сценарии

### Развертывание в Kubernetes (Helm / Manifests)

Для стабильной работы в K8s рекомендуется использовать внешнюю базу данных (PostgreSQL) и Persistent Volume для кэширования репозиториев.

#### 1. Подготовка секретов

Сгенерируйте ключ шифрования: `openssl rand -hex 16`.

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
  SEMAPHORE_ACCESS_KEY_ENCRYPTION: "4a1e71f9a2b8b9d0c8e3f2a1b5c4d6e7"
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
  SEMAPHORE_LDAP_ENABLE: "no" # Установите "yes" для включения LDAP
```

#### 2. Оптимизированный Deployment

Использование кастомного образа с предустановленными зависимостями сокращает время запуска задач.

```yaml
# semaphore-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: semaphore
  namespace: semaphore
spec:
  replicas: 1
  strategy:
    type: Recreate # Важно при использовании SQLite или RWO volumes
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
          envFrom:
            - configMapRef:
                name: semaphore-cm
            - secretRef:
                name: semaphore-secret
          volumeMounts:
            - name: data
              mountPath: "/tmp/semaphore"
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: semaphore-pvc
```

### Автоматизация через API

Semaphore предоставляет полный REST API (Swagger доступен по пути `/api` вашего инстанса).

**Пример запуска задачи через `curl`:**
```bash
curl -X POST "https://semaphore.example.com/api/project/1/templates/5/tasks" \
     -H "Authorization: Bearer <YOUR_API_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"environment_vars": {"target_version": "v1.2.3"}}'
```

### Использование Semaphore как Terraform Backend

Для использования Semaphore в качестве бэкенда добавьте следующий блок в конфигурацию Terraform:

```hcl
terraform {
  backend "http" {
    address        = "https://semaphore.example.com/api/project/<ID>/terraform/state/<NAME>"
    lock_address   = "https://semaphore.example.com/api/project/<ID>/terraform/state/<NAME>/lock"
    unlock_address = "https://semaphore.example.com/api/project/<ID>/terraform/state/<NAME>/lock"
    username       = "api-user"
    password       = "api-token-here"
  }
}
```

### Мониторинг и уведомления

- **Метрики:** Semaphore предоставляет метрики в формате Prometheus по пути `/metrics`. Они включают информацию о количестве запущенных задач, их статусе и загрузке раннеров.
- **Уведомления:** Поддерживается интеграция с **Slack**, **Telegram**, **Discord**, **Email** и произвольными **Webhooks**. Настройка производится на уровне проекта или конкретного шаблона задачи.

## Дополнительная информация

### Процесс обновления и бэкапы

1.  **Бэкап базы данных:** Обязателен перед любым обновлением. Semaphore автоматически выполняет миграции БД при запуске новой версии.
    - PostgreSQL: `pg_dump -U semaphore semaphore > backup.sql`
2.  **Сохранение ключа:** Убедитесь, что `SEMAPHORE_ACCESS_KEY_ENCRYPTION` сохранен в надежном месте (Vault/Keepass).
3.  **Обновление:** При использовании Docker просто обновите тег образа. При бинарной установке — замените исполняемый файл и перезапустите службу.
4.  **Откат:** В случае неудачи восстановите базу из бэкапа и верните предыдущую версию ПО.

### Работа с зависимостями Ansible

Если плейбуки требуют специфических коллекций или Python-библиотек:
- **Requirements:** Создайте файлы `requirements.yml` (для Ansible Galaxy) и `requirements.txt` (для pip) в корне репозитория. Semaphore автоматически установит их перед запуском задачи, если включена соответствующая опция в шаблоне.
- **Кастомные образы:** Для ускорения работы соберите собственный образ:
  ```dockerfile
  FROM semaphoreui/semaphore:v2.20.2
  RUN ansible-galaxy collection install community.general community.docker
  RUN pip install boto3 botocore
  ```

### Смотрите также

- [Лучшие практики безопасности Ansible](./ansible_security_best_practices.md)
- [Основы Ansible Vault](./Vault/basics.md)
- [Интеграция Ansible с GitLab CI/CD](../CI-CD/GitLab_CI/Tutorials/ansible_integration.md)
- [Модели управления конфигурацией](../Concepts/configuration_management_models.md)
