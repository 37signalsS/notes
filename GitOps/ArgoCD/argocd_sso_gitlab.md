# ArgoCD: Настройка SSO через GitLab

> **Актуальность (2026):** Argo CD v3.x: Dex **остаётся стандартным** посредником для GitLab OIDC (v3.x не отказался от Dex для GitLab-коннектора). Начиная с v3.0+, Argo CD поддерживает нативную интеграцию с OIDC-провайдерами **без Dex** (LDAP, OIDC через `oidc.config`), но для GitLab рекомендуется использовать Dex по причинам: (1) поддержка вложенных групп, (2) автоматическое обновление групп при каждом входе, (3) централизованная настройка через ConfigMap.

Настройка Single Sign-On (SSO) в ArgoCD через GitLab позволяет централизованно управлять доступом пользователей, используя существующие учетные записи и группы GitLab. Для реализации используется встроенный сервер **Dex**.

## Предварительные требования

1. **Kubernetes кластер:** v1.26+ (рекомендуется v1.28+).
2. **Argo CD установлен:** Версия 2.x или 3.x. Проверка: `kubectl get pods -n argocd` — все поды в статусе `Running`.
3. **Dex сервер работает:** Под `argocd-dex-server` в статусе `Running`. Проверка: `kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server`.
4. **GitLab доступен:** SaaS (gitlab.com) или Self-managed инстанс с версией 15.0+.
5. **HTTPS настроен:** ArgoCD должен быть доступен по внешнему URL с валидным TLS-сертификатом.
6. **Кластерный доступ:** Вы具有 администраторские права для редактирования ConfigMap и Secret в namespace `argocd`.
7. **CLI `argocd`:** Установлен и настроен (`argocd login`).

## Определения

- **SSO (Single Sign-On)** — технология единого входа, позволяющая пользователю переходить между различными приложениями без повторной аутентификации.
- **Dex** — федеративный OpenID Connect (OIDC) провайдер, который выступает посредником между ArgoCD и внешними Identity Providers (IdP). Dex поддерживает多种 типы коннекторов: GitLab, GitHub, Google, LDAP, SAML, OIDC.
- **OIDC (OpenID Connect)** — протокол идентификации на базе OAuth 2.0, расширяющий его информацией о пользователе (Claims).
- **RBAC (Role-Based Access Control)** — механизм разграничения прав доступа на основе ролей, сопоставленных с группами пользователей.
- **Claims** — набор утверждений (атрибутов) о пользователе, возвращаемый IdP в OIDC-токене: `email`, `groups`, `sub`, `preferred_username`.
- **Политика доступа (Policy)** — набор правил в `argocd-rbac-cm`, определяющих, какие действия разрешены для каких ролей.
- **Группы (Groups)** — атрибут OIDC-токена, содержащий список групп, в которые входит пользователь в GitLab. Используется для маппинга на роли ArgoCD.

## Базовые концепции

### Архитектура взаимодействия

```
┌─────────────────────────────────────────────────────────────────────┐
│              ArgoCD SSO через GitLab: Архитектура OIDC             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│  │   Пользователь│───▶│ argocd-server│───▶│ argocd-dex   │          │
│  │   (Браузер)  │◀───│ (API/UI)     │◀───│ (OIDC-посредник)│        │
│  └──────────────┘    └──────────────┘    └──────────────┘          │
│         │                   │                   │                   │
│         │                   │                   ▼                   │
│         │                   │         ┌──────────────┐             │
│         │                   │         │    GitLab     │             │
│         │                   │         │  (IdP/Issuer) │             │
│         │                   │         └──────────────┘             │
│         │                   │                   │                   │
│         │                   ▼                   ▼                   │
│         │         ┌──────────────┐    ┌──────────────┐             │
│         │         │ argocd-rbac  │    │ OIDC-токен   │             │
│         │         │ (Политики)   │    │ (Claims:     │             │
│         │         └──────────────┘    │  email,      │             │
│         │                             │  groups)     │             │
│         │                             └──────────────┘             │
│         │                                                           │
│         ▼                                                           │
│  ┌──────────────┐                                                   │
│  │ Доступ к UI  │                                                   │
│  │ и API ArgoCD │                                                   │
│  └──────────────┘                                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Пошаговый процесс:**

1. **Запрос:** Пользователь инициирует вход в веб-интерфейсе ArgoCD (через UI или CLI `argocd login --sso`).
2. **Редирект:** `argocd-server` перенаправляет запрос к `argocd-dex-server`.
3. **Редирект к IdP:** Dex перенаправляет пользователя в GitLab (authorize endpoint).
4. **Аутентификация:** Пользователь вводит учетные данные в GitLab.
5. **Авторизация (GitLab):** GitLab запрашивает согласие пользователя на доступ к профилю (email, groups).
6. **Callback:** После успешного входа GitLab возвращает OIDC-токен (authorization code) серверу Dex через callback URL.
7. **Обмен токеном:** Dex обменивает authorization code на access token и id token.
8. **Извлечение Claims:** Dex извлекает Claims (email, groups) из id token.
9. **Сессия:** Dex создает сессию и перенаправляет пользователя обратно в ArgoCD с session cookie.
10. **Авторизация (ArgoCD):** ArgoCD применяет политики из `argocd-rbac-cm`, сопоставляя группы из Claims с ролями.

### Требования

- ArgoCD версии 2.x или 3.x.
- Доступ к GitLab (SaaS или Self-managed).
- Настроенный внешний URL для ArgoCD (обязательно HTTPS).
- Под `argocd-dex-server` в статусе `Running`.

**Важно для Argo CD v3.x:**
- Dex **обязателен** для GitLab-коннектора (нативный OIDC в v3 не поддерживает GitLab-специфичные поля groups).
- Если используется **только** GitHub/Google/LDAP — Dex можно отключить и использовать нативный `oidc.config` в `argocd-cm`.
- Для GitLab **рекомендуется** Dex из-за поддержки вложенных групп и автоматического обновления Claims.

### Claims в GitLab OIDC

GitLab возвращает следующие Claims в OIDC-токене:

| Claim | Описание | Пример |
| :--- | :--- | :--- |
| `sub` | Уникальный идентификатор пользователя | `gitlab\|12345678` |
| `email` | Email пользователя | `user@example.com` |
| `preferred_username` | Имя пользователя в GitLab | `john-doe` |
| `groups` | Список групп, в которые входит пользователь | `["infra/team", "shop/backend"]` |
| `groups_direct` | Только прямые группы (без вложенных) | `["infra/team"]` |
| `profile` | URL профиля в GitLab | `https://gitlab.com/john-doe` |

**Важно:** Группы в Claims передаются как **полные пути** (`path/to/group`), а не просто имена. Это критично для маппинга в RBAC.

### Политики доступа: Синтаксис и логика

ArgoCD использует собственный синтаксис политик в `argocd-rbac-cm`:

**Структура политики:**
```
p, <роль>, <ресурс>, <действие>, <объект>, <решение>
g, <субъект>, <роль>
```

**Параметры:**

| Поле | Описание | Примеры |
| :--- | :--- | :--- |
| **Роль** | Имя роли (начинается с `role:`) | `role:admin`, `role:dev-shop` |
| **Ресурс** | Тип ресурса ArgoCD | `applications`, `clusters`, `repositories`, `projects` |
| **Действие** | Операция над ресурсом | `get`, `create`, `sync`, `delete`, `override` |
| **Объект** | Паттерн имени ресурса (с подстановочными знаками) | `*/*`, `shop/*`, `shop/frontend-*` |
| **Решение** | Разрешение или запрет | `allow`, `deny` |

**Группировка (Group mapping):**
```
g, "<-gitlab-group-path>", <роль>
```

**Пример:**
```yaml
policy.csv: |
  # Полные права для группы infra/kubernetes-admins
  g, "infra/kubernetes-admins", role:admin

  # Кастомная роль для разработчиков проекта shop
  p, role:dev-shop, applications, get, shop/*, allow
  p, role:dev-shop, applications, sync, shop/*, allow

  # Маппинг вложенной группы GitLab на роль
  g, "shop-team/backend-devs", role:dev-shop

  # Запрет удаления для всех
  p, role:dev-shop, applications, delete, shop/*, deny
```

**Приоритет правил:**
1. `deny` всегда имеет приоритет над `allow`.
2. Правила проверяются сверху вниз.
3. Если ни одно правило не совпало — действие запрещено (по умолчанию `policy.default: role:readonly`).

**Стандартные роли ArgoCD:**

| Роль | Описание |
| :--- | :--- |
| `role:readonly` | Только чтение (get) для всех ресурсов |
| `role:admin` | Полный доступ ко всем ресурсам |
| `role:developer` | Чтение + синхронизация (по умолчанию) |

## Практические сценарии

### Шаг 1: Регистрация приложения в GitLab

1. В GitLab перейдите в **Settings → Applications** (на уровне инстанса или конкретной группы).
2. Заполните параметры:

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| **Name** | `ArgoCD` | Отображаемое имя приложения |
| **Redirect URI** | `https://<argocd-url>/api/dex/callback` | URI для возврата после аутентификации |
| **Confidential** | `Yes` (включено) | Обязательно для OIDC |
| **Scopes** | `openid`, `profile`, `email`, `read_api` | Минимально необходимые области доступа |
| **_expire_token_after** | `3600` | Время жизни токена (рекомендуется 1 час) |

3. Сохраните **Application ID** и **Secret**.

**Примечание для Self-managed GitLab:**
- Убедитесь, что GitLab доступен по HTTPS с валидным сертификатом.
- Если используется внутренний CA — добавьте корневой сертификат в `argocd-cm` (см. Шаг 3).

### Шаг 2: Хранение секрета в Kubernetes

Для обеспечения безопасности `clientSecret` рекомендуется хранить в `argocd-secret`.

**Вариант А: Редактирование существующего секрета**
```bash
# Кодирование секрета в base64
echo -n "ваш_секрет_gitlab" | base64

# Добавление в argocd-secret
kubectl edit secret -n argocd argocd-secret
```
Добавьте поле `gitlab.clientSecret` в секцию `data`.

**Вариант Б: Декларативный манифест (External Secrets / SOPS)**
Если вы используете GitOps для секретов, определите поле в `stringData`:
```yaml
stringData:
  gitlab.clientSecret: "ваш_секрет_gitlab"
```

**Важно:**
- Никогда не храните секреты в `argocd-cm` — используйте `argocd-secret`.
- Для продакшена рекомендуется использовать External Secrets Operator или Sealed Secrets.

### Шаг 3: Настройка коннектора в ConfigMap

Отредактируйте `argocd-cm` для настройки связи с GitLab.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com
  dex.config: |
    connectors:
      - type: gitlab
        id: gitlab
        name: GitLab
        config:
          baseURL: https://gitlab.example.com # URL вашего GitLab инстанса
          clientID: <application_id>
          clientSecret: $gitlab.clientSecret
          redirectURI: https://argocd.example.com/api/dex/callback
          # Дополнительные настройки для безопасности и групп:
          requestedScopes: ["openid", "profile", "email", "groups"]
          # Автоматическое обновление Groups при каждом входе
          # groupMemberAttributes: true
          # Фильтрация групп (опционально)
          # groups: ["infra/*", "shop/*"]
```

**Примечание для Self-managed GitLab с внутренним CA:**
Если GitLab использует самоподписанный сертификат, добавьте корневой сертификат в `argocd-cm`:
```yaml
dex.config: |
  logger:
    level: debug
  connectors:
    - type: gitlab
      ...
      config:
        rootCAData: <base64_encoded_ca_cert>
```

**Примечание для GitLab.com (SaaS):**
```yaml
dex.config: |
  connectors:
    - type: gitlab
      id: gitlab
      name: GitLab
      config:
        baseURL: https://gitlab.com
        clientID: <application_id>
        clientSecret: $gitlab.clientSecret
        requestedScopes: ["openid", "profile", "email", "groups"]
```

### Шаг 4: Настройка политик доступа (RBAC)

Маппинг групп GitLab на роли ArgoCD выполняется в `argocd-rbac-cm`.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    # Группа 'infra-admins' получает полные права
    g, "infra/kubernetes-admins", role:admin
    
    # Кастомная роль для разработчиков проекта 'shop'
    p, role:dev-shop, applications, get, shop/*, allow
    p, role:dev-shop, applications, sync, shop/*, allow
    
    # Маппинг вложенной группы GitLab на роль
    g, "shop-team/backend-devs", role:dev-shop
```

*Важно: Названия групп в GitLab при использовании OIDC передаются как полные пути (`path/to/group`).*

### Шаг 5: Верификация и тестирование

**1. Проверка логов Dex:**
```bash
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server --tail=50 -f
```

**2. Вход через UI:**
- Откройте URL ArgoCD в браузере.
- Нажмите **LOGIN VIA GITLAB**.
- Введите учетные данные GitLab.
- Проверьте, что вы авторизованы и видите нужные приложения.

**3. Проверка Claims:**
```bash
# Просмотр информации о текущем пользователе
argocd account get

# Просмотр Roles и Groups
argocd admin settings rbac
```

**4. Проверка политик:**
```bash
# Проверка доступа конкретного пользователя к конкретному приложению
argocd admin settings rbac can role:dev-shop get applications shop/frontend
# → YES или NO

# Проверка доступа группы
argocd admin settings rbac can role:admin get clusters
# → YES
```

### Шаг 6: Обновление групп при входе (Auto-Refresh)

По умолчанию Dex обновляет Claims (группы) только при первом входе. Для автоматического обновления групп при каждом входе включите параметр `groupMemberAttributes`:

```yaml
dex.config: |
  connectors:
    - type: gitlab
      config:
        groupMemberAttributes: true
        requestedScopes: ["openid", "profile", "email", "groups"]
```

**Важно:** Это может увеличить время входа на 1-2 секунды из-за дополнительных запросов к GitLab API.

## Диагностика и устранение неисправностей

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **Invalid redirect URI** | Несоответствие URL в GitLab и `argocd-cm`. | Проверьте наличие завершающего слэша и протокола HTTPS. Убедитесь, что URL совпадает exactly: `https://<argocd-url>/api/dex/callback`. |
| **Internal Server Error (500)** | Ошибка связи с GitLab или неверный Secret. | Проверьте логи пода `argocd-dex-server`. Убедитесь, что `clientSecret` корректен. |
| **Пользователь залогинился, но нет прав** | Ошибка в маппинге групп в `policy.csv`. | Проверьте точное написание группы во вкладке **User Info** в ArgoCD. Группы передаются как полные пути. |
| **No such user** | Пользователь не найден в GitLab или отключен. | Убедитесь, что пользователь активен в GitLab и имеет доступ к приложению. |
| **Token has expired** | Время жизни токена истекло. | Настройте `_expire_token_after` в GitLab или перезайдите. |
| **Groups not received** | GitLab не возвращает группы в Claims. | Проверьте, что `requestedScopes` включает `groups`. Убедитесь, что пользователь является членом хотя бы одной группы. |
| **TLS certificate error** | Самоподписанный сертификат GitLab. | Добавьте `rootCAData` в конфигурацию коннектора в `argocd-cm`. |
| **Dex pod CrashLoopBackOff** | Ошибка в конфигурации Dex. | Проверьте логи: `kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server`. |

### Полезные команды для отладки

```bash
# Проверка логов Dex (самый важный источник информации)
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-dex-server

# Проверка конфигурации RBAC в реальном времени
argocd admin settings rbac

# Просмотр всех пользователей и их ролей
argocd account list

# Просмотр информации о текущем пользователе
argocd account get

# Проверка доступа (RBAC check)
argocd admin settings rbac can <роль> <действие> <ресурс>

# Просмотр событий в namespace argocd
kubectl get events -n argocd --sort-by='.lastTimestamp'

# Проверка статуса пода Dex
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-dex-server -o wide
```

### Проверка OIDC-конфигурации

```bash
# Просмотр текущей конфигурации argocd-cm
kubectl get configmap argocd-cm -n argocd -o yaml

# Просмотр текущей конфигурации argocd-rbac-cm
kubectl get configmap argocd-rbac-cm -n argocd -o yaml

# Просмотр секрета (без decoded значений)
kubectl get secret argocd-secret -n argocd -o yaml
```

## Рекомендации и лучшие практики

### Безопасность

- **HTTPS обязателен:** ArgoCD должен быть доступен по HTTPS с валидным TLS-сертификатом.
- **Секреты в argocd-secret:** Никогда не храните `clientSecret` в `argocd-cm`. Используйте `argocd-secret` или External Secrets Operator.
- **Минимальные Scopes:** Используйте только необходимые scopes: `openid`, `profile`, `email`, `groups`. Избегайте `api` scope.
- **Время жизни токенов:** Настройте `_expire_token_after` в GitLab (рекомендуется 3600 секунд / 1 час).
- **AppProject:** Всегда создавайте отдельные AppProject для разных команд/окружений с ограничениями по источникам и namespace.

### Производительность

- **Кеширование Groups:** Если GitLab содержит много групп (>100), используйте `groupMemberAttributes: false` для ускорения входа (обновление групп только при первом входе).
- **Интервал обновления:** Не используйте слишком частое обновление групп — это нагружает GitLab API.
- **Dex Logging:** В продакшене установите `logger.level: info` (не `debug`) для снижения нагрузки на логирование.

### Надежность

- **Мониторинг Dex:** Добавьте алерты на CrashLoopBackOff пода `argocd-dex-server`.
- **Fallback:** Настройте `policy.default: role:readonly` для пользователей без явного маппинга групп.
- **Тестирование:** Перед изменением политик проверяйте доступ через `argocd admin settings rbac can`.
- **Backup конфигурации:** Регулярно делайте бэкап `argocd-cm` и `argocd-rbac-cm`.

### Устранение проблем

- **Логирование:** Включите `logger.level: debug` в `dex.config` для отладки, затем верните `info`.
- **Группы:** Если группы не отображаются — проверьте `requestedScopes` и наличие атрибута `groups` в GitLab.
- **Вложенные группы:** Убедитесь, что в `argocd-cm` включен `groupMemberAttributes: true` для поддержки вложенных групп.

## Ограничения и edge cases

### Ограничения

1. **GitLab Groups через Dex:** Вложенные группы поддерживаются только через Dex (не через нативный OIDC ArgoCD).
2. **Лимит Claims:** OIDC-токен ограничен размером (обычно 4KB). Если у пользователя >50 групп, некоторые группы могут быть обрезаны.
3. **Кеширование сессий:** Dex кеширует сессии в Redis. При изменении групп в GitLab пользователю необходимо перезайти.
4. **Нативный OIDC vs Dex:** Для GitLab **обязательно** использовать Dex (нативный OIDC не поддерживает GitLab-специфичные поля groups).

### Edge Cases

1. **Пользователь в нескольких группах:** ArgoCD объединяет права всех ролей, назначенных пользователю через группы.
2. **Группа не существует в GitLab:** Если группа удалена из GitLab, Dex не вернет её в Claims при следующем входе.
3. **Самоподписанный сертификат GitLab:** Добавьте `rootCAData` в конфигурацию коннектора.
4. **GitLab Group Membership:** Если пользователь является членом группы через LDAP-синхронизацию, GitLab все равно возвращает эту группу в Claims.
5. **Несколько коннекторов:** Каждый коннектор должен иметь уникальный `id`. Пользователь может войти через любой доступный коннектор.
6. **RBAC и AppProject:** Политики RBAC работают совместно с AppProject. Даже если роль разрешает `sync`, AppProject может запретить этот ресурс.
7. **Отзыв доступа:** При отзыве доступа пользователя в GitLab его сессия в ArgoCD остается активной до истечения времени жизни токена.

## Дополнительная информация

### Использование нескольких коннекторов

Dex позволяет одновременно настроить несколько провайдеров (например, GitLab для сотрудников и Google для подрядчиков). Каждый коннектор должен иметь уникальный `id`.

**Пример: GitLab + Google:**
```yaml
dex.config: |
  connectors:
    - type: gitlab
      id: gitlab
      name: GitLab (Corporate)
      config:
        baseURL: https://gitlab.example.com
        clientID: <gitlab_client_id>
        clientSecret: $gitlab.clientSecret
        requestedScopes: ["openid", "profile", "email", "groups"]
    - type: google
      id: google
      name: Google (Contractors)
      config:
        clientID: <google_client_id>
        clientSecret: $google.clientSecret
        redirectURI: https://argocd.example.com/api/dex/callback
        hostedDomains: ["contractor.example.com"]
```

### См. также

- [ArgoCD: Установка и настройка HA](./argocd_installation_and_setup.md)
- [Диагностика и мониторинг ArgoCD](./argocd_troubleshooting_and_monitoring.md)
- [ArgoCD: Автоматизация через API и Ansible](./argocd_api_automation.md)
- [RBAC — модель доступа](./argocd_rbac_deep.md) — Модель доступа, policy.csv, встроенные роли, JWT-токены, диагностика.
- [AppProject — изоляция проектов](./argocd_appproject_deep.md) — Изоляция проектов, квоты, restrictions, кастомные роли.
- [Безопасность](./argocd_security_hardening.md) — GPG, NetworkPolicies, mTLS, SecurityContext, proxy, audit logging.
- [Мультитенантность](./argocd_multi_tenancy.md) — Паттерны мультитенантности, tenant isolation, project-per-team.

### Официальные ресурсы

- [ArgoCD OIDC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/gitlab/)
- [Dex GitLab Connector Specs](https://dexidp.io/docs/connectors/gitlab/)
- [ArgoCD RBAC Configuration](https://argo-cd.readthedocs.io/en/stable/operator-manual/rbac/)
