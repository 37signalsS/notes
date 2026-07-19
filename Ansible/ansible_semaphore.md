# Semaphore — веб-интерфейс для Ansible и Terraform

## Определения

**Semaphore (Semaphore UI)** — это легковесный веб-интерфейс (UI) с открытым исходным кодом для управления задачами автоматизации. Первоначально созданный как альтернатива **Ansible Automation Platform (ранее Ansible Tower)** или **AWX**, Semaphore значительно менее требователен к ресурсам и поддерживает не только Ansible, но и **Terraform**, **OpenTofu**, **Terragrunt** и выполнение произвольных Bash-скриптов.

## Основные концепции

### Архитектура и компоненты

Semaphore — это приложение на Go, которое использует внешнюю базу данных для хранения состояния. Основные сущности системы:
- **Инвентарь (Inventory):** Список хостов и групп, на которых будут выполняться задачи.
- **Учетные данные (Credentials):** SSH-ключи, пароли, токены и секреты из внешних хранилищ.
- **Шаблоны задач (Task Templates):** Описания запусков, объединяющие плейбук, инвентарь, учетные данные и параметры окружения.
- **Проекты (Projects):** Изолированные пространства имен для разделения доступа между командами или окружениями.

### Современные возможности (v2.18+)

*   **Интеграция с Secret Managers:** Поддержка HashiCorp Vault, AWS Secrets Manager и Azure Key Vault для динамического получения секретов.
*   **Безопасность:** Поддержка двухфакторной аутентификации (2FA) и интеграция с LDAP/Active Directory.
*   **Многофункциональность:** Возможность запуска Terraform/OpenTofu с хранением стейта через HTTP-бэкенд Semaphore.
*   **API и CLI:** Полный программный доступ ко всем функциям и возможность экспорта/импорта проектов.

### Управление конфигурацией

В Docker-окружениях Semaphore настраивается через переменные окружения. При старте встроенный скрипт `semaphore-wrapper` генерирует `config.json`.
Критически важный параметр — `SEMAPHORE_ACCESS_KEY_ENCRYPTION`. Это 16-байтовый (32 символа в hex) ключ, которым шифруются все секреты в базе данных. Его потеря делает невозможным использование существующих учетных данных после миграции.

## Практические сценарии

### Развертывание в Kubernetes

Ниже приведен пример манифестов для развертывания Semaphore в кластере Kubernetes с использованием внешней базы данных PostgreSQL.

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

PVC необходим для хранения склонированных репозиториев и временных файлов задач.

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
          image: semaphoreui/semaphore:v2.18.27
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

### Разделение CI и CD для повышения безопасности

Semaphore эффективно решает проблему "слишком широких прав" у CI-систем (например, GitLab CI или GitHub Actions).

**Логика разделения:**
1.  **CI (Build):** Собирает артефакты (Docker-образы, бинарные файлы) и пушит их в реестр. CI не имеет SSH-ключей от серверов или токенов от продакшн-облаков.
2.  **Semaphore (CD):** Обладает правами на деплой. Он запускается либо по вебхуку из CI, либо по расписанию (поллинг).
3.  **Валидация:** Semaphore может быть настроен на проверку цифровой подписи коммита или артефакта перед запуском деплоя, гарантируя, что код прошел все проверки безопасности.

## Дополнительная информация

### Рекомендации по эксплуатации

-   **Бэкапы:** Регулярно делайте дампы базы данных и обязательно сохраняйте `SEMAPHORE_ACCESS_KEY_ENCRYPTION` в защищенном месте (например, корпоративном Vault).
-   **Логирование:** Для интеграции с централизованными системами сбора логов используйте параметр `SEMAPHORE_LOG=true` и драйверы логирования контейнера.
-   **Обновления:** При переходе между мажорными версиями Semaphore автоматически выполняет миграции схемы базы данных при первом запуске нового образа.

### Работа с внешними зависимостями

Если ваши плейбуки требуют специфических коллекций Ansible или Python-библиотек:
1.  Создайте кастомный Docker-образ на базе официального.
2.  Добавьте установку зависимостей через `ansible-galaxy collection install` и `pip install`.
3.  Используйте этот образ в Deployment.

### Смотрите также

- [Лучшие практики безопасности Ansible](./ansible_security_best_practices.md)
- [Основы Ansible Vault](./Vault/basics.md)
- [Модели управления конфигурацией](../Concepts/configuration_management_models.md)
