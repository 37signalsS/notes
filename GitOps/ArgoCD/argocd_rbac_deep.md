# Argo CD: RBAC — модель доступа, policy.csv и практические сценарии

> **Актуальность (2026):** Модель RBAC Argo CD v3.x поддерживает встроенные роли (`role:readonly`, `role:admin`), кастомные роли через `policy.csv` в `argocd-rbac-cm`, JWT-токены для автоматизации и интеграцию с SSO (OIDC/LDAP) через scopes и groups. Политики оцениваются сверху вниз, первое совпадение определяет результат. По умолчанию — `policy.default: role:readonly`.

## Предварительные требования

1. **Argo CD установлен и доступен** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
2. **kubectl** с доступом к namespace `argocd`.
3. **argocd CLI** настроен и авторизован.
4. **SSO настроен** (опционально, для интеграции с группами) — см. [SSO с GitLab](./argocd_sso_gitlab.md).
5. **Понимание AppProject** — RBAC тесно связан с проектами (см. [AppProject](./argocd_appproject_deep.md)).

## Определения

**RBAC Argo CD (Role-Based Access Control)** — модель управления доступом, определяющая, какие действия (get, create, sync, delete и др.) пользователи и группы могут выполнять с приложениями, проектами и кластерами в Argo CD.

**Policy (Политика)** — правило в формате CSV, определяющее разрешение или запрет конкретного действия для роли или пользователя. Записывается в `argocd-rbac-cm` ConfigMap.

**Role (Роль)** — именованный набор разрешений. Начинается с `role:` (например, `role:readonly`, `role:admin`). Роли назначаются пользователям через маппинги `g,` (group).

**Subject (Субъект)** — пользователь, группа или сервисный аккаунт, которому назначается роль. В Argo CD субъекты привязываются к ролям через записи `g,` в policy.csv.

**JWT (JSON Web Token)** — токен авторизации, генерируемый Argo CD для CLI/API-доступа. Содержит claim `sub` (имя пользователя) и опционально `groups`. Истекает через заданное время.

**Scopes (Области)** — параметр `scopes` в `argocd-rbac-cm`, определяющий, какие claims из OIDC-токена используются для определения групп пользователя (по умолчанию `[groups]`).

## Базовые концепции

### Архитектура RBAC в Argo CD

```text
Запрос (CLI/API/UI)
    │
    ▼
┌─────────────────────────┐
│  Аутентификация         │  ← SSO (OIDC/LDAP) или локальный пользователь
│  (Who are you?)         │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  Авторизация (RBAC)     │  ← policy.csv + встроенные роли
│  (What can you do?)     │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────┐
│  AppProject Restrictions│  ← namespaceResourceWhitelist/Blacklist
│  (Where can you apply?) │
└─────────────────────────┘
```

### Структура policy.csv

Файл `policy.csv` в ConfigMap `argocd-rbac-cm` содержит записи двух типов:

**1. Правила разрешений (p):**
```csv
p, <role>, <resource>, <action>, <object>, <allow|deny>
```

| Поле | Описание | Примеры |
| :--- | :--- | :--- |
| `p` | Тип записи (policy) | `p` |
| `<role>` | Имя роли | `role:readonly`, `role:dev-team` |
| `<resource>` | Тип ресурса | `applications`, `clusters`, `repositories`, `logs`, `exec` |
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
| `<subject>` | Пользователь или группа | `admin`, `team-dev`, ` infra/k8s-admins` |
| `<role>` | Имя роли | `role:readonly`, `role:admin` |

### Встроенные роли

| Роль | Описание |
| :--- | :--- |
| `role:readonly` | Только чтение (`get`) для всех ресурсов. Используется как `policy.default`. |
| `role:admin` | Полный доступ ко всем ресурсам и действиям. |

### Порядок оценки политик

```text
1. Точное совпадение (конкретный пользователь + ресурс + действие)
   │
2. Совпадение по роли (role:dev-team + ресурс + действие)
   │
3. policy.default (если ни одно правило не совпало)
   │
4. Запрет по умолчанию (если policy.default не задан)
```

**Важно:** политики оцениваются **сверху вниз**. Последнее совпадающее правило определяет результат. Если есть `deny` — он имеет приоритет над `allow` на том же уровне.

### Поддерживаемые ресурсы и действия

| Ресурс | Действия | Описание |
| :--- | :--- | :--- |
| `applications` | `get`, `create`, `sync`, `delete`, `override` | Управление приложениями |
| `clusters` | `get`, `create`, `delete` | Управление кластерами |
| `repositories` | `get`, `create`, `delete` | Управление репозиториями |
| `logs` | `get` | Просмотр логов |
| `exec` | `create` | Выполнение команд в подах (terminal) |
| `projects` | `get`, `create`, `delete` | Управление AppProject |

### Маски объектов (Object Masks)

| Маска | Описание | Пример |
| :--- | :--- | :--- |
| `*/*` | Все проекты, все приложения | `p, role:readonly, applications, get, */*, allow` |
| `project1/*` | Все приложения в проекте `project1` | `p, role:dev, applications, get, project1/*, allow` |
| `project1/app1` | Конкретное приложение | `p, role:dev, applications, sync, project1/app1, allow` |
| `*/app1` | Приложение `app1` во всех проектах | `p, role:dev, applications, get, */app1, allow` |

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

## Ограничения и edge cases

### Ограничения

- **Нет вложенности ролей:** Роли не наследуют друг друга. Каждая роль — независимый набор правил.
- **Нет условий (conditions):** Политики не поддерживают условную логику (например, "только в рабочие часы"). Для этого используйте [Sync Windows](./synchronization/scenarios/sync_windows.md).
- **Одна policy.csv:** Все правила хранятся в одном ConfigMap. Нет возможности разделить политики по namespace.
- **Делегирование через AppProject:** Argo CD не поддерживает делегирование управления RBAC — все политики глобальны.

### Edge Cases

- **Отрицание vs разрешение:** Если `deny` и `allow` совпадают на одном уровне, `deny` имеет приоритет.
- **Удаление policy.csv:** При удалении всех правил пользователи теряют доступ (остаётся только `policy.default`).
- **SSO группы меняются:** При обновлении групп в OIDC-провайдере Argo CD не обновляет кэш до истечения сессии.
- **Токен истёк:** При использовании JWT-токена с истёкшим сроком действия — Argo CD возвращает 401.

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
