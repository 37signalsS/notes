# Argo CD: RBAC — модель доступа, policy.csv и практические сценарии

**Актуально для:** Argo CD v3.4+ (покрывает v3.4.x, v3.5.x, v3.6.x; отличаются `applicationsets` ресурс, `scopes` поведение, JWT token lifetime defaults)

## Предварительные требования

Перед работой с RBAC Argo CD убедитесь в выполнении следующих условий:

1. **Кластер Kubernetes:** версия v1.26+ (рекомендуется v1.28+ для полной поддержки RBAC-интеграции с OIDC).
2. **Argo CD установлен и доступен:** проверьте статус подов:
   ```bash
   kubectl get pods -n argocd
   # → все поды в статусе Running, READY 1/1 или 2/2
   ```
3. **kubectl** с доступом к namespace `argocd` (права на чтение/запись ConfigMap).
4. **argocd CLI** установлен (версия, совместимая с сервером) и настроен вход:
   ```bash
   argocd version
   argocd login <ARGOCD_SERVER> --username admin --password <password>
   ```
5. **Git-репозиторий:** доступен для Argo CD (настроены credentials в `argocd-repo-server` или публичный доступ).
6. **RBAC:** права администратора кластера для первоначальной настройки `argocd-rbac-cm`. Для операций управления приложениями достаточно соответствующих ролей в AppProject.
7. **SSO настроен** (опционально, для интеграции с группами) — см. [SSO с GitLab](./argocd_sso_gitlab.md).
8. **Понимание AppProject** — RBAC тесно связан с проектами (см. [AppProject](./argocd_appproject_deep.md)).
9. **Работающая базовая авторизация:** приложение успешно синхронизировалось хотя бы один раз вручную перед настройкой кастомных политик.

## Определения

**RBAC Argo CD (Role-Based Access Control)** — модель управления доступом, определяющая, какие действия (`get`, `create`, `sync`, `delete`, `override` и др.) пользователи и группы могут выполнять с ресурсами Argo CD: приложениями (`applications`), кластерами (`clusters`), репозиториями (`repositories`), логами (`logs`), терминалом (`exec`), проектами (`projects`) и ApplicationSet (`applicationsets`).

**Policy (Политика)** — правило в формате CSV, определяющее разрешение или запрет конкретного действия для роли или пользователя. Записывается в ConfigMap `argocd-rbac-cm` в поле `policy.csv`.

**Role (Роль)** — именованный набор разрешений. Имя роли всегда начинается с префикса `role:` (например, `role:readonly`, `role:admin`, `role:dev-team`). Роли назначаются пользователям через маппинги `g,` (group) в policy.csv.

**Subject (Субъект)** — пользователь, группа или сервисный аккаунт, которому назначается роль. В Argo CD субъекты привязываются к ролям через записи `g,` в policy.csv. Формат: `g, <subject>, <role>`.

**JWT (JSON Web Token)** — токен авторизации, генерируемый Argo CD для CLI/API-доступа. Содержит claim `sub` (имя пользователя/аккаунта) и опционально `groups`. Истекает через время, заданное в `users.session.duration` в `argocd-cm` (по умолчанию 24 часа).

**Scopes (Области)** — параметр `scopes` в `argocd-rbac-cm`, определяющий, какие claims из OIDC-токена используются для определения групп пользователя (по умолчанию `[groups]`).

**AppProject Restrictions** — дополнительный слой авторизации, проверяемый после RBAC: namespaceResourceWhitelist/Blacklist, destinations, source repositories. См. [AppProject](./argocd_appproject_deep.md).

## Основные концепции

### Архитектура RBAC в Argo CD

```text
Запрос (CLI/API/UI)
    │
    ▼
┌─────────────────────────┐
│  Аутентификация         │  ← SSO (OIDC/LDAP), локальный пользователь,
│  (Who are you?)         │     JWT-токен (account:token)
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Авторизация (RBAC)     │  ← policy.csv + встроенные роли
│  (What can you do?)     │     Оценка: p/rules → g/mappings → policy.default
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  AppProject Restrictions│  ← namespaceResourceWhitelist/Blacklist,
│  (Where can you apply?) │     destinations, source repos, sync windows
└─────────────────────────┘
```

**Порядок проверки (Defense-in-Depth):**
1. **Аутентификация** — проверка личности (SSO, local account, JWT)
2. **RBAC** — проверка действия на ресурсе (`p, role:X, applications, sync, proj/*, allow`)
3. **AppProject** — проверка границ (может ли пользователь вообще видеть этот проект/кластер/репозиторий)

### Структура policy.csv

Файл `policy.csv` в ConfigMap `argocd-rbac-cm` содержит записи двух типов:

**1. Правила разрешений (p):**
```csv
p, <role>, <resource>, <action>, <object>, <allow|deny>
```

| Поле | Описание | Примеры |
| :--- | :--- | :--- |
| `p` | Тип записи (policy) | `p` |
| `<role>` | Имя роли (обязательно с префиксом `role:`) | `role:readonly`, `role:dev-team`, `role:ci-bot` |
| `<resource>` | Тип ресурса | `applications`, `clusters`, `repositories`, `logs`, `exec`, `projects`, `applicationsets` |
| `<action>` | Действие | `get`, `create`, `sync`, `delete`, `override` |
| `<object>` | Объект (маска) | `*/*` (все), `proj1/*` (проект), `app1` (конкретное приложение) |
| `<allow\|deny>` | Результат | `allow` или `deny` |

**2. Маппинги групп (g):**
```csv
g, <subject>, <role>
```

| Поле | Описание | Примеры |
| :--- | :--- | :--- |
| `g` | Тип записи (group) | `g` |
| `<subject>` | Пользователь или группа (как приходят из OIDC/SSO) | `admin`, `team-dev`, `infra/k8s-admins`, `ci-bot` |
| `<role>` | Имя роли (с префиксом `role:`) | `role:readonly`, `role:admin`, `role:dev-team` |

### Встроенные роли

| Роль | Описание |
| :--- | :--- |
| `role:readonly` | Только чтение (`get`) для всех ресурсов. Используется как `policy.default` по умолчанию. |
| `role:admin` | Полный доступ ко всем ресурсам и действиям (включая `override`, `clusters`, `repositories`). |

### Порядок оценки политик

```text
1. Точное совпадение (конкретный пользователь через g, + ресурс + действие)
   │
2. Совпадение по роли (role:dev-team + ресурс + действие) — правила p, сверху вниз
   │
3. policy.default (если ни одно правило не совпало)
   │
4. Запрет по умолчанию (если policy.default не задан)
```

**Важно:** политики `p,` оцениваются **сверху вниз**. Первое совпадающее правило определяет результат. Если есть `deny` и `allow` на одном уровне специфичности — `deny` имеет приоритет.

### Поддерживаемые ресурсы и действия

| Ресурс | Действия | Описание |
| :--- | :--- | :--- |
| `applications` | `get`, `create`, `sync`, `delete`, `override` | Управление приложениями (sync, rollback, patch) |
| `clusters` | `get`, `create`, `delete` | Управление подключенными кластерами |
| `repositories` | `get`, `create`, `delete` | Управление Git/Helm репозиториями |
| `logs` | `get` | Просмотр логов подов приложений |
| `exec` | `create` | Выполнение команд в подах (terminal/webshell) |
| `projects` | `get`, `create`, `delete` | Управление AppProject |
| `applicationsets` | `get`, `create`, `delete`, `sync` | Управление ApplicationSet (v3.5+) |

### Маски объектов (Object Masks)

| Маска | Описание | Пример |
| :--- | :--- | :--- |
| `*/*` | Все проекты, все приложения | `p, role:readonly, applications, get, */*, allow` |
| `project1/*` | Все приложения в проекте `project1` | `p, role:dev, applications, get, project1/*, allow` |
| `project1/app1` | Конкретное приложение | `p, role:dev, applications, sync, project1/app1, allow` |
| `*/app1` | Приложение `app1` во всех проектах | `p, role:dev, applications, get, */app1, allow` |

**Синтаксис масок:** `project` может быть `*` (любой), `name` (конкретный). `application` может быть `*` (все в проекте) или `name` (конкретное). Для ресурсов без проекта (clusters, repositories) используется просто `*`.

## Практические сценарии

### Сценарий 1: Базовая настройка RBAC —readonly для всех

Все пользователи по умолчанию видят приложения, но не могут их синхронизировать или удалять.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
```

**Валидация:**
```bash
# Проверка текущей политики
kubectl get configmap argocd-rbac-cm -n argocd -o yaml | grep -A5 "policy.default"

# Тестирование доступа (от имени пользователя без кастомных ролей)
argocd admin settings rbac can role:readonly get applications '*/app1'
# → yes

argocd admin settings rbac can role:readonly sync applications '*/app1'
# → no
```

### Сценарий 2: Команда разработки — полный доступ к проекту

Команда `dev-team` имеет полный доступ ко всем приложениям в проекте `development`, но только чтение в `production`.

```yaml
data:
  policy.default: role:readonly
  policy.csv: |
    # Роль для dev-team
    p, role:dev-team, applications, get, development/*, allow
    p, role:dev-team, applications, create, development/*, allow
    p, role:dev-team, applications, sync, development/*, allow
    p, role:dev-team, applications, delete, development/*, allow

    # Роль для production — только sync и get
    p, role:prod-viewer, applications, get, production/*, allow
    p, role:prod-viewer, applications, sync, production/*, allow

    # Маппинг групп
    g, dev-team, role:dev-team
    g, dev-team, role:prod-viewer
```

**Валидация:**
```bash
argocd admin settings rbac can role:dev-team sync applications 'development/my-app'
# → yes

argocd admin settings rbac can role:dev-team delete applications 'production/my-app'
# → no

argocd admin settings rbac can role:prod-viewer sync applications 'production/my-app'
# → yes
```

### Сценарий 3: CI/CD бот с ограниченными правами

GitHub Actions или GitLab CI нужен доступ только для синхронизации конкретных приложений.

```yaml
data:
  policy.csv: |
    # Роль для CI-бота
    p, role:ci-bot, applications, get, */*, allow
    p, role:ci-bot, applications, sync, */*, allow
    p, role:ci-bot, applications, create, */*, allow
    # Запрет на удаление
    p, role:ci-bot, applications, delete, */*, deny

    # Назначение токена
    g, ci-bot, role:ci-bot
```

**Генерация JWT-токена:**
```bash
argocd account generate-token --account ci-bot
# → eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Использование токена в CI/CD
argocd app sync my-app --server argocd.example.com --auth-token eyJhbGci...
```

**Настройка срока действия токена:**
```yaml
# argocd-cm ConfigMap
data:
  # Токен по умолчанию истекает через 24 часа
  # Для CI/CD рекомендуется увеличить:
  users.session.duration: "720h"  # 30 дней
```

### Сценарий 4: Отдельная роль для чтения логов

SRE-команда может просматривать логи и терминал в подах, но не может синхронизировать.

```yaml
data:
  policy.csv: |
    p, role:sre, applications, get, */*, allow
    p, role:sre, logs, get, */*, allow
    p, role:sre, exec, create, */*, allow

    g, sre-team, role:sre
```

### Сценарий 5: Запрет удаления для конкретного проекта

Ни один пользователь (кроме admin) не может удалять приложения в проекте `critical-apps`.

```yaml
data:
  policy.csv: |
    # Явный запрет для всех ролей
    p, role:readonly, applications, delete, critical-apps/*, deny
    p, role:dev-team, applications, delete, critical-apps/*, deny
    p, role:sre, applications, delete, critical-apps/*, deny

    # Только admin может удалять (встроенный role:admin)
```

### Сценарий 6: LDAP/OIDC группы в RBAC

При SSO-аутентификации Argo CD получает claims из OIDC-токена и сопоставляет их с группами.

```yaml
data:
  policy.csv: |
    # Группы из GitLab/OIDC
    g, "infra/k8s-admins", role:admin
    g, "dev/backend-team", role:dev-backend
    g, "dev/frontend-team", role:dev-frontend
    g, "sre/on-call", role:sre

    # Роли
    p, role:dev-backend, applications, get, backend/*, allow
    p, role:dev-backend, applications, sync, backend/*, allow
    p, role:dev-frontend, applications, get, frontend/*, allow
    p, role:dev-frontend, applications, sync, frontend/*, allow
    p, role:sre, applications, get, */*, allow
    p, role:sre, logs, get, */*, allow

  # Области для OIDC claims
  scopes: "[groups]"
```

**Просмотр текущих групп пользователя:**
```bash
argocd account get-user-info
# → Name: john.doe
# → Groups: [infra/k8s-admins]

# Или через API
argocd account get --account john.doe
```

### Сценарий 7: JWT-токены для автоматизации (API)

Для автоматизации API без SSO используются静态ные JWT-токены.

**Создание сервисного аккаунта:**
```bash
# Создание пользователя
argocd account update-password --account automation-bot --new-password <secure-password>

# Генерация токена
argocd account generate-token --account automation-bot
```

**Настройка жизни токена:**
```yaml
# argocd-cm
data:
  # Максимальное время жизни токена
  users.session.duration: "8760h"  # 1 год (для bot-аккаунтов)
```

**Использование в скриптах:**
```bash
#!/bin/bash
ARGOCD_SERVER="argocd.example.com"
ARGOCD_TOKEN="eyJhbGciOiJIUzI1NiIs..."

# Синхронизация
argocd app sync my-app \
  --server "$ARGOCD_SERVER" \
  --auth-token "$ARGOCD_TOKEN" \
  --insecure

# Проверка статуса
argocd app get my-app \
  --server "$ARGOCD_SERVER" \
  --auth-token "$ARGOCD_TOKEN" \
  --insecure
```

### Сценарий 8: Диагностика доступа

Пошаговая процедура при ошибке `permission denied`.

**1. Проверка текущего пользователя:**
```bash
argocd account get-user-info
# → Name: <username>
# → Groups: [<group1>, <group2>]
```

**2. Проверка конкретного разрешения:**
```bash
# Синтаксис: argocd admin settings rbac can <role> <action> <resource> <object>
argocd admin settings rbac can role:dev-team sync applications 'development/my-app'
# → yes или no

# Проверка для конкретного пользователя
argocd admin settings rbac can role:readonly get applications '*/my-app'
```

**3. Просмотр всех политик:**
```bash
kubectl get configmap argocd-rbac-cm -n argocd -o yaml | grep -A50 "policy.csv"
```

**4. Проверка групп в OIDC:**
```bash
# Если SSO — проверьте claims в токене
argocd account get-user-info --account <username>

# Или через API
curl -s -H "Authorization: Bearer $TOKEN" \
  https://argocd.example.com/api/v1/account | jq '.groups'
```

**5. Типичные ошибки:**

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `permission denied` | Нет политики для роли | Добавьте `p, role:X, applications, action, proj/*, allow` |
| `permission denied` (sync) | `deny` имеет приоритет | Проверьте порядок правил в policy.csv |
| `groups is empty` | OIDC не передаёт groups | Проверьте `scopes` в `argocd-rbac-cm` |
| `role not found` | Некорректное имя роли | Имя должно начинаться с `role:` |

## Валидация

### 1. Проверка RBAC-политики на валидность
```bash
argocd admin settings rbac validate
# → RBAC configuration is valid
```

### 2. Проверка конкретного разрешения для роли
```bash
# Синтаксис: argocd admin settings rbac can <role> <action> <resource> <object>
argocd admin settings rbac can role:dev-team sync applications 'development/my-app'
# → yes

argocd admin settings rbac can role:readonly sync applications '*/my-app'
# → no
```

### 3. Проверка разрешений конкретного пользователя
```bash
# Через account (показывает эффективные группы и политики)
argocd account get-user-info
# → Name: john.doe
# → Groups: [infra/k8s-admins]

argocd admin settings rbac can role:readonly get applications '*/my-app'
# → yes
```

### 4. Проверка политики для ApplicationSet (v3.5+)
```bash
argocd admin settings rbac can role:admin create applicationsets '*/*, allow'
# → yes

argocd admin settings rbac can role:dev-team create applicationsets 'production/*, allow'
# → no
```

### 5. Проверка срока действия токена
```bash
# Расшифровка JWT (без проверки подписи)
argocd account generate-token --account test-user | cut -d. -f2 | base64 -d | jq '.exp'
# → 1735689600  (Unix timestamp)

# Сравнение с текущим временем
date +%s
# → 1735603200
```

### 6. Полная проверка конфигурации RBAC
```bash
# Экспорт полной конфигурации
kubectl get configmap argocd-rbac-cm -n argocd -o yaml

# Проверка policy.default
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.policy\.default}'
# → role:readonly

# Проверка scopes
kubectl get configmap argocd-rbac-cm -n argocd -o jsonpath='{.data.scopes}'
# → [groups]
```

### 7. Проверка через API
```bash
# Список всех аккаунтов
curl -s -H "Authorization: Bearer $TOKEN" \
  https://argocd.example.com/api/v1/accounts | jq '.[] | {name, capabilities}'

# Группы конкретного пользователя
curl -s -H "Authorization: Bearer $TOKEN" \
  https://argocd.example.com/api/v1/account | jq '.groups'
```

## Рекомендации и лучшие практики

### Безопасность

- **Принцип наименьших привилегий:** Каждая роль должна иметь минимально необходимые разрешения.
- **Запрет по умолчанию:** Используйте `policy.default: role:readonly` и явно разрешайте только необходимое.
- **Раздельные роли для CI/CD:** Не используйте `role:admin` для автоматизации — создайте отдельную роль `role:ci-bot`.
- **Регулярный аудит:** Проверяйте policy.csv на предмет устаревших или избыточных правил.
- **Изоляция production:** Явно запрещайте `delete` для production-проектов.

### Производительность

- **Минимальное количество правил:** Чем меньше записей в policy.csv, тем быстрее оценка.
- **Группировка:** Используйте группы вместо индивидуальных ролей для каждого пользователя.
- **Кэширование:** Argo CD кэширует результаты RBAC-оценки — избегайте частых изменений policy.csv.

### Надежность

- **Тестирование перед деплоем:** Используйте `argocd admin settings rbac can` для проверки политик.
- **Версионирование:** Храните argocd-rbac-cm в Git и применяйте через Argo CD (Dogfooding).
- **Бэкап:** Экспортируйте argocd-rbac-cm перед изменениями.

## Диагностика и устранение неисправностей

### Пошаговый алгоритм диагностики при ошибке `permission denied`

```text
1. argocd account get-user-info
   ├── Нет? → Проблема аутентификации (SSO, токен, локальный аккаунт)
   └── Есть? → Перейдите к шагу 2

2. argocd admin settings rbac can <role> <action> <resource> <object>
   ├── yes → Доступ должен быть, проверьте AppProject restrictions
   └── no → Перейдите к шагу 3

3. kubectl get configmap argocd-rbac-cm -n argocd -o yaml
   ├── policy.default задан? → Нет? Добавьте role:readonly
   ├── policy.csv содержит нужные p, правила? → Нет? Добавьте
   ├── g, маппинги корректны? → Нет? Исправьте названия групп
   └── scopes настроен? → Нет? Добавьте scopes: "[groups]"

4. Проверьте AppProject:
   kubectl get appproject <project> -o yaml
   ├── namespaceResourceWhitelist/Blacklist блокирует?
   ├── destinations разрешен?
   └── sourceRepositories разрешен?
```

### Расширенная таблица ошибок

| Ошибка / Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `permission denied` (get applications) | Нет `p, role:X, applications, get, ..., allow` | `argocd admin settings rbac can role:X get applications 'proj/*'` | Добавьте правило `p, role:X, applications, get, proj/*, allow` |
| `permission denied` (sync) | `deny` перекрывает `allow` | Проверьте порядок в policy.csv: `deny` выше `allow` | Переместите `allow` выше `deny` или удалите `deny` |
| `permission denied` (create ApplicationSet) | Нет ресурса `applicationsets` в policy | `argocd admin settings rbac can role:X create applicationsets '*/*'` | Добавьте `p, role:admin, applicationsets, create, */*, allow` (v3.5+) |
| `groups is empty` / `groups: []` | OIDC не передаёт `groups` claim | `argocd account get-user-info` → Groups: [] | Настройте `scopes: "[groups]"` в argocd-rbac-cm; проверьте OIDC provider |
| `role not found` | Имя роли без префикса `role:` | Ошибка в policy.csv или g, маппинге | Все роли должны начинаться с `role:` |
| `token expired` / `401 Unauthorized` | JWT истёк (`exp` claim < now) | `argocd account generate-token ... \| cut -d. -f2 \| base64 -d \| jq '.exp'` | Сгенерируйте новый токен; увеличьте `users.session.duration` в argocd-cm |
| `SSO login successful but no permissions` | Группы из OIDC не совпадают с g, | `argocd account get-user-info` → Groups: ["exact/path"] | Точное совпадение строки в g, (case-sensitive, полные пути) |
| `argocd admin settings rbac validate` fails | Синтаксическая ошибка в policy.csv | `argocd admin settings rbac validate` | Исправьте CSV: правильное количество полей, нет лишних пробелов |
| `exec: permission denied` | Нет `p, role:X, exec, create, *, allow` | `argocd admin settings rbac can role:X create exec '*'` | Добавьте правило для ресурса `exec` |
| `logs: permission denied` | Нет `p, role:X, logs, get, *, allow` | `argocd admin settings rbac can role:X get logs '*'` | Добавьте правило для ресурса `logs` |
| `clusters: permission denied` | Нет прав на кластер | `argocd admin settings rbac can role:X get clusters '*'` | Добавьте правила для ресурса `clusters` |
| `repositories: permission denied` | Нет прав на репозиторий | `argocd admin settings rbac can role:X get repositories '*'` | Добавьте правила для ресурса `repositories` |
| `projects: permission denied` | Нет прав на AppProject | `argocd admin settings rbac can role:X get projects '*'` | Добавьте правила для ресурса `projects` |

### Команды для глубокой диагностики

```bash
# 1. Полный дамп RBAC конфигурации
kubectl get configmap argocd-rbac-cm -n argocd -o yaml

# 2. Проверка кэша RBAC (перезапуск argocd-server очищает кэш)
kubectl rollout restart deployment argocd-server -n argocd

# 3. Логи argocd-server для RBAC-решений
kubectl logs -n argocd deployment/argocd-server | grep -i rbac

# 4. Тест маски объекта
argocd admin settings rbac can role:dev-team get applications 'proj/app'
# → yes/no

# 5. Проверка эффективных групп после SSO
argocd account get-user-info --account <username>

# 6. Проверка argocd-cm для token duration
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.users\.session\.duration}'
# → 24h (default) или настроенное значение
```

## Ограничения и edge cases

### Ограничения

- **Нет вложенности ролей:** Роли не наследуют друг друга. Каждая роль — независимый набор правил.
- **Нет условий (conditions):** Политики не поддерживают условную логику (например, "только в рабочие часы"). Для этого используйте [Sync Windows](./synchronization/scenarios/sync_windows.md).
- **Одна policy.csv:** Все правила хранятся в одном ConfigMap. Нет возможности разделить политики по namespace.
- **Делегирование через AppProject:** Argo CD не поддерживает делегирование управления RBAC — все политики глобальны.

### Edge Cases

- **Отрицание vs разрешение:** Если `deny` и `allow` совпадают на одном уровне специфичности, `deny` имеет приоритет. Порядок правил `p,` в policy.csv важен: первое совпадение побеждает.
- **Удаление policy.csv:** При удалении всех правил `p,` пользователи теряют доступ (остаётся только `policy.default`). Если `policy.default` не задан — полный запрет.
- **SSO группы меняются:** При обновлении групп в OIDC-провайдере Argo CD не обновляет кэш групп до истечения сессии пользователя (по умолчанию 24 часа, настраивается `users.session.duration`). Требуется релогин или перезапуск argocd-server.
- **Токен истёк:** При использовании JWT-токена с истёкшим сроком действия (`exp` claim) — Argo CD возвращает 401. Обновите токен через `argocd account generate-token` или увеличьте `users.session.duration` в `argocd-cm`.
- **Case-sensitivity групп:** Маппинг `g, "Infra/Admins", role:admin` не сработает для группы `infra/admins` из OIDC — точное совпадение строки (включая регистр и слеши).
- **policy.default не применяется к админам:** Встроенный `role:admin` игнорирует `policy.default` и имеет неявный `allow` на все ресурсы. Нельзя ограничить админа через policy.csv.
- **ApplicationSet RBAC отделен от applications:** Право `applications: sync` не даёт `applicationsets: create`. Нужен отдельный ресурс `applicationsets` (v3.5+).
- **AppProject не заменяет RBAC:** Даже с правильным RBAC, если AppProject не разрешает destination/repo — доступ будет заблокирован на уровне проекта (Defense-in-Depth).
- **Нет wildcard для действий:** Нельзя написать `p, role:X, applications, *, proj/*, allow` — каждое действие (`get`, `create`, `sync`, `delete`, `override`) требует отдельного правила.
- **override действие:** `override` позволяет форсировать синхронизацию с `--force`/`--replace` флагами. Требует явного `allow` даже если есть `sync`.
- **Кэш RBAC:** Argo CD кэширует результаты оценки RBAC. После изменения policy.csv изменения вступают в силу не мгновенно — до истечения TTL кэша или перезапуска argocd-server.
- **Локальные пользователи vs SSO:** Локальные пользователи (созданные через `argocd account update-password`) не имеют групп. Им нужно назначать роли напрямую через `g, username, role:X`.
- **scopes влияет только на OIDC:** Параметр `scopes: "[groups]"` в argocd-rbac-cm влияет только на группы из OIDC-токена. Локальные пользователи и JWT-токены не используют scopes.
- **Максимальная длина policy.csv:** ConfigMap ограничен 1 MB (Kubernetes limit). При очень большом количестве правил — выносите в отдельные ConfigMap невозможно (одна policy.csv), придётся оптимизировать правила.
- **Deny по умолчанию:** Если `policy.default` не задан — неявный `deny` для всех. Всегда задавайте `policy.default: role:readonly` как базу.

## Дополнительная информация

### См. также

- [Установка и настройка RBAC](./argocd_installation_and_setup.md#сценарий-6-настройка-rbac-и-локальных-пользователей)
- [SSO с GitLab (OIDC)](./argocd_sso_gitlab.md)
- [AppProject — ограничения](./argocd_appproject_deep.md)
- [API автоматизация](./argocd_api_automation.md)
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Disaster Recovery](./argocd_disaster_recovery.md) — Бэкап, восстановление, etcd snapshot, HA, geo-recovery.

### Ссылки

- [Argo CD RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
- [Argo CD Admin CLI](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [JWT Tokens in Argo CD](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/)
